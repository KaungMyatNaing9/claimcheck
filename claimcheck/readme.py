"""Load a README and map a quote back to the line it came from.

Line numbers are 1-based and inclusive. The mapper checks the model's quote
against the file. It does not trust the line number the model reports.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from claimcheck.errors import ReadmeError

_README_NAMES = ("README.md", "README.markdown", "README.mdown", "readme.md")
_GIT_URL = re.compile(r"^(https?://|ssh://|git://|file://|git@)")
_LEADING_LINE_PREFIX = re.compile(r"^\d+\|")


@dataclass(frozen=True)
class QuoteSpan:
    """Where a quote sits in the README."""

    start: int
    end: int
    ignored_emphasis: bool


@dataclass(frozen=True)
class ReadmeDocument:
    """A README split into lines, without trailing newlines."""

    path: Path
    display_path: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def is_git_url(value: str) -> bool:
    """True for a remote git URL. Local paths, including ones that contain @, are not."""
    text = value.strip()
    if not text or text.startswith(".") or text.startswith("/") or text.startswith("~"):
        return False
    # Windows and relative paths are local even if a name ends in .git.
    if "\\" in text or text.startswith("./") or text.startswith("../"):
        return False
    return _GIT_URL.match(text) is not None


def resolve_readme(path: Path) -> Path:
    """Return the README file for a file or directory path."""
    if path.is_file():
        return path
    if path.is_dir():
        for name in _README_NAMES:
            candidate = path / name
            if candidate.is_file():
                return candidate
        raise ReadmeError(
            f"No README.md in {path}. Pass a README file or a directory that contains one."
        )
    raise ReadmeError(f"Path does not exist: {path}")


def display_path(path: Path) -> str:
    """Prefer a path relative to the working directory so reports stay portable."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def load_readme(path: Path) -> ReadmeDocument:
    """Read a README as UTF-8. Reject directories and missing files first."""
    file_path = resolve_readme(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReadmeError(f"{file_path} is not UTF-8") from exc
    except OSError as exc:
        raise ReadmeError(f"Could not read {file_path}: {exc}") from exc
    return ReadmeDocument(
        path=file_path,
        display_path=display_path(file_path),
        lines=tuple(text.splitlines()),
    )


def numbered_text(document: ReadmeDocument) -> str:
    """README text with `N|` prefixes so a model can cite lines. The mapper strips them."""
    return "\n".join(f"{number}|{line}" for number, line in enumerate(document.lines, start=1))


def locate_quote(lines: tuple[str, ...] | list[str], quote: str) -> list[QuoteSpan]:
    """Find every span whose text contains `quote`.

    Matching ignores runs of whitespace. A leading `12|` prefix, which the
    prompt adds, is stripped. If the quote only matches after Markdown
    emphasis markers are removed, the span says so.
    """
    cleaned = quote.strip()
    cleaned = _LEADING_LINE_PREFIX.sub("", cleaned).strip()
    if not cleaned:
        return []
    exact = _find_spans(lines, cleaned, ignored_emphasis=False)
    if exact:
        return exact
    return _find_spans(lines, _strip_emphasis(cleaned), ignored_emphasis=True)


def choose_span(spans: list[QuoteSpan], hint: int | None) -> QuoteSpan:
    """Pick the span the model pointed at, or the earliest span."""
    if hint is not None:
        for span in spans:
            if span.start <= hint <= span.end:
                return span
    return min(spans, key=lambda span: (span.start, span.end))


def _strip_emphasis(text: str) -> str:
    return text.replace("*", "").replace("_", "")


def _normalize_line(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def _find_spans(
    lines: tuple[str, ...] | list[str], needle: str, *, ignored_emphasis: bool
) -> list[QuoteSpan]:
    needle_norm = _normalize_line(needle)
    if not needle_norm:
        return []
    haystack, owners = _indexed_text(lines, strip_emphasis=ignored_emphasis)
    spans: list[QuoteSpan] = []
    start = 0
    while True:
        index = haystack.find(needle_norm, start)
        if index < 0:
            break
        covered = [owner for owner in owners[index : index + len(needle_norm)] if owner is not None]
        if covered:
            spans.append(
                QuoteSpan(start=covered[0], end=covered[-1], ignored_emphasis=ignored_emphasis)
            )
        start = index + 1
    return _unique_spans(spans)


def _indexed_text(
    lines: tuple[str, ...] | list[str], *, strip_emphasis: bool
) -> tuple[str, list[int | None]]:
    parts: list[str] = []
    owners: list[int | None] = []
    for number, line in enumerate(lines, start=1):
        text = _strip_emphasis(line) if strip_emphasis else line
        normalized = _normalize_line(text)
        if not normalized:
            continue
        if parts:
            parts.append(" ")
            owners.append(None)
        parts.append(normalized)
        owners.extend([number] * len(normalized))
    return "".join(parts), owners


def _unique_spans(spans: list[QuoteSpan]) -> list[QuoteSpan]:
    seen: set[tuple[int, int, bool]] = set()
    unique: list[QuoteSpan] = []
    for span in spans:
        key = (span.start, span.end, span.ignored_emphasis)
        if key in seen:
            continue
        seen.add(key)
        unique.append(span)
    return unique
