"""Label one claim from lines this repository actually retrieved.

The model may cite only those lines. A ``contradicted`` label also needs a
second pass that confirms the cited lines are counter-evidence. Anything
short of that is ``unverifiable``.
"""

import re
from pathlib import Path

from claimcheck.extract import LLMClient, parse_json_object
from claimcheck.models import Claim, Evidence, Label, Verdict
from claimcheck.retrieve import (
    Measurement,
    NumericJudgment,
    Snippet,
    content_tokens,
    display_words,
    judge_numbers,
    retrieve,
)

VERDICT_SYSTEM = """You label one README claim using only the evidence lines provided.

Return JSON only, with this shape:
{"label": "supported", "citations": ["E1"], "rationale": "one or two sentences"}

label is one of supported, not_found, contradicted, unverifiable.
citations are the E-numbers of lines you used, or path:line copies of those lines.
Rules:
- supported and contradicted require at least one citation.
- Cite a line only if its text bears on this claim. Do not cite a line that merely shares a topic.
- contradicted requires the cited line to state the opposite of the claim,
  or a measurement of the same metric with a different number.
- If the lines are missing, ambiguous, or about a different metric, use unverifiable.
- not_found means you looked at the lines and they do not contain the claimed behavior.
- Do not use knowledge from outside the lines.
"""

CONFIRM_SYSTEM = """You check a proposed contradicted label. Confirm it only when the cited
lines are concrete counter-evidence: they state the opposite, or they report
a different value for the same metric.

Return JSON only: {"confirm": false, "rationale": "one sentence"}
confirm is true only when you are sure. If the lines are related, incomplete,
or about something else, confirm is false.
"""


def judge_claim(
    root: Path,
    claim: Claim,
    client: LLMClient,
    *,
    readme: Path | None = None,
    max_attempts: int = 3,
) -> tuple[Verdict, list[str]]:
    """Return the verdict and any warnings. Does not raise on a bad model response."""
    snippets = retrieve(root, claim.text, readme=readme)
    numbers = judge_numbers(claim.text, root, readme=readme)
    if claim.kind.value == "benchmark_number" and numbers.relation in {"absent", "ambiguous"}:
        return _unverifiable(claim.id, numbers.detail, downgraded_from=None), []
    if claim.kind.value != "benchmark_number" and not snippets:
        searched = ", ".join(display_words(claim.text)) or "no content words"
        return (
            Verdict(
                claim_id=claim.id,
                label=Label.not_found,
                evidence=[],
                rationale=(
                    "The symbol index and text search returned no line for this claim. "
                    f"Words used: {searched}."
                ),
            ),
            [],
        )
    proposal, warnings = _ask(client, _verdict_user(claim, snippets), max_attempts)
    if proposal is None:
        return _unverifiable(
            claim.id, "The model response for this claim was not usable."
        ), warnings
    label, cited, rationale = proposal
    if label is None:
        return _unverifiable(claim.id, rationale), warnings
    evidence = _evidence(cited)
    if label in {Label.supported, Label.contradicted} and not evidence:
        return (
            _unverifiable(
                claim.id,
                "The model cited no retrieved line, so the label was not kept.",
                downgraded_from=label,
            ),
            warnings,
        )
    if claim.kind.value == "benchmark_number":
        return _numeric_label(
            claim, label, evidence, numbers, rationale, client, root, max_attempts, warnings
        )
    if label is Label.contradicted:
        return _contradicted_or_downgrade(
            claim, evidence, rationale, client, numbers, max_attempts, warnings
        )
    return (
        Verdict(claim_id=claim.id, label=label, evidence=evidence, rationale=rationale),
        warnings,
    )


def _numeric_label(
    claim: Claim,
    label: Label,
    evidence: list[Evidence],
    numbers: NumericJudgment,
    rationale: str,
    client: LLMClient,
    root: Path,
    max_attempts: int,
    warnings: list[str],
) -> tuple[Verdict, list[str]]:
    cited_measurements = [row for row in numbers.measurements if _cited(row, evidence)]
    if numbers.relation == "match" and label is Label.supported and cited_measurements:
        if _still(root, cited_measurements, numbers.relation):
            return (
                Verdict(
                    claim_id=claim.id, label=Label.supported, evidence=evidence, rationale=rationale
                ),
                warnings,
            )
        return _unverifiable(
            claim.id, "Re-reading the benchmark file did not reproduce the match."
        ), warnings
    if numbers.relation == "conflict" and label is Label.contradicted and cited_measurements:
        return _contradicted_or_downgrade(
            claim, evidence, rationale, client, numbers, max_attempts, warnings, root=root
        )
    rejected = label if label in {Label.supported, Label.contradicted} else None
    detail = (
        numbers.detail or "The number in the claim and the cited lines do not support that label."
    )
    return _unverifiable(claim.id, detail, downgraded_from=rejected), warnings


