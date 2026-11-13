"""Milestone 1 scan: extract claims, then label each one unverifiable.

The label is a placeholder. It is not a statement that the claim lacks
evidence in the repository. Evidence retrieval is a later milestone.
"""

from datetime import datetime, timezone

from claimcheck.constants import STUB_LIMITATIONS, STUB_MODE, STUB_RATIONALE, __version__
from claimcheck.extract import LLMClient, extract_claims
from claimcheck.models import Label, Report, Verdict
from claimcheck.readme import ReadmeDocument


def project_name(document: ReadmeDocument) -> str:
    """Directory name for a README.md, otherwise the file stem."""
    if document.path.name.lower().startswith("readme."):
        return document.path.parent.name or document.path.stem
    return document.path.stem


def build_stub_report(
    document: ReadmeDocument,
    client: LLMClient,
    *,
    project: str | None = None,
    generated_at: datetime | None = None,
    max_attempts: int = 3,
) -> Report:
    """Extract claims and attach one provisional unverifiable verdict to each checkable claim."""
    extraction = extract_claims(document, client, max_attempts=max_attempts)
    when = generated_at or datetime.now(timezone.utc)
    verdicts = [
        Verdict(
            claim_id=claim.id,
            label=Label.unverifiable,
            evidence=[],
            rationale=STUB_RATIONALE,
            provisional=True,
        )
        for claim in extraction.claims
        if claim.checkable
    ]
    return Report(
        tool_version=__version__,
        mode=STUB_MODE,
        project=project or project_name(document),
        readme_path=document.display_path,
        generated_at=when,
        claims=extraction.claims,
        verdicts=verdicts,
        limitations=list(STUB_LIMITATIONS),
        warnings=list(extraction.warnings),
    )
