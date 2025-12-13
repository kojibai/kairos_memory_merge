# app/api/routes.py
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Query, UploadFile
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


def _safe_name(f: UploadFile | None) -> str:
    name = (getattr(f, "filename", None) or "").strip()
    if not name:
        return "krystal.json"
    return name if len(name) <= 160 else (name[:120] + "…" + name[-30:])


def _err(status_code: int, msg: str, *, extra: dict | None = None) -> JSONResponse:
    payload = InhaleResponse(status="error", errors=[msg]).model_dump(exclude_none=False)
    if extra:
        payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)


async def _read_limited(uf: UploadFile, *, limit: int) -> bytes:
    # read only up to limit+1 to enforce a hard cap
    blob = await uf.read(limit + 1)
    if len(blob) > limit:
        raise ValueError(f"{_safe_name(uf)} exceeds max_bytes_per_file={limit} (got {len(blob)} bytes)")
    return blob


@router.post(
    "/inhale",
    summary="INHALE memory krystals (JSON) → merge into global sigil state",
    response_model=InhaleResponse,
)
async def inhale(
    # Preferred: multi-file uploads
    files: list[UploadFile] | None = File(
        default=None,
        description="One or more JSON files (memory krystals). Field name: 'files'.",
    ),
    # Legacy: single file upload
    file: UploadFile | None = File(
        default=None,
        description="Legacy single-file field name: 'file'.",
    ),
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
        description="Safety cap per file (bytes).",
    ),
    max_total_bytes: int = Query(
        50_000_000,
        ge=10_000,
        le=500_000_000,
        description="Safety cap on total bytes across all uploaded files.",
    ),
) -> InhaleResponse:
    incoming: list[UploadFile] = []
    if files:
        incoming.extend(files)
    if file is not None:
        incoming.append(file)

    if not incoming:
        return _err(
            400,
            "No files received. Send multipart field 'files' (preferred) or legacy 'file'.",
        )

    if len(incoming) > max_files:
        return _err(
            413,
            f"Too many files: received={len(incoming)} exceeds max_files={max_files}.",
        )

    store = get_store()

    total_bytes = 0
    file_blobs: list[tuple[str, bytes]] = []
    warnings: list[str] = []

    for uf in incoming:
        name = _safe_name(uf)
        try:
            ct = (uf.content_type or "").strip().lower()
            if ct and (ct not in _ALLOWED_JSON_CT) and (not ct.endswith("+json")):
                warnings.append(f"{name}: unexpected content-type '{ct}' (still attempting JSON parse).")

            try:
                blob = await _read_limited(uf, limit=max_bytes_per_file)
            except ValueError as ve:
                return _err(413, str(ve), extra={"files_received": len(incoming)})

            total_bytes += len(blob)
            if total_bytes > max_total_bytes:
                return _err(
                    413,
                    f"Total upload too large: total_bytes={total_bytes} exceeds max_total_bytes={max_total_bytes}.",
                    extra={"files_received": len(incoming)},
                )

            file_blobs.append((name, blob))
        finally:
            # prevent fd leaks under heavy multipart loads
            try:
                await uf.close()
            except Exception:
                pass

    # Merge (Kai-only). Bad krystals should not poison the run.
    try:
        report = store.inhale_files(file_blobs)
    except Exception as e:
        return _err(
            500,
            f"INHALE failed: {type(e).__name__}: {e}",
            extra={"files_received": len(file_blobs)},
        )

    if warnings:
        report.errors.extend(warnings)

    state: SigilState | None = None
    urls: list[str] | None = None

    # Avoid duplicate work: if we compute state, we already have urls in state.urls
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
        description="urls = JSON list of canonical URLs; state = full merged state object",
    ),
) -> ExhaleResponse:
    store = get_store()
    if mode == "urls":
        return ExhaleResponse(status="ok", mode="urls", urls=store.exhale_urls(), state=None)
    return ExhaleResponse(status="ok", mode="state", urls=None, state=store.get_state())
