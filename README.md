# ClaimCheck

ClaimCheck reads a repository README and lists claims a reviewer could check against the repo: benchmark numbers, features, properties such as "lossless", and compatibility statements. Marketing that names none of those is kept, marked not checkable, and left out of the verdict list.

This repository is **pre-alpha, milestone 1**. Extraction works. Judging claims does not.

## What works now

- `claimcheck extract <local README or directory>` asks an OpenAI-compatible chat model for claims, checks that each quote is actually in the README, stores the line the quote occupies, and retries when the response is not valid JSON of the expected shape.
- Claims are labeled with a kind: `benchmark_number`, `feature`, `property`, `compatibility`, or `other`.
- `claimcheck scan` runs that extraction and writes `report.md` and `report.json`. Every checkable claim is labeled `unverifiable`. That label is a placeholder. It means this version did not look for evidence. It is not a finding about the claim.
- Reports carry one verdict per checkable claim. Evidence, when a later version has any, is a file path and line. The milestone 1 reports cite no evidence and say so.
- `eval/` holds hand-labeled claims and a script that scores extraction recall. See [eval/README.md](eval/README.md). No live model has been scored here, so this README has no recall or accuracy figure.

## What does not work yet

Planned for later milestones, and not implemented:

- Evidence retrieval: code search, a symbol index, and parsers for benchmark result files (JSON, CSV, logs), with numeric claims compared in code rather than by the model.
- Verdicts. The intended rule is that the model may only apply `supported`, `not_found`, `contradicted`, or `unverifiable` to evidence it cites. `contradicted` would require concrete counter-evidence and a second check, and would be downgraded to `unverifiable` if that check failed. Milestone 1 never emits `contradicted`.
- `claimcheck scan` of a git URL. Passing one exits with an error. Cloning is not implemented.
- A GitHub Action for maintainers running this on their own repositories.

## Install

Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `[dev]` extra installs pytest and ruff. You do not need it to run the commands below.

## Usage

Recorded response, no API key and no network. `examples/sample_readme.md` is a fictional project used to exercise the CLI. The "under 50 ms" sentence in that file is part of the fiction, not a measurement of ClaimCheck.

```bash
claimcheck extract examples/sample_readme.md \
  --replay examples/sample_extract_response.json

claimcheck scan examples/sample_readme.md \
  --replay examples/sample_extract_response.json \
  --output-dir /tmp/claimcheck-sample
```

`extract` prints the claims. `--json` prints them as JSON, and `--output` writes that JSON to a file. The recorded sample marks line 1 on a quote that is not on line 1. The command stores the line the quote is actually on and prints a warning.

A live model is optional. The client sends `POST {base URL}/chat/completions`. The base URL is the API root, the part that ends in `/v1`, not the full completions URL. That is the shape OpenAI and local servers such as Ollama document. This milestone's tests use a fake transport and recorded responses. A live server was not called while this milestone was put together, because no API key was configured for it.

```bash
export CLAIMCHECK_BASE_URL=http://127.0.0.1:11434/v1
export CLAIMCHECK_MODEL=your-model-name
# Leave the key unset, or empty, if the server does not check one.
export CLAIMCHECK_API_KEY=

claimcheck extract path/to/repo
```

`OPENAI_BASE_URL`, `OPENAI_MODEL`, and `OPENAI_API_KEY` are used when the `CLAIMCHECK_*` variable is unset. There is no default model. `CLAIMCHECK_TIMEOUT` is seconds, default 60.

`--replay` accepts a JSON list of strings (one model response per attempt) or any other file as a single response, including a JSON object of claims.

## Labels

A finished report is meant to use only these labels:

| Label | Intended meaning |
| --- | --- |
| `supported` | The cited evidence shows the claim. |
| `not_found` | The search did not find the claimed behavior or number. |
| `contradicted` | The cited evidence shows the claim is false. |
| `unverifiable` | The repo does not contain enough to decide, or this version did not look. |

Milestone 1 writes `unverifiable` for every checkable claim, with `provisional: true` and an empty evidence list. The report's limitations section says that in the file itself.

## Eval

The seeded set is the seven README claims in the opening table of [MemPalace/mempalace#27](https://github.com/MemPalace/mempalace/issues/27), pinned to commit `0808ad96c29d5acb9fd3b465025ea201711bd28d` on `develop` (the newest commit on the current history of that branch dated before the issue was opened). The file records the issue's severity and maps it onto the four labels. It is not a ClaimCheck verdict, and the code in that repository was not re-audited for this file.

```bash
python eval/score_extraction.py \
  eval/ground_truth/mempalace_issue_27.json \
  path/to/extraction.json
```

## Development

```bash
ruff check .
ruff format --check .
pytest
```

Tests do not use the network and do not need an API key. The GitHub Actions workflow runs those three commands on Python 3.10 and 3.12. That describes the workflow file. It is not a claim about a particular CI run.

See [CONTRIBUTING.md](CONTRIBUTING.md). Do not add a benchmark number to this README unless a script in this repository produces it.

## License

[MIT](LICENSE).
