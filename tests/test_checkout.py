"""Git URLs are cloned into a temp directory. A revision is checked out there."""

import os
import subprocess
from pathlib import Path

import pytest
from claimcheck.checkout import cloned_repo
from claimcheck.cli import main
from claimcheck.errors import CheckoutError

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "ClaimCheck",
    "GIT_AUTHOR_EMAIL": "claimcheck@example.com",
    "GIT_COMMITTER_NAME": "ClaimCheck",
    "GIT_COMMITTER_EMAIL": "claimcheck@example.com",
}


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=GIT_ENV)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True, env=GIT_ENV)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=GIT_ENV,
    )
    return sha.stdout.strip()


def test_revision_checks_out_that_commit_in_the_clone(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=origin, check=True, env=GIT_ENV)
    readme = origin / "README.md"
    readme.write_text("old text\n", encoding="utf-8")
    old = _commit(origin, "old")
    readme.write_text("new text\n", encoding="utf-8")
    _commit(origin, "new")
    with cloned_repo(origin.as_uri(), old) as checkout:
        assert (checkout / "README.md").read_text(encoding="utf-8") == "old text\n"
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
        )
        assert head.stdout.strip() == old


def test_missing_local_url_fails_without_network(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "scan",
            "file:///tmp/claimcheck-no-such-repo",
            "--replay",
            "examples/sample_extract_response.json",
        ]
    )
    assert code == 2
    assert "git clone failed" in capsys.readouterr().err


def test_bad_revision_is_rejected_before_clone() -> None:
    with pytest.raises(CheckoutError, match="Revision"):
        with cloned_repo("file:///tmp/unused", "--detach"):
            pass
