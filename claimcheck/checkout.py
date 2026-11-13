"""Clone a git URL into a temporary directory and optionally check out a revision.

The clone is explicit: git is invoked with a argument list, and the result is
a new directory. A local working tree is not checked out in place.
"""

import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from claimcheck.errors import CheckoutError

_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def project_name_from_source(source: str) -> str:
    """Last path segment of a URL or filesystem path, without a trailing .git."""
    name = source.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return name or "repo"


@contextmanager
def cloned_repo(source: str, revision: str | None = None) -> Iterator[Path]:
    """Yield a fresh clone. The directory is deleted when the caller finishes."""
    with tempfile.TemporaryDirectory(prefix="claimcheck-") as temporary:
        destination = Path(temporary) / "repo"
        clone_repo(source, revision, destination)
        yield destination


def clone_repo(source: str, revision: str | None, destination: Path) -> None:
    """Run git clone, then git checkout when a revision was requested."""
    if revision is not None and (revision.startswith("-") or _REVISION.fullmatch(revision) is None):
        raise CheckoutError(f"Revision {revision!r} is not a commit, branch, or tag name.")
    _run(["git", "clone", "--quiet", source, str(destination)], "git clone")
    if revision is not None:
        _run(["git", "-C", str(destination), "checkout", "--quiet", revision], "git checkout")


def _run(args: list[str], what: str) -> None:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CheckoutError("git is not installed, so a repository URL cannot be cloned.") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckoutError(f"{what} timed out after 180 seconds.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"{what} failed").strip()
        raise CheckoutError(f"{what} failed: {detail[:500]}")
