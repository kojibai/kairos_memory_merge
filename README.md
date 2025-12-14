# GlyphStream™ Sync Core
**Kairos Sigil Merge API (LAH-MAH-TOR) — seal-based convergence for a zero-DB global registry**

Author: **BJ Klock** — *Kai Rex Klok (K℞K)*  
Live: **https://align.kaiklok.com**

GlyphStream™ is the sync primitive that makes “global state with no database” real:

- **Clients** build a lineage graph locally from share URLs (witness chains + Kai payload).
- **This API** provides **optional convergence** across devices via:
  - a deterministic **state seal** (like an ETag for truth),
  - a paged **URL registry** (the shared “known set”),
  - and a batched **inhale** endpoint for uploading new krystals.

No feeds table. No thread table. No graph table.  
Just **URLs + seals + deterministic merge.**

---

## What this repo is

A production FastAPI service that:
1. **Inhales** krystal batches (`POST /sigils/inhale`)
2. Extracts / dedupes / merges URLs + Kai payload
3. Maintains a **registry state** (URLs + latest Kai moments)
4. Exposes:
   - `GET /sigils/seal` → current state seal
   - `GET /sigils/urls` → paged URL list + state seal

This is the backend counterpart to the client-side GlyphStream™ explorer.

---

## Repo layout (as shipped)

```

app/
main.py                 # FastAPI app entrypoint
api/routes.py           # HTTP endpoints (/sigils/*)
core/
merge_engine.py       # deterministic merge + dedupe
state_store.py        # persistence of shared registry state
witness.py            # witness-chain parsing + synthesis support
url_extract.py        # url parsing / normalization
kai_time.py           # Kai-only ordering helpers (KKS-1.0)
jsonio.py             # canonical json IO helpers
models/
payload.py            # payload/krystal models
state.py              # state registry models
tests/
test_merge_engine.py
test_curl.sh
vercel.json
requirements.txt
README.md
LICENSE

````

---

## API

### 1) Get current state seal
**GET** `/sigils/seal`

Returns a deterministic fingerprint of server state:
```json
{ "seal": "2f0ff4ef2d08249cece9ee58cdc4050b" }
````

### 2) List known URLs (paged)

**GET** `/sigils/urls?offset=0&limit=200`

```json
{
  "status": "ok",
  "state_seal": "2f0ff4ef2d08249cece9ee58cdc4050b",
  "total": 1,
  "offset": 0,
  "limit": 200,
  "urls": [
    "https://align.kaiklok.com/s/<hash>?p=..."
  ]
}
```

### 3) Inhale krystals (batched upload)

**POST** `/sigils/inhale`

* `multipart/form-data`
* `file=@batch.json;type=application/json`
* batch file is a JSON array of krystal records

Example krystal record:

```json
{
  "url": "https://align.kaiklok.com/s/<hash>?p=...",
  "pulse": 9615429,
  "beat": 26,
  "stepIndex": 8,
  "kaiSignature": "…",
  "chakraDay": "Heart"
}
```

The server should ingest idempotently (dedupe by URL) and update state seal only when state changes.

---

## Why “seal → urls” works

GlyphStream™ clients don’t need “real-time DB sync.” They need one question answered:

> “Has the shared registry changed since the last breath?”

So the client does:

1. `GET /sigils/seal`
2. If changed → `GET /sigils/urls` and import what’s new

This keeps the sync surface tiny, observable, cacheable, and debuggable.

---

## Kai-time (KKS-1.0)

This service is Kai-native:

* ordering and “latest” calculations use **pulse → beat → stepIndex**
* no Chronos timestamps are required for truth ordering
* Chronos may exist at the infrastructure layer, but not as a correctness primitive

See:

* `app/core/kai_time.py`

---

## Local development

### 1) Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Run

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3) Smoke test

```bash
bash test_curl.sh
```

Or direct:

```bash
curl -s "http://localhost:8000/sigils/seal" | jq
curl -s "http://localhost:8000/sigils/urls?offset=0&limit=10" | jq
```

---

## Production verification (align.kaiklok.com)

