# app/core/state_store.py
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.jsonio import dumps_canonical_json, loads_json_bytes
from app.core.kai_time import latest_kai
from app.core.merge_engine import build_ordered_urls, inhale_files_into_registry
from app.models.payload import SigilPayloadLoose
from app.models.state import InhaleReport, KaiMoment, SigilEntry, SigilState


def _env_truthy(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def _default_base_origin() -> str:
    """
    Base origin is ONLY used when:
      - an input is relative, OR
      - an input is a bare token (we convert to /stream/p/<token>)

    Absolute URLs keep their own origin and are not rewritten.
    """
    return os.getenv("KAI_BASE_ORIGIN", "https://example.invalid").strip() or "https://example.invalid"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


@dataclass(slots=True)
class SigilStateStore:
    """
    In-memory, single-source-of-truth registry.

    registry maps:
      canonical_url_key -> SigilPayloadLoose

    Determinism:
    - Merge decisions use Kai tuple ONLY: (pulse, beat, stepIndex).
    - EXHALE order is Kai-desc, tie-broken by URL string.
    - No Chronos fields are created or consulted.
    """

    base_origin: str
    persist_path: Path | None

    _lock: threading.RLock
    _registry: dict[str, SigilPayloadLoose]

    def __init__(self, *, base_origin: str | None = None, persist_path: str | None = None) -> None:
        self.base_origin = (base_origin or _default_base_origin()).strip()
        self.persist_path = Path(persist_path).expanduser().resolve() if persist_path else None
        self._lock = threading.RLock()
        self._registry = {}

        # Optional persistence (OFF unless a path is provided)
        if self.persist_path and self.persist_path.exists():
            self._load_from_disk()

    # ──────────────────────────────────────────────────────────────────
    # Persistence (optional)
    # ──────────────────────────────────────────────────────────────────

    def _load_from_disk(self) -> None:
        assert self.persist_path is not None
        try:
            blob = self.persist_path.read_bytes()
            obj = loads_json_bytes(blob, name=str(self.persist_path))
            if not isinstance(obj, dict):
                return
            reg = obj.get("registry")
            if not isinstance(reg, dict):
                return

            next_reg: dict[str, SigilPayloadLoose] = {}
            for url, payload_obj in reg.items():
                if not isinstance(url, str) or not url.strip():
                    continue
                if not isinstance(payload_obj, dict):
                    continue
                try:
                    next_reg[url] = SigilPayloadLoose.model_validate(payload_obj)
                except Exception:
                    continue

            with self._lock:
                self._registry = next_reg
        except Exception:
            # If disk state is corrupt, we fail-closed to empty registry (no crash).
            with self._lock:
                self._registry = {}

    def _save_to_disk(self) -> None:
        if not self.persist_path:
            return
        with self._lock:
            obj: dict[str, Any] = {
                "spec": "KKS-1.0",
                "registry": {u: p.model_dump(exclude_none=False) for (u, p) in self._registry.items()},
            }
        _atomic_write_text(self.persist_path, dumps_canonical_json(obj))

    # ──────────────────────────────────────────────────────────────────
    # Breath actions
    # ──────────────────────────────────────────────────────────────────

    def inhale_files(self, files: list[tuple[str, bytes]]) -> InhaleReport:
        """
        INHALE: merge uploaded krystal JSON files into the global registry.
        Returns a deterministic report.
        """
        with self._lock:
            report = inhale_files_into_registry(self._registry, files, base_origin=self.base_origin)

        # Persist only after successful merge run (even if some files failed)
        self._save_to_disk()
        return report

    def exhale_urls(self) -> list[str]:
        """
        EXHALE (urls mode): SigilExplorer-compatible export list.
        This matches the frontend import format: JSON array of canonical URLs.
        """
        with self._lock:
            return build_ordered_urls(self._registry)

    def get_state(self) -> SigilState:
        """
        EXHALE (state mode): full merged registry (Kai-ordered).
        """
        with self._lock:
            ordered_urls = build_ordered_urls(self._registry)

            entries: list[SigilEntry] = []
            payloads: list[SigilPayloadLoose] = []

            for url in ordered_urls:
                p = self._registry.get(url)
                if p is None:
                    continue
                entries.append(SigilEntry(url=url, payload=p))
                payloads.append(p)

            lt = latest_kai(payloads)
            latest = KaiMoment(pulse=lt.pulse, beat=lt.beat, stepIndex=lt.stepIndex)

            return SigilState(
                spec="KKS-1.0",
                total_urls=len(entries),
                latest=latest,
                registry=entries,
                urls=[e.url for e in entries],
            )


# ──────────────────────────────────────────────────────────────────────
# Singleton store accessor (simple + robust)
# ──────────────────────────────────────────────────────────────────────

_STORE: SigilStateStore | None = None


def get_store() -> SigilStateStore:
    """
    Global store. Configuration via env:
      - KAI_BASE_ORIGIN: base for relative URLs / bare tokens
      - KAI_STATE_PATH: if set, enables persistence to disk
    """
    global _STORE
    if _STORE is None:
        persist = os.getenv("KAI_STATE_PATH")
        _STORE = SigilStateStore(
            base_origin=_default_base_origin(),
            persist_path=persist.strip() if persist else None,
        )
    return _STORE
