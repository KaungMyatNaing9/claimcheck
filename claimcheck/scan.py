"""Scan a repository: extract claims, retrieve evidence, and assign one verdict each."""

from datetime import datetime, timezone
from pathlib import Path

from claimcheck.constants import SCAN_LIMITATIONS, SCAN_MODE, __version__
from claimcheck.extract import LLMClient, extract_claims
from claimcheck.models import Report
from claimcheck.readme import ReadmeDocument
from claimcheck.verdict import judge_claim


def project_name(document: ReadmeDocument) -> str:
    """Directory name for a README.md, otherwise the file stem."""
    if document.path.name.lower().startswith("readme."):
        return document.path.parent.name or document.path.stem
    return document.path.stem


def repo_root_for(readme: Path) -> Path:
    """The directory whose code and benchmark files are evidence for this README."""
    if readme.is_dir():
        return readme.resolve()
    return readme.resolve().parent


def build_report(
    document: ReadmeDocument,
    client: LLMClient,
    *,
    repo_root: Path | None = None,
    project: str | None = None,
    generated_at: datetime | None = None,
    max_attempts: int = 3,
) -> Report:
    """Extract claims and judge each checkable one against files under repo_root."""
    root = (repo_root or repo_root_for(document.path)).resolve()
    extraction = extract_claims(document, client, max_attempts=max_attempts)
    warnings = list(extraction.warnings)
    verdicts = []
    for claim in extraction.claims:
        if not claim.checkable:
            continue
        verdict, extra = judge_claim(
            root,
            claim,
            client,
            readme=document.path,
            max_attempts=max_attempts,
        )
        warnings.extend(extra)
        verdicts.append(verdict)
    return Report(
        tool_version=__version__,
        mode=SCAN_MODE,
        project=project or project_name(document),
        readme_path=document.display_path,
        generated_at=generated_at or datetime.now(timezone.utc),
        claims=extraction.claims,
        verdicts=verdicts,
        limitations=list(SCAN_LIMITATIONS),
        warnings=warnings,
    )