### Inspect URL registry

```bash
curl -s "https://align.kaiklok.com/sigils/urls?offset=0&limit=200" \
  | jq '. | {total, offset, limit, state_seal, sample: (.urls[0:10])}'
```

### Inspect seal

```bash
curl -s "https://align.kaiklok.com/sigils/seal" | jq
```

---

## Client integration (GlyphStream™ Explorer)

The client-side Explorer:

* stores URLs locally (registry)
* reconstructs lineage from witness chains (`add=`) + derived context
* posts new local URLs to this API (`/sigils/inhale`)
* polls each φ-pulse for seal changes (`/sigils/seal`)
* pulls new URLs if the seal changed (`/sigils/urls`)

This API intentionally does not need to know about UI trees or thread rendering.
It only maintains the shared “known set” and a deterministic seal.

---

## Security model

This service is designed to be simple and composable:

* Put it behind auth / WAF / rate limits if you need access control.
* Treat `inhale` as untrusted input: enforce size limits and validate JSON.
* The server should never assume payload fields are “true” beyond parsing/shape.

---

## Contributing

This repo is **source-available** under the GlyphStream™ license.
Pull requests are not accepted unless explicitly requested by the Author.

For commercial licensing, integration rights, or partnerships:
**Contact BJ Klock (Kai Rex Klok).**

---

## Trademarks

* **GlyphStream™**
* **LAH-MAH-TOR**
* **Kai-Klok / KKS**
* **Kai Rex Klok (K℞K)**
* **Φ / PhiNet**

These marks are reserved and are not licensed for use except as explicitly stated.

---

## License

See **LICENSE** — GlyphStream™ Source-Available License (GSAL-1.0).
Publicly readable, verifiable source — **not** an OSI “open source” license.

````

