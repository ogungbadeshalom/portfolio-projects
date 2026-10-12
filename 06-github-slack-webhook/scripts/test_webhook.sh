#!/usr/bin/env bash
# Send a signed GitHub webhook to a local /webhook/github endpoint (default :5000).
# Usage: ./scripts/test_webhook.sh [event_type] [host:port]
set -euo pipefail

EVENT="${1:-push}"
BASE="${2:-http://localhost:5000}"
SECRET="${GITHUB_WEBHOOK_SECRET:-dev-secret}"
FIXTURE="tests/fixtures/github_payloads/${EVENT}.json"

if [[ ! -f "$FIXTURE" ]]; then
  echo "No fixture for event type '$EVENT' (expected $FIXTURE)" >&2
  exit 1
fi

PAYLOAD=$(cat "$FIXTURE")
TEMP=$(mktemp)
printf '%s' "$PAYLOAD" > "$TEMP"

SIG=$(python -c 'import hmac,hashlib,sys;print("sha256="+hmac.new(sys.argv[1].encode(),open(sys.argv[2],"rb").read(),hashlib.sha256).hexdigest())' "$SECRET" "$TEMP")

echo "Sending '$EVENT' webhook to $BASE/webhook/github"
curl -sS -X POST "${BASE}/webhook/github" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ${EVENT}" \
  -H "X-GitHub-Delivery: $(uuidgen 2>/dev/null || echo "00000000-0000-4000-8000-000000000000")" \
  -H "X-Hub-Signature-256: ${SIG}" \
  --data-binary "@${TEMP}"

rm -f "$TEMP"
echo