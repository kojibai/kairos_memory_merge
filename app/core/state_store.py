# app/core/state_store.py
from __future__ import annotations

import hashlib
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


def _default_base_origin() -> str:
    """
    Base origin is ONLY used when:
      - an input is relative, OR
      - an input is a bare token (we convert to /stream/p/<token>)

    Absolute URLs keep their own origin and are not rewritten.
    """
    return os.getenv("KAI_BASE_ORIGIN", "https://example.invalid").strip() or "https://example.invalid"


def _safe_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v
    except Exception:
        return default


def _atomic_write_text(path: Path, text: str, *, keep_backup: bool = True) -> None:
    """
    Atomic write with optional backup.
    - Writes to <path>.tmp, fsyncs, then os.replace() into place.
    - If keep_backup and target exists, we save <path>.bak as last-known-good.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    bak = path.with_suffix(path.suffix + ".bak")

    # write tmp (same dir for atomic replace)
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

    # backup current
    if keep_backup and path.exists():
        try:
            # best effort; do not fail write if backup fails
            bak.write_bytes(path.read_bytes())
        except Exception:
            pass

    os.replace(tmp, path)


def _load_json_file_best_effort(path: Path) -> dict[str, Any] | None:
    """
    Load dict JSON from path (canonical or not). Returns None on failure.
    """
    try:
        blob = path.read_bytes()
        obj = loads_json_bytes(blob, name=str(path))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _compute_state_seal(urls: list[str]) -> str:
    """
    Deterministic seal for the exhaled snapshot (NOT a security boundary).
    blake2b over canonical JSON of the ordered URL list.
    """
    blob = dumps_canonical_json({"urls": urls}).encode("utf-8")
    return hashlib.blake2b(blob, digest_size=16).hexdigest()


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

    Robustness:
    - Optional persistence with atomic writes + last-known-good backup.
    - Corrupt disk state fails closed to empty (and tries .bak).
    """

    base_origin: str
    persist_path: Path | None

    _lock: threading.RLock
    _registry: dict[str, SigilPayloadLoose]

    # Optional cap for runaway registries (0 = disabled)
    _prune_keep: int

    def __init__(self, *, base_origin: str | None = None, persist_path: str | None = None) -> None:
        self.base_origin = (base_origin or _default_base_origin()).strip()
        self.persist_path = Path(persist_path).expanduser().resolve() if persist_path else None
        self._lock = threading.RLock()
        self._registry = {}
        self._prune_keep = _safe_int("KAI_REGISTRY_KEEP", 0)

        if self.persist_path:
            self._load_from_disk_best_effort()

    # ──────────────────────────────────────────────────────────────────
    # Persistence (optional)
    # ──────────────────────────────────────────────────────────────────

    def _load_from_disk_best_effort(self) -> None:
        """
        Attempt load in this order:
        1) main file
        2) backup file
        Otherwise: empty registry.
        """
        assert self.persist_path is not None
        main = self.persist_path
        bak = self.persist_path.with_suffix(self.persist_path.suffix + ".bak")

        obj = _load_json_file_best_effort(main)
        if obj is None:
            obj = _load_json_file_best_effort(bak)

        next_reg: dict[str, SigilPayloadLoose] = {}
        if isinstance(obj, dict):
            reg = obj.get("registry")
            if isinstance(reg, dict):
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

    def _save_to_disk_best_effort(self) -> None:
        if not self.persist_path:
            return
        with self._lock:
            obj: dict[str, Any] = {
                "spec": "KKS-1.0",
                "registry": {u: p.model_dump(exclude_none=False) for (u, p) in self._registry.items()},
            }
        try:
            _atomic_write_text(self.persist_path, dumps_canonical_json(obj), keep_backup=True)
        except Exception:
            # Persistence failure must never break the API.
            # Memory state remains authoritative.
            return

    def _maybe_prune(self) -> None:
        """
        Optional safety valve: keep only newest N entries (Kai-desc) if configured.
        Disabled by default (KAI_REGISTRY_KEEP=0).
        """
        keep = self._prune_keep
        if keep <= 0:
            return
        if len(self._registry) <= keep:
            return

        ordered = build_ordered_urls(self._registry)  # Kai-desc
        survivors = set(ordered[:keep])

        next_reg: dict[str, SigilPayloadLoose] = {}
        for url in ordered[:keep]:
            p = self._registry.get(url)
            if p is not None:
                next_reg[url] = p

        self._registry = next_reg
        _ = survivors  # (silence linters)

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
            self._maybe_prune()

        self._save_to_disk_best_effort()
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
        EXHALE (state mode): full merged registry (Kai-ordered),
        with top-level convenience fields on each entry.
        """
        with self._lock:
            ordered_urls = build_ordered_urls(self._registry)  # Kai-desc
            entries: list[SigilEntry] = []
            payloads: list[SigilPayloadLoose] = []

            for url in ordered_urls:
                p = self._registry.get(url)
                if p is None:
                    continue
                entries.append(SigilEntry(url=url, payload=p))
                payloads.append(p)

            # latest_kai should be Kai-only; still guard empty.
            if payloads:
                lt = latest_kai(payloads)
                latest = KaiMoment(pulse=int(lt.pulse), beat=int(lt.beat), stepIndex=int(lt.stepIndex))
            else:
                latest = KaiMoment()

            seal = _compute_state_seal(ordered_urls)

            return SigilState(
                spec="KKS-1.0",
                total_urls=len(entries),
                latest=latest,
                state_seal=seal,
                registry=entries,
                urls=ordered_urls,
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
      - KAI_REGISTRY_KEEP: optional cap (keep newest N; 0 disables)
    """
    global _STORE
    if _STORE is None:
        persist = os.getenv("KAI_STATE_PATH")
        _STORE = SigilStateStore(
            base_origin=_default_base_origin(),
            persist_path=persist.strip() if persist else None,
        )
    return _STORE
