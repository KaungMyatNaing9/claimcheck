"""GitHub Action entry point.

Runs a scan of the checked-out repository, appends the report to the job
summary, and optionally updates one pull request comment. Comment posting is
off unless the workflow sets it. This module is what the tests call. The
composite action in action.yml only sets environment variables and starts it.
"""

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from claimcheck.action_report import (
    PullRequestDiff,
    fail_on_code,
    highlights_for,
    parse_hunks,
    parse_name_status,
    render_comment,
    render_job_summary,
)
from claimcheck.errors import ClaimCheckError
from claimcheck.llm import OpenAICompatibleClient, load_config_from_env, load_replay
from claimcheck.readme import load_readme
from claimcheck.scan import build_report, project_name, repo_root_for

_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class CommentError(ClaimCheckError):
    """The optional pull request comment could not be posted or updated."""


class PullRequestCommenter:
    """GitHub issue-comment API. Tests use a stand-in with the same three methods."""

    def list_comments(self, repository: str, number: int) -> list[dict[str, object]]:
        raise NotImplementedError

    def create_comment(self, repository: str, number: int, body: str) -> None:
        raise NotImplementedError

    def update_comment(self, repository: str, comment_id: int, body: str) -> None:
        raise NotImplementedError


def run(
    env: Mapping[str, str] | None = None,
    *,
    commenter: PullRequestCommenter | None = None,
) -> int:
    """Scan, write the summary, then apply fail-on. Returns a process status."""
    settings = dict(os.environ if env is None else env)
    try:
        fail_on = _fail_on(settings)
        path = Path(settings.get("CLAIMCHECK_PATH", ".") or ".")
        document = load_readme(path)
        root = repo_root_for(path if path.is_dir() else document.path)
        client = _client(settings)
        report = build_report(document, client, repo_root=root, project=project_name(document))
        diff = load_diff(
            root,
            settings.get("CLAIMCHECK_BASE_SHA", ""),
            settings.get("CLAIMCHECK_HEAD_SHA", ""),
        )
        highlights = highlights_for(report, diff)
        summary = render_job_summary(report, diff, highlights)
        _write_summary(settings, summary)
        _write_output(settings, report)
        if _as_bool(settings.get("CLAIMCHECK_COMMENT", "false")):
            _comment(settings, render_comment(report, diff, highlights), commenter)
        return fail_on_code(report, fail_on)
    except CommentError as exc:
        print(f"claimcheck: {exc}", file=sys.stderr)
        _write_summary(settings, f"\nThe pull request comment was not posted.\n\n{exc}\n")
        return 1
    except ClaimCheckError as exc:
        print(f"claimcheck: {exc}", file=sys.stderr)
        _write_summary(settings, f"# ClaimCheck\n\nThe scan failed.\n\n{exc}\n")
        return 1


def load_diff(root: Path, base: str, head: str) -> PullRequestDiff:
    """Read a pull request diff. A missing or unreadable diff does not fail the scan."""
    base = base.strip()
    head = head.strip()
    if not base or not head:
        return PullRequestDiff(
            available=False,
            note="No base and head commits were provided, so claims are not marked against a diff.",
            files={},
        )
    if not _safe_revision(base) or not _safe_revision(head):
        return PullRequestDiff(
            available=False,
            note="The base or head value is not a commit name, so the diff was skipped.",
            files={},
        )
    status = _git(root, ["diff", "--name-status", f"{base}...{head}"])
    if status.returncode != 0:
        status = _git(root, ["diff", "--name-status", base, head])
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "git diff failed").strip()
        return PullRequestDiff(
            available=False,
            note=f"git diff failed, so claims are not marked against a diff: {detail[:300]}",
            files={},
        )
    names = parse_name_status(status.stdout)
    files: dict[str, tuple[tuple[int, int], ...] | None] = {}
    for path, letter in names.items():
        if letter in {"A", "D"}:
            files[path] = None
            continue
        hunk = _git(root, ["diff", "-U0", f"{base}...{head}", "--", path])
        if hunk.returncode != 0:
            hunk = _git(root, ["diff", "-U0", base, head, "--", path])
        files[path] = None if hunk.returncode != 0 else parse_hunks(hunk.stdout)
    note = (
        "Diff is empty. No claim is marked as changed."
        if not files
        else f"{len(files)} file(s) differ between the base and head commits."
    )
    return PullRequestDiff(available=True, note=note, files=files)


def upsert_comment(commenter: PullRequestCommenter, repository: str, number: int, body: str) -> str:
    """Update the existing ClaimCheck comment, or create one. Returns created or updated."""
    for comment in commenter.list_comments(repository, number):
        existing = comment.get("body")
        if isinstance(existing, str) and "<!-- claimcheck-report -->" in existing:
            comment_id = comment.get("id")
            if isinstance(comment_id, int) or (
                isinstance(comment_id, str) and comment_id.isdigit()
            ):
                commenter.update_comment(repository, int(comment_id), body)
                return "updated"
    commenter.create_comment(repository, number, body)
    return "created"


