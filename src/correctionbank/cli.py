"""Command line for CorrectionBank."""

from __future__ import annotations

import argparse
from typing import Any

from .ledgers import corrections, decisions, failures
from .runner import Command, main_wrapper, run

DB_OPTION = (
    ("--database", "-d"),
    {"default": "correctionbank.sqlite3", "help": "SQLite file (default: correctionbank.sqlite3)"},
)
ROOT_OPTION = (("--root",), {"default": ".", "help": "folder that tracked file paths are under"})


def _corrections(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    return corrections(data, args.database)


def _failures(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    return failures(data, args.database)


def _decisions(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    return decisions(data, args.database, args.root)


COMMANDS = {
    "corrections": Command(
        _corrections,
        "Store and export scoped correction rules",
        frozenset({"ADDED", "DUPLICATE_IGNORED"}),
        options=[DB_OPTION],
        protect=("database",),
    ),
    "failures": Command(
        _failures,
        "Store regression cases and evaluate outputs against them",
        frozenset({"ADDED", "PASS"}),
        options=[DB_OPTION],
        protect=("database",),
    ),
    "decisions": Command(
        _decisions,
        "Record decisions and check tracked files for drift",
        frozenset({"ADDED", "UNCHANGED"}),
        options=[DB_OPTION, ROOT_OPTION],
        protect=("database",),
    ),
}


def main(argv: list[str] | None = None) -> int:
    return run("correctionbank", "A local memory of what went wrong with AI work.", COMMANDS, argv)


if __name__ == "__main__":
    main_wrapper(main)
