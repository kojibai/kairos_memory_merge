# app/models/payload.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SigilPayloadLoose(BaseModel):
    """
    SigilSharePayloadLoose (Python) — tolerant, schema-flexible payload container.

    Rules:
    - Accepts extra fields (we preserve everything we don't explicitly model).
    - Normalizes common alias keys into canonical Kai fields.
    - Kai-time ordering is derived from (pulse, beat, stepIndex) ONLY.
    - Chronos fields (e.g., ts, createdAt) are accepted but NEVER used for ordering.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Canonical Kai fields
    pulse: int | None = None
    beat: int | None = None
    stepIndex: int | None = Field(default=None)

    # Common optional fields used by your ecosystem
    chakraDay: str | None = None
    kaiSignature: str | None = None

    # Topology (may be explicit or derived from witness-chain)
    originUrl: str | None = None
    parentUrl: str | None = None

    # Identity aliases (we do not force one — we preserve all)
    userPhiKey: str | None = None
    phiKey: str | None = None
    phikey: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        d = dict(data)

        # --- Short-key forms (seen in compact payloads) ---
        # NOTE: 'u' appears in compact tokens; in your sample it behaves like pulse.
        if "pulse" not in d and isinstance(d.get("u"), int):
            d["pulse"] = d.get("u")
        if "beat" not in d and isinstance(d.get("b"), int):
            d["beat"] = d.get("b")
        if "stepIndex" not in d and isinstance(d.get("s"), int):
            d["stepIndex"] = d.get("s")
        if "chakraDay" not in d and isinstance(d.get("c"), str):
            d["chakraDay"] = d.get("c")

        # --- Common snake_case aliases ---
        if "stepIndex" not in d and isinstance(d.get("step_index"), int):
            d["stepIndex"] = d.get("step_index")
        if "chakraDay" not in d and isinstance(d.get("chakra_day"), str):
            d["chakraDay"] = d.get("chakra_day")
        if "kaiSignature" not in d and isinstance(d.get("kai_signature"), str):
            d["kaiSignature"] = d.get("kai_signature")
        if "originUrl" not in d and isinstance(d.get("origin_url"), str):
            d["originUrl"] = d.get("origin_url")
        if "parentUrl" not in d and isinstance(d.get("parent_url"), str):
            d["parentUrl"] = d.get("parent_url")

        # --- Alternate naming we've seen in the wild ---
        if "stepIndex" not in d and isinstance(d.get("step"), int):
            d["stepIndex"] = d.get("step")

        return d

    def kai_tuple(self) -> tuple[int, int, int]:
        """
        Canonical Kai-time tuple. Missing fields collapse to 0.
        Used for deterministic ordering and "newer wins" resolution.
        """
        p = int(self.pulse or 0)
        b = int(self.beat or 0)
        s = int(self.stepIndex or 0)
        return (p, b, s)
