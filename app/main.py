# app/main.py
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.routes import router as sigils_router

# ──────────────────────────────────────────────────────────────────────────────
# KAIROS SIGIL MERGE API — “LAH-MAH-TOR · THE PORTAL”
#
# One coherent gate:
#   INHALE  → deterministic merge (Kai-time intrinsic)
#   EXHALE  → SigilExplorer-compatible state + urls
#
# IMPORTANT (in-memory truth):
# - This service’s “global registry” is process-local memory by design.
# - If you run >1 worker/process, you create >1 independent registries.
# - Run a single worker for a single coherent gate.
# ──────────────────────────────────────────────────────────────────────────────

SERVICE_NAME = "LAH-MAH-TOR"
SERVICE_CODENAME = "ATLANTEAN GATE · Φ-SEAL"
VERSION = "3.9.0"

# Breath unit (T = 3 + √5 seconds)
GOLDEN_BREATH_S = 5.2360679775
GOLDEN_BREATH_HZ = 0.1909830056

TAGLINE = "INHALE Memory Krystals → determinate merge → EXHALE koherent sigil state (Kai-ordered)."

PURPOSE = (
    "LAH-MAH-TOR is a Breath-native, Kai-time deterministic merge gate for Memory Krystals.\n\n"
    "It accepts JSON proof-objects whose timeline is intrinsic to the artifact (pulse / beat / stepIndex). "
    "It validates shape and required Kai fields, canonicalizes structure for repeatability, deduplicates "
    "idempotent repeats, and merges all valid entries into a single coherent registry.\n\n"
    "It then EXHALES a materialized truth view that is fully deterministic:\n"
    "• ordering is derived strictly from Kai-time fields\n"
    "• state identity is expressed as a determinate seal\n"
    "• correctness does not depend on server clocks, arrival order, or Chronos timestamps\n\n"
    "Humans see the Portal (HTML). Machines see the Manifest and State (JSON). "
    "One source. Two faces. One koherent breath."
)

KAI_SPEC = {
    "standard": "KKS-1.0",
    "breath_unit": {
        "name": "T",
        "definition": "T = 3 + √5 seconds",
        "approx_seconds": GOLDEN_BREATH_S,
        "approx_hz": GOLDEN_BREATH_HZ,
    },
    "grid": {
        "pulses_per_step": 11,
        "steps_per_beat": 44,
        "beats_per_arc": 6,
        "arcs_per_day": 6,
        "beats_per_day": 36,
    },
    # NOTE: The API itself exposes Kai-ordered views; clients are free to render ascending/descending.
    "ordering_rule": "Primary order derives from Kai fields (pulse → beat → stepIndex). No Chronos fields are required.",
}

ROUTES = [
    {"path": "/", "method": "GET", "purpose": "The Portal (HTML for browsers, JSON for machines)"},
    {"path": "/health", "method": "GET", "purpose": "Liveness check"},
    {"path": "/docs", "method": "GET", "purpose": "Interactive Swagger UI"},
    {"path": "/redoc", "method": "GET", "purpose": "ReDoc documentation"},
    {"path": "/openapi.json", "method": "GET", "purpose": "OpenAPI schema"},
    {"path": "/sigils/*", "method": "ALL", "purpose": "INHALE/EXHALE endpoints (merge + state + urls + seal)"},
]


def _canonical_json(obj: Any) -> str:
    # Canonical JSON: stable key order, stable separators, UTF-8 safe.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _phi_seal(manifest: dict[str, Any]) -> str:
    """
    Determinate seal of the portal manifest.
    Not a security boundary — a coherence marker for identity and repeatability.
    """
    blob = _canonical_json(manifest).encode("utf-8")
    return hashlib.blake2b(blob, digest_size=32).hexdigest()


def build_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "name": SERVICE_NAME,
        "codename": SERVICE_CODENAME,
        "version": VERSION,
        "tagline": TAGLINE,
        "purpose": PURPOSE,
        "kai": KAI_SPEC,
        "routes": ROUTES,
        "docs": {"swagger": "/docs", "redoc": "/redoc", "openapi": "/openapi.json"},
        "contract": {
            "inputs": ["application/json (Memory Krystals)"],
            "outputs": ["SigilExplorer-compatible urls export", "Kai-ordered state snapshot", "determinate seal"],
            "guarantees": [
                "Determinism: merge and ordering derive from Kai fields, not server time",
                "Idempotence: repeated ingestion converges (no duplicate drift)",
                "Coherence: state identity expressed as a determinate seal",
                "Compatibility: urls/state views are designed for SigilExplorer hydration",
            ],
        },
        "axioms": [
            "Truth is a procedure, not a timestamp.",
            "Ordering is intrinsic to the artifact when the artifact carries Kai-time.",
            "Convergence beats authority: repeat inputs must repeat outputs.",
        ],
        "vow": [
            "No silent corruption.",
            "No vague success.",
            "If it cannot be merged coherently, it is rejected explicitly.",
            "If it cannot be proven deterministically, it is not claimed.",
        ],
    }
    manifest["phi_seal"] = _phi_seal(manifest)
    return manifest


