"""Action summary, diff highlights, fail-on, and comment updates. No GitHub calls."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from claimcheck.action import run, upsert_comment
from claimcheck.action_report import (
    COMMENT_MARKER,
    PullRequestDiff,
    fail_on_code,
    highlights_for,
    parse_hunks,
    parse_name_status,
    render_comment,
    render_job_summary,
)
from claimcheck.models import Claim, ClaimKind, Evidence, Label, Report, Verdict

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "tiny_repo"
REPLAY = ROOT / "fixtures" / "tiny_repo_replay.json"
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "ClaimCheck",
    "GIT_AUTHOR_EMAIL": "claimcheck@example.com",
    "GIT_COMMITTER_NAME": "ClaimCheck",
    "GIT_COMMITTER_EMAIL": "claimcheck@example.com",
}


class FakeComments:
    def __init__(self, existing: list[dict[str, object]] | None = None) -> None:
        self.comments = list(existing or [])
        self.created: list[str] = []
        self.updated: list[tuple[int, str]] = []

    def list_comments(self, repository: str, number: int) -> list[dict[str, object]]:
        return list(self.comments)

    def create_comment(self, repository: str, number: int, body: str) -> None:
        self.created.append(body)

    def update_comment(self, repository: str, comment_id: int, body: str) -> None:
        self.updated.append((comment_id, body))


def test_hunks_and_name_status_parse() -> None:
    names = parse_name_status("M\ttinylib/facts.py\nA\tnew.py\n")
    assert names == {"tinylib/facts.py": "M", "new.py": "A"}
    hunks = parse_hunks("@@ -4,0 +5,1 @@\n+changed line\n")
    assert hunks == ((5, 5),)
    assert parse_hunks("@@ -5,1 +5,0 @@\n-removed\n") == ()


def test_highlights_follow_evidence_lines_and_readme_hunks() -> None:
    report = _report()
    diff = PullRequestDiff(
        available=True,
        note="1 file differs.",
        files={"tinylib/facts.py": ((5, 5),), "README.md": ((9, 9),)},
    )
    found = {item.claim_id: item for item in highlights_for(report, diff)}
    assert set(found) == {"c002", "c003"}
    assert "evidence `tinylib/facts.py` changed" in found["c002"].reasons
    assert "README line 9 is in the diff" in found["c003"].reasons
    summary = render_job_summary(report, diff, list(found.values()))
    assert "## Claims touched by this pull request" in summary
    assert "c001" not in summary.split("# ClaimCheck report")[0]


def test_missing_diff_does_not_invent_highlights() -> None:
    diff = PullRequestDiff(
        available=False, note="No base and head commits were provided.", files={}
    )
    summary = render_job_summary(_report(), diff, [])
    assert "No base and head" in summary
    assert "Claims touched" not in summary


def test_fail_on_none_ignores_contradicted_and_contradicted_fails() -> None:
    report = _report()
    assert fail_on_code(report, "none") == 0
    assert fail_on_code(report, "contradicted") == 1
    with pytest.raises(ValueError):
        fail_on_code(report, "not_found")


def test_upsert_updates_the_existing_marker_comment() -> None:
    client = FakeComments([{"id": 9, "body": f"{COMMENT_MARKER}\nold"}])
    assert upsert_comment(client, "owner/name", 3, f"{COMMENT_MARKER}\nnew") == "updated"
    assert client.created == []
    assert client.updated == [(9, f"{COMMENT_MARKER}\nnew")]
    fresh = FakeComments()
    assert upsert_comment(fresh, "owner/name", 3, f"{COMMENT_MARKER}\nnew") == "created"
    assert len(fresh.created) == 1
    assert COMMENT_MARKER in fresh.created[0]


def test_comment_body_starts_with_the_marker() -> None:
    diff = PullRequestDiff(available=False, note="skipped", files={})
    body = render_comment(_report(), diff, [])
    assert body.startswith(COMMENT_MARKER)


def test_replay_scan_writes_the_summary_and_can_fail_on_contradicted(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    code = run(
        {
            "CLAIMCHECK_PATH": str(FIXTURE),
            "CLAIMCHECK_REPLAY": str(REPLAY),
            "CLAIMCHECK_FAIL_ON": "contradicted",
            "CLAIMCHECK_COMMENT": "false",
            "GITHUB_STEP_SUMMARY": str(summary),
        }
    )
    assert code == 1
    text = summary.read_text(encoding="utf-8")
    assert "contradicted 2" in text
    assert "No base and head commits were provided" in text
    quiet = tmp_path / "quiet.md"
    assert (
        run(
            {
                "CLAIMCHECK_PATH": str(FIXTURE),
                "CLAIMCHECK_REPLAY": str(REPLAY),
                "CLAIMCHECK_FAIL_ON": "none",
                "GITHUB_STEP_SUMMARY": str(quiet),
            }
        )
        == 0
    )


def test_diff_highlights_only_the_edited_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=GIT_ENV)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=GIT_ENV)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True, env=GIT_ENV)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=GIT_ENV,
    ).stdout.strip()
    facts = (repo / "tinylib" / "facts.py").read_text(encoding="utf-8")
    facts = facts.replace(
        "does not check for contradictions.",
        "does not check for contradictions. Edited.",
    )
    (repo / "tinylib" / "facts.py").write_text(facts, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=GIT_ENV)
    subprocess.run(["git", "commit", "-q", "-m", "edit"], cwd=repo, check=True, env=GIT_ENV)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=GIT_ENV,
    ).stdout.strip()
    summary = tmp_path / "summary.md"
    code = run(
        {
            "CLAIMCHECK_PATH": str(repo),
            "CLAIMCHECK_REPLAY": str(REPLAY),
            "CLAIMCHECK_FAIL_ON": "none",
            "CLAIMCHECK_BASE_SHA": base,
            "CLAIMCHECK_HEAD_SHA": head,
            "GITHUB_STEP_SUMMARY": str(summary),
        }
    )
    assert code == 0
    text = summary.read_text(encoding="utf-8")
    touched = text.split("## Claims touched by this pull request", 1)[1]
    touched = touched.split("# ClaimCheck report", 1)[0]
    assert "contradictions in stored facts" in touched
    assert "tinylib/facts.py" in touched
    assert "SQLite database" not in touched


def test_comment_flag_uses_the_injected_client_and_not_the_network(tmp_path: Path) -> None:
    client = FakeComments([{"id": "15", "body": f"{COMMENT_MARKER}\nprevious"}])
    summary = tmp_path / "summary.md"
    code = run(
        {
            "CLAIMCHECK_PATH": str(FIXTURE),
            "CLAIMCHECK_REPLAY": str(REPLAY),
            "CLAIMCHECK_COMMENT": "true",
            "CLAIMCHECK_PR_NUMBER": "8",
            "CLAIMCHECK_REPOSITORY": "example/repo",
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        commenter=client,
    )
    assert code == 0
    assert client.created == []
    assert len(client.updated) == 1
    assert client.updated[0][0] == 15
    assert COMMENT_MARKER in client.updated[0][1]


def test_action_and_example_workflow_keep_comment_and_fail_on_off() -> None:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    example = (ROOT / "docs" / "example-workflow.yml").read_text(encoding="utf-8")
    assert "using: composite" in action
    assert "fail-on:" in action
    assert 'default: "false"' in action
    assert "api-key-secret-name:" in action
    assert "pull_request:" in example
    assert "README.md" in example
    assert "fail-on: none" in example
    assert "comment: false" in example
    assert "api-key-secret-name: CLAIMCHECK_API_KEY" in example
    assert "has not been executed on" in example


def _report() -> Report:
    from datetime import datetime, timezone

    claims = [
        _claim("c001", "The index function writes SQLite.", 5),
        _claim("c002", "It detects contradictions before saving.", 7),
        _claim("c003", "It exposes a GraphQL endpoint.", 9),
    ]
    verdicts = [
        Verdict(
            claim_id="c001",
            label=Label.supported,
            evidence=[Evidence(path="tinylib/index.py", line=6, quote="def index_notes")],
            rationale="The function exists.",
        ),
        Verdict(
            claim_id="c002",
            label=Label.contradicted,
            evidence=[
                Evidence(path="tinylib/facts.py", line=5, quote="does not check for contradictions")
            ],
            rationale="The docstring says it does not check.",
        ),
        Verdict(
            claim_id="c003",
            label=Label.not_found,
            rationale="No line mentions GraphQL.",
        ),
    ]
    return Report(
        tool_version="0.3.0",
        mode="test",
        project="demo",
        readme_path="README.md",
        generated_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        claims=claims,
        verdicts=verdicts,
    )


def _claim(claim_id: str, text: str, line: int) -> Claim:
    return Claim(
        id=claim_id,
        text=text,
        kind=ClaimKind.feature,
        checkable=True,
        readme_path="README.md",
        readme_line=line,
        readme_line_end=line,
        quote=text,
    )
