"""Three small local ledgers in one SQLite file: corrections, failure cases and decisions.

All three are scoped (a scope is a project or topic name), append-only through this API, and
store plain text. The hashes stored with decisions make accidental edits visible; they do
not stop someone who can rewrite the database from rewriting both a record and its hash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import (
    InputError,
    canonical,
    database,
    digest,
    file_digest,
    finding,
    inside,
    now,
    report,
    require,
)


def _scope(data: dict[str, Any]) -> str:
    scope = require(data, "scope", str)
    if not scope.strip():
        raise InputError("Scope must not be empty")
    return scope


def _action(data: dict[str, Any], allowed: tuple[str, ...]) -> str:
    action = data.get("action", "list")
    if action not in allowed:
        raise InputError(f"action must be one of: {', '.join(allowed)}")
    return str(action)


# -- corrections ---------------------------------------------------------------------------


def corrections(data: dict[str, Any], db_path: str | Path) -> dict[str, Any]:
    scope = _scope(data)
    action = _action(data, ("add", "list", "export"))
    with database(db_path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS rules (id TEXT PRIMARY KEY, scope TEXT NOT NULL, "
            "rule TEXT NOT NULL, provenance TEXT NOT NULL, created TEXT NOT NULL)"
        )
        added = False
        if action == "add":
            rule, provenance = require(data, "rule", str), require(data, "provenance", str)
            if not rule.strip() or not provenance.strip():
                raise InputError("Rule and provenance must not be empty")
            ident = digest({"scope": scope, "rule": rule.strip()})
            cursor = db.execute(
                "INSERT OR IGNORE INTO rules VALUES (?, ?, ?, ?, ?)",
                (ident, scope, rule.strip(), provenance, now()),
            )
            added = cursor.rowcount == 1
        rows = db.execute(
            "SELECT id, scope, rule, provenance, created FROM rules WHERE scope = ? "
            "ORDER BY created, id",
            (scope,),
        ).fetchall()
    rules = [
        dict(zip(("id", "scope", "rule", "provenance", "created"), r, strict=True)) for r in rows
    ]
    findings = []
    if action == "add":
        findings.append(
            finding(
                "ADDED" if added else "DUPLICATE_IGNORED",
                "Correction stored." if added else "The same rule already exists in this scope.",
            )
        )
    return report(
        "CorrectionBank",
        findings,
        rules=rules,
        instructions="\n".join(f"- {r['rule']}" for r in rules) if action == "export" else None,
        scope=f"scope '{scope}' only; rules are exported, never applied automatically",
    )


# -- failure cases -------------------------------------------------------------------------

SUPPORTED = {"equals", "contains", "not_contains", "status_in"}


def evaluate_expectation(expected: dict[str, Any], actual: Any) -> list[tuple[str, bool]]:
    """Deterministic checks of `actual` against `expected`. Every check must pass."""
    if not isinstance(expected, dict) or not expected or set(expected) - SUPPORTED:
        raise InputError("expected needs one or more of: " + ", ".join(sorted(SUPPORTED)))
    checks: list[tuple[str, bool]] = []
    if "equals" in expected:
        checks.append(("equals", canonical(actual) == canonical(expected["equals"])))
    for key in ("contains", "not_contains"):
        if key in expected:
            terms = expected[key]
            if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
                raise InputError(f"{key} must be an array of strings")
            if not isinstance(actual, str):
                checks.append((key, False))
            else:
                for term in terms:
                    present = term in actual
                    checks.append((f"{key}: {term}", present if key == "contains" else not present))
    if "status_in" in expected:
        statuses = expected["status_in"]
        if not isinstance(statuses, list) or not all(isinstance(s, str) for s in statuses):
            raise InputError("status_in must be an array of strings")
        checks.append(("status_in", isinstance(actual, dict) and actual.get("status") in statuses))
    return checks


def failures(data: dict[str, Any], db_path: str | Path) -> dict[str, Any]:
    scope = _scope(data)
    action = _action(data, ("add", "list", "export", "evaluate"))
    actuals = data.get("actuals", {})
    if not isinstance(actuals, dict):
        raise InputError("'actuals' must be an object keyed by case id")
    case = None
    if action == "add":
        ident = require(data, "id", str)
        if not ident.strip():
            raise InputError("Case id must not be empty")
        expected = require(data, "expected", dict)
        evaluate_expectation(expected, None)  # validates the contract before anything is stored
        case = {
            "id": ident,
            "scope": scope,
            "description": require(data, "description", str),
            "input": data.get("case_input"),
            "expected": expected,
            "observed_failure": data.get("observed_failure"),
            "provenance": require(data, "provenance", str),
            "created_at": now(),
        }
    with database(db_path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS failure_cases (scope TEXT, id TEXT, body TEXT NOT NULL, "
            "PRIMARY KEY (scope, id))"
        )
        if case:
            exists = db.execute(
                "SELECT 1 FROM failure_cases WHERE scope=? AND id=?", (scope, case["id"])
            ).fetchone()
            if exists:
                raise InputError("Case id already exists; create a new versioned id instead")
            db.execute(
                "INSERT INTO failure_cases VALUES (?,?,?)", (scope, case["id"], canonical(case))
            )
        cases = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT body FROM failure_cases WHERE scope=? ORDER BY rowid", (scope,)
            )
        ]
    out: list[dict[str, Any]] = []
    if action == "add":
        out.append(finding("ADDED", "Regression case stored.", case=case["id"] if case else None))
    if action == "evaluate":
        known = {c["id"] for c in cases}
        for ident in sorted(set(actuals) - known):
            out.append(
                finding("UNKNOWN_CASE", "No stored case with this id in this scope.", case=ident)
            )
        for stored in cases:
            if stored["id"] not in actuals:
                out.append(
                    finding("NOT_RUN", "No output supplied for this case.", case=stored["id"])
                )
                continue
            checks = evaluate_expectation(stored["expected"], actuals[stored["id"]])
            ok = all(passed for _, passed in checks)
            out.append(
                finding(
                    "PASS" if ok else "REGRESSION",
                    "Compared the supplied output with the stored expectations.",
                    case=stored["id"],
                    checks=[{"check": label, "passed": passed} for label, passed in checks],
                )
            )
        if not cases:
            out.append(finding("NO_CASES", "No regression cases are stored for this scope."))
    return report(
        "CorrectionBank Failures",
        out,
        cases=cases,
        scope="stores cases and compares outputs you supply; models are never run and meaning is not graded",
    )


# -- decisions -----------------------------------------------------------------------------


def decisions(data: dict[str, Any], db_path: str | Path, root: str | Path) -> dict[str, Any]:
    scope = _scope(data)
    action = _action(data, ("add", "list", "check"))
    new: dict[str, Any] | None = None
    if action == "add":
        ident = require(data, "id", str)
        if not ident.strip():
            raise InputError("Decision id must not be empty")
        tracked = []
        for relative in data.get("files", []):
            path = inside(root, relative)
            if path == Path(db_path).resolve():
                raise InputError("Do not track the decision database itself")
            if not path.is_file():
                raise InputError(f"Tracked file does not exist: {relative}")
            tracked.append({"path": relative, "sha256": file_digest(path)})
        new = {
            "id": ident,
            "scope": scope,
            "title": require(data, "title", str),
            "rationale": require(data, "rationale", str),
            "evidence": data.get("evidence", []),
            "approved_by": data.get("approved_by"),
            "supersedes": data.get("supersedes"),
            "files": tracked,
            "created_at": now(),
        }
    with database(db_path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS decisions (scope TEXT, id TEXT, body TEXT NOT NULL, "
            "hash TEXT NOT NULL, PRIMARY KEY (scope, id))"
        )
        if new:
            old = new["supersedes"]
            if old:
                if not db.execute(
                    "SELECT 1 FROM decisions WHERE scope=? AND id=?", (scope, old)
                ).fetchone():
                    raise InputError("The decision you supersede does not exist in this scope")
                for (body,) in db.execute("SELECT body FROM decisions WHERE scope=?", (scope,)):
                    if json.loads(body).get("supersedes") == old:
                        raise InputError(
                            "That decision is already superseded; supersede its successor"
                        )
            if db.execute(
                "SELECT 1 FROM decisions WHERE scope=? AND id=?", (scope, new["id"])
            ).fetchone():
                raise InputError("Decision id already exists; append a new decision instead")
            db.execute(
                "INSERT INTO decisions VALUES (?,?,?,?)",
                (scope, new["id"], canonical(new), digest(new)),
            )
        rows = db.execute(
            "SELECT body, hash FROM decisions WHERE scope=? ORDER BY rowid", (scope,)
        ).fetchall()
    records: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    for body, stored_hash in rows:
        record = json.loads(body)
        if digest(record) != stored_hash:
            out.append(
                finding(
                    "TAMPERED_RECORD",
                    "A stored decision does not match its stored hash.",
                    decision=record.get("id"),
                )
            )
        records.append(record)
    superseded = {d["supersedes"] for d in records if d.get("supersedes")}
    if action == "add":
        out.append(finding("ADDED", "Decision recorded.", decision=new["id"] if new else None))
    if action == "check":
        for record in records:
            if record["id"] in superseded:
                continue
            if not record.get("approved_by"):
                out.append(
                    finding("UNAPPROVED_RECORD", "No approver is recorded.", decision=record["id"])
                )
            for entry in record["files"]:
                path = inside(root, entry["path"])
                actual = file_digest(path) if path.is_file() else None
                same = actual == entry["sha256"]
                out.append(
                    finding(
                        "UNCHANGED" if same else "DECISION_DRIFT",
                        "File is as it was when the decision was made."
                        if same
                        else "File differs from, or is missing since, the decision. Review it.",
                        decision=record["id"],
                        path=entry["path"],
                        expected=entry["sha256"],
                        actual=actual,
                    )
                )
    return report(
        "CorrectionBank Decisions",
        out,
        decisions=[{**d, "superseded": d["id"] in superseded} for d in records],
        scope="append-only through this tool; approvals are what you typed, not signatures",
    )
