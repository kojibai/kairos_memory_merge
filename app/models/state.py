# app/models/state.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.payload import SigilPayloadLoose


class KaiMoment(BaseModel):
    """Kai-time stamp (no Chronos)."""

    pulse: int = 0
    beat: int = 0
    stepIndex: int = 0


class SigilEntry(BaseModel):
    """
    One canonical registry entry: URL + decoded payload (loose).

    NOTE:
    We keep `payload` as the full truth-object, but we ALSO expose
    top-level Kai + identity fields for:
      - jq ergonomics (.pulse instead of .payload.pulse)
      - faster client sorting/filtering without digging into payload
    """

    url: str

    # Flattened convenience fields (never Chronos; never required)
    pulse: int | None = None
    beat: int | None = None
    stepIndex: int | None = None
    chakraDay: str | None = None

    # Flattened identity/provenance convenience fields
    userPhiKey: str | None = None
    kaiSignature: str | None = None

    # Full decoded payload (the canonical truth object)
    payload: SigilPayloadLoose


class SigilState(BaseModel):
    """
    Global merged registry state.

    Determinism:
    - `registry` is sorted by Kai time DESC (most recent first).
    - `urls` is the same ordering as registry.url.
    - No Chronos timestamps are emitted or required.
    """

    spec: str = Field(default="KKS-1.0", description="Kai-Klok spec used for ordering/merging")
    total_urls: int = 0
    latest: KaiMoment = Field(default_factory=KaiMoment)

    registry: list[SigilEntry] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class InhaleReport(BaseModel):
    """Internal merge report from one inhale run (across uploaded files)."""

    crystals_total: int = 0
    crystals_imported: int = 0
    crystals_failed: int = 0

    registry_urls: int = 0
    latest_pulse: int | None = None

    errors: list[str] = Field(default_factory=list)


class InhaleResponse(BaseModel):
    status: Literal["ok", "error"] = "ok"

    files_received: int = 0

    crystals_total: int = 0
    crystals_imported: int = 0
    crystals_failed: int = 0

    registry_urls: int = 0
    latest_pulse: int | None = None

    # Optional payloads for callers that want immediate sync
    urls: list[str] | None = None
    state: SigilState | None = None

    errors: list[str] = Field(default_factory=list)


class ExhaleResponse(BaseModel):
    status: Literal["ok", "error"] = "ok"
    mode: Literal["urls", "state"] = "urls"

    urls: list[str] | None = None
    state: SigilState | None = None
