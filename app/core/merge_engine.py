# app/core/merge_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.jsonio import loads_json_bytes
from app.core.kai_time import kai_tuple_from_payload, kai_newer, kai_sort_key_desc
from app.core.url_extract import (
    canonicalize_url,
    extract_many_payloads_from_any,
    extract_payload_from_url,
)
from app.core.witness import (
    derive_witness_context,
    merge_derived_context,
    synthesize_edges_from_witness_chain,
)
from app.models.payload import SigilPayloadLoose
from app.models.state import InhaleReport


def _is_missing(v: object) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return len(v.strip()) == 0
    if isinstance(v, (list, tuple, set)):
        return len(v) == 0
    if isinstance(v, dict):
        return len(v) == 0
    return False


def _richness_score(p: SigilPayloadLoose) -> int:
    """
    Deterministic payload richness score:
    - counts non-missing fields (including extras)
    - weights topology + identity slightly higher
    Used only for tie-breaks when Kai-time is equal.
    """
    d = p.model_dump(exclude_none=False)
    score = 0
    for k, v in d.items():
        if _is_missing(v):
            continue
        score += 1
        if k in ("originUrl", "parentUrl", "kaiSignature", "userPhiKey", "phiKey", "phikey"):
            score += 2
        if k in ("pulse", "beat", "stepIndex", "chakraDay"):
            score += 1
    return score


def _canonicalize_topology(p: SigilPayloadLoose, *, base_origin: str) -> SigilPayloadLoose:
    """
    Canonicalize originUrl/parentUrl (if present) to stable absolute URL keys.
    Mirrors the frontend behavior: relative → absolute, tokens → /stream/p/<token>.
    """
    changed = False
    next_p = p

    if isinstance(p.originUrl, str) and p.originUrl.strip():
        o = canonicalize_url(p.originUrl, base_origin=base_origin)
        if o and o != p.originUrl:
            next_p = SigilPayloadLoose.model_validate(next_p.model_dump())
            next_p.originUrl = o
            changed = True

    if isinstance(p.parentUrl, str) and p.parentUrl.strip():
        pr = canonicalize_url(p.parentUrl, base_origin=base_origin)
        if pr and pr != p.parentUrl:
            if not changed:
                next_p = SigilPayloadLoose.model_validate(next_p.model_dump())
            next_p.parentUrl = pr

    return next_p


def _merge_payload(prev: SigilPayloadLoose, inc: SigilPayloadLoose) -> SigilPayloadLoose:
    """
    Deterministic merge:
    1) Prefer newer payload by Kai tuple (pulse, beat, stepIndex).
    2) If equal Kai tuple, prefer richer payload.
    3) Fill missing fields from the other payload (never overwrite existing non-missing).
    """
    prev_k = kai_tuple_from_payload(prev).as_tuple()
    inc_k = kai_tuple_from_payload(inc).as_tuple()

    if inc_k > prev_k:
        base = inc
        other = prev
    elif inc_k < prev_k:
        base = prev
        other = inc
    else:
        # tie: choose richer as base
        if _richness_score(inc) > _richness_score(prev):
            base = inc
            other = prev
        else:
            base = prev
            other = inc

    bd = base.model_dump(exclude_none=False)
    od = other.model_dump(exclude_none=False)

    # Fill missing keys only
    for k, ov in od.items():
        bv = bd.get(k)
        if _is_missing(bv) and not _is_missing(ov):
            bd[k] = ov

    return SigilPayloadLoose.model_validate(bd)


def _ensure_url_in_registry(
    reg: dict[str, SigilPayloadLoose],
    url: str,
    *,
    base_origin: str,
) -> bool:
    """
    Best-effort: ensure a URL is present in registry by decoding its embedded token (if any).
    Returns True if inserted.
    """
    hit = extract_payload_from_url(url, base_origin=base_origin)
    if hit is None:
        return False
    if hit.url_key in reg:
        return False
    reg[hit.url_key] = hit.payload
    return True


