# app/api/routes.py
from __future__ import annotations

import os
from typing import Literal

import anyio
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.core.state_store import get_store
from app.models.state import ExhaleResponse, InhaleResponse, SigilState

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────
# Production knobs (env)
# ──────────────────────────────────────────────────────────────────────

_MAX_CONCURRENT_INHALES = max(1, int(os.getenv("KAI_MAX_CONCURRENT_INHALES", "32")))
_INHALE_SEM = anyio.Semaphore(_MAX_CONCURRENT_INHALES)

# Stream-read chunk size for uploads (bytes)
_READ_CHUNK_BYTES = max(64 * 1024, int(os.getenv("KAI_READ_CHUNK_BYTES", str(1024 * 1024))))

# Safety: prevent huge inline responses on inhale (default safe)
_MAX_INLINE_STATE_URLS = max(1, int(os.getenv("KAI_MAX_INLINE_STATE_URLS", "10000")))
_MAX_INLINE_URLS = max(1, int(os.getenv("KAI_MAX_INLINE_URLS", "20000")))


# ──────────────────────────────────────────────────────────────────────
# Response models for non-Pydantic dict routes
# ──────────────────────────────────────────────────────────────────────

class SealResponse(BaseModel):
    seal: str = Field(..., description="Deterministic state seal (ETag candidate)")


class UrlsPageResponse(BaseModel):
    status: Literal["ok"] = "ok"
    state_seal: str
    total: int
    offset: int
    limit: int
    urls: list[str]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _etag_from_seal(seal: str) -> str:
    return f"\"{seal}\""


def _no_store_cache_headers(response: Response, *, etag: str) -> None:
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"


def _resp_304(*, etag: str) -> Response:
    return Response(
        status_code=304,
        headers={
            "ETag": etag,
            "Cache-Control": "private, max-age=0, must-revalidate",
        },
    )


def _inhale_error(
    *,
    message: str,
    status_code: int = 400,
    files_received: int = 0,
    errors: list[str] | None = None,
) -> JSONResponse:
    payload = InhaleResponse(
        status="error",
        files_received=int(files_received),
        crystals_total=0,
        crystals_imported=0,
        crystals_failed=0,
        registry_urls=0,
        latest_pulse=None,
        urls=None,
        state=None,
        errors=(errors if errors is not None else [message]),
    ).model_dump(exclude_none=False)
    return JSONResponse(status_code=status_code, content=payload)


async def _collect_uploads(request: Request) -> list[UploadFile]:
    """
    Multipart collector immune to client naming quirks:
    - Accepts: file, files, files[], or ANY key as long as value is UploadFile.
    - Avoids FastAPI/Pydantic list parsing edge cases entirely.
    """
    form = await request.form()
    uploads: list[UploadFile] = []
    for _k, v in form.multi_items():
        if isinstance(v, UploadFile):
            uploads.append(v)
    return uploads


async def _read_upload_capped(up: UploadFile, *, max_bytes: int) -> tuple[bytes | None, list[str]]:
    """
    Stream-read with hard cap.
    Returns (bytes_or_none, notes). Notes may include warnings or fail-soft reasons.
    """
    name = up.filename or "krystal.json"
    notes: list[str] = []

    ctype = (up.content_type or "").strip().lower()
    if ctype and ctype not in ("application/json", "application/octet-stream"):
        notes.append(f"{name}: unexpected content-type '{up.content_type}' (still attempting JSON parse).")

    buf = bytearray()
    try:
        while True:
            chunk = await up.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > max_bytes:
                return (
                    None,
                    [
                        f"{name}: file too large ({len(buf)} bytes) exceeds max_bytes_per_file={max_bytes}.",
                        f"{name}: skipped",
                    ],
                )
    finally:
        try:
            await up.close()
        except Exception:
            pass

    if not buf:
        return (None, [f"{name}: empty file", f"{name}: skipped"])

    return (bytes(buf), notes)


def _store_seal(store: object) -> str:
    """
    Preferred: store.get_seal() (fast, cached).
    Fallback: derive from state.state_seal.
    """
    get_seal = getattr(store, "get_seal", None)
    if callable(get_seal):
        s = get_seal()
        if isinstance(s, str) and s:
            return s

    st = getattr(store, "get_state")()
    s2 = getattr(st, "state_seal", "") or ""
    return s2


def _store_urls_page(store: object, *, offset: int, limit: int) -> tuple[list[str], int]:
    """
    Preferred: store.exhale_urls_page(offset, limit) -> (page, total).
    Fallback: slice store.exhale_urls().
    """
    fn = getattr(store, "exhale_urls_page", None)
    if callable(fn):
        out = fn(offset=offset, limit=limit)
        if (
            isinstance(out, tuple)
            and len(out) == 2
            and isinstance(out[0], list)
            and isinstance(out[1], int)
        ):
            return (out[0], out[1])

    urls = getattr(store, "exhale_urls")()
    total = len(urls)
    page = urls[offset : offset + limit]
    return (page, total)


# ──────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────