```text
GLYPHSTREAM™ SOURCE-AVAILABLE LICENSE (GSAL-1.0)
Version 1.0 — 2025-12-13

Copyright (c) 2025
BJ Klock — Kai Rex Klok (K℞K)
All rights reserved.

This License is a SOURCE-AVAILABLE license. It allows public access to source
code for verification, auditing, and personal evaluation while preserving the
Author’s exclusive rights for commercial exploitation, redistribution, and
derivative public release.

───────────────────────────────────────────────────────────────────────────────
1. DEFINITIONS
───────────────────────────────────────────────────────────────────────────────

1.1 “Software” means the source code, documentation, schemas, tests, build
    files, and any associated materials in this repository.

1.2 “Author” means BJ Klock, also known as Kai Rex Klok (K℞K), and any entity
    explicitly authorized in writing by the Author.

1.3 “You” means any individual or legal entity exercising permissions granted
    by this License.

1.4 “Non-Commercial Use” means use that is not primarily intended for or
    directed toward commercial advantage, monetary compensation, or revenue
    generation (including indirect revenue such as advertising, paid access,
    paid services, subscriptions, or selling related products).

1.5 “Distribute” means to copy, publish, sublicense, sell, transfer, provide,
    or otherwise make the Software (or substantial portions of it) available to
    any third party, whether publicly or privately, including via hosted
    services, container registries, package registries, app stores, or code
    hosting platforms.

1.6 “Derivative Work” means any modification, adaptation, translation,
    refactor, port, fork, extension, or work based on the Software, including
    any work that incorporates the Software or a substantial portion of it.

1.7 “Provide as a Service” means to host, operate, or expose the Software (or
    a Derivative Work) for third-party use over a network, including APIs,
    SaaS, managed services, consulting deliverables, or “internal tools” made
    available to customers or clients.

1.8 “Trademarks” means the names, marks, and brand identifiers associated with
    the Author and the Software, including but not limited to:
    “GlyphStream™”, “LAH-MAH-TOR”, “Kai-Klok”, “KKS”, “Kai Rex Klok”, “K℞K”, “Φ”.

───────────────────────────────────────────────────────────────────────────────
2. PERMISSIONS (WHAT YOU MAY DO)
───────────────────────────────────────────────────────────────────────────────

Subject to full compliance with Section 3 (Conditions) and Section 4
(Restrictions), the Author grants You a limited, revocable, non-exclusive,
non-transferable license to:

2.1 View, download, and run the Software for personal evaluation,
    experimentation, research, and Non-Commercial Use.

2.2 Modify the Software privately for Your own Non-Commercial Use, provided You
    do not Distribute the Software or any Derivative Work.

2.3 Use the documentation to understand the system and implement interoperable
    clients that do not copy substantial portions of the Software.

───────────────────────────────────────────────────────────────────────────────
3. CONDITIONS (WHAT YOU MUST DO)
───────────────────────────────────────────────────────────────────────────────

3.1 Attribution.
    You must retain all copyright notices, authorship notices, and this License
    text in any copies You make for permitted uses.

3.2 No Removal of Notices.
    You may not remove, obscure, or alter any attribution, trademark notices,
    headers, or provenance statements contained in the Software.

3.3 Naming Integrity.
    If You refer to the Software publicly (e.g., in articles, posts, demos),
    You must credit: “BJ Klock (Kai Rex Klok, K℞K)” as the Author.

───────────────────────────────────────────────────────────────────────────────
4. RESTRICTIONS (WHAT YOU MAY NOT DO)
───────────────────────────────────────────────────────────────────────────────

4.1 No Commercial Use.
    You may not use the Software (or any portion of it) for Commercial Use
    without a separate written commercial license from the Author.

4.2 No Distribution.
    You may not Distribute the Software or any Derivative Work, in whole or in
    part, without explicit written permission from the Author.

4.3 No Derivative Public Release.
    You may not publish, share, open-source, or otherwise release any
    Derivative Work without explicit written permission from the Author.

4.4 No “As-a-Service”.
    You may not Provide as a Service the Software or any Derivative Work,
    whether paid or free, without explicit written permission from the Author.

4.5 No Model Training / Dataset Extraction.
    You may not use the Software, its outputs, or the repository contents as
    training data for machine learning models, embeddings, or dataset creation,
    nor for “AI fine-tuning,” without explicit written permission from the
    Author.

4.6 No Trademark License.
    This License does not grant permission to use the Trademarks. You may not
    use the Trademarks to market, brand, name, or imply endorsement of any
    product, service, fork, or Derivative Work without explicit written
    permission from the Author.

4.7 No Misrepresentation.
    You may not represent the Software or any Derivative Work as Your own
    original work, nor claim authorship of the underlying system, design, or
    architecture embodied here.

───────────────────────────────────────────────────────────────────────────────
5. TERMINATION
───────────────────────────────────────────────────────────────────────────────

5.1 Automatic Termination.
    Any breach of this License immediately terminates all permissions granted
    to You.

5.2 Effect of Termination.
    Upon termination, You must cease all use of the Software and destroy all
    copies in Your possession or control, including private forks and builds,
    except where retention is required by law.

───────────────────────────────────────────────────────────────────────────────
6. DISCLAIMER OF WARRANTY
───────────────────────────────────────────────────────────────────────────────

THE SOFTWARE IS PROVIDED “AS IS” AND “AS AVAILABLE,” WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, OR
TITLE. YOU BEAR ALL RISK OF USE.

───────────────────────────────────────────────────────────────────────────────
7. LIMITATION OF LIABILITY
───────────────────────────────────────────────────────────────────────────────

TO THE MAXIMUM EXTENT PERMITTED BY LAW, IN NO EVENT SHALL THE AUTHOR BE LIABLE
FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR
THE USE OR OTHER DEALINGS IN THE SOFTWARE.

───────────────────────────────────────────────────────────────────────────────
8. COMMERCIAL LICENSING
───────────────────────────────────────────────────────────────────────────────

Commercial use, redistribution rights, derivative public release rights, and
hosted service rights are available ONLY by separate written agreement with the
Author.

───────────────────────────────────────────────────────────────────────────────
9. INTERPRETATION
───────────────────────────────────────────────────────────────────────────────

If any provision of this License is held unenforceable, the remaining
provisions shall remain in effect.

END OF TERMS AND CONDITIONS
