# app/core/witness.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.core.url_extract import (
    canonicalize_url,
    extract_payload_from_url,
    looks_like_bare_token,
    safe_decode_uri_component,
)
from app.models.payload import SigilPayloadLoose

WITNESS_ADD_MAX = 512


@dataclass(frozen=True, slots=True)
class WitnessCtx:
    """
    Witness context derived from add= chain.

    chain: origin..parent URLs (canonical absolute)
    originUrl: first entry in chain (if any)
    parentUrl: last entry in chain (if any)
    """
    chain: list[str]
    originUrl: str | None = None
    parentUrl: str | None = None


def _extract_add_values_from_url(url: str) -> list[str]:
    """
    Extract raw add= values from BOTH query and fragment.

    Mirrors SigilExplorer behavior:
      rawAdds = [...u.searchParams.getAll("add"), ...hashParams.getAll("add")]
    """
    u = urlsplit(url)

    # query add=
    q = parse_qs(u.query or "", keep_blank_values=False)
    raw_adds: list[str] = [v for v in (q.get("add") or []) if isinstance(v, str)]

    # fragment add= (#add=...&add=...)
    frag = u.fragment or ""
    if frag.startswith("#"):
        frag = frag[1:]
    if frag:
        h = parse_qs(frag, keep_blank_values=False)
        raw_adds.extend([v for v in (h.get("add") or []) if isinstance(v, str)])

    return [a for a in raw_adds if a and a.strip()]


def extract_witness_chain_from_url(url: str, *, base_origin: str) -> list[str]:
    """
    Extract and normalize #add= witness chain from a URL.

    Rules (matches SigilExplorer):
    - Decode each add value (best-effort).
    - If add value is a bare token, treat it as /stream/p/<token> at base_origin.
    - Canonicalize each into a stable absolute URL key.
    - Deduplicate in-order.
    - Keep only the last WITNESS_ADD_MAX entries.
    """
    abs_url = canonicalize_url(url, base_origin=base_origin)
    if not abs_url:
        return []

    raw_adds = _extract_add_values_from_url(abs_url)
    out: list[str] = []
    seen: set[str] = set()

    for raw in raw_adds:
        decoded = safe_decode_uri_component(str(raw)).strip()
        if not decoded:
            continue

        # bare token -> /stream/p/<token>
        if looks_like_bare_token(decoded):
            decoded = f"/stream/p/{decoded}"

        link = canonicalize_url(decoded, base_origin=base_origin)
        if not link:
            continue

        if link in seen:
            continue
        seen.add(link)
        out.append(link)

    if len(out) > WITNESS_ADD_MAX:
        out = out[-WITNESS_ADD_MAX:]
    return out


def derive_witness_context(url: str, *, base_origin: str) -> WitnessCtx:
    """
    Derive (originUrl, parentUrl) from witness chain.
    chain is origin..parent (URLs).
    """
    chain = extract_witness_chain_from_url(url, base_origin=base_origin)
    if not chain:
        return WitnessCtx(chain=[])
    return WitnessCtx(
        chain=chain,
        originUrl=chain[0] if chain else None,
        parentUrl=chain[-1] if chain else None,
    )


def merge_derived_context(payload: SigilPayloadLoose, ctx: WitnessCtx) -> SigilPayloadLoose:
    """
    Merge derived witness context into payload WITHOUT overriding explicit payload fields.
    """
    next_p = SigilPayloadLoose.model_validate(payload.model_dump())
    if ctx.originUrl and not next_p.originUrl:
        next_p.originUrl = ctx.originUrl
    if ctx.parentUrl and not next_p.parentUrl:
        next_p.parentUrl = ctx.parentUrl
    return next_p


def _soft_patch_topology(
    p: SigilPayloadLoose,
    *,
    originUrl: str | None,
    parentUrl: str | None,
) -> tuple[SigilPayloadLoose, bool]:
    """
    Only fills missing originUrl/parentUrl. Never overwrites.
    Returns (patched_payload, changed?).
    """
    changed = False
    next_p = p

    if originUrl and not next_p.originUrl:
        next_p = SigilPayloadLoose.model_validate(next_p.model_dump())
        next_p.originUrl = originUrl
        changed = True

    if parentUrl and not next_p.parentUrl:
        if not changed:
            next_p = SigilPayloadLoose.model_validate(next_p.model_dump())
        next_p.parentUrl = parentUrl
        changed = True

    return next_p, changed


def synthesize_edges_from_witness_chain(
    chain: list[str],
    leaf_url: str,
    reg: dict[str, SigilPayloadLoose],
    *,
    base_origin: str,
) -> int:
    """
    Given:
      chain = [origin .. parent] (canonical absolute URLs)
      leaf_url = the URL that carried this chain (reply/child)

    This synthesizes parent relations exactly like SigilExplorer’s intent:
      - origin.originUrl = origin (if missing)
      - for i in 1..len(chain)-1:
          chain[i].originUrl = origin (if missing)
          chain[i].parentUrl = chain[i-1] (if missing)
      - leaf.originUrl = origin (if missing)
      - leaf.parentUrl = chain[-1] (if missing)

    Important:
      - We do NOT overwrite existing originUrl/parentUrl.
      - If a chain URL is missing from reg, we attempt to decode a payload from the URL itself
        (only if it carries a token). If it can’t be decoded, we skip it.
      - Returns the number of registry entries that changed (patched or inserted).
    """
    if not chain:
        return 0

    # Canonicalize all inputs (defensive)
    chain_abs = [canonicalize_url(u, base_origin=base_origin) for u in chain]
    chain_abs = [u for u in chain_abs if u]
    if not chain_abs:
        return 0

    origin = chain_abs[0]
    leaf_abs = canonicalize_url(leaf_url, base_origin=base_origin)
    if not leaf_abs:
        return 0

    changed = 0

    def ensure(url: str) -> None:
        nonlocal changed
        if url in reg:
            return
        hit = extract_payload_from_url(url, base_origin=base_origin)
        if hit is None:
            return
        reg[hit.url_key] = hit.payload
        changed += 1

    # Ensure origin exists (if decodable)
    ensure(origin)

    # Patch origin: originUrl=self (soft), parentUrl untouched unless missing (we leave missing)
    if origin in reg:
        p0 = reg[origin]
        patched, did = _soft_patch_topology(p0, originUrl=origin, parentUrl=None)
        if did:
            reg[origin] = patched
            changed += 1

    # Walk chain nodes, synthesize parent relations
    for i in range(1, len(chain_abs)):
        child = chain_abs[i]
        parent = chain_abs[i - 1]

        ensure(child)
        if child in reg:
            p = reg[child]
            patched, did = _soft_patch_topology(p, originUrl=origin, parentUrl=parent)
            if did:
                reg[child] = patched
                changed += 1

    # Ensure leaf exists (it should, but keep robust)
    ensure(leaf_abs)

    # Patch leaf with origin + parent=last chain entry
    if leaf_abs in reg:
        leaf_parent = chain_abs[-1]
        p = reg[leaf_abs]
        patched, did = _soft_patch_topology(p, originUrl=origin, parentUrl=leaf_parent)
        if did:
            reg[leaf_abs] = patched
            changed += 1

    return changed
