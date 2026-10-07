<p align="center">
  <img src="assets/logo.png" alt="CorrectionBank logo" width="420">
</p>

# CorrectionBank

A local, scoped memory of what went wrong with AI work, so the same mistake is not made twice.

AI feedback usually gets trapped in old chats. CorrectionBank keeps it in one SQLite file on your machine, in three ledgers that share a command line and a scope (a project or topic name):

| Ledger | Keeps | For |
| --- | --- | --- |
| `corrections` | Rules such as "Use British spelling", with where they came from | Exporting a clean instruction list to paste into a prompt or `AGENTS.md` |
| `failures` | Regression cases: a known bad behaviour and a deterministic check for it | Testing future outputs against past mistakes |
| `decisions` | Decisions with a rationale, an approver and the hashes of the files they depend on | Noticing when something a decision relied on has changed |

It uses only the Python standard library and makes no network requests. The database is plain text on disk, so do not store secrets in it.

## Install

Requires Python 3.10 or newer.

```bash
pip install git+https://github.com/seun-john/correctionbank.git
```

## Corrections

```bash
correctionbank corrections add.json -o report.json
```

```json
{"scope": "thesis", "action": "add", "rule": "Use British spelling", "provenance": "supervisor email, 2026-10-01"}
```

Actions: `add`, `list` (default), `export`. Adding the same rule twice in a scope is ignored and reported as `DUPLICATE_IGNORED`. `export` returns the scope's rules as a `- rule` list in `instructions`. Scopes never mix.

## Failure cases

```json
{"scope": "bot", "action": "add", "id": "no-fake-doi-v1", "description": "Never invents a DOI",
 "provenance": "review 2026-10-01", "case_input": "What is the DOI of ...?",
 "expected": {"contains": ["unknown"], "not_contains": ["10.9999/"]}}
```

```json
{"scope": "bot", "action": "evaluate", "actuals": {"no-fake-doi-v1": "The DOI is unknown."}}
```

Expectations are deterministic and all must pass: `equals` (exact JSON equality), `contains` and `not_contains` (strings, applied to a string output) and `status_in` (the output is an object whose `status` is in the list). Results are `PASS`, `REGRESSION`, `NOT_RUN` (no output supplied for a stored case) and `UNKNOWN_CASE`. Cases are immutable: when an expectation changes, add `no-fake-doi-v2`. CorrectionBank does not run models and cannot judge meaning, so design expectations around things a string check can see.

## Decisions

```json
{"scope": "proj", "action": "add", "id": "D1", "title": "Use SQLite", "rationale": "Single user, no server",
 "approved_by": "Seun", "files": ["db/schema.sql"], "supersedes": null}
```

```bash
correctionbank decisions check.json --root /path/to/project
```

Adding records the SHA-256 of each tracked file. `check` (with `{"scope": "proj", "action": "check"}`) compares the files with those hashes: `UNCHANGED` or `DECISION_DRIFT` (the file changed or is gone), plus `UNAPPROVED_RECORD` when nobody is named as approver. Drift means "look at this again", not "the decision was broken". A new decision can supersede a current one in the same scope; superseded decisions are no longer checked. Each record carries its own hash, and a record that no longer matches it is reported as `TAMPERED_RECORD`.

## Options and exit codes

All commands take `--database FILE` (default `correctionbank.sqlite3`), `-o report.json`, `--html report.html` and `--strict`. Exit codes: 0 completed, 1 `--strict` and something other than `ADDED`, `DUPLICATE_IGNORED`, `PASS` or `UNCHANGED` was reported, 2 unusable input or a rejected change.

## Limits

- Everything is stored in plain text. Approvals are the names you type, not signatures.
- Records are append-only through this tool. Someone with write access to the SQLite file can still edit it; the hashes make casual edits to decisions visible, nothing more.
- Corrections are exported, never applied automatically.
- There is no automatic extraction of corrections from chats and no semantic conflict detection.

## Develop

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest -q
```

MIT licence.
