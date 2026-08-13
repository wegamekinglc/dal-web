#!/usr/bin/env python3
"""dal-web consistency gates: requirement-file sync and launcher portability."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _requirement_name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip().lower()


def _declared_requirements() -> set[str]:
    with (BACKEND / "pyproject.toml").open("rb") as stream:
        config = tomllib.load(stream)
    return {_requirement_name(d) for d in config["project"]["dependencies"]}


def _requirements_file() -> set[str]:
    names: set[str] = set()
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            names.add(_requirement_name(stripped))
    return names


def check_requirement_sets(errors: list[str]) -> None:
    declared = _declared_requirements()
    recorded = _requirements_file()
    missing = declared - recorded
    extra = recorded - declared
    if missing:
        errors.append(
            "backend/requirements.txt: missing dependencies declared by "
            f"pyproject.toml: {sorted(missing)}"
        )
    if extra:
        errors.append(
            "backend/requirements.txt: dependencies absent from pyproject.toml: "
            f"{sorted(extra)}"
        )


def check_launcher_portability(errors: list[str]) -> None:
    start = (ROOT / "scripts" / "start.sh").read_text(encoding="utf-8")
    stop = (ROOT / "scripts" / "stop.sh").read_text(encoding="utf-8")
    if "ss -tln" in start and "lsof" not in start:
        errors.append("scripts: macOS launchers must not require Linux-only ss")
    if "xargs -r" in stop:
        errors.append("scripts/stop.sh: GNU-only xargs -r is not macOS portable")
    if re.search(r"\bseq\b", start + stop):
        errors.append("scripts: macOS launchers must not require GNU/Coreutils seq")


def main() -> int:
    errors: list[str] = []
    check_requirement_sets(errors)
    check_launcher_portability(errors)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