def _stitch_explicit_parent_chain(
    reg: dict[str, SigilPayloadLoose],
    start_url: str,
    *,
    base_origin: str,
    max_depth: int = 128,
) -> int:
    """
    Fallback ancestry (backend version of “older payload formats” support):
    If a payload explicitly carries parentUrl/originUrl, try to ensure those
    URLs exist in the registry (only if decodable) and soft-fill topology.

    This never overwrites explicit fields; it only inserts missing ancestors
    and allows later witness synthesis to complete edges.
    """
    changed = 0
    cur_url = start_url
    depth = 0

    while depth < max_depth:
        depth += 1
        p = reg.get(cur_url)
        if p is None:
            break

        # Ensure originUrl exists (if decodable)
        if isinstance(p.originUrl, str) and p.originUrl.strip():
            o = canonicalize_url(p.originUrl, base_origin=base_origin)
            if o:
                if _ensure_url_in_registry(reg, o, base_origin=base_origin):
                    changed += 1

        # Walk parent chain
        if not (isinstance(p.parentUrl, str) and p.parentUrl.strip()):
            break

        parent = canonicalize_url(p.parentUrl, base_origin=base_origin)
        if not parent:
            break

        if _ensure_url_in_registry(reg, parent, base_origin=base_origin):
            changed += 1

        cur_url = parent

    return changed


def upsert_payload(
    reg: dict[str, SigilPayloadLoose],
    url_key: str,
    payload: SigilPayloadLoose,
) -> bool:
    """
    Upsert by URL key with deterministic merge rules.
    Returns True if registry changed (insert or material update).
    """
    prev = reg.get(url_key)
    if prev is None:
        reg[url_key] = payload
        return True

    merged = _merge_payload(prev, payload)

    # Detect material change (topology + Kai tuple + signature changes)
    prev_d = prev.model_dump(exclude_none=False)
    merged_d = merged.model_dump(exclude_none=False)

    if prev_d == merged_d:
        return False

    reg[url_key] = merged
    return True


def inhale_files_into_registry(
    reg: dict[str, SigilPayloadLoose],
    files: list[tuple[str, bytes]],
    *,
    base_origin: str,
) -> InhaleReport:
    """
    Core breath-merge engine.

    Input: one or more JSON files (krystals).
    Output: InhaleReport; mutates `reg` in place.

    Determinism & Rules:
    - No Chronos time is used (ever).
    - Ordering and "newer wins" is Kai tuple (pulse, beat, stepIndex).
    - Witness chain (#add= / ?add=) is used to derive and synthesize topology.
    - Explicit payload fields are never overwritten by derived context.
    """
    report = InhaleReport()
    registry_changes = 0

    for name, blob in files:
        try:
            obj = loads_json_bytes(blob, name=name)
        except Exception as e:
            report.crystals_failed += 1
            report.errors.append(str(e))
            continue

        # Extract all decodable payload hits embedded anywhere in the JSON
        hits = extract_many_payloads_from_any(obj, base_origin=base_origin)

        report.crystals_total += len(hits)

        # Process each hit
        for hit in hits:
            url_key = canonicalize_url(hit.url_key, base_origin=base_origin)
            if not url_key:
                continue

            # Derive witness context from the URL itself (query + hash add=)
            ctx = derive_witness_context(url_key, base_origin=base_origin)
            merged_leaf = merge_derived_context(hit.payload, ctx)
            merged_leaf = _canonicalize_topology(merged_leaf, base_origin=base_origin)

            changed = upsert_payload(reg, url_key, merged_leaf)
            if changed:
                registry_changes += 1
                report.crystals_imported += 1

            # If witness chain exists, synthesize edges across chain + leaf (soft fill)
            if ctx.chain:
                registry_changes += synthesize_edges_from_witness_chain(
                    ctx.chain,
                    url_key,
                    reg,
                    base_origin=base_origin,
                )

            # Fallback ancestry from explicit parent/origin fields
            registry_changes += _stitch_explicit_parent_chain(
                reg,
                url_key,
                base_origin=base_origin,
                max_depth=128,
            )

    report.registry_urls = len(reg)

    # Compute latest pulse across registry (Kai-only)
    latest_pulse: int | None = None
    for p in reg.values():
        if p.pulse is None:
            continue
        if latest_pulse is None or int(p.pulse) > latest_pulse:
            latest_pulse = int(p.pulse)
    report.latest_pulse = latest_pulse

    return report


def build_ordered_urls(reg: dict[str, SigilPayloadLoose]) -> list[str]:
    """
    Deterministic SigilExplorer export:
    - Returns canonical URL keys sorted by Kai time DESC, tie-broken by URL string ASC.
    """
    items = list(reg.items())

    def key(item: tuple[str, SigilPayloadLoose]) -> tuple[tuple[int, int, int], str]:
        url, payload = item
        return (kai_sort_key_desc(payload), url)

    items.sort(key=key, reverse=True)
    return [u for (u, _) in items]
