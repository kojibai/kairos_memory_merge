#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000/sigils}"
KRYSTAL="${KRYSTAL:-./memory_krystal_test.json}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1" >&2; exit 1; }; }
need curl
need jq

echo "BASE=$BASE"
echo "KRYSTAL=$KRYSTAL"
echo

# 1) Inhale (single file) + include_state + include_urls
echo "== 1) inhale single file (state+urls) =="
curl -s -X POST "$BASE/inhale?include_state=true&include_urls=true" \
  -H "accept: application/json" \
  -F "files=@${KRYSTAL};type=application/json" \
| jq '{status, files_received, crystals_total, crystals_imported, crystals_failed, registry_urls, latest: .state.latest, errors}'
echo

# 2) Bad JSON file alongside good file (should report error, keep state stable)
echo "== 2) inhale with one bad file (error surfaced, state remains coherent) =="
BAD="/tmp/bad_krystal.json"
printf '{not json' > "$BAD"
curl -s -X POST "$BASE/inhale?include_state=true&include_urls=true" \
  -H "accept: application/json" \
  -F "files=@${KRYSTAL};type=application/json" \
  -F "files=@${BAD};type=application/json" \
| jq '{status, files_received, crystals_total, crystals_imported, crystals_failed, registry_urls, latest: .state.latest, errors}'
echo

# 3) Invariant: latest.pulse == max(registry[].pulse)
echo "== 3) invariant: latest pulse equals max pulse in registry =="
curl -s -X POST "$BASE/inhale?include_state=true&include_urls=false" \
  -H "accept: application/json" \
  -F "files=@${KRYSTAL};type=application/json" \
| jq '
  if (.status != "ok") then .
  else
    .state as $s
    | ($s.registry | map(.pulse // 0) | max) as $max
    | {
        latest: $s.latest,
        registryCount: ($s.registry | length),
        maxPulse: $max,
        latestMatchesMax: (($s.latest.pulse // 0) == ($max // 0))
      }
  end'
echo

# 4) Invariant: registry sorted DESC by (pulse, beat, stepIndex)
echo "== 4) invariant: registry sorted DESC by (pulse, beat, stepIndex) =="
curl -s -X POST "$BASE/inhale?include_state=true&include_urls=false" \
  -H "accept: application/json" \
  -F "files=@${KRYSTAL};type=application/json" \
| jq '
  def k(e): [ (e.pulse//0), (e.beat//0), (e.stepIndex//0) ];
  .state.registry as $r
  | ( [range(0; ($r|length)-1) | (k($r[.]) >= k($r[.+1]))] | all )'
echo

# 5) Invariant: top N rows echo payload pulse/beat/stepIndex exactly
echo "== 5) invariant: registry row fields match payload fields (first 50) =="
curl -s -X POST "$BASE/inhale?include_state=true&include_urls=false" \
  -H "accept: application/json" \
  -F "files=@${KRYSTAL};type=application/json" \
| jq '
  if (.status != "ok") then .
  else
    .state.registry[:50]
    | map({
        okPulse: ((.pulse//0) == (.payload.pulse//0)),
        okBeat: ((.beat//0) == (.payload.beat//0)),
        okStep: ((.stepIndex//0) == (.payload.stepIndex//0))
      })
    | { allOk: (all(.[]; .okPulse and .okBeat and .okStep)) }
  end'
echo

# 6) Cache: /seal supports ETag + 304
echo "== 6) cache: /seal ETag + 304 =="
SEAL="$(curl -s "$BASE/seal" | jq -r '.seal')"
ETAG="\"$SEAL\""
echo "seal=$SEAL"
curl -i -s "$BASE/seal" | head -n 20
echo
curl -i -s "$BASE/seal" -H "If-None-Match: $ETAG" | head -n 20
echo

# 7) Cache: /state supports same ETag + 304 (uses seal)
echo "== 7) cache: /state ETag + 304 =="
curl -i -s "$BASE/state" | head -n 20
echo
curl -i -s "$BASE/state" -H "If-None-Match: $ETAG" | head -n 20
echo

echo "✅ curl test suite complete."
