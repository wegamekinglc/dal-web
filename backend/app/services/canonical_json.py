"""Canonical JSON bytes shared by persisted evidence.

Single source of truth for the canonical byte form used by calibration
integrity evidence (``calibrations.py``, including the persisted
``canonical_error_utf8`` field) and Curve Lab fingerprints/audit hashes:
sorted keys, compact separators, no NaN/Infinity, UTF-8 without ASCII
escaping. Both stores verify these bytes, so the rule must exist exactly
once.
"""

from __future__ import annotations

import hashlib
import json


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
