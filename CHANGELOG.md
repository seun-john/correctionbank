# Changelog

## Unreleased

- `failures` evaluate and `decisions` check reports have a `coverage` block (cases run or not run; decisions that can or cannot be watched), a one-line summary on stderr and in the HTML report.
- `--min-coverage PCT`: exit 3 when fewer than PCT percent of items were decided and nothing else failed.
- `decisions`: a tracked file can carry anchor text, `{"path": "README.md", "anchor": "support@help.example"}` (or `"anchors": [...]`). When the file changes but every anchor is still present, `check` reports `FILE_CHANGED_DECISION_INTACT` instead of `DECISION_DRIFT`. If an anchor is gone, or the file is missing, it is still `DECISION_DRIFT`. The anchor must exist in the file when the decision is recorded. `--strict` does not fail on `FILE_CHANGED_DECISION_INTACT`.
- Tracked files given as plain paths behave exactly as before, and their stored records are unchanged.

## 0.1.0

First release.

- `corrections`: scoped, deduplicated rules with provenance, exportable as instructions.
- `failures`: immutable regression cases with deterministic expectations; evaluate supplied outputs against them.
- `decisions`: append-only decision records that capture file hashes, with drift checks and supersession.
