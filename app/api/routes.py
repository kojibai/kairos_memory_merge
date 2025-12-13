# app/api/routes.py
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.core.state_store import get_store
from app.models.state import ExhaleResponse, InhaleResponse, SigilState


router = APIRouter()


@router.post(
    "/inhale",
    summary="INHALE memory krystals (JSON) → merge into global sigil state",
    response_model=InhaleResponse,
)
async def inhale(
    files: list[UploadFile] = File(..., description="One or more JSON files (memory krystals)"),
    include_state: bool = Query(
        True,
        description="If true, include the merged global state in the response (deterministic ordering).",
    ),
    include_urls: bool = Query(
        True,
        description="If true, include the SigilExplorer-compatible URL export list in the response.",
    ),
    max_bytes_per_file: int = Query(
        10_000_000,
        ge=1_000,
        le=100_000_000,
        description="Safety cap per file (bytes). Rejects any file larger than this.",
    ),
) -> InhaleResponse:
    """
    Breath label:
      - INHALE = upload JSON krystals
      - This endpoint merges all krystals into the canonical registry
      - Ordering + conflict resolution uses Kai time (pulse, beat, stepIndex), NEVER Chronos
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files received for inhale.")

    store = get_store()

    file_blobs: list[tuple[str, bytes]] = []
    for f in files:
        name = f.filename or "krystal.json"
        blob = await f.read()

        if len(blob) > max_bytes_per_file:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {name} ({len(blob)} bytes) exceeds max_bytes_per_file={max_bytes_per_file}.",
            )

        file_blobs.append((name, blob))

    report = store.inhale_files(file_blobs)

    state: SigilState | None = store.get_state() if include_state else None
    urls: list[str] | None = store.exhale_urls() if include_urls else None

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
    store = get_store()
    return store.get_state()


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
    """
    Breath label:
      - EXHALE = download the merged result
      - mode=urls matches SigilExplorer import/export format: JSON list of URLs
      - mode=state returns the full merged payload registry (deterministic ordering)
    """
    store = get_store()

    if mode == "urls":
        return ExhaleResponse(
            status="ok",
            mode="urls",
            urls=store.exhale_urls(),
            state=None,
        )

    return ExhaleResponse(
        status="ok",
        mode="state",
        urls=None,
        state=store.get_state(),
    )