@router.post(
    "/inhale",
    summary="INHALE memory krystals (JSON) → merge into global sigil state",
    response_model=InhaleResponse,
)
async def inhale(
    request: Request,
    response: Response,
    include_state: bool = Query(True),
    include_urls: bool = Query(True),
    max_bytes_per_file: int = Query(
        10_000_000,
        ge=1_000,
        le=100_000_000,
        description="Safety cap per file (bytes). Oversized files fail-soft (skipped) and do not block others.",
    ),
) -> InhaleResponse:
    async with _INHALE_SEM:
        uploads = await _collect_uploads(request)
        if not uploads:
            # Keep `.status` contract
            return _inhale_error(message="No files received for inhale.", status_code=400)  # type: ignore[return-value]

        file_blobs: list[tuple[str, bytes]] = []
        soft_notes: list[str] = []
        total_uploads = len(uploads)

        for up in uploads:
            blob, notes = await _read_upload_capped(up, max_bytes=max_bytes_per_file)
            if notes:
                soft_notes.extend(notes)
            if blob is None:
                continue
            name = up.filename or "krystal.json"
            file_blobs.append((name, blob))

        if not file_blobs:
            return _inhale_error(
                message="All uploaded files were rejected or empty.",
                status_code=400,
                files_received=total_uploads,
                errors=(soft_notes if soft_notes else None),
            )  # type: ignore[return-value]

        store = get_store()

        # Merge off event loop
        report = await anyio.to_thread.run_sync(store.inhale_files, file_blobs)

        # Deterministic seal/ETag
        seal = _store_seal(store)
        etag = _etag_from_seal(seal)
        _no_store_cache_headers(response, etag=etag)

        registry_urls = int(report.registry_urls)
        errors: list[str] = list(report.errors)
        if soft_notes:
            errors.extend(soft_notes)

        state: SigilState | None = None
        urls: list[str] | None = None

        if include_state:
            if registry_urls > _MAX_INLINE_STATE_URLS:
                errors.append(
                    f"state suppressed: registry_urls={registry_urls} exceeds KAI_MAX_INLINE_STATE_URLS={_MAX_INLINE_STATE_URLS}. Use GET /sigils/state."
                )
            else:
                state = store.get_state()

        if include_urls:
            if registry_urls > _MAX_INLINE_URLS:
                errors.append(
                    f"urls suppressed: registry_urls={registry_urls} exceeds KAI_MAX_INLINE_URLS={_MAX_INLINE_URLS}. Use GET /sigils/urls paging."
                )
            else:
                urls = store.exhale_urls()

        return InhaleResponse(
            status="ok",
            files_received=total_uploads,
            crystals_total=report.crystals_total,
            crystals_imported=report.crystals_imported,
            crystals_failed=report.crystals_failed,
            registry_urls=report.registry_urls,
            latest_pulse=report.latest_pulse,
            urls=urls,
            state=state,
            errors=errors,
        )


@router.get(
    "/seal",
    summary="Deterministic state seal (ETag candidate) — fast, Kai-only",
    response_model=SealResponse,
    responses={304: {"description": "Not Modified"}},
)
def seal(request: Request, response: Response) -> SealResponse | Response:
    store = get_store()
    s = _store_seal(store)
    etag = _etag_from_seal(s)

    inm = (request.headers.get("if-none-match") or "").strip()
    if inm == etag:
        return _resp_304(etag=etag)

    _no_store_cache_headers(response, etag=etag)
    return SealResponse(seal=s)


@router.get(
    "/state",
    summary="Current merged global sigil state (Kai-ordered, no Chronos)",
    response_model=SigilState,
    responses={304: {"description": "Not Modified"}},
)
def state(request: Request, response: Response) -> SigilState | Response:
    store = get_store()
    s = _store_seal(store)
    etag = _etag_from_seal(s)

    inm = (request.headers.get("if-none-match") or "").strip()
    if inm == etag:
        return _resp_304(etag=etag)

    _no_store_cache_headers(response, etag=etag)
    return store.get_state()


@router.get(
    "/urls",
    summary="EXHALE urls list (paged) — built for huge registries",
    response_model=UrlsPageResponse,
    responses={304: {"description": "Not Modified"}},
)
def urls(
    request: Request,
    response: Response,
    offset: int = Query(0, ge=0),
    limit: int = Query(10_000, ge=1, le=200_000),
) -> UrlsPageResponse | Response:
    store = get_store()
    s = _store_seal(store)
    etag = _etag_from_seal(s)

    inm = (request.headers.get("if-none-match") or "").strip()
    if inm == etag and offset == 0:
        return _resp_304(etag=etag)

    _no_store_cache_headers(response, etag=etag)

    page, total = _store_urls_page(store, offset=int(offset), limit=int(limit))
    return UrlsPageResponse(
        state_seal=s,
        total=int(total),
        offset=int(offset),
        limit=int(limit),
        urls=page,
    )


@router.get(
    "/exhale",
    summary="EXHALE the merged state (urls list for SigilExplorer, or full state)",
    response_model=ExhaleResponse,
    responses={304: {"description": "Not Modified"}},
)
def exhale(
    request: Request,
    response: Response,
    mode: Literal["urls", "state"] = Query("urls"),
) -> ExhaleResponse | Response:
    store = get_store()
    s = _store_seal(store)
    etag = _etag_from_seal(s)

    inm = (request.headers.get("if-none-match") or "").strip()
    if inm == etag:
        return _resp_304(etag=etag)

    _no_store_cache_headers(response, etag=etag)

    if mode == "urls":
        return ExhaleResponse(status="ok", mode="urls", urls=store.exhale_urls(), state=None)

    return ExhaleResponse(status="ok", mode="state", urls=None, state=store.get_state())