PORTAL_MANIFEST = build_manifest()


def portal_html(manifest: dict[str, Any]) -> str:
    # Self-contained portal. No CDN. No external assets. Mobile-perfect.
    seal_full = str(manifest.get("phi_seal", ""))
    seal_short = f"{seal_full[:10]}…{seal_full[-8:]}" if len(seal_full) > 22 else seal_full
    breath = GOLDEN_BREATH_S

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" />
  <meta name="color-scheme" content="dark light" />
  <title>{manifest["name"]} · {manifest["codename"]}</title>
  <style>
    :root {{
      --breath: {breath}s;

      --bg0: #07070b;
      --bg1: #0b0c12;

      --ink: rgba(255,255,255,.92);
      --muted: rgba(255,255,255,.70);
      --dim: rgba(255,255,255,.50);

      --glass: rgba(255,255,255,.06);
      --glass2: rgba(255,255,255,.10);
      --line: rgba(255,255,255,.12);

      --r: 22px;
      --shadow: 0 20px 90px rgba(0,0,0,.58);

      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }}

    /* HARD MOBILE GUARANTEES: no right-edge bleed */
    html, body {{
      width: 100%;
      max-width: 100%;
      overflow-x: hidden;
    }}
    * {{ box-sizing: border-box; min-width: 0; }}

    body {{
      margin: 0;
      font-family: var(--sans);
      color: var(--ink);
      background:
        radial-gradient(1200px 800px at 20% 10%, rgba(140, 255, 228, .16), transparent 55%),
        radial-gradient(1100px 700px at 85% 18%, rgba(170, 132, 255, .18), transparent 58%),
        radial-gradient(900px 650px at 60% 85%, rgba(255, 205, 140, .14), transparent 60%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }}

    .wrap {{
      max-width: 1120px;
      margin: 0 auto;
      padding:
        max(18px, env(safe-area-inset-top))
        clamp(14px, 4vw, 20px)
        max(26px, env(safe-area-inset-bottom));
    }}

    .hero {{
      position: relative;
      border-radius: calc(var(--r) + 10px);
      padding: 28px 26px;
      background: linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.04));
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      overflow: hidden;

      backdrop-filter: blur(18px) saturate(140%);
      -webkit-backdrop-filter: blur(18px) saturate(140%);

      animation: heroBreathe var(--breath) ease-in-out infinite;
    }}

    .hero:before {{
      content: "";
      position: absolute;
      inset: -2px;
      background:
        radial-gradient(900px 420px at 18% 20%, rgba(120, 255, 226, .22), transparent 55%),
        radial-gradient(720px 380px at 80% 22%, rgba(184, 140, 255, .20), transparent 60%),
        radial-gradient(620px 460px at 55% 95%, rgba(255, 215, 140, .16), transparent 62%);
      filter: blur(14px);
      opacity: .78;
      pointer-events: none;
      animation: auroraShift var(--breath) ease-in-out infinite;
    }}

    /* crystalline “grain” overlay */
    .hero:after {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      opacity: .22;
      background:
        linear-gradient(120deg,
          rgba(255,255,255,.06),
          rgba(255,255,255,0) 40%,
          rgba(255,255,255,.05) 70%,
          rgba(255,255,255,0));
      mix-blend-mode: overlay;
      animation: sheen var(--breath) ease-in-out infinite;
    }}

    .hero > * {{ position: relative; z-index: 1; }}

    @keyframes heroBreathe {{
      0%,100% {{ transform: translateZ(0); }}
      50% {{ transform: translateZ(0) scale(1.004); }}
    }}
    @keyframes auroraShift {{
      0%,100% {{ transform: translate3d(0,0,0) scale(1.00); opacity: .76; }}
      50% {{ transform: translate3d(0,-6px,0) scale(1.03); opacity: .92; }}
    }}
    @keyframes sheen {{
      0%,100% {{ transform: translateX(-6%) skewX(-6deg); opacity: .18; }}
      50% {{ transform: translateX(6%) skewX(-6deg); opacity: .34; }}
    }}

    .topline {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: 12px;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      background: rgba(0,0,0,.22);
      border-radius: 999px;
      font-family: var(--mono);
      font-size: 12px;
      color: var(--muted);

      max-width: 100%;
      flex: 1 1 auto;
    }}

    .pulseDot {{
      width: 10px; height: 10px; border-radius: 999px;
      background: rgba(140, 255, 228, .95);
      box-shadow: 0 0 0 3px rgba(140, 255, 228, .18), 0 0 28px rgba(140, 255, 228, .35);
      animation: breathe var(--breath) ease-in-out infinite;
      flex: 0 0 auto;
    }}

    @keyframes breathe {{
      0%,100% {{ transform: scale(1); opacity: .78; }}
      50% {{ transform: scale(1.35); opacity: 1; }}
    }}

    .sealText {{
      color: rgba(255,255,255,.92);
      max-width: min(560px, 72vw);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(26px, 5.2vw, 44px);
      letter-spacing: -0.02em;
      line-height: 1.05;
      background: linear-gradient(90deg, rgba(255,255,255,.96), rgba(140,255,228,.92), rgba(184,140,255,.92));
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }}

    .sub {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.45;
      max-width: 78ch;
    }}

    .grid {{
      display: grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 16px;
      margin-top: 16px;
    }}
    @media (max-width: 920px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}

    .card {{
      border-radius: var(--r);
      border: 1px solid var(--line);
      background: rgba(255,255,255,.05);
      padding: 16px;
      box-shadow: 0 14px 60px rgba(0,0,0,.35);

      backdrop-filter: blur(12px) saturate(140%);
      -webkit-backdrop-filter: blur(12px) saturate(140%);
    }}

    .card h2 {{
      margin: 0 0 10px 0;
      font-size: 13px;
      letter-spacing: .14em;
      text-transform: uppercase;
      color: rgba(255,255,255,.86);
    }}

    .kvs {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      font-family: var(--mono);
      font-size: 12px;
      color: var(--muted);
    }}

    .row {{
      display: flex;
      gap: 10px;
      align-items: baseline;
      justify-content: space-between;
      border: 1px solid rgba(255,255,255,.08);
      background: rgba(0,0,0,.22);
      padding: 10px 12px;
      border-radius: 14px;
      max-width: 100%;
    }}
    .key {{ color: rgba(255,255,255,.78); }}
    .val {{
      color: rgba(255,255,255,.92);
      text-align: right;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}

    a {{
      color: rgba(140, 255, 228, .95);
      text-decoration: none;
    }}
    a:hover {{ text-decoration: underline; }}

    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}

    .btn {{
      appearance: none;
      border: 1px solid rgba(255,255,255,.16);
      background: rgba(0,0,0,.26);
      color: var(--ink);
      border-radius: 14px;
      padding: 10px 12px;
      font-family: var(--mono);
      font-size: 12px;
      cursor: pointer;
      transition: transform .12s ease, background .12s ease, border-color .12s ease;
      touch-action: manipulation;
    }}
    .btn:hover {{
      transform: translateY(-1px);
      background: rgba(255,255,255,.08);
      border-color: rgba(140,255,228,.38);
    }}

    .code {{
      font-family: var(--mono);
      font-size: 12px;
      color: rgba(255,255,255,.88);
      background: rgba(0,0,0,.38);
      border: 1px solid rgba(255,255,255,.12);
      border-radius: 16px;
      padding: 12px;
      overflow-x: auto;
      max-width: 100%;
      line-height: 1.45;
    }}

    .footer {{
      margin-top: 16px;
      color: var(--dim);
      font-family: var(--mono);
      font-size: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      opacity: .92;
    }}

    .status {{
      display: inline-flex;
      gap: 8px;
      align-items: center;
      padding: 8px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,.14);
      background: rgba(0,0,0,.22);
      max-width: 100%;
    }}

    .sDot {{
      width: 8px; height: 8px; border-radius: 999px;
      background: rgba(255, 190, 120, .95);
      box-shadow: 0 0 0 3px rgba(255,190,120,.16);
      animation: breathe var(--breath) ease-in-out infinite;
    }}
    .ok .sDot {{
      background: rgba(140, 255, 228, .95);
      box-shadow: 0 0 0 3px rgba(140,255,228,.16);
    }}

    .axiom {{
      margin-top: 10px;
      font-family: var(--mono);
      font-size: 12px;
      color: rgba(255,255,255,.84);
      opacity: .96;
    }}

    /* MOBILE: eliminate any possibility of right-edge cutoff */
    @media (max-width: 520px) {{
      .hero {{ padding: 18px 14px; border-radius: calc(var(--r) + 6px); }}
      .badge {{ width: 100%; justify-content: flex-start; }}
      .sealText {{ max-width: 70vw; }}
      .row {{ flex-direction: column; align-items: flex-start; }}
      .val {{ text-align: left; }}
      .code {{
        overflow-x: hidden;
        white-space: pre-wrap;
        word-break: break-word;
      }}
    }}

    @media (prefers-reduced-motion: reduce) {{
      .hero, .hero:before, .hero:after, .pulseDot, .sDot {{ animation: none !important; }}
    }}
  </style>
