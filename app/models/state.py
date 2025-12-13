# app/models/state.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from app.models.payload import SigilPayloadLoose


class KaiMoment(BaseModel):
    """Kai-time stamp (no Chronos)."""

    pulse: int = 0
    beat: int = 0
    stepIndex: int = 0


class SigilEntry(BaseModel):
    """
    One canonical registry entry: URL + decoded payload (loose).

    UX Contract:
    - We ALWAYS expose top-level convenience fields (pulse/beat/stepIndex/etc)
      so callers can do `.state.registry | map(.pulse)` without digging into `.payload.*`.
    - The authoritative source remains `.payload` (single source of truth).
    """

    url: str
    payload: SigilPayloadLoose

    # ──────────────────────────────────────────────────────────────────
    # Convenience projections (computed from payload; output-only)
    # ──────────────────────────────────────────────────────────────────

    @computed_field(return_type=int)
    def pulse(self) -> int:
        return int(self.payload.pulse or 0)

    @computed_field(return_type=int)
    def beat(self) -> int:
        return int(self.payload.beat or 0)

    @computed_field(return_type=int)
    def stepIndex(self) -> int:
        return int(self.payload.stepIndex or 0)

    @computed_field(return_type=str | None)
    def chakraDay(self) -> str | None:
        return self.payload.chakraDay

    @computed_field(return_type=str | None)
    def kaiSignature(self) -> str | None:
        return self.payload.kaiSignature

    @computed_field(return_type=str | None)
    def originUrl(self) -> str | None:
        return self.payload.originUrl

    @computed_field(return_type=str | None)
    def parentUrl(self) -> str | None:
        return self.payload.parentUrl

    @computed_field(return_type=str | None)
    def userPhiKey(self) -> str | None:
        return self.payload.userPhiKey

    @computed_field(return_type=str | None)
    def phiKey(self) -> str | None:
        return self.payload.phiKey

    @computed_field(return_type=str | None)
    def phikey(self) -> str | None:
        return self.payload.phikey

    @computed_field(return_type=str | None)
    def id(self) -> str | None:
        """
        A single best-effort identity projection (does not overwrite anything).
        Priority: userPhiKey → phikey → phiKey
        """
        return self.payload.userPhiKey or self.payload.phikey or self.payload.phiKey


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

    # A deterministic seal (hash) for cache/ETag-like behavior.
    # Computed by the store (not Chronos) and stable across nodes given same registry.
    state_seal: str = Field(default="", description="Deterministic seal of the exhaled state")

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
