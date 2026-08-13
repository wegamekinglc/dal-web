#!/usr/bin/env python3
"""dal-web consistency gates: requirement-file sync, launcher portability, and Curve Lab endpoint inventory."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

HTTP_METHODS = {"delete", "get", "patch", "post", "put"}


def _requirement_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9_.-]+", requirement.strip())
    if match is None:
        raise ValueError(f"invalid requirement: {requirement!r}")
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _declared_requirements() -> set[str]:
    with (BACKEND / "pyproject.toml").open("rb") as stream:
        metadata = tomllib.load(stream)
    project = metadata["project"]
    return {
        _requirement_name(requirement)
        for requirement in (
            *project.get("dependencies", ()),
            *project.get("optional-dependencies", {}).get("dev", ()),
        )
    }


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
    if ("ss -tln" in start and "lsof" not in start) or (
        "ss -tln" in stop and "lsof" not in stop
    ):
        errors.append("scripts: macOS launchers must not require Linux-only ss")
    if "xargs -r" in stop:
        errors.append("scripts/stop.sh: GNU-only xargs -r is not macOS portable")
    if re.search(r"\bseq\b", start) or re.search(r"\bseq\b", stop):
        errors.append("scripts: macOS launchers must not require GNU/Coreutils seq")


def normalized_endpoint(method: str, path: str) -> tuple[str, str]:
    return method.upper(), re.sub(r"\{[^}]+\}", "{}", path)


def check_curve_lab_endpoint_inventory(errors: list[str]) -> None:
    document = ROOT / "docs/curve-lab.md"
    text = document.read_text(encoding="utf-8")
    try:
        table = text.split("All Curve Lab endpoints are under `/api/curve-lab`:", maxsplit=1)[1]
        table = table.split("\n\nThe live Swagger UI", maxsplit=1)[0]
    except IndexError:
        errors.append("docs/curve-lab.md: missing canonical REST endpoint inventory")
        return

    documented = {
        normalized_endpoint(method, f"/api/curve-lab{path}")
        for method, path in re.findall(
            r"`(GET|POST|PUT|PATCH|DELETE)\s+(/[^`\s]+)`",
            table,
        )
    }
    openapi_path = BACKEND / "openapi/dal-web.openapi.json"
    openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    actual = {
        normalized_endpoint(method, path)
        for path, operations in openapi["paths"].items()
        if path.startswith("/api/curve-lab")
        for method in operations
        if method.lower() in HTTP_METHODS
    }
    if documented != actual:
        errors.append(
            "docs/curve-lab.md: Curve Lab endpoint inventory drift: "
            f"documented-only={sorted(documented - actual)}, "
            f"OpenAPI-only={sorted(actual - documented)}"
        )


def main() -> int:
    errors: list[str] = []
    check_requirement_sets(errors)
    check_launcher_portability(errors)
    check_curve_lab_endpoint_inventory(errors)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