</head>

<body>
  <div class="wrap">
    <div class="hero">
      <div class="topline">
        <div class="badge" title="Breath-synced heartbeat (visual only)">
          <span class="pulseDot"></span>
          <span>Φ-SEAL · <a href="https://github.com/kojibai/klok" target="_blank" rel="noreferrer">{manifest["kai"]["standard"]}</a> · T={GOLDEN_BREATH_S:.10f}s</span>
        </div>

        <div class="badge" title="Determinate portal seal (BLAKE2b-256 over canonical manifest)">
          <span>SEAL</span>
          <span class="sealText" id="sealText" title="{seal_full}">{seal_short}</span>
          <button class="btn" style="padding:8px 10px; border-radius: 999px;" onclick="remember(this, '{seal_full}')">REMEMBER</button>
        </div>
      </div>

      <h1>{manifest["name"]}</h1>

      <div class="sub">
        <div style="font-family: var(--mono); color: rgba(255,255,255,.84); margin-bottom: 8px;">
          {manifest["codename"]} · <a href="https://github.com/kojibai/kairos_memory_stream" target="_blank" rel="noreferrer">v{manifest["version"]}</a>
        </div>

        <div><strong>{manifest["tagline"]}</strong></div>
        <div style="margin-top: 10px;">{manifest["purpose"]}</div>

        <div class="axiom">
          Axiom: ordering is intrinsic when the artifact carries Kai-time. The gate enforces convergence.
        </div>
      </div>

      <div class="grid">
        <div class="card">
          <h2>Entry Points</h2>
          <div class="kvs">
            <div class="row"><div class="key">Swagger</div><div class="val"><a href="/docs">/docs</a></div></div>
            <div class="row"><div class="key">ReDoc</div><div class="val"><a href="/redoc">/redoc</a></div></div>
            <div class="row"><div class="key">OpenAPI</div><div class="val"><a href="/openapi.json">/openapi.json</a></div></div>
            <div class="row"><div class="key">Health</div><div class="val"><a href="/health">/health</a></div></div>
          </div>

          <div class="actions">
            <button class="btn" onclick="remember(this, window.location.origin + '/docs')">REMEMBER /docs</button>
            <button class="btn" onclick="remember(this, window.location.origin + '/openapi.json')">REMEMBER /openapi.json</button>
            <button class="btn" onclick="remember(this, window.location.origin + '/health')">REMEMBER /health</button>
          </div>

          <div style="margin-top: 12px;">
            <div class="code" id="curl">curl -s -X GET "__ORIGIN__/health" | jq