def _contradicted_or_downgrade(
    claim: Claim,
    evidence: list[Evidence],
    rationale: str,
    client: LLMClient,
    numbers: NumericJudgment,
    max_attempts: int,
    warnings: list[str],
    root: Path | None = None,
) -> tuple[Verdict, list[str]]:
    concrete = _concrete(claim.text, evidence, numbers)
    if not concrete:
        return (
            _unverifiable(
                claim.id,
                "The cited lines do not state the opposite or a disagreeing measurement.",
                downgraded_from=Label.contradicted,
            ),
            warnings,
        )
    if root is not None and numbers.relation == "conflict":
        if not _still(root, numbers.measurements, "conflict"):
            return (
                _unverifiable(
                    claim.id,
                    "Re-reading the benchmark file did not reproduce the disagreement.",
                    downgraded_from=Label.contradicted,
                ),
                warnings,
            )
    confirmed, confirm_warnings = _confirm(client, claim, evidence, numbers, max_attempts)
    warnings = [*warnings, *confirm_warnings]
    if not confirmed:
        return (
            _unverifiable(
                claim.id,
                "A second pass did not confirm that the cited lines contradict the claim.",
                downgraded_from=Label.contradicted,
            ),
            warnings,
        )
    return (
        Verdict(
            claim_id=claim.id,
            label=Label.contradicted,
            evidence=evidence,
            rationale=rationale,
        ),
        warnings,
    )


def _concrete(claim_text: str, evidence: list[Evidence], numbers: NumericJudgment) -> bool:
    if numbers.relation == "conflict" and any(
        _cited(row, evidence) for row in numbers.measurements
    ):
        return True
    claim = content_tokens(claim_text)
    for item in evidence:
        if content_tokens(item.quote) & claim:
            return True
    return False


def _still(
    root: Path, measurements: list[Measurement] | tuple[Measurement, ...], relation: str
) -> bool:
    """Re-parse the cited files. The disagreement or agreement has to still be there."""
    from claimcheck.retrieve import parse_benchmarks

    fresh = {(row.path, row.line, row.metric): row for row in parse_benchmarks(root)}
    for measurement in measurements:
        current = fresh.get((measurement.path, measurement.line, measurement.metric))
        if current is None or current.value != measurement.value or current.raw != measurement.raw:
            return False
    return relation in {"match", "conflict"}


def _cited(measurement: Measurement, evidence: list[Evidence]) -> bool:
    return any(item.path == measurement.path and item.line == measurement.line for item in evidence)


