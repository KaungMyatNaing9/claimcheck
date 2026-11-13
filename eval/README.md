# Extraction eval

This directory holds hand-labeled README claims and a scorer for extraction recall. It does not score verdicts. Milestone 1 has no verdict pipeline to score.

No live model has been run against this set in this repository, so there is no recall number to report.

## Ground truth

`ground_truth/mempalace_issue_27.json` has seven rows, one per cell in the opening table of [MemPalace/mempalace issue #27](https://github.com/MemPalace/mempalace/issues/27).

| Field | Meaning |
| --- | --- |
| `repo`, `branch`, `commit` | MemPalace `develop` at `0808ad96c29d5acb9fd3b465025ea201711bd28d`, the newest commit on the current history of that branch whose committer time is before the issue was opened (`2026-04-07T08:47:47Z`). |
| `claim_text` | The claim being scored. Some rows use a verbatim README span. Others use the issue's own wording when the README splits the claim across markup. |
| `issue_claim` | The opening table's claim cell. |
| `expected_label` | The issue's severity, mapped through `label_mapping`. |
| `issue_severity` | The severity words from the issue, unchanged. |
| `mapping_is_coarse` | True when the issue's words are not a direct fit for the four labels. Read `label_mapping_note` before treating the label as a clean verdict. |
| `evidence_notes` | The issue's "what the code actually does" cell, prefixed so it is clear ClaimCheck did not re-check the code. |
| `readme_quote`, `readme_line` | A verbatim README span at the pinned commit. `readme_sha256` is the digest of that `README.md`. |
| `sources` | The issue body, and the issue comment that restates the row. |
| `match_texts` | Extra phrases the recall scorer may match. They are the issue's words, a verbatim span, or the README sentence with Markdown emphasis removed. They are not additional claims. |

Rows that are not in the opening table were left out on purpose. Later comments discuss other code and later revisions, including a 2026-11-10 rerun of a 96.6% figure on a newer MemPalace version. Those comments are named in `provenance` and are not rows.

`expected_label` is for a future verdict eval. `eval/score_extraction.py` ignores it.

## Score extraction recall

```bash
python eval/score_extraction.py \
  eval/ground_truth/mempalace_issue_27.json \
  path/to/extraction.json
```

`extraction.json` is the JSON from `claimcheck extract --json` or `--output`. A report JSON also works, because it has a `claims` list.

A gold row counts as found when any extracted `text` satisfies either of these:

- the gold phrase appears in the extracted text after whitespace is collapsed, and the phrase is at least 12 characters, or
- at least 75% of the gold phrase's content tokens appear in the extracted text, and every token that contains a digit appears too.

That is lexical overlap. A paraphrase that shares neither the phrase nor the numbers can count as a miss. One extracted string that contains every gold phrase scores perfect recall. The script prints that limit with the score.

`--min-recall` exits 1 when recall is lower than the given value. The default run always exits 0 when the files are valid, so a low score is not a test failure until you set a bar.
