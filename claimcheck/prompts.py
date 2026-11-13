"""The claim-extraction prompt.

The model lists candidate claims. It does not decide whether they are true.
A separate check maps each quote onto a README line and rejects quotes that
are not in the file.
"""

from claimcheck.readme import ReadmeDocument, numbered_text

SYSTEM_PROMPT = """You extract checkable claims from a software project's README.

A claim is one statement a reviewer could confirm or refute from the repository
itself: source code, tests, benchmark scripts, or benchmark result files.
You are not that reviewer. Do not say whether a claim is true, false, or exaggerated.

Return JSON only. No markdown fence. No prose before or after the JSON. Use this shape:

{
  "claims": [
    {
      "text": "one standalone sentence stating the claim",
      "kind": "benchmark_number",
      "quote": "verbatim excerpt copied from the README",
      "line": 1,
      "checkable": true,
      "skip_reason": null
    }
  ]
}

kind is one of:
- benchmark_number: a quantitative result, such as a score, percentage, latency,
  recall, or compression ratio.
- feature: a behavior or component the project says it has.
- property: a qualitative property such as lossless, local-only, deterministic,
  or zero information loss.
- compatibility: a runtime, model, format, operating system, or protocol the
  project says it works with.
- other: checkable, but none of the above.

Rules:
- quote must be copied from the README, contiguous, without an ellipsis and
  without added words. You may change only whitespace. Do not include the N|
  line-number prefixes from the prompt.
- line is the 1-based number of the first line of quote.
- One statement per object. Do not merge unrelated claims. If the same claim
  is repeated, emit it once and quote the most specific occurrence.
- checkable is false only for marketing that names no behavior, number,
  property, or compatibility the repository could settle. Examples: "the best",
  "nothing else like it", "beautiful", "a game changer". For those, kind is
  "other" and skip_reason is a short phrase. Otherwise skip_reason is null.
- Do not invent claims that the README does not state.
- If there is nothing to extract, return {"claims": []}.
"""


def build_user_prompt(document: ReadmeDocument) -> str:
    """Number every README line so the model can cite one, and so we can check it."""
    body = numbered_text(document) if document.lines else "(empty file)"
    return (
        "Extract claims from this README. Lines are prefixed with their "
        f"1-based line number and a pipe character.\n\n{body}"
    )


def retry_note(errors: list[str]) -> str:
    """Text appended after a rejected response. The errors come from the validator."""
    bullet_list = "\n".join(f"- {error}" for error in errors)
    return (
        "The previous response was rejected:\n"
        f"{bullet_list}\n\n"
        "Respond again with only the JSON object."
    )
