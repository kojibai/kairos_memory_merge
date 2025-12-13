# app/core/url_extract.py
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import ParseResult, parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit

from app.models.payload import SigilPayloadLoose

# ──────────────────────────────────────────────────────────────────────────────
# Token / URL patterns (covers your known shapes)
# ──────────────────────────────────────────────────────────────────────────────

_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# /stream/p/<token>
_STREAM_P_RE = re.compile(r"^/stream/p/([^/]+)$")
# /p~<token>  (SMS-safe short route)
_P_TILDE_RE = re.compile(r"^/p~([^/]+)$")
# /stream/p~<token> (if ever used)
_STREAM_P_TILDE_RE = re.compile(r"^/stream/p~([^/]+)$")

# Content-ID routes (no embedded payload)
_STREAM_C_RE = re.compile(r"^/stream/c/([0-9a-fA-F]{16,})$")


@dataclass(frozen=True, slots=True)
class UrlPayloadHit:
    """
    One extracted payload from a URL.
    - url_key: canonicalized absolute URL used as registry key
    - payload: decoded payload object
    """
    url_key: str
    payload: SigilPayloadLoose


def safe_decode_uri_component(v: str) -> str:
    try:
        return unquote(v)
    except Exception:
        return v


def looks_like_bare_token(s: str) -> bool:
    t = s.strip()
    if len(t) < 16:
        return False
    return bool(_B64URL_RE.match(t))


def _add_b64_padding(s: str) -> str:
    # base64url may be unpadded; pad to multiple of 4
    r = len(s) % 4
    if r == 0:
        return s
    return s + ("=" * (4 - r))


def _decode_base64url_to_bytes(token: str, *, max_decoded_bytes: int = 2_000_000) -> bytes:
    raw = token.strip()
    raw = _add_b64_padding(raw)
    try:
        out = base64.urlsafe_b64decode(raw.encode("utf-8"))
    except Exception as e:
        raise ValueError(f"token is not valid base64url: {e}") from e

    if len(out) > max_decoded_bytes:
        raise ValueError(f"decoded token too large ({len(out)} bytes)")
    return out


def _strip_token_prefixes(token: str) -> str:
    """
    Your ecosystem uses prefixed tokens like:
      - c:<b64url>   (compact)
      - j:<b64url>   (json)
      - p:<b64url> / t:<b64url> (historical variants)
    We strip known single-letter prefixes ONLY.
    """
    t = token.strip()
    if len(t) >= 3 and t[1] == ":":
        prefix = t[0].lower()
        if prefix in ("c", "j", "p", "t"):
            return t[2:]
    return t