curl -s "__ORIGIN__/openapi.json" | jq '.info'
# INHALE / EXHALE lives under /sigils/* (see /docs for exact contracts)</div>

            <div class="actions">
              <button class="btn" onclick="remember(this, document.getElementById('curl').innerText.replaceAll('__ORIGIN__', window.location.origin))">REMEMBER cURL</button>
            </div>
          </div>
        </div>

        <div class="card">
          <h2>Live Status</h2>
          <div class="kvs">
            <div class="row"><div class="key">Service</div><div class="val">{manifest["name"]}</div></div>
            <div class="row"><div class="key">Version</div><div class="val"><a href="https://github.com/kojibai/kairos_memory_stream" target="_blank" rel="noreferrer">v{manifest["version"]}</a></div></div>
            <div class="row"><div class="key">KAI Standard</div><div class="val"><a href="https://github.com/kojibai/klok" target="_blank" rel="noreferrer">{manifest["kai"]["standard"]}</a></div></div>
          </div>

          <div style="margin-top: 12px;" class="status" id="healthChip" title="Fetched from /health">
            <span class="sDot"></span>
            <span style="font-family: var(--mono); font-size: 12px;">CHECKING /health …</span>
          </div>

          <div style="margin-top: 12px;">
            <h2>Law</h2>
            <div class="code">{manifest["kai"]["ordering_rule"]}</div>
          </div>
        </div>
      </div>

      <div class="footer">
        <div>
          <span style="color: rgba(255,255,255,.90);">{manifest["codename"]}</span>
          <span style="margin: 0 8px; opacity: .6;">·</span>
          <span>Determinate Portal Manifest</span>
        </div>
        <div style="opacity: .92;">
          <span style="margin-right: 8px;">Machine view:</span>
          <a href="/?format=json">/?format=json</a>
        </div>
      </div>
    </div>
  </div>

  <script>
    async function copyText(t) {{
      try {{
        await navigator.clipboard.writeText(String(t));
      }} catch (e) {{
        const el = document.createElement('textarea');
        el.value = String(t);
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
      }}
    }}

    async function remember(btn, t) {{
      const b = btn;
      const prev = (b && b.innerText) ? b.innerText : 'REMEMBER';
      try {{
        await copyText(t);
        if (b) {{
          b.innerText = 'REMEMBERED';
          b.disabled = true;
          setTimeout(() => {{
            b.innerText = prev;
            b.disabled = false;
          }}, 1100);
        }}
      }} catch (e) {{
        if (b) {{
          b.innerText = 'REMEMBERED';
          setTimeout(() => {{
            b.innerText = prev;
          }}, 1100);
        }}
      }}
    }}

    async function pingHealth() {{
      const chip = document.getElementById('healthChip');
      try {{
        const res = await fetch('/health', {{ cache: 'no-store' }});
        const j = await res.json();
        const ok = (j && j.status === 'ok');
        chip.className = 'status ' + (ok ? 'ok' : '');
        chip.innerHTML =
          '<span class="sDot"></span>' +
          '<span style="font-family: var(--mono); font-size: 12px;">/health → ' +
          (ok ? 'OK' : 'NOT OK') + '</span>';
      }} catch (e) {{
        chip.className = 'status';
        chip.innerHTML =
          '<span class="sDot"></span>' +
          '<span style="font-family: var(--mono); font-size: 12px;">/health → ERROR</span>';
      }}
    }}
    pingHealth();
  </script>
