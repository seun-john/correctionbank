from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from correctionbank.cli import main
from correctionbank.core import InputError
from correctionbank.ledgers import corrections, decisions, failures


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return tmp_path / "bank.sqlite3"


def statuses(result: dict[str, Any]) -> list[str]:
    return [f["status"] for f in result["findings"]]


def test_database_is_released_after_use(db: Path) -> None:
    """Regression: an open handle keeps the file locked on Windows."""
    corrections({"scope": "p", "action": "add", "rule": "r", "provenance": "x"}, db)
    db.unlink()
    assert not db.exists()


# -- corrections ---------------------------------------------------------------------------


def add_rule(db: Path, scope: str = "thesis", rule: str = "Use British spelling") -> dict[str, Any]:
    return corrections(
        {"scope": scope, "action": "add", "rule": rule, "provenance": "supervisor email"}, db
    )


def test_add_is_idempotent_and_reports_it(db: Path) -> None:
    assert statuses(add_rule(db)) == ["ADDED"]
    again = add_rule(db)
    assert statuses(again) == ["DUPLICATE_IGNORED"] and len(again["rules"]) == 1


def test_whitespace_does_not_defeat_dedup(db: Path) -> None:
    add_rule(db, rule="Use British spelling")
    assert statuses(add_rule(db, rule="  Use British spelling  ")) == ["DUPLICATE_IGNORED"]


def test_scopes_are_isolated(db: Path) -> None:
    add_rule(db, scope="a")
    assert corrections({"scope": "b"}, db)["rules"] == []
    assert len(corrections({"scope": "a"}, db)["rules"]) == 1


def test_export_is_a_bullet_list(db: Path) -> None:
    add_rule(db, rule="One")
    add_rule(db, rule="Two")
    result = corrections({"scope": "thesis", "action": "export"}, db)
    assert result["instructions"] == "- One\n- Two"


@pytest.mark.parametrize(
    "bad",
    [
        {"scope": " ", "action": "list"},
        {"scope": "s", "action": "wipe"},
        {"scope": "s", "action": "add", "rule": "", "provenance": "x"},
        {"scope": "s", "action": "add", "rule": "r", "provenance": " "},
    ],
)
def test_invalid_corrections_input(db: Path, bad: dict[str, Any]) -> None:
    with pytest.raises(InputError):
        corrections(bad, db)


# -- failures ------------------------------------------------------------------------------


def add_case(db: Path, ident: str = "c1", expected: dict[str, Any] | None = None) -> dict[str, Any]:
    return failures(
        {
            "scope": "bot",
            "action": "add",
            "id": ident,
            "description": "never invents a DOI",
            "provenance": "review 2026-10-01",
            "expected": expected
            if expected is not None
            else {"not_contains": ["10.9999/fake"], "contains": ["unknown"]},
        },
        db,
    )


def evaluate(db: Path, actuals: dict[str, Any]) -> dict[str, Any]:
    return failures({"scope": "bot", "action": "evaluate", "actuals": actuals}, db)


def test_pass_and_regression(db: Path) -> None:
    add_case(db)
    assert statuses(evaluate(db, {"c1": "The DOI is unknown."})) == ["PASS"]
    bad = evaluate(db, {"c1": "It is 10.9999/fake"})
    assert statuses(bad) == ["REGRESSION"]
    failed = [c for c in bad["findings"][0]["evidence"]["checks"] if not c["passed"]]
    assert {c["check"] for c in failed} == {"not_contains: 10.9999/fake", "contains: unknown"}


def test_not_run_and_unknown_case(db: Path) -> None:
    add_case(db)
    assert statuses(evaluate(db, {})) == ["NOT_RUN"]
    assert statuses(evaluate(db, {"c1": "unknown", "zzz": "x"})) == ["UNKNOWN_CASE", "PASS"]


def test_equals_and_status_in(db: Path) -> None:
    add_case(db, "e", {"equals": {"a": [1, 2]}})
    add_case(db, "s", {"status_in": ["ok", "warn"]})
    result = evaluate(db, {"e": {"a": [1, 2]}, "s": {"status": "fail"}})
    assert statuses(result) == ["PASS", "REGRESSION"]


def test_contains_on_a_non_string_fails(db: Path) -> None:
    add_case(db, "c", {"contains": ["x"]})
    assert statuses(evaluate(db, {"c": 5})) == ["REGRESSION"]


def test_cases_are_immutable(db: Path) -> None:
    add_case(db)
    with pytest.raises(InputError):
        add_case(db)


def test_bad_expectation_is_rejected_before_storing(db: Path) -> None:
    with pytest.raises(InputError):
        add_case(db, expected={"matches": ["x"]})
    with pytest.raises(InputError):
        add_case(db, expected={})
    assert failures({"scope": "bot"}, db)["cases"] == []


