# app/core/jsonio.py
from __future__ import annotations

import json
from typing import Any


def loads_json_bytes(blob: bytes, *, name: str = "krystal.json") -> Any:
    """
    Parse JSON bytes with strict UTF-8 decode.
    Raises ValueError with a crisp message (we surface these in inhale errors).
    """
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"{name}: not valid UTF-8 ({e})") from e

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{name}: invalid JSON ({e.msg} at line {e.lineno} col {e.colno})") from e


def dumps_canonical_json(obj: Any) -> str:
    """
    Deterministic JSON dump:
    - sorted keys
    - no trailing spaces
    - stable separators
    - UTF-8 safe (ensure_ascii=False)
    """
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def dumps_pretty_json(obj: Any) -> str:
    """Human-friendly (still deterministic ordering)."""
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
