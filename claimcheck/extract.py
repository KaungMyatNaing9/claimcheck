"""Turn a README into claims by asking a model, then checking its quotes.

Malformed JSON, unknown fields that matter, and quotes that are not in the
README are rejected. The call is retried with the validator errors attached.
The line stored on a claim is the line the quote actually occupies.
"""

import json
import re
from typing import Protocol

from claimcheck.constants import __version__
from claimcheck.errors import ExtractionError
from claimcheck.models import Claim, ClaimKind, ExtractionResult
from claimcheck.prompts import SYSTEM_PROMPT, build_user_prompt, retry_note
from claimcheck.readme import ReadmeDocument, choose_span, locate_quote

_KINDS = {kind.value for kind in ClaimKind}
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class LLMClient(Protocol):
    """Anything that can answer one chat turn. ReplayClient and the HTTP client both do."""

    def complete(self, *, system: str, user: str) -> str: ...


def extract_claims(
    document: ReadmeDocument,
    client: LLMClient,
    *,
    max_attempts: int = 3,
) -> ExtractionResult:
    """Extract claims, retrying when the response fails validation."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    base_user = build_user_prompt(document)
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        user = base_user if attempt == 1 else f"{base_user}\n\n{retry_note(errors)}"
        raw = client.complete(system=SYSTEM_PROMPT, user=user)
        claims, warnings, errors = validate_model_output(document, raw)
        if errors:
            continue
        return ExtractionResult(
            tool_version=__version__,
            readme_path=document.display_path,
            claims=claims or [],
            attempts=attempt,
            warnings=warnings,
        )
    raise ExtractionError(
        f"Model output was still invalid after {max_attempts} attempts.",
        errors=errors,
        attempts=max_attempts,
    )


def validate_model_output(
    document: ReadmeDocument, raw: str
) -> tuple[list[Claim] | None, list[str], list[str]]:
    """Return claims, warnings, and errors. Errors empty means the claims are usable."""
    try:
        payload = parse_json_object(raw)
    except ValueError as exc:
        return None, [], [str(exc)]
    claims_raw = payload.get("claims")
    if not isinstance(claims_raw, list):
        return None, [], ["response JSON must contain a 'claims' array"]

    errors: list[str] = []
    warnings: list[str] = []
    drafted: list[tuple[int, int, Claim]] = []
    for index, item in enumerate(claims_raw, start=1):
        claim, item_warnings, item_errors = _one_claim(document, index, item)
        errors.extend(item_errors)
        warnings.extend(item_warnings)
        if claim is not None:
            drafted.append((claim.readme_line, index, claim))
    if errors:
        return None, [], errors

    drafted.sort(key=lambda row: (row[0], row[1]))
    claims: list[Claim] = []
    seen: set[tuple[str, int, str]] = set()
    for _, _, claim in drafted:
        key = (claim.text.strip().casefold(), claim.readme_line, claim.kind.value)
        if key in seen:
            warnings.append(
                f"Dropped a duplicate claim at {document.display_path}:{claim.readme_line}"
            )
            continue
        seen.add(key)
        claims.append(claim.model_copy(update={"id": f"c{len(claims) + 1:03d}"}))
    return claims, warnings, []


def _one_claim(
    document: ReadmeDocument, index: int, item: object
) -> tuple[Claim | None, list[str], list[str]]:
    prefix = f"claims[{index}]"
    if not isinstance(item, dict):
        return None, [], [f"{prefix} must be an object"]
    errors: list[str] = []
    text = item.get("text")
    kind = item.get("kind")
    quote = item.get("quote")
    checkable = item.get("checkable")
    skip_reason = item.get("skip_reason")
    if not isinstance(text, str) or not text.strip():
        errors.append(f"{prefix}.text must be a non-empty string")
    if not isinstance(kind, str) or kind not in _KINDS:
        errors.append(f"{prefix}.kind must be one of: {', '.join(sorted(_KINDS))}")
    if not isinstance(quote, str) or not quote.strip():
        errors.append(f"{prefix}.quote must be a non-empty string copied from the README")
    if not isinstance(checkable, bool):
        errors.append(f"{prefix}.checkable must be a JSON boolean")
    if checkable is False and (not isinstance(skip_reason, str) or not skip_reason.strip()):
        errors.append(f"{prefix}.skip_reason is required when checkable is false")
    if checkable is True and skip_reason not in (None, ""):
        errors.append(f"{prefix}.skip_reason must be null when checkable is true")
    hint, hint_error = _line_hint(item.get("line"), prefix)
    if hint_error:
        errors.append(hint_error)
    quote_ok = isinstance(quote, str)
    text_ok = isinstance(text, str)
    kind_ok = isinstance(kind, str)
    if errors or not quote_ok or not text_ok or not kind_ok:
        return None, [], errors

    spans = locate_quote(document.lines, quote)
    if not spans:
        return None, [], [f"{prefix}.quote was not found in the README: {quote.strip()[:120]!r}"]
    span = choose_span(spans, hint)
    warnings: list[str] = []
    if hint is not None and not (span.start <= hint <= span.end):
        warnings.append(
            f"{prefix} reported line {hint}, but the quote is on "
            f"line {span.start}"
            + (f"-{span.end}" if span.end != span.start else "")
            + ". The stored line is the quote's line."
        )
    if span.ignored_emphasis:
        warnings.append(
            f"{prefix} quote matched {document.display_path}:{span.start} "
            "after ignoring Markdown emphasis markers."
        )
    claim = Claim(
        id="pending",
        text=text.strip(),
        kind=ClaimKind(kind),
        checkable=bool(checkable),
        skip_reason=skip_reason.strip() if isinstance(skip_reason, str) and not checkable else None,
        readme_path=document.display_path,
        readme_line=span.start,
        readme_line_end=span.end,
        quote=quote.strip(),
    )
    return claim, warnings, []


def _line_hint(value: object, prefix: str) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, f"{prefix}.line must be an integer"
    if isinstance(value, int):
        if value < 1:
            return None, f"{prefix}.line must be >= 1"
        return value, None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        if number < 1:
            return None, f"{prefix}.line must be >= 1"
        return number, None
    return None, f"{prefix}.line must be an integer"


def parse_json_object(raw: str) -> dict[str, object]:
    """Parse a model response, including one wrapped in a markdown fence or a sentence."""
    text = raw.strip()
    text = _FENCE.sub("", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("response was not a JSON object") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"response was not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("response JSON must be an object")
    return data