def test_no_cases(db: Path) -> None:
    assert statuses(evaluate(db, {})) == ["NO_CASES"]


# -- decisions -----------------------------------------------------------------------------


def decide(db: Path, root: Path, ident: str, **extra: Any) -> dict[str, Any]:
    data = {
        "scope": "proj",
        "action": "add",
        "id": ident,
        "title": "Use SQLite",
        "rationale": "simple",
        "approved_by": "Seun",
        **extra,
    }
    return decisions(data, db, root)


def check(db: Path, root: Path) -> dict[str, Any]:
    return decisions({"scope": "proj", "action": "check"}, db, root)


def test_drift_and_missing_file(db: Path, tmp_path: Path) -> None:
    (tmp_path / "schema.sql").write_text("v1", encoding="utf-8")
    decide(db, tmp_path, "D1", files=["schema.sql"])
    assert statuses(check(db, tmp_path)) == ["UNCHANGED"]
    (tmp_path / "schema.sql").write_text("v2", encoding="utf-8")
    assert statuses(check(db, tmp_path)) == ["DECISION_DRIFT"]
    (tmp_path / "schema.sql").unlink()
    result = check(db, tmp_path)
    assert statuses(result) == ["DECISION_DRIFT"]
    assert result["findings"][0]["evidence"]["actual"] is None


def test_unapproved_decision_is_flagged(db: Path, tmp_path: Path) -> None:
    decide(db, tmp_path, "D1", approved_by=None)
    assert "UNAPPROVED_RECORD" in statuses(check(db, tmp_path))


def test_supersession(db: Path, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    decide(db, tmp_path, "D1", files=["a.txt"])
    decide(db, tmp_path, "D2", supersedes="D1")
    (tmp_path / "a.txt").write_text("2", encoding="utf-8")
    assert "DECISION_DRIFT" not in statuses(check(db, tmp_path))
    listed = decisions({"scope": "proj"}, db, tmp_path)["decisions"]
    assert [d["superseded"] for d in listed] == [True, False]
    with pytest.raises(InputError):
        decide(db, tmp_path, "D3", supersedes="D1")
    with pytest.raises(InputError):
        decide(db, tmp_path, "D4", supersedes="NOPE")


def test_decisions_cannot_be_overwritten(db: Path, tmp_path: Path) -> None:
    decide(db, tmp_path, "D1")
    with pytest.raises(InputError):
        decide(db, tmp_path, "D1")


def test_tampered_record_is_detected(db: Path, tmp_path: Path) -> None:
    decide(db, tmp_path, "D1")
    with sqlite3.connect(db) as conn:
        body = conn.execute("SELECT body FROM decisions").fetchone()[0]
        conn.execute("UPDATE decisions SET body=?", (body.replace("simple", "edited"),))
    conn.close()
    assert "TAMPERED_RECORD" in statuses(check(db, tmp_path))


def test_decision_paths_cannot_escape_root(db: Path, tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("x", encoding="utf-8")
    with pytest.raises(InputError):
        decide(db, root, "D1", files=["../outside.txt"])


def test_missing_tracked_file_is_rejected(db: Path, tmp_path: Path) -> None:
    with pytest.raises(InputError):
        decide(db, tmp_path, "D1", files=["nope.txt"])


def test_decisions_are_scoped(db: Path, tmp_path: Path) -> None:
    decide(db, tmp_path, "D1")
    assert decisions({"scope": "other"}, db, tmp_path)["decisions"] == []


# -- command line --------------------------------------------------------------------------


def test_cli_round_trip_and_strict(db: Path, tmp_path: Path) -> None:
    src = tmp_path / "in.json"
    src.write_text(
        json.dumps({"scope": "p", "action": "add", "rule": "Be brief", "provenance": "me"}),
        encoding="utf-8",
    )
    args = ["corrections", str(src), "-d", str(db), "-o", str(tmp_path / "o.json"), "--strict"]
    assert main(args) == 0
    assert main(args) == 0  # a duplicate is not a problem
    case = tmp_path / "case.json"
    case.write_text(
        json.dumps({"scope": "p", "action": "evaluate", "actuals": {}}),
        encoding="utf-8",
    )
    assert (
        main(["failures", str(case), "-d", str(db), "-o", str(tmp_path / "o2.json"), "--strict"])
        == 1
    )


def test_cli_will_not_write_the_report_over_the_database(db: Path, tmp_path: Path) -> None:
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"scope": "p"}), encoding="utf-8")
    assert main(["corrections", str(src), "-d", str(db), "-o", str(db)]) == 2


def test_cli_reports_input_errors_with_exit_2(db: Path, tmp_path: Path) -> None:
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"scope": ""}), encoding="utf-8")
    assert main(["corrections", str(src), "-d", str(db)]) == 2
