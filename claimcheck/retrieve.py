"""Find lines a verdict is allowed to cite.

Three sources: a Python symbol index (with a small name pattern for other
files), a lexical line search, and parsers for benchmark JSON, CSV, and logs.
Numbers in a claim are compared to parsed measurements here, in code.
"""

import ast
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
}
_TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".md",
    ".rst",
    ".txt",
    ".json",
    ".csv",
    ".log",
    ".out",
    ".toml",
    ".yml",
    ".yaml",
    ".js",
    ".ts",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".sh",
}
_MAX_BYTES = 1_000_000
_MAX_SNIPPETS = 12
_PERCENT_TOLERANCE = 0.5
_NAME_PATTERN = re.compile(r"^(?:def|class|function|fn|func)\s+([A-Za-z_][\w]*)", re.MULTILINE)
_PERCENT = re.compile(r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*%")
_RATIO = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)x\b", re.IGNORECASE)
_LOG_MEASUREMENT = re.compile(
    r"(?P<metric>[A-Za-z][A-Za-z0-9_@./-]{1,60})\s*[:=]\s*(?P<value>[+-]?\d+(?:\.\d+)?%?)"
)
_STOP = frozenset(
    """
    a an the of to and or in on for with from as is are was were be this that
    it its by at into your you we our their they them but if than then so such
    before after not no nor function method class return value data
    """.split()
)


@dataclass(frozen=True)
class Snippet:
    """One citable line. The quote is the file text, not a model paraphrase."""

    path: str
    line: int
    line_end: int
    text: str
    origin: str

    @property
    def citation(self) -> str:
        if self.line_end != self.line:
            return f"{self.path}:{self.line}-{self.line_end}"
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class ClaimNumber:
    """A measurement stated in a claim. Bare integers such as the 5 in R@5 are not included."""

    raw: str
    value: float
    is_percent: bool


@dataclass(frozen=True)
class Measurement:
    """A number read from a benchmark JSON, CSV, or log file."""

    path: str
    line: int
    metric: str
    value: float
    raw: str

    def percent_points(self) -> float | None:
        """Scale a fraction to percent points. Exactly 1 with no % sign is ambiguous."""
        if self.raw.endswith("%"):
            return self.value
        if self.value == 1:
            return None
        if 0 <= self.value <= 1:
            return self.value * 100
        return self.value


@dataclass(frozen=True)
class NumericJudgment:
    """How claim numbers compare to parsed measurements. ``absent`` means no shared metric word."""

    relation: str
    measurements: tuple[Measurement, ...]
    detail: str


def retrieve(root: Path, claim_text: str, *, readme: Path | None = None) -> list[Snippet]:
    """Snippets the model may cite for this claim, in a stable order."""
    readme_resolved = readme.resolve() if readme is not None else None
    numbers = claim_numbers(claim_text)
    measurements = parse_benchmarks(root, skip=readme_resolved)
    judgment = compare_numbers(claim_text, numbers, measurements)
    chosen: list[Snippet] = []
    seen: set[tuple[str, int]] = set()

    def add(snippet: Snippet) -> None:
        key = (snippet.path, snippet.line)
        if key in seen or len(chosen) >= _MAX_SNIPPETS:
            return
        if not snippet.text.strip():
            return
        seen.add(key)
        chosen.append(snippet)

    for measurement in judgment.measurements:
        add(
            Snippet(
                path=measurement.path,
                line=measurement.line,
                line_end=measurement.line,
                text=_line_text(root, measurement.path, measurement.line),
                origin=(
                    f"benchmark file; parsed {measurement.metric}={measurement.raw} "
                    f"({judgment.relation})"
                ),
            )
        )
    for symbol_line, symbol_path, symbol_name in symbol_hits(
        root, claim_text, skip=readme_resolved
    ):
        add(
            Snippet(
                path=symbol_path,
                line=symbol_line,
                line_end=symbol_line,
                text=_line_text(root, symbol_path, symbol_line),
                origin=f"symbol index; {symbol_name}",
            )
        )
    for path, line, text in search_hits(root, claim_text, skip=readme_resolved):
        add(Snippet(path=path, line=line, line_end=line, text=text, origin="text search"))
    return chosen