def _parse_token_to_obj(token: str) -> dict[str, Any]:
    """
    Token -> dict payload.
    Accepts:
      - base64url(json)
      - prefixed base64url: c:..., j:..., p:..., t:...
      - raw json text (rare) if token begins with '{'
    """
    tok = safe_decode_uri_component(token).strip()

    # If someone handed raw JSON directly
    if tok.startswith("{") and tok.endswith("}"):
        try:
            obj = json.loads(tok)
        except Exception as e:
            raise ValueError(f"raw json token invalid: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError("raw json token must decode to an object")
        return obj

    # Strip known prefixes then base64url-decode
    b64 = _strip_token_prefixes(tok)
    decoded = _decode_base64url_to_bytes(b64)
    try:
        text = decoded.decode("utf-8")
    except Exception as e:
        raise ValueError(f"decoded token is not utf-8 json: {e}") from e

    try:
        obj = json.loads(text)
    except Exception as e:
        raise ValueError(f"decoded token is not valid json: {e}") from e

    if not isinstance(obj, dict):
        raise ValueError("decoded token must be a JSON object")
    return obj


def _canonicalize_parsed(u: ParseResult) -> str:
    """
    Deterministic canonicalization, close to browser `new URL(...).toString()`:
    - scheme + netloc are lowercased (URL semantics)
    - everything else preserved as-is
    """
    scheme = (u.scheme or "").lower()
    netloc = (u.netloc or "").lower()
    return urlunsplit((scheme, netloc, u.path or "", u.query or "", u.fragment or ""))


def canonicalize_url(url: str, *, base_origin: str) -> str:
    """
    Make a stable absolute URL key.
    - Resolves relative URLs against base_origin.
    - If given a bare token, converts to /stream/p/<token> at base_origin.
    - Normalizes /p~<token> → /stream/p/<token> (preserving query + hash).
    """
    raw = (url or "").strip()
    if not raw:
        return ""

    # Bare token → canonical stream URL
    if looks_like_bare_token(raw):
        raw = f"/stream/p/{raw}"

    abs_url = urljoin(base_origin, raw)
    u = urlsplit(abs_url)

    # If /p~TOKEN or /stream/p~TOKEN → rewrite to /stream/p/TOKEN (keep query/fragment)
    m = _P_TILDE_RE.match(u.path or "")
    if m:
        token = m.group(1)
        new_path = f"/stream/p/{quote(token, safe='')}"
        u = u._replace(path=new_path)
        return _canonicalize_parsed(u)

    m2 = _STREAM_P_TILDE_RE.match(u.path or "")
    if m2:
        token = m2.group(1)
        new_path = f"/stream/p/{quote(token, safe='')}"
        u = u._replace(path=new_path)
        return _canonicalize_parsed(u)

    return _canonicalize_parsed(u)


def _extract_candidate_tokens_from_url(u: ParseResult) -> list[str]:
    """
    Pull possible payload tokens from:
      - path forms (/stream/p/<token>)
      - query params (p=, t=, root=, token=)
      - fragment params (same keys)
    Returns candidates in priority order (most likely first).
    """
    candidates: list[str] = []

    path = u.path or ""

    # Ignore content-id routes (no payload embedded)
    if _STREAM_C_RE.match(path):
        return []

    # /stream/p/<token>
    m = _STREAM_P_RE.match(path)
    if m:
        candidates.append(m.group(1))

    # /p~<token> and /stream/p~<token> are rewritten by canonicalize_url(),
    # but keep a fallback extraction here anyway:
    m = _P_TILDE_RE.match(path)
    if m:
        candidates.append(m.group(1))
    m = _STREAM_P_TILDE_RE.match(path)
    if m:
        candidates.append(m.group(1))

    # query params
    q = parse_qs(u.query or "", keep_blank_values=False)
    for key in ("p", "t", "root", "token"):
        vals = q.get(key) or []
        for v in vals:
            if isinstance(v, str) and v.strip():
                candidates.append(v.strip())

    # fragment params (#k=v&...)
    frag = (u.fragment or "")
    if frag.startswith("#"):
        frag = frag[1:]
    if frag:
        h = parse_qs(frag, keep_blank_values=False)
        for key in ("p", "t", "root", "token"):
            vals = h.get(key) or []
            for v in vals:
                if isinstance(v, str) and v.strip():
                    candidates.append(v.strip())

    # de-dupe in-order
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        c2 = safe_decode_uri_component(c).strip()
        if not c2:
            continue
        if c2 in seen:
            continue
        seen.add(c2)
        out.append(c2)
    return out


def extract_payload_from_url(url: str, *, base_origin: str) -> UrlPayloadHit | None:
    """
    Best-effort: extract a SigilPayloadLoose from any URL that carries a token.
    Returns None if no token/payload found.

    Determinism:
    - The returned url_key is canonicalized absolute (stable registry key).
    - Payload normalization is handled by SigilPayloadLoose (short keys → canonical fields).
    """
    key = canonicalize_url(url, base_origin=base_origin)
    if not key:
        return None

    u = urlsplit(key)

    candidates = _extract_candidate_tokens_from_url(u)
    if not candidates:
        return None

    # Try candidates until one decodes to a dict
    last_err: Exception | None = None
    for tok in candidates:
        try:
            obj = _parse_token_to_obj(tok)
            payload = SigilPayloadLoose.model_validate(obj)
            return UrlPayloadHit(url_key=key, payload=payload)
        except Exception as e:
            last_err = e
            continue

    # No candidate decoded successfully → treat as "not a payload URL"
    # (We intentionally do not raise; caller can count it as non-importable.)
    _ = last_err
    return None


def extract_many_payloads_from_any(obj: Any, *, base_origin: str) -> list[UrlPayloadHit]:
    """
    Walk arbitrary JSON structures and extract payload URLs/tokens wherever found.
    This is what makes INHALE robust to different krystal file shapes.

    Rules:
    - Any string that looks like a URL or a bare token is tried.
    - Returns hits; duplicates by url_key are NOT removed here (merge_engine will decide).
    """
    hits: list[UrlPayloadHit] = []

    def visit(x: Any) -> None:
        if x is None:
            return
        if isinstance(x, str):
            s = x.strip()
            if not s:
                return

            # Try only if it looks plausibly relevant:
            # - bare token
            # - contains /stream/ or /s/ or /p~ or "http"
            if looks_like_bare_token(s) or ("/stream" in s) or ("/s/" in s) or ("/p~" in s) or ("http" in s):
                hit = extract_payload_from_url(s, base_origin=base_origin)
                if hit is not None:
                    hits.append(hit)
            return

        if isinstance(x, dict):
            for v in x.values():
                visit(v)
            return

        if isinstance(x, list):
            for v in x:
                visit(v)
            return

        # ignore other primitives

    visit(obj)
    return hits


def unique_by_url_key(hits: Iterable[UrlPayloadHit]) -> list[UrlPayloadHit]:
    """Deterministic in-order unique by url_key."""
    out: list[UrlPayloadHit] = []
    seen: set[str] = set()
    for h in hits:
        if h.url_key in seen:
            continue
        seen.add(h.url_key)
        out.append(h)
    return out
