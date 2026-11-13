"""Claim, evidence, verdict, and report records.

One claim has one verdict. A verdict cites evidence by file and line, or it
cites nothing and says so. JSON is the stable form of a report.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClaimKind(str, Enum):
    """What sort of statement the claim is. The kind does not say it is true."""

    benchmark_number = "benchmark_number"
    feature = "feature"
    property = "property"
    compatibility = "compatibility"
    other = "other"


class Label(str, Enum):
    """The only labels a verdict may use."""

    supported = "supported"
    not_found = "not_found"
    contradicted = "contradicted"
    unverifiable = "unverifiable"


class Claim(BaseModel):
    """A statement taken from a README, tied to the line it came from."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: ClaimKind
    checkable: bool
    skip_reason: str | None = None
    readme_path: str = Field(min_length=1)
    readme_line: int = Field(ge=1)
    readme_line_end: int = Field(ge=1)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def _line_span_and_skip_reason(self) -> "Claim":
        if self.readme_line_end < self.readme_line:
            raise ValueError("readme_line_end is before readme_line")
        if self.checkable and self.skip_reason:
            raise ValueError("checkable claims do not take a skip_reason")
        if not self.checkable and not (self.skip_reason and self.skip_reason.strip()):
            raise ValueError("a claim that is not checkable needs a skip_reason")
        return self


class Evidence(BaseModel):
    """One place in the repository used to support a verdict."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    line: int = Field(ge=1)
    line_end: int | None = Field(default=None, ge=1)
    quote: str = Field(min_length=1)
    note: str | None = None

    @model_validator(mode="after")
    def _line_span(self) -> "Evidence":
        if self.line_end is not None and self.line_end < self.line:
            raise ValueError("line_end is before line")
        return self

    def location(self) -> str:
        """File and line, the form reports print and tests assert on."""
        if self.line_end is not None and self.line_end != self.line:
            return f"{self.path}:{self.line}-{self.line_end}"
        return f"{self.path}:{self.line}"


class Verdict(BaseModel):
    """The single label for one claim, plus the evidence that label used."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    label: Label
    evidence: list[Evidence] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    provisional: bool = False


class ExtractionResult(BaseModel):
    """What `claimcheck extract` returns. No verdicts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    tool_version: str
    readme_path: str
    claims: list[Claim]
    attempts: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list)


class Report(BaseModel):
    """A scan report. Every checkable claim has exactly one verdict."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    tool_version: str
    mode: str = Field(min_length=1)
    project: str = Field(min_length=1)
    readme_path: str = Field(min_length=1)
    generated_at: datetime
    claims: list[Claim]
    verdicts: list[Verdict]
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _one_verdict_per_checkable_claim(self) -> "Report":
        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim ids must be unique")
        checkable = {claim.id for claim in self.claims if claim.checkable}
        verdict_ids = [verdict.claim_id for verdict in self.verdicts]
        if len(verdict_ids) != len(set(verdict_ids)):
            raise ValueError("a claim has more than one verdict")
        if set(verdict_ids) != checkable:
            raise ValueError("verdicts must cover the checkable claims and no others")
        known = set(claim_ids)
        for verdict in self.verdicts:
            if verdict.claim_id not in known:
                raise ValueError(f"verdict cites unknown claim {verdict.claim_id}")
        return self

    def verdict_for(self, claim_id: str) -> Verdict:
        for verdict in self.verdicts:
            if verdict.claim_id == claim_id:
                return verdict
        raise KeyError(claim_id)
