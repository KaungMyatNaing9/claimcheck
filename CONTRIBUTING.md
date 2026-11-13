# Contributing

ClaimCheck is pre-alpha. Milestone 1 extracts README claims. It does not decide whether they are true.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.10 or newer.

## Checks

```bash
ruff check .
ruff format --check .
pytest
```

The test suite does not call a network and does not need an API key. Use `ReplayClient` or `claimcheck --replay` for model responses.

## Honesty rules

- Do not put a benchmark number, accuracy figure, or performance claim in the README, docs, or eval notes unless a script in this repository produces it and the docs say which script.
- Do not describe a planned feature as working. Evidence retrieval, real verdicts, git-URL clones, and the GitHub Action are not implemented yet.
- A `contradicted` label is an accusation. Do not add a path that emits it without concrete counter-evidence and the second check described in the v1 design. Milestone 1 does not emit it.
- Ground-truth rows must cite the page they came from. Do not invent claims, labels, or evidence notes for a repository you did not read.

## Model settings

`CLAIMCHECK_BASE_URL`, `CLAIMCHECK_MODEL`, and `CLAIMCHECK_API_KEY` select an OpenAI-compatible chat API. `OPENAI_BASE_URL`, `OPENAI_MODEL`, and `OPENAI_API_KEY` are fallbacks. The base URL is the API root (the part that ends in `/v1`), not the full `/chat/completions` URL.
