# ClaimCheck

ClaimCheck reads a repository README, lists claims a reviewer could check, and compares them to code and benchmark files in that repository. Marketing that names no behavior, number, property, or compatibility is kept, marked not checkable, and left out of the verdict list.

This repository is **pre-alpha, milestone 2**. Extraction, evidence retrieval, and verdicts run locally. A GitHub Action does not.

## What works now

- `claimcheck extract` asks an OpenAI-compatible chat model for claims, checks that each quote is in the README, stores the line the quote occupies, and retries when the response is not valid JSON of the expected shape.
- Claims have a kind: `benchmark_number`, `feature`, `property`, `compatibility`, or `other`.
- `claimcheck scan` writes `report.md` and `report.json` with one verdict per checkable claim. Evidence is a file path and line copied from the repository.
- Evidence comes from three places: a Python AST symbol index (other text files get a `def` / `class` / `function` / `fn` line pattern), a lexical text search, and parsers for JSON, CSV, and log files.
- A percent or an `Nx` ratio in a claim is compared in code to parsed measurements whose metric name shares a word with the claim. `90%` agrees with `0.90`. A bare integer such as the 5 in "recall at 5" is not treated as the score.
- The model may cite only lines that retrieval returned. `supported` and `contradicted` are dropped when the citation is not one of those lines.
- `contradicted` is kept only when the cited line shares the claim's words or is a disagreeing measurement, a second model pass sets `confirm` to true, and a re-read of a benchmark file still shows the same number. Otherwise the label becomes `unverifiable` and the report says what it was downgraded from.
- A git URL, or any path passed with `--revision`, is cloned with `git clone` into a temporary directory. `--revision` checks out that commit in the clone. The directory is removed after the report is written. A local directory without `--revision` is read in place.
- `eval/` scores extraction recall and, separately, verdict labels. Coarse-mapping rows are counted apart from the others. See [eval/README.md](eval/README.md).

## What this version will not do

- `not_found` means the symbol index and the text search returned no line. A paraphrase that uses different words can be missed. The report's limitations section says this.
- A benchmark number with no related metric in a JSON, CSV, or log file is `unverifiable`. It is not called false just because the number is absent.
- The symbol index does not resolve types, imports, or non-Python grammars beyond the line pattern above.
- Search is not semantic. There is no embedding index.

## Planned

Not implemented:

- A GitHub Action for maintainers running this on their own repositories.
- Partial clones. A remote URL is a full `git clone`, so a large repository takes as long as git takes.

## Install

Python 3.10 or newer, and `git` if you pass a URL or `--revision`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `[dev]` extra installs pytest and ruff. You do not need it to run the commands below.

## Usage

Recorded responses, no API key and no network.

`examples/northwind/` is a fictional README with no code beside it. The "under 50 ms" sentence is part of that fiction, not a measurement of ClaimCheck. Scanning it labels the feature and compatibility sentences `not_found` and the timing sentence `unverifiable`, because there is nothing else in that directory to cite.

```bash
claimcheck extract examples/northwind \
  --replay examples/sample_extract_response.json

claimcheck scan examples/northwind \
  --replay examples/sample_extract_response.json \
  --output-dir /tmp/claimcheck-sample
```

`fixtures/tiny_repo` is a small tree with a true feature, a false feature, a missing feature, a matching benchmark number, a disagreeing benchmark number, and a number that no parsed metric names. The recorded responses are `fixtures/tiny_repo_replay.json`.

```bash
claimcheck scan fixtures/tiny_repo \
  --replay fixtures/tiny_repo_replay.json \
  --output-dir /tmp/claimcheck-tiny
```

`extract` prints the claims. `--json` prints them as JSON, and `--output` writes that JSON to a file. The northwind recording cites line 1 for a quote that is on line 7. The command stores line 7 and prints a warning.

A live model is optional. The client sends `POST {base URL}/chat/completions`. The base URL is the API root, the part that ends in `/v1`, not the full completions URL. Tests use a fake transport and recorded responses. A live server was not called for this milestone, because no API key was configured.

```bash
export CLAIMCHECK_BASE_URL=http://127.0.0.1:11434/v1
export CLAIMCHECK_MODEL=your-model-name
# Leave the key unset, or empty, if the server does not check one.
export CLAIMCHECK_API_KEY=

claimcheck scan path/to/repo
```

`OPENAI_BASE_URL`, `OPENAI_MODEL`, and `OPENAI_API_KEY` are used when the `CLAIMCHECK_*` variable is unset. There is no default model. `CLAIMCHECK_TIMEOUT` is seconds, default 60.

`--replay` accepts a JSON list of strings, or `{"responses": ["...", "..."]}`, one model response per call in order: extraction, then one verdict per claim that has evidence to show, then a confirmation call after each proposed `contradicted` label. Any other file is a single response.

```bash
claimcheck scan https://example.com/some-repo.git --revision <commit>
```

That clones into a temporary directory. Tests cover this with a local `file://` repository. A remote host was not cloned.

## Labels

| Label | When this version uses it |
| --- | --- |
| `supported` | The model cited a retrieved line, and for a number the parsed measurement agrees. |
| `not_found` | The symbol index and text search returned no line. |
| `contradicted` | The cited line is counter-evidence and the second pass confirmed it. |
| `unverifiable` | The files are not enough, the citation was not retrieved, or the second pass did not confirm. |

A downgraded verdict sets `provisional` and `downgraded_from`. The markdown report prints both.

## Eval

Hand-labeled claims from [MemPalace/mempalace#27](https://github.com/MemPalace/mempalace/issues/27) are in `eval/ground_truth/mempalace_issue_27.json`, pinned to commit `0808ad96c29d5acb9fd3b465025ea201711bd28d` on `develop`. That file records the issue's severity beside the mapped label. `mapping_is_coarse` is true when those are not the same kind of judgment. ClaimCheck has not scanned that repository, so there is no verdict score for it here.

`eval/ground_truth/tiny_repo.json` is the specification of `fixtures/tiny_repo`. Its commit field is `local`.

```bash
python eval/score_extraction.py \
  eval/ground_truth/mempalace_issue_27.json \
  path/to/extraction.json

python eval/score_verdicts.py \
  eval/ground_truth/tiny_repo.json \
  path/to/report.json
```

`score_verdicts.py` prints strict rows and coarse-mapping rows separately, with `issue_severity` beside `expected_label` and `predicted_label`.

## Development

```bash
ruff check .
ruff format --check .
pytest
```

Tests do not use the network and do not need an API key. The GitHub Actions workflow runs those three commands on Python 3.10 and 3.12. That describes the workflow file. It is not a claim about a particular CI run.

See [CONTRIBUTING.md](CONTRIBUTING.md). Do not add a benchmark number to this README unless a script in this repository produces it and the README names that script.

## License

[MIT](LICENSE).
