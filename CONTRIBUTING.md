# Contributing

ClaimCheck is pre-alpha. Milestone 2 extracts README claims and judges them against code and benchmark files in the tree.

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
- Do not describe a planned feature as working. The GitHub Action is not implemented. Remote clones are full clones.
- A `contradicted` label is an accusation. Do not add a path that emits it unless the cited line is counter-evidence and the second pass confirms. If that pass does not confirm, the label is `unverifiable`.
- Ground-truth rows must cite the page they came from. Do not invent claims, labels, or evidence notes for a repository you did not read.

## Model settings

`CLAIMCHECK_BASE_URL`, `CLAIMCHECK_MODEL`, and `CLAIMCHECK_API_KEY` select an OpenAI-compatible chat API. `OPENAI_BASE_URL`, `OPENAI_MODEL`, and `OPENAI_API_KEY` are fallbacks. The base URL is the API root (the part that ends in `/v1`), not the full `/chat/completions` URL.