</body>
</html>
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title=SERVICE_NAME,
        version=VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        description=(
            "LAH-MAH-TOR — Determinate Breath Gate (KKS-1.0)\n\n"
            "Operational definition\n"
            "LAH-MAH-TOR receives Memory Krystals (JSON proof-objects) that carry intrinsic Kai-time "
            "(pulse / beat / stepIndex). It validates, canonicalizes, deduplicates, and merges them into "
            "a single coherent registry. It then exposes deterministic materialized views (urls/state) "
            "intended for SigilExplorer hydration and replication.\n\n"
            "Contract\n"
            "Input:\n"
            "• Memory Krystals (application/json) containing Kai-time indexing and payload content\n\n"
            "Process:\n"
            "• Validate: required Kai fields + schema coherence\n"
            "• Canonicalize: stable representation for repeatable results\n"
            "• Deduplicate: idempotent repeats converge (no duplicate drift)\n"
            "• Merge: deterministic union under defined conflict rules\n"
            "• Materialize: urls/state snapshots + determinate seal\n\n"
            "Output:\n"
            "• urls export (SigilExplorer-compatible)\n"
            "• state snapshot (Kai-ordered view)\n"
            "• seal (deterministic identity marker)\n\n"
            "Core guarantees\n"
            "• Determinism: repeat inputs produce repeat outputs\n"
            "• Convergence: ingestion is idempotent\n"
            "• Kai-native: correctness does not require Chronos timestamps\n"
            "• Machine-readable: JSON responses with explicit contracts\n\n"
            "Portal homepage\n"
            "• Human (HTML): /\n"
            "• Machine (JSON): /?format=json\n"
        ),
    )

    # CORS: permissive for public clients (Explorer, local dev, cross-device)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Breath-labeled API routes live under /sigils
    app.include_router(sigils_router, prefix="/sigils", tags=["sigils"])

    @app.get("/health", summary="Health check", response_class=JSONResponse, tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/",
        summary="The Portal (HTML for browsers, JSON for machines)",
        response_class=HTMLResponse,
        tags=["system"],
    )
    def root(request: Request, format: str | None = None) -> Any:
        accept = (request.headers.get("accept") or "").lower()
        wants_json = (format or "").lower() == "json" or "application/json" in accept

        if wants_json:
            # Explicitly no-store so clients always read the current manifest
            return JSONResponse(
                {
                    **PORTAL_MANIFEST,
                    "endpoints_hint": "Explore /docs for /sigils INHALE/EXHALE routes.",
                },
                headers={"Cache-Control": "no-store"},
            )

        return HTMLResponse(portal_html(PORTAL_MANIFEST))

    return app


app = create_app()
