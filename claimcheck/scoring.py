"""Lexical extraction-recall scorer for hand-labeled claims.

This does not score verdicts. A hit means an extracted string shares a gold
phrase, either as a whitespace-normalized substring or as token overlap that
also keeps every number from that phrase. Paraphrases that share neither can
count as misses. That limit is part of the metric.
"""

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from claimcheck.errors import GroundTruthError
from claimcheck.ground_truth import GoldClaim

DEFAULT_RECALL_THRESHOLD = 0.75
_MIN_SUBSTRING = 12
_STOP = frozenset(
    """
    a an the of to and or in on for with from as is are was were be this that
    it its by at into your you we our their they them but if than then so such
    """.split()
)
_TOKEN = re.compile(r"[a-z0-9.+%-]+")


class Miss(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    claim_text: str


class ScoreResult(BaseModel):
    """Recall of gold claims, plus precision of the extracted strings against those claims."""

    model_config = ConfigDict(extra="forbid")

    gold: int = Field(ge=0)
    hits: int = Field(ge=0)
    misses: list[Miss]
    recall: float
    extracted: int = Field(ge=0)
    extracted_matched: int = Field(ge=0)
    precision: float | None
    threshold: float
    note: str


def score_extraction(
    cases: list[GoldClaim],
    extracted_texts: list[str],
    *,
    threshold: float = DEFAULT_RECALL_THRESHOLD,
) -> ScoreResult:
    """Score whether each gold claim shows up in the extracted texts."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    misses: list[Miss] = []
    hit_count = 0
    for case in cases:
        if _case_hit(case, extracted_texts, threshold):
            hit_count += 1
        else:
            misses.append(Miss(id=case.id, claim_text=case.claim_text))
    matched = sum(1 for text in extracted_texts if _text_hits_any(text, cases, threshold))
    gold = len(cases)
    recall = 1.0 if gold == 0 else hit_count / gold
    precision = None if not extracted_texts else matched / len(extracted_texts)
    return ScoreResult(
        gold=gold,
        hits=hit_count,
        misses=misses,
        recall=recall,
        extracted=len(extracted_texts),
        extracted_matched=matched,
        precision=precision,
        threshold=threshold,
        note=(
            "Lexical overlap only. This is extraction recall, not verdict accuracy, "
            "and not a measure of a live model unless you just scored one."
        ),
    )


def load_extracted_texts(path: Path) -> list[str]:
    """Accept extract JSON, a report JSON, a list of strings, or a list of {text} objects."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GroundTruthError(f"Could not read extraction file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GroundTruthError(f"{path} is not JSON: {exc.msg}") from exc
    return extracted_texts_from(data)


def extracted_texts_from(data: object) -> list[str]:
    if isinstance(data, dict) and "claims" in data:
        data = data["claims"]
    if not isinstance(data, list):
        raise GroundTruthError("Extraction JSON must be a list, or an object with a 'claims' list.")
    texts: list[str] = []
    for index, item in enumerate(data, start=1):
        if isinstance(item, str):
            texts.append(item)
            continue
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            texts.append(item["text"])
            continue
        raise GroundTruthError(f"extraction item {index} has no text")
    return texts


def phrase_matches(needle: str, haystack: str, *, threshold: float) -> bool:
    """True when haystack contains the gold phrase closely enough to count as a hit."""
    needle_norm = _squash(needle)
    haystack_norm = _squash(haystack)
    if len(needle_norm) >= _MIN_SUBSTRING and needle_norm in haystack_norm:
        return True
    needle_tokens = _tokens(needle)
    if len(needle_tokens) < 2:
        return False
    haystack_tokens = set(_tokens(haystack))
    if not haystack_tokens:
        return False
    overlap = len(set(needle_tokens) & haystack_tokens) / len(set(needle_tokens))
    if overlap < threshold:
        return False
    return _numbers(needle_tokens) <= _numbers(haystack_tokens)


def _case_hit(case: GoldClaim, texts: list[str], threshold: float) -> bool:
    needles = case.match_phrases()
    return any(
        phrase_matches(needle, text, threshold=threshold)
        for text in texts
        for needle in needles
        if needle.strip()
    )


def _text_hits_any(text: str, cases: list[GoldClaim], threshold: float) -> bool:
    return any(_case_hit(case, [text], threshold) for case in cases)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip().casefold()


def _tokens(text: str) -> list[str]:
    keys: list[str] = []
    for raw in _TOKEN.findall(text.casefold()):
        token = raw[1:] if raw.startswith("+") else raw
        if token.endswith("%"):
            token = token[:-1]
        if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
            token = token[:-1]
        if len(token) <= 1 or token in _STOP:
            continue
        keys.append(token)
    return keys


def _numbers(tokens: list[str] | set[str]) -> set[str]:
    return {token for token in tokens if any(character.isdigit() for character in token)}
