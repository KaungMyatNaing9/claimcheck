"""Score report labels against hand-labeled claims.

Strict rows and coarse-mapping rows are counted separately. A coarse row is
one whose issue severity was not already one of the four labels' own words
in a direct way: the ground-truth file sets ``mapping_is_coarse``.
"""

from pydantic import BaseModel, ConfigDict, Field

from claimcheck.ground_truth import GoldClaim
from claimcheck.models import Label, Report
from claimcheck.scoring import DEFAULT_RECALL_THRESHOLD, phrase_matches


class VerdictRow(BaseModel):
    """One gold claim next to the label a report gave the matching extracted claim."""

    model_config = ConfigDict(extra="forbid")

    id: str
    issue_severity: str
    expected_label: Label
    predicted_label: Label | None
    mapping_is_coarse: bool
    matched_claim_id: str | None = None


class VerdictScore(BaseModel):
    """Agreement with expected labels, split by whether the mapping was coarse."""

    model_config = ConfigDict(extra="forbid")

    gold: int = Field(ge=0)
    matched: int = Field(ge=0)
    strict_correct: int = Field(ge=0)
    strict_total: int = Field(ge=0)
    coarse_correct: int = Field(ge=0)
    coarse_total: int = Field(ge=0)
    rows: list[VerdictRow]
    note: str


def score_verdicts(
    cases: list[GoldClaim],
    report: Report,
    *,
    threshold: float = DEFAULT_RECALL_THRESHOLD,
) -> VerdictScore:
    """Match each gold claim to at most one report claim, then compare labels."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    unused = [claim for claim in report.claims if claim.checkable]
    rows: list[VerdictRow] = []
    for case in cases:
        match = _take_match(case, unused, threshold)
        predicted = report.verdict_for(match.id).label if match is not None else None
        rows.append(
            VerdictRow(
                id=case.id,
                issue_severity=case.issue_severity,
                expected_label=case.expected_label,
                predicted_label=predicted,
                mapping_is_coarse=case.mapping_is_coarse,
                matched_claim_id=None if match is None else match.id,
            )
        )
    strict = [row for row in rows if not row.mapping_is_coarse]
    coarse = [row for row in rows if row.mapping_is_coarse]
    return VerdictScore(
        gold=len(cases),
        matched=sum(1 for row in rows if row.predicted_label is not None),
        strict_correct=sum(1 for row in strict if row.predicted_label == row.expected_label),
        strict_total=len(strict),
        coarse_correct=sum(1 for row in coarse if row.predicted_label == row.expected_label),
        coarse_total=len(coarse),
        rows=rows,
        note=(
            "Strict rows and coarse-mapping rows are separate. "
            "A coarse row keeps the issue's own severity beside the mapped label. "
            "This is agreement with the hand-labeled file, not a live-model accuracy figure "
            "unless the report you passed was produced by one."
        ),
    )


def _take_match(case: GoldClaim, unused: list, threshold: float):
    for index, claim in enumerate(unused):
        if any(
            phrase_matches(needle, claim.text, threshold=threshold)
            for needle in case.match_phrases()
        ):
            return unused.pop(index)
    return None
