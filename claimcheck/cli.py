"""Command line: extract claims, or scan a tree and write a report."""

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from claimcheck.checkout import cloned_repo, project_name_from_source
from claimcheck.constants import __version__
from claimcheck.errors import CheckoutError, ClaimCheckError, ConfigError, ReadmeError
from claimcheck.extract import extract_claims
from claimcheck.format import format_extraction, render_json, render_markdown
from claimcheck.llm import OpenAICompatibleClient, load_config_from_env, load_replay
from claimcheck.models import Label
from claimcheck.readme import is_git_url, load_readme
from claimcheck.scan import build_report, project_name, repo_root_for


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns a process status code and does not call sys.exit."""
    try:
        return _main(argv)
    except (ConfigError, ReadmeError, CheckoutError) as exc:
        print(f"claimcheck: {exc}", file=sys.stderr)
        return 2
    except ClaimCheckError as exc:
        print(f"claimcheck: {exc}", file=sys.stderr)
        return 1


def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        prog="claimcheck",
        description=(
            "Extract README claims and, with scan, compare them to code and benchmark files. "
            "A contradicted label is kept only after a second pass."
        ),
    )
    parser.add_argument("--version", action="version", version=f"claimcheck {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="Print claims found in a README")
    _add_common(extract)
    extract.add_argument("--json", action="store_true", help="Print the extraction as JSON")
    extract.add_argument("--output", type=Path, help="Also write the extraction JSON to this file")

    scan = subparsers.add_parser(
        "scan",
        help="Write report.md and report.json with one verdict per checkable claim",
    )
    _add_common(scan)
    scan.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for report.md and report.json (default: the working directory)",
    )

    args = parser.parse_args(argv)
    if args.max_attempts < 1:
        print("claimcheck: --max-attempts must be at least 1", file=sys.stderr)
        return 2

    source = args.path
    remote = is_git_url(source)
    if remote or args.revision:
        clone_source = source if remote else str(Path(source).resolve())
        with cloned_repo(clone_source, args.revision) as root:
            return _run(args, root, project_name_from_source(clone_source))
    return _run(args, Path(source), None)


def _run(args: argparse.Namespace, path: Path, project: str | None) -> int:
    document = load_readme(path)
    client = _client(args.replay)
    if args.command == "extract":
        result = extract_claims(document, client, max_attempts=args.max_attempts)
        payload = result.model_dump_json(indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        sys.stdout.write(payload if args.json else format_extraction(result))
        return 0

    report = build_report(
        document,
        client,
        repo_root=repo_root_for(path if path.is_dir() else document.path),
        project=project or project_name(document),
        generated_at=datetime.now(timezone.utc),
        max_attempts=args.max_attempts,
    )
    output_dir = args.output_dir if args.output_dir is not None else Path(".")
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "report.md"
    json_path = output_dir / "report.json"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(render_json(report), encoding="utf-8")
    counts = Counter(verdict.label.value for verdict in report.verdicts)
    summary = ", ".join(f"{label.value} {counts[label.value]}" for label in Label)
    print(f"Wrote {markdown_path} and {json_path}. {len(report.verdicts)} verdict(s): {summary}.")
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", help="Local README or directory, or a git URL")
    parser.add_argument(
        "--revision",
        help="Commit, branch, or tag to check out in a fresh clone. Implies a clone.",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        help=(
            "Use recorded model responses instead of calling an API. "
            "A JSON list of strings is one response per attempt, in call order."
        ),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="How many model responses to accept before failing a call (default: 3)",
    )


def _client(replay: Path | None):
    if replay is not None:
        return load_replay(replay)
    config = load_config_from_env()
    return OpenAICompatibleClient(config)