def judge_numbers(claim_text: str, root: Path, *, readme: Path | None = None) -> NumericJudgment:
    """Compare numbers in the claim to parsed benchmark files."""
    skip = readme.resolve() if readme is not None else None
    return compare_numbers(claim_text, claim_numbers(claim_text), parse_benchmarks(root, skip=skip))


def claim_numbers(text: str) -> list[ClaimNumber]:
    """Percents, then ``30x`` ratios, then decimals. Bare integers are parameters, not scores."""
    percents = [
        ClaimNumber(raw=f"{match.group(1)}%", value=float(match.group(1)), is_percent=True)
        for match in _PERCENT.finditer(text)
    ]
    if percents:
        return percents
    ratios = [
        ClaimNumber(raw=f"{match.group(1)}x", value=float(match.group(1)), is_percent=False)
        for match in _RATIO.finditer(text)
    ]
    if ratios:
        return ratios
    return []


def compare_numbers(
    claim_text: str, numbers: list[ClaimNumber], measurements: list[Measurement]
) -> NumericJudgment:
    """Pair the claim with measurements that share a metric word."""
    if not numbers:
        return NumericJudgment("absent", (), "The claim states no percent or Nx ratio to compare.")
    claim_tokens = content_tokens(claim_text)
    grouped: dict[str, list[Measurement]] = {}
    for measurement in measurements:
        if content_tokens(measurement.metric) & claim_tokens:
            grouped.setdefault(measurement.metric, []).append(measurement)
    if not grouped:
        return NumericJudgment(
            "absent",
            (),
            "No parsed JSON, CSV, or log metric shares a word with the claim.",
        )
    relations: dict[str, str] = {}
    for metric, rows in grouped.items():
        relations[metric] = _metric_relation(numbers, rows)
    kinds = set(relations.values())
    if "ambiguous" in kinds or ({"match", "conflict"} <= kinds):
        return NumericJudgment(
            "ambiguous",
            tuple(row for rows in grouped.values() for row in rows),
            "More than one related metric, and they do not agree about the claim.",
        )
    relation = "match" if kinds == {"match"} else "conflict"
    chosen = tuple(
        row for metric, rows in grouped.items() if relations[metric] == relation for row in rows
    )
    detail = _detail(relation, numbers, chosen)
    return NumericJudgment(relation, chosen, detail)


def parse_benchmarks(root: Path, *, skip: Path | None = None) -> list[Measurement]:
    """Read numeric leaves from benchmark-like JSON, CSV, and log files."""
    found: list[Measurement] = []
    for path in iter_files(root):
        if skip is not None and path.resolve() == skip:
            continue
        suffix = path.suffix.casefold()
        relative = _relative(root, path)
        text = _read_text(path)
        if text is None:
            continue
        if suffix == ".json" and _looks_like_results(path, text):
            found.extend(_parse_json(relative, text))
        elif suffix == ".csv":
            found.extend(_parse_csv(relative, text))
        elif suffix in {".log", ".out"} or "benchmark" in relative.casefold():
            if suffix not in {".json", ".csv", ".py"}:
                found.extend(_parse_log(relative, text))
    return found


def symbol_hits(
    root: Path, claim_text: str, *, skip: Path | None = None
) -> list[tuple[int, str, str]]:
    """Definitions whose names appear in the claim. ``(line, relative path, name)``."""
    folded = claim_text.casefold()
    hits: list[tuple[int, str, str]] = []
    for path in iter_files(root):
        if skip is not None and path.resolve() == skip:
            continue
        relative = _relative(root, path)
        for name, line in _symbols_in(path):
            if name.casefold() in folded:
                hits.append((line, relative, name))
    hits.sort(key=lambda item: (item[1], item[0], item[2]))
    return hits


