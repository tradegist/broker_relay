#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# poll-now.sh — Trigger an immediate Flex poll on the droplet
# Usage: ./poll-now.sh      (poller 1)
#        ./poll-now.sh 2    (poller 2)
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi
source "$SCRIPT_DIR/poller2-profile.sh"

POLLER_NUM="${1:-}"

if [[ "$POLLER_NUM" == "2" ]]; then
  if ! _validate_poller_env "_2"; then
    echo "Error: Poller 2 is not configured. Set IBKR_FLEX_TOKEN_2, IBKR_FLEX_QUERY_ID_2, TARGET_WEBHOOK_URL_2, and WEBHOOK_SECRET_2 in .env" >&2
    exit 1
  fi
  ENDPOINT="/ibkr/run-poll-2"
  LABEL="poller-2"
else
  if ! _validate_poller_env ""; then
    echo "Error: Poller is not configured. Set IBKR_FLEX_TOKEN, IBKR_FLEX_QUERY_ID, TARGET_WEBHOOK_URL, and WEBHOOK_SECRET in .env" >&2
    exit 1
  fi
  ENDPOINT="/ibkr/run-poll"
  LABEL="poller"
fi

TRADE_DOMAIN="${TRADE_DOMAIN:?Set TRADE_DOMAIN in .env}"
API_TOKEN="${API_TOKEN:?Set API_TOKEN in .env}"

echo "Triggering immediate poll ($LABEL)..."
curl -s -X POST "https://${TRADE_DOMAIN}${ENDPOINT}" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  | python3 -m json.tool
