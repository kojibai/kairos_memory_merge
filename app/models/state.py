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
    One canonical registry entry.

    UX guarantee:
    - Top-level Kai + identity fields exist for jq / clients.
    - Full original payload is preserved under `payload`.
    """

    url: str = Field(..., description="Canonical URL key (absolute, deterministic)")

    # Convenience mirrors of payload fields (so callers don’t have to dig into .payload.*)
    pulse: int = Field(0, description="Kai pulse (0 if missing)")
    beat: int = Field(0, description="Kai beat (0 if missing)")
    stepIndex: int = Field(0, description="Kai stepIndex (0 if missing)")

    chakraDay: str | None = Field(default=None, description="Chakra day label (if present)")
    userPhiKey: str | None = Field(default=None, description="Primary identity marker (if present)")
    kaiSignature: str | None = Field(default=None, description="Kai Signature / seal (if present)")

    payload: SigilPayloadLoose = Field(..., description="Full decoded payload (extras preserved)")


class SigilState(BaseModel):
    """
    Global merged registry state.

    Determinism:
    - `registry` is sorted by Kai time DESC (most recent first).
    - `urls` is the same ordering as registry.url.
    - No Chronos timestamps are emitted or required.
    """

    spec: str = Field(default="KKS-1.0", description="Kai-Klok spec used for ordering/merging")
    total_urls: int = Field(default=0, description="Count of registry entries")
    latest: KaiMoment = Field(default_factory=KaiMoment, description="Latest KaiMoment across registry")

    registry: list[SigilEntry] = Field(default_factory=list, description="Ordered entries (Kai-desc)")
    urls: list[str] = Field(default_factory=list, description="Ordered URL list (Kai-desc)")


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