def search_hits(
    root: Path, claim_text: str, *, skip: Path | None = None, limit: int = 8
) -> list[tuple[str, int, str]]:
    """Lines that share content words with the claim, highest overlap first."""
    needles = content_tokens(claim_text)
    if not needles:
        return []
    scored: list[tuple[int, str, int, str]] = []
    for path in iter_files(root):
        if skip is not None and path.resolve() == skip:
            continue
        text = _read_text(path)
        if text is None:
            continue
        relative = _relative(root, path)
        for number, line in enumerate(text.splitlines(), start=1):
            overlap = len(content_tokens(line) & needles)
            if overlap:
                scored.append((overlap, relative, number, line.strip()))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [(path, line, text) for _, path, line, text in scored[:limit]]


def display_words(text: str) -> list[str]:
    """Content words as they appear, for rationales. Matching uses content_tokens."""
    words: set[str] = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_+-]*", text):
        token = raw.casefold()
        if len(token) <= 2 or token in _STOP:
            continue
        words.add(token)
    return sorted(words)


def content_tokens(text: str) -> set[str]:
    """Words used to pair a claim with a metric or a source line. Digits are dropped."""
    found: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9_+%-]+", text):
        for part in raw.split("_"):
            token = part.casefold().strip("%+")
            if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
                token = token[:-1]
            if len(token) <= 2 or token in _STOP or any(character.isdigit() for character in token):
                continue
            found.add(token)
    return found


def iter_files(root: Path):
    """Text files under root, skipping dependency and VCS directories."""
    root = root.resolve()
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.casefold() not in _TEXT_SUFFIXES and "benchmark" not in path.as_posix():
            continue
        try:
            if path.stat().st_size > _MAX_BYTES:
                continue
        except OSError:
            continue
        yield path


def _symbols_in(path: Path) -> list[tuple[str, int]]:
    text = _read_text(path)
    if text is None:
        return []
    if path.suffix.casefold() == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            found: list[tuple[str, int]] = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    found.append((node.name, node.lineno))
            return found
    return [
        (match.group(1), text[: match.start()].count("\n") + 1)
        for match in _NAME_PATTERN.finditer(text)
    ]


def _parse_json(relative: str, text: str) -> list[Measurement]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    found: list[Measurement] = []

    def walk(node: object, metric: str | None) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)) and metric:
            raw = _raw_number(text, metric, node)
            found.append(
                Measurement(
                    path=relative,
                    line=_line_of(text, f'"{metric}"'),
                    metric=metric,
                    value=float(node),
                    raw=raw,
                )
            )
            return
        if isinstance(node, dict):
            metric_name = node.get("metric", node.get("name"))
            if (
                isinstance(metric_name, str)
                and "value" in node
                and isinstance(node["value"], (int, float))
            ):
                if not isinstance(node["value"], bool):
                    found.append(
                        Measurement(
                            path=relative,
                            line=_line_of(text, f'"{metric_name}"'),
                            metric=metric_name,
                            value=float(node["value"]),
                            raw=_raw_number(text, metric_name, node["value"]),
                        )
                    )
            for key, value in node.items():
                if key in {"metric", "name", "value"} and isinstance(metric_name, str):
                    continue
                walk(value, key if isinstance(key, str) else metric)
        elif isinstance(node, list):
            for item in node:
                walk(item, metric)

    walk(data, None)
    return found