def main() -> int:
    """Process entry used by `python -m claimcheck.action`."""
    return run()


def _client(settings: Mapping[str, str]):
    replay = settings.get("CLAIMCHECK_REPLAY", "").strip()
    if replay:
        return load_replay(Path(replay))
    key = _api_key(settings)
    model = settings.get("CLAIMCHECK_MODEL", "").strip()
    base_url = settings.get("CLAIMCHECK_BASE_URL", "").strip() or "https://api.openai.com/v1"
    if not model:
        from claimcheck.errors import ConfigError

        raise ConfigError(
            "Set the model input, or CLAIMCHECK_REPLAY for a recorded response. "
            "The action does not pick a default model."
        )
    keys = ("CLAIMCHECK_MODEL", "CLAIMCHECK_BASE_URL", "CLAIMCHECK_API_KEY")
    saved = {name: os.environ.get(name) for name in keys}
    os.environ["CLAIMCHECK_MODEL"] = model
    os.environ["CLAIMCHECK_BASE_URL"] = base_url
    if key is None:
        os.environ.pop("CLAIMCHECK_API_KEY", None)
    else:
        os.environ["CLAIMCHECK_API_KEY"] = key
    try:
        config = load_config_from_env()
    finally:
        for name, previous in saved.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
    return OpenAICompatibleClient(config)


def _api_key(settings: Mapping[str, str]) -> str | None:
    """Prefer the api-key input. Otherwise use the env var named by api-key-secret-name.

    A composite action cannot read secrets[name] by itself. The workflow exports
    the secret into an environment variable, and this input selects that variable.
    """
    direct = settings.get("CLAIMCHECK_ACTION_API_KEY", "").strip()
    if direct:
        return direct
    secret_name = settings.get("CLAIMCHECK_API_KEY_SECRET_NAME", "CLAIMCHECK_API_KEY").strip()
    if not secret_name:
        return None
    value = settings.get(secret_name, "").strip()
    return value or None


def _comment(
    settings: Mapping[str, str], body: str, commenter: PullRequestCommenter | None
) -> None:
    number_text = settings.get("CLAIMCHECK_PR_NUMBER", "").strip()
    repository = settings.get("CLAIMCHECK_REPOSITORY", "").strip()
    if not number_text or not repository:
        raise CommentError(
            "comment is true, but the pull request number or repository was not provided."
        )
    try:
        number = int(number_text)
    except ValueError as exc:
        raise CommentError(f"Pull request number {number_text!r} is not an integer.") from exc
    token = settings.get("GITHUB_TOKEN", "")
    client = commenter if commenter is not None else GitHubCommenter(token)
    upsert_comment(client, repository, number, body)


def _write_summary(settings: Mapping[str, str], text: str) -> None:
    path = settings.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def _write_output(settings: Mapping[str, str], report) -> None:
    """Write report files only when the workflow sets an output directory."""
    raw = settings.get("CLAIMCHECK_OUTPUT_DIR", "").strip()
    if not raw:
        return
    from claimcheck.format import render_json, render_markdown

    destination = Path(raw)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "claimcheck-report.md").write_text(render_markdown(report), encoding="utf-8")
    (destination / "claimcheck-report.json").write_text(render_json(report), encoding="utf-8")


def _fail_on(settings: Mapping[str, str]) -> str:
    value = settings.get("CLAIMCHECK_FAIL_ON", "none").strip().lower() or "none"
    if value not in {"none", "contradicted"}:
        from claimcheck.errors import ConfigError

        raise ConfigError("fail-on must be 'none' or 'contradicted'.")
    return value


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_revision(value: str) -> bool:
    return _REVISION.fullmatch(value) is not None


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class GitHubCommenter(PullRequestCommenter):
    """POST and PATCH issue comments. Tests pass a stand-in instead of this class."""

    def __init__(self, token: str) -> None:
        self._token = token.strip()

    def list_comments(self, repository: str, number: int) -> list[dict[str, object]]:
        comments: list[dict[str, object]] = []
        for page in range(1, 6):
            payload = self._request(
                "GET",
                f"/repos/{repository}/issues/{number}/comments?per_page=100&page={page}",
            )
            if not isinstance(payload, list) or not payload:
                break
            comments.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < 100:
                break
        return comments

    def create_comment(self, repository: str, number: int, body: str) -> None:
        self._request("POST", f"/repos/{repository}/issues/{number}/comments", {"body": body})

    def update_comment(self, repository: str, comment_id: int, body: str) -> None:
        self._request("PATCH", f"/repos/{repository}/issues/comments/{comment_id}", {"body": body})

    def _request(self, method: str, path: str, payload: dict[str, str] | None = None) -> object:
        import json
        import urllib.error
        import urllib.request

        if not self._token:
            raise CommentError("comment is true, but no github-token was provided.")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "https://api.github.com" + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise CommentError(f"GitHub comment API returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CommentError(f"GitHub comment API request failed: {exc.reason}") from exc
        if not raw:
            return None
        return json.loads(raw)


if __name__ == "__main__":
    raise SystemExit(main())
