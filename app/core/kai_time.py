# app/core/kai_time.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeVar

from app.models.payload import SigilPayloadLoose


@dataclass(frozen=True, slots=True)
class KaiTuple:
    """
    Canonical Kai-time tuple (KKS-1.0).
    Used for ordering and deterministic "newer vs older" decisions.

    Ordering: higher is newer.
    """
    pulse: int
    beat: int
    stepIndex: int

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.pulse, self.beat, self.stepIndex)


def _safe_int(v: object) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != v:  # NaN
            return 0
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0
        try:
            # allow "123" or "123.0"
            f = float(s)
            if f != f:
                return 0
            return int(f)
        except Exception:
            return 0
    return 0


def kai_tuple_from_payload(p: SigilPayloadLoose) -> KaiTuple:
    """
    Derive KaiTuple from payload fields ONLY (no Chronos).
    Missing fields collapse to 0.

    Note: We do NOT clamp pulse/beat/stepIndex here; negative values are allowed
    but will naturally sort earlier than positive values.
    """
    # Prefer model fields (already normalized), but keep this robust.
    pulse = _safe_int(getattr(p, "pulse", None))
    beat = _safe_int(getattr(p, "beat", None))
    step = _safe_int(getattr(p, "stepIndex", None))
    return KaiTuple(pulse=pulse, beat=beat, stepIndex=step)


def kai_newer(a: SigilPayloadLoose, b: SigilPayloadLoose) -> bool:
    """True if a is strictly newer than b by Kai ordering."""
    return kai_tuple_from_payload(a).as_tuple() > kai_tuple_from_payload(b).as_tuple()


def kai_equal(a: SigilPayloadLoose, b: SigilPayloadLoose) -> bool:
    """True if a and b share the same Kai tuple."""
    return kai_tuple_from_payload(a).as_tuple() == kai_tuple_from_payload(b).as_tuple()


def kai_sort_key_desc(p: SigilPayloadLoose) -> tuple[int, int, int]:
    """
    Sort key for "most recent first".
    Python sorts ascending by default, so callers should pass reverse=True
    OR use negative key. We keep it explicit: return the natural tuple and reverse=True.
    """
    return kai_tuple_from_payload(p).as_tuple()


T = TypeVar("T")


def sort_by_kai_desc(
    items: Iterable[T],
    payload_of: callable[[T], SigilPayloadLoose],
) -> list[T]:
    """
    Deterministic sorting helper: most recent first by (pulse, beat, stepIndex).

    Example:
        sorted_entries = sort_by_kai_desc(entries, lambda e: e.payload)
    """
    return sorted(items, key=lambda x: kai_sort_key_desc(payload_of(x)), reverse=True)


def latest_kai(items: Iterable[SigilPayloadLoose]) -> KaiTuple:
    """Return the latest KaiTuple across items; returns (0,0,0) if empty."""
    latest = KaiTuple(0, 0, 0)
    for p in items:
        kt = kai_tuple_from_payload(p)
        if kt.as_tuple() > latest.as_tuple():
            latest = kt
    return latest