def _ask(
    client: LLMClient, user: str, max_attempts: int
) -> tuple[tuple[Label | None, list[Snippet], str] | None, list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    packet = _packet_from_user(user)
    prompt = user.split("\n@@PACKET", 1)[0]
    for _attempt in range(max(1, max_attempts)):
        raw = client.complete(
            system=VERDICT_SYSTEM, user=prompt if not errors else prompt + _retry(errors)
        )
        try:
            payload = parse_json_object(raw)
        except ValueError as exc:
            errors = [str(exc)]
            continue
        label_text = payload.get("label")
        if not isinstance(label_text, str) or label_text not in {item.value for item in Label}:
            errors = ["label must be supported, not_found, contradicted, or unverifiable"]
            continue
        citations = payload.get("citations", [])
        if citations is None:
            citations = []
        if not isinstance(citations, list):
            errors = ["citations must be a list"]
            continue
        rationale = payload.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            errors = ["rationale must be a non-empty string"]
            continue
        cited = _resolve_all(citations, packet)
        if len(cited) != len([item for item in citations if str(item).strip()]):
            warnings.append("Dropped a citation that was not one of the retrieved lines.")
        return (Label(label_text), cited, rationale.strip()), warnings
    warnings.append("Verdict response stayed invalid: " + "; ".join(errors))
    return None, warnings


def _confirm(
    client: LLMClient,
    claim: Claim,
    evidence: list[Evidence],
    numbers: NumericJudgment,
    max_attempts: int,
) -> tuple[bool, list[str]]:
    lines = "\n".join(f"- {item.path}:{item.line}: {item.quote}" for item in evidence)
    user = f"Claim: {claim.text}\n\nCited lines:\n{lines}\n\nNumeric comparison: {numbers.detail}\n"
    warnings: list[str] = []
    errors: list[str] = []
    for _attempt in range(max(1, max_attempts)):
        prompt = user if not errors else user + _retry(errors)
        raw = client.complete(system=CONFIRM_SYSTEM, user=prompt)
        try:
            payload = parse_json_object(raw)
        except ValueError as exc:
            errors = [str(exc)]
            continue
        confirm = payload.get("confirm")
        if not isinstance(confirm, bool):
            errors = ["confirm must be a JSON boolean"]
            continue
        return confirm, warnings
    warnings.append("Second pass response stayed invalid, so contradicted was not kept.")
    return False, warnings


def _verdict_user(claim: Claim, snippets: list[Snippet]) -> str:
    blocks = []
    for index, snippet in enumerate(snippets, start=1):
        blocks.append(f"[E{index}] {snippet.citation}\n{snippet.text}")
    evidence = "\n\n".join(blocks) if blocks else "(no lines retrieved)"
    # A trailing marker lets the parser recover the packet without a second argument.
    marker = "\n".join(
        f"@@{snippet.path}|{snippet.line}|{snippet.line_end}|{snippet.origin}|{snippet.text}"
        for snippet in snippets
    )
    return (
        f"Claim ({claim.kind.value}): {claim.text}\n\nEvidence:\n{evidence}\n\n@@PACKET\n{marker}"
    )


def _packet_from_user(user: str) -> list[Snippet]:
    if "@@PACKET" not in user:
        return []
    body = user.split("@@PACKET", 1)[1]
    # Drop a retry suffix if we appended one after the packet. Retries are added
    # after the whole user string, so slice only the original packet lines.
    snippets: list[Snippet] = []
    for line in body.splitlines():
        if not line.startswith("@@"):
            continue
        path, line_no, line_end, origin, text = line[2:].split("|", 4)
        snippets.append(
            Snippet(
                path=path,
                line=int(line_no),
                line_end=int(line_end),
                text=text,
                origin=origin,
            )
        )
    return snippets


def _resolve_all(citations: list[object], snippets: list[Snippet]) -> list[Snippet]:
    resolved: list[Snippet] = []
    seen: set[tuple[str, int]] = set()
    for citation in citations:
        snippet = _resolve_one(str(citation), snippets)
        if snippet is None:
            continue
        key = (snippet.path, snippet.line)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(snippet)
    return resolved


def _resolve_one(citation: str, snippets: list[Snippet]) -> Snippet | None:
    text = citation.strip()
    match = re.fullmatch(r"E(\d+)", text, re.IGNORECASE)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(snippets):
            return snippets[index]
        return None
    located = re.fullmatch(r"(.+):(\d+)", text)
    if not located:
        return None
    path, line = located.group(1), int(located.group(2))
    for snippet in snippets:
        if snippet.path == path and snippet.line <= line <= snippet.line_end:
            return snippet
    return None


def _evidence(snippets: list[Snippet]) -> list[Evidence]:
    return [
        Evidence(
            path=snippet.path, line=snippet.line, quote=snippet.text[:500], note=snippet.origin
        )
        for snippet in snippets
        if snippet.text.strip()
    ]


def _unverifiable(claim_id: str, rationale: str, downgraded_from: Label | None = None) -> Verdict:
    return Verdict(
        claim_id=claim_id,
        label=Label.unverifiable,
        evidence=[],
        rationale=rationale,
        provisional=downgraded_from is not None,
        downgraded_from=downgraded_from,
    )


def _retry(errors: list[str]) -> str:
    bullets = "\n".join(f"- {error}" for error in errors)
    return (
        "\n\nThe previous response was rejected:\n"
        f"{bullets}\nRespond again with only the JSON object."
    )
