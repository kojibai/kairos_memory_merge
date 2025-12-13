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
        return int(raw)
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

    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

    if keep_backup and path.exists():
        try:
            bak.write_bytes(path.read_bytes())
        except Exception:
            pass

    os.replace(tmp, path)


def _load_json_file_best_effort(path: Path) -> dict[str, Any] | None:
    try:
        blob = path.read_bytes()
        obj = loads_json_bytes(blob, name=str(path))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _compute_seal_from_urls(urls: list[str]) -> str:
    """
    Deterministic seal for cache/ETag-like behavior (NOT a security boundary).
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

    Production throughput:
    - Exhale/state are cached and recomputed ONLY after inhale mutates the registry.
    """

    base_origin: str
    persist_path: Path | None

    _lock: threading.RLock
    _registry: dict[str, SigilPayloadLoose]

    # optional cap for runaway registries (0 = disabled)
    _prune_keep: int

    # cache (valid until next mutate)
    _cache_urls: list[str] | None
    _cache_seal: str
    _cache_state: SigilState | None

    def __init__(self, *, base_origin: str | None = None, persist_path: str | None = None) -> None:
        self.base_origin = (base_origin or _default_base_origin()).strip()
        self.persist_path = Path(persist_path).expanduser().resolve() if persist_path else None
        self._lock = threading.RLock()
        self._registry = {}
        self._prune_keep = _safe_int("KAI_REGISTRY_KEEP", 0)

        self._cache_urls = None
        self._cache_seal = ""
        self._cache_state = None

        if self.persist_path:
            self._load_from_disk_best_effort()
            self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        self._cache_urls = None
        self._cache_seal = ""
        self._cache_state = None

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
            # persistence failure must never break the API
            return

    def _maybe_prune(self) -> None:
        keep = self._prune_keep
        if keep <= 0:
            return
        if len(self._registry) <= keep:
            return

        ordered = build_ordered_urls(self._registry)  # Kai-desc
        next_reg: dict[str, SigilPayloadLoose] = {}
        for url in ordered[:keep]:
            p = self._registry.get(url)
            if p is not None:
                next_reg[url] = p
        self._registry = next_reg

    # ──────────────────────────────────────────────────────────────────
    # Cache builders (called only when needed)
    # ──────────────────────────────────────────────────────────────────

    def _ensure_urls_cache(self) -> None:
        if self._cache_urls is not None:
            return
        ordered = build_ordered_urls(self._registry)  # Kai-desc
        self._cache_urls = ordered
        self._cache_seal = _compute_seal_from_urls(ordered)

    def _ensure_state_cache(self) -> None:
        if self._cache_state is not None:
            return
        self._ensure_urls_cache()
        assert self._cache_urls is not None

        entries: list[SigilEntry] = []
        payloads: list[SigilPayloadLoose] = []

        for url in self._cache_urls:
            p = self._registry.get(url)
            if p is None:
                continue
            entries.append(SigilEntry(url=url, payload=p))
            payloads.append(p)

        if payloads:
            lt = latest_kai(payloads)
            latest = KaiMoment(pulse=int(lt.pulse), beat=int(lt.beat), stepIndex=int(lt.stepIndex))
        else:
            latest = KaiMoment()

        self._cache_state = SigilState(
            spec="KKS-1.0",
            total_urls=len(entries),
            latest=latest,
            state_seal=self._cache_seal,
            registry=entries,
            urls=self._cache_urls,
        )

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
            self._invalidate_cache()

        self._save_to_disk_best_effort()
        return report

    def exhale_urls(self) -> list[str]:
        """
        EXHALE (urls mode): SigilExplorer-compatible export list.
        Cached (fast) — recomputed only after inhale.
        """
        with self._lock:
            self._ensure_urls_cache()
            assert self._cache_urls is not None
            return self._cache_urls

    def exhale_urls_page(self, *, offset: int, limit: int) -> tuple[list[str], int]:
        """
        Cached paging for huge registries.
        Returns (page_urls, total_urls).
        """
        o = max(0, int(offset))
        l = max(1, int(limit))
        with self._lock:
            self._ensure_urls_cache()
            assert self._cache_urls is not None
            total = len(self._cache_urls)
            return (self._cache_urls[o : o + l], total)

    def get_seal(self) -> str:
        """
        Fast deterministic seal (ETag candidate). Cached.
        """
        with self._lock:
            self._ensure_urls_cache()
            return self._cache_seal

    def get_state(self) -> SigilState:
        """
        EXHALE (state mode): full merged registry (Kai-ordered).
        Cached (fast) — recomputed only after inhale.
        """
        with self._lock:
            self._ensure_state_cache()
            assert self._cache_state is not None
            # defensive copy so callers can’t mutate cached object
            return self._cache_state.model_copy(deep=False)


# ──────────────────────────────────────────────────────────────────────
# Singleton store accessor
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
