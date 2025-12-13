# app/api/routes.py
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.state_store import get_store
from app.models.state import ExhaleResponse, InhaleResponse, SigilState

router = APIRouter()

_ALLOWED_JSON_CT: set[str] = {
    "application/json",
    "text/json",
    "application/*+json",
    "application/octet-stream",  # common when tools don’t set JSON correctly
}


def _safe_name(name: str | None) -> str:
    n = (name or "").strip()
    if not n:
        return "krystal.json"
    return n if len(n) <= 160 else (n[:120] + "…" + n[-30:])


def _err(status_code: int, msg: str, *, files_received: int = 0, errors: list[str] | None = None) -> JSONResponse:
    e = [msg]
    if errors:
        e.extend(errors)
    payload = InhaleResponse(
        status="error",
        files_received=files_received,
        errors=e,
    ).model_dump(exclude_none=False)
    return JSONResponse(status_code=status_code, content=payload)


async def _read_limited_bytes(uf, *, per_file_limit: int) -> bytes:
    """
    Read UploadFile in chunks with a hard cap (per_file_limit).
    Raises ValueError on overflow.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await uf.read(1024 * 1024)  # 1MB
        if not chunk:
            break
        total += len(chunk)
        if total > per_file_limit:
            raise ValueError(f"{_safe_name(getattr(uf, 'filename', None))} exceeds max_bytes_per_file={per_file_limit} (got >{per_file_limit} bytes)")
        chunks.append(chunk)
    return b"".join(chunks)


def _collect_uploads(form) -> list:
    """
    Collect UploadFile objects from multipart form under:
      - files (preferred; repeated)
      - files[] (browser-friendly)
      - file (legacy single)
    """
    items: list = []

    # Starlette FormData supports getlist
    for key in ("files", "files[]", "file"):
        try:
            values = form.getlist(key)
        except Exception:
            v = form.get(key)
            values = [v] if v is not None else []

        for v in values:
            # UploadFile is a Starlette type; duck-type it safely
            if hasattr(v, "filename") and hasattr(v, "read"):
                items.append(v)

    return items


@router.post(
    "/inhale",
    summary="INHALE memory krystals (JSON) → merge into global sigil state",
    response_model=InhaleResponse,
)
async def inhale(
    request: Request,
    include_state: bool = Query(
        True,
        description="If true, include the merged global state in the response (deterministic ordering).",
    ),
    include_urls: bool = Query(
        True,
        description="If true, include the SigilExplorer-compatible URL export list in the response.",
    ),
    max_files: int = Query(
        64,
        ge=1,
        le=512,
        description="Safety cap on number of files per request.",
    ),
    max_bytes_per_file: int = Query(
        10_000_000,
        ge=1_000,
        le=100_000_000,
        description="Safety cap per file (bytes). Rejects any file larger than this.",
    ),
    max_total_bytes: int = Query(
        50_000_000,
        ge=10_000,
        le=500_000_000,
        description="Safety cap on total bytes across all uploaded files.",
    ),
) -> InhaleResponse:
    """
    Breath label:
      - INHALE = upload JSON krystals (multipart)
      - Merges into canonical registry
      - Ordering + conflict resolution uses Kai tuple only: (pulse, beat, stepIndex)
      - No Chronos fields are emitted or consulted
    """

    # Parse multipart manually to avoid FastAPI list coercion edge-cases (422 drift).
    try:
        form = await request.form()
    except Exception as e:
        return _err(
            400,
            f"Invalid multipart form: {type(e).__name__}: {e}",
        )

    uploads = _collect_uploads(form)
    if not uploads:
        return _err(
            400,
            "No files received. Send multipart fields 'files' (preferred, repeatable) or legacy 'file'.",
        )

    if len(uploads) > max_files:
        return _err(
            413,
            f"Too many files: received={len(uploads)} exceeds max_files={max_files}.",
            files_received=len(uploads),
        )

    warnings: list[str] = []
    total_bytes = 0
    file_blobs: list[tuple[str, bytes]] = []

    for uf in uploads:
        name = _safe_name(getattr(uf, "filename", None))

        try:
            ct = (getattr(uf, "content_type", "") or "").strip().lower()
            if ct and (ct not in _ALLOWED_JSON_CT) and (not ct.endswith("+json")):
                warnings.append(f"{name}: unexpected content-type '{ct}' (still attempting JSON parse).")

            try:
                blob = await _read_limited_bytes(uf, per_file_limit=max_bytes_per_file)
            except ValueError as ve:
                return _err(413, str(ve), files_received=len(uploads))

            total_bytes += len(blob)
            if total_bytes > max_total_bytes:
                return _err(
                    413,
                    f"Total upload too large: total_bytes={total_bytes} exceeds max_total_bytes={max_total_bytes}.",
                    files_received=len(uploads),
                )

            file_blobs.append((name, blob))
        finally:
            try:
                await uf.close()
            except Exception:
                pass

    store = get_store()

    try:
        report = store.inhale_files(file_blobs)
    except Exception as e:
        return _err(
            500,
            f"INHALE failed: {type(e).__name__}: {e}",
            files_received=len(file_blobs),
        )

    if warnings:
        report.errors.extend(warnings)

    # Avoid duplicate work: if we compute state, we already have urls in state.urls.
    state: SigilState | None = None
    urls: list[str] | None = None

    if include_state:
        state = store.get_state()
        if include_urls:
            urls = list(state.urls)
    elif include_urls:
        urls = store.exhale_urls()

    return InhaleResponse(
        status="ok",
        files_received=len(file_blobs),
        crystals_total=report.crystals_total,
        crystals_imported=report.crystals_imported,
        crystals_failed=report.crystals_failed,
        registry_urls=report.registry_urls,
        latest_pulse=report.latest_pulse,
        urls=urls,
        state=state,
        errors=report.errors,
    )


@router.get(
    "/state",
    summary="Current merged global sigil state (Kai-ordered, no Chronos)",
    response_model=SigilState,
)
def state() -> SigilState:
    return get_store().get_state()


@router.get(
    "/exhale",
    summary="EXHALE the merged state (urls list for SigilExplorer, or full state)",
    response_model=ExhaleResponse,
)
def exhale(
    mode: Literal["urls", "state"] = Query(
        "urls",
        description="urls = SigilExplorer import format (JSON list of canonical URLs); state = full merged state object",
    ),
) -> ExhaleResponse:
    store = get_store()
    if mode == "urls":
        return ExhaleResponse(status="ok", mode="urls", urls=store.exhale_urls(), state=None)
    return ExhaleResponse(status="ok", mode="state", urls=None, state=store.get_state())