def _parse_csv(relative: str, text: str) -> list[Measurement]:
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return []
    header = [cell.strip() for cell in rows[0]]
    folded = [cell.casefold() for cell in header]
    found: list[Measurement] = []
    if "metric" in folded and "value" in folded:
        metric_index = folded.index("metric")
        value_index = folded.index("value")
        for offset, row in enumerate(rows[1:], start=2):
            if len(row) <= max(metric_index, value_index):
                continue
            number = _float_token(row[value_index])
            if number is None or not row[metric_index].strip():
                continue
            found.append(
                Measurement(
                    path=relative,
                    line=offset,
                    metric=row[metric_index].strip(),
                    value=number[0],
                    raw=number[1],
                )
            )
        return found
    for column, name in enumerate(header):
        if not name or name.casefold() in {"metric", "name"}:
            continue
        for offset, row in enumerate(rows[1:], start=2):
            if column >= len(row):
                continue
            number = _float_token(row[column])
            if number is None:
                continue
            found.append(
                Measurement(
                    path=relative,
                    line=offset,
                    metric=name,
                    value=number[0],
                    raw=number[1],
                )
            )
    return found


def _parse_log(relative: str, text: str) -> list[Measurement]:
    found: list[Measurement] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _LOG_MEASUREMENT.finditer(line):
            number_token = _float_token(match.group("value"))
            if number_token is None:
                continue
            found.append(
                Measurement(
                    path=relative,
                    line=number,
                    metric=match.group("metric").strip(),
                    value=number_token[0],
                    raw=number_token[1],
                )
            )
    return found


def _metric_relation(numbers: list[ClaimNumber], rows: list[Measurement]) -> str:
    outcomes = {_agree(number, row) for number in numbers for row in rows}
    if "ambiguous" in outcomes or ({"match", "conflict"} <= outcomes):
        return "ambiguous"
    if outcomes == {"match"}:
        return "match"
    return "conflict"


def _agree(number: ClaimNumber, measurement: Measurement) -> str:
    if number.is_percent:
        points = measurement.percent_points()
        if points is None:
            return "ambiguous"
        return "match" if abs(number.value - points) <= _PERCENT_TOLERANCE else "conflict"
    return "match" if abs(number.value - measurement.value) <= _PERCENT_TOLERANCE else "conflict"


def _detail(relation: str, numbers: list[ClaimNumber], rows: tuple[Measurement, ...]) -> str:
    claimed = ", ".join(number.raw for number in numbers)
    found = ", ".join(f"{row.metric}={row.raw} at {row.path}:{row.line}" for row in rows)
    if relation == "match":
        return f"Claimed {claimed}; parsed measurements agree: {found}."
    return f"Claimed {claimed}; parsed measurements disagree: {found}."


def _looks_like_results(path: Path, text: str) -> bool:
    name = path.as_posix().casefold()
    if any(piece in name for piece in ("benchmark", "result", "score", "metric")):
        return True
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if isinstance(data, dict) and {"dependencies", "devdependencies", "scripts"} & {
        key.casefold() for key in data
    }:
        return False
    return _has_number(data)


def _has_number(node: object) -> bool:
    if isinstance(node, bool) or node is None:
        return False
    if isinstance(node, (int, float)):
        return True
    if isinstance(node, dict):
        return any(_has_number(value) for value in node.values())
    if isinstance(node, list):
        return any(_has_number(item) for item in node)
    return False


def _float_token(raw: str) -> tuple[float, str] | None:
    text = raw.strip()
    if not text:
        return None
    percent = text.endswith("%")
    body = text[:-1] if percent else text
    try:
        value = float(body)
    except ValueError:
        return None
    return value, text


def _raw_number(text: str, metric: str, value: float) -> str:
    pattern = re.compile(rf'"{re.escape(metric)}"\s*:\s*([+-]?\d+(?:\.\d+)?)')
    match = pattern.search(text)
    if match:
        return match.group(1)
    return format(value, "g")


def _line_of(text: str, needle: str) -> int:
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    return 1


def _line_text(root: Path, relative: str, line: int) -> str:
    path = root / relative
    file_text = _read_text(path)
    if file_text is None:
        return ""
    rows = file_text.splitlines()
    if line < 1 or line > len(rows):
        return ""
    return rows[line - 1].strip()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
