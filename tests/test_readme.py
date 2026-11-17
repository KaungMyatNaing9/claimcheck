"""README loading and quote-to-line mapping."""

from pathlib import Path

import pytest
from claimcheck.errors import ReadmeError
from claimcheck.readme import choose_span, is_git_url, load_readme, locate_quote, resolve_readme


def test_directory_resolves_to_readme(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n\nHello\n", encoding="utf-8")
    document = load_readme(tmp_path)
    assert document.lines == ("# Title", "", "Hello")
    assert document.path == readme


def test_missing_readme_names_the_directory(tmp_path: Path) -> None:
    with pytest.raises(ReadmeError, match="No README.md"):
        resolve_readme(tmp_path)


def test_git_urls_are_not_local_paths() -> None:
    assert is_git_url("https://github.com/MemPalace/mempalace.git")
    assert is_git_url("git@github.com:MemPalace/mempalace.git")
    assert is_git_url("ssh://git@github.com/MemPalace/mempalace.git")
    assert is_git_url("file:///tmp/example-repo")
    assert not is_git_url("README.md")
    assert not is_git_url("./repo.git")
    assert not is_git_url("/tmp/repo")


def test_quote_maps_to_the_line_that_contains_it() -> None:
    lines = ("alpha", "beta gamma", "delta")
    spans = locate_quote(lines, "beta gamma")
    assert [(span.start, span.end) for span in spans] == [(2, 2)]


def test_quote_can_span_lines_and_ignore_extra_whitespace() -> None:
    lines = ("alpha beta", "gamma delta")
    span = choose_span(locate_quote(lines, "beta   gamma"), hint=None)
    assert (span.start, span.end) == (1, 2)


def test_emphasis_markers_do_not_block_a_match() -> None:
    lines = ("**Closets** — compressed summaries",)
    span = choose_span(locate_quote(lines, "Closets — compressed summaries"), hint=None)
    assert span.start == 1
    assert span.ignored_emphasis


def test_hint_selects_the_later_copy() -> None:
    lines = ("same words", "other", "same words")
    spans = locate_quote(lines, "same words")
    chosen = choose_span(spans, hint=3)
    assert chosen.start == 3


def test_prompt_line_prefix_is_stripped() -> None:
    lines = ("only this",)
    span = choose_span(locate_quote(lines, "1|only this"), hint=None)
    assert span.start == 1


def test_missing_quote_returns_no_span() -> None:
    assert locate_quote(("alpha",), "not in the file") == []
