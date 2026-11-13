"""Load a hand-labeled extraction eval file.

The file records claims a person already audited, the label they would expect,
and where that judgment was written down. Loading it checks the shape. It does
not re-run the audit.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from claimcheck.errors import GroundTruthError
from claimcheck.models import Label


class Source(BaseModel):
    """A page that documents this row. The URL is the citation."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["issue_body", "issue_comment"]
    url: str = Field(min_length=1)
    author: str = Field(min_length=1)
    note: str = Field(min_length=1)


class GoldClaim(BaseModel):
    """One audited README claim, pinned to a repository commit."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    commit: str
    claim_text: str = Field(min_length=1)
    issue_claim: str = Field(min_length=1)
    expected_label: Label
    issue_severity: str = Field(min_length=1)
    label_mapping_note: str = Field(min_length=1)
    mapping_is_coarse: bool
    evidence_notes: str = Field(min_length=1)
    readme_path: str = Field(min_length=1)
    readme_line: int = Field(ge=1)
    readme_line_end: int = Field(ge=1)
    readme_quote: str = Field(min_length=1)
    also_readme_lines: list[int] = Field(default_factory=list)
    match_texts: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(min_length=1)

    @field_validator("commit")
    @classmethod
    def _full_commit(cls, value: str) -> str:
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("commit must be a 40-character lowercase git SHA")
        return value

    @field_validator("also_readme_lines")
    @classmethod
    def _also_lines(cls, value: list[int]) -> list[int]:
        if any(line < 1 for line in value):
            raise ValueError("also_readme_lines entries must be >= 1")
        return value

    @model_validator(mode="after")
    def _span(self) -> "GoldClaim":
        if self.readme_line_end < self.readme_line:
            raise ValueError("readme_line_end is before readme_line")
        return self

    def match_phrases(self) -> list[str]:
        """Phrases the recall scorer may match. All of them come from this row."""
        phrases = [self.claim_text, self.issue_claim, self.readme_quote, *self.match_texts]
        unique: list[str] = []
        seen: set[str] = set()
        for phrase in phrases:
            key = phrase.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique


class GroundTruth(BaseModel):
    """A set of gold claims and the rule used to decide what was included."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int
    dataset: str = Field(min_length=1)
    inclusion_rule: str = Field(min_length=1)
    label_mapping: dict[str, Label]
    provenance: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    commit: str
    commit_committed_at: str = Field(min_length=1)
    commit_selection: str = Field(min_length=1)
    issue_url: str = Field(min_length=1)
    issue_created_at: str = Field(min_length=1)
    readme_sha256: str
    cases: list[GoldClaim] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported ground-truth schema_version")
        return value

    @field_validator("commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("commit must be a 40-character lowercase git SHA")
        return value

    @field_validator("readme_sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("readme_sha256 must be a 64-character lowercase hex digest")
        return value

    @model_validator(mode="after")
    def _cases_follow_the_mapping(self) -> "GroundTruth":
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("ground-truth case ids must be unique")
        for case in self.cases:
            if case.repo != self.repo or case.commit != self.commit or case.branch != self.branch:
                raise ValueError(f"{case.id} does not match the file's repo, branch, or commit")
            mapped = self.label_mapping.get(case.issue_severity)
            if mapped is None:
                raise ValueError(f"{case.id} has issue_severity with no label_mapping entry")
            if case.expected_label != mapped:
                raise ValueError(
                    f"{case.id} expected_label {case.expected_label.value} "
                    f"does not follow label_mapping for {case.issue_severity!r}"
                )
        return self


def load_ground_truth(path: Path) -> GroundTruth:
    """Read and validate a ground-truth file. Raises GroundTruthError on a bad file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GroundTruthError(f"Could not read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GroundTruthError(f"{path} is not JSON: {exc.msg}") from exc
    try:
        return GroundTruth.model_validate(data)
    except Exception as exc:
        raise GroundTruthError(f"{path} failed validation: {exc}") from exc
