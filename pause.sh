#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# pause.sh — Snapshot the droplet, unassign the reserved IP, delete the droplet.
#             Saves snapshot ID and reserved IP to .pause-state for resume.sh.
#
# This stops billing for the droplet (~$12/mo) while preserving its state.
# Reserved IPs are free when unassigned, snapshots cost $0.06/GB/mo.
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_FILE="$SCRIPT_DIR/.pause-state"

if [[ -f "$STATE_FILE" ]]; then
  echo "Error: .pause-state already exists — environment is already paused."
  echo "Run ./resume.sh first, or delete .pause-state if stale."
  exit 1
fi

# Load .env
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "Error: .env file not found." >&2
  exit 1
fi
set -a; source "$SCRIPT_DIR/.env"; set +a

DO_TOKEN="${DO_API_TOKEN:?Set DO_API_TOKEN in .env}"
RESERVED_IP="${DROPLET_IP:?Set DROPLET_IP in .env}"
API="https://api.digitalocean.com/v2"
AUTH="Authorization: Bearer $DO_TOKEN"

# ---------------------------------------------------------------------------
# 1. Find the droplet ID from the reserved IP assignment
# ---------------------------------------------------------------------------
echo "Looking up droplet assigned to $RESERVED_IP..."
DROPLET_ID=$(curl -s -H "$AUTH" "$API/reserved_ips/$RESERVED_IP" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
d = data.get('reserved_ip', {}).get('droplet')
print(d['id'] if d else '')
")

if [[ -z "$DROPLET_ID" ]]; then
  echo "Error: No droplet is assigned to reserved IP $RESERVED_IP"
  exit 1
fi
echo "  Droplet ID: $DROPLET_ID"

# ---------------------------------------------------------------------------
# 2. Power off the droplet (required for consistent snapshots)
# ---------------------------------------------------------------------------
echo "Powering off droplet..."
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  "$API/droplets/$DROPLET_ID/actions" \
  -d '{"type":"power_off"}' > /dev/null

# Wait for power off
for i in $(seq 1 30); do
  STATUS=$(curl -s -H "$AUTH" "$API/droplets/$DROPLET_ID" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['droplet']['status'])")
  if [[ "$STATUS" == "off" ]]; then
    echo "  Droplet is off."
    break
  fi
  sleep 2
done

if [[ "$STATUS" != "off" ]]; then
  echo "Error: Droplet did not power off in time."
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. Create a snapshot
# ---------------------------------------------------------------------------
SNAP_NAME="ibkr-relay-pause-$(date +%Y%m%d-%H%M%S)"
echo "Creating snapshot: $SNAP_NAME..."
ACTION_ID=$(curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  "$API/droplets/$DROPLET_ID/actions" \
  -d "{\"type\":\"snapshot\",\"name\":\"$SNAP_NAME\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['action']['id'])")

echo "  Waiting for snapshot (this may take a few minutes)..."
for i in $(seq 1 120); do
  SNAP_STATUS=$(curl -s -H "$AUTH" "$API/actions/$ACTION_ID" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['action']['status'])")
  if [[ "$SNAP_STATUS" == "completed" ]]; then
    break
  fi
  sleep 5
done

if [[ "$SNAP_STATUS" != "completed" ]]; then
  echo "Error: Snapshot did not complete in time."
  exit 1
fi

# Get snapshot ID
SNAPSHOT_ID=$(curl -s -H "$AUTH" "$API/droplets/$DROPLET_ID/snapshots" \
  | python3 -c "
import json, sys
snaps = json.load(sys.stdin)['snapshots']
match = [s for s in snaps if s['name'] == '$SNAP_NAME']
print(match[0]['id'] if match else '')
")

if [[ -z "$SNAPSHOT_ID" ]]; then
  echo "Error: Could not find snapshot ID."
  exit 1
fi
echo "  Snapshot ID: $SNAPSHOT_ID"

# ---------------------------------------------------------------------------
# 4. Unassign the reserved IP
# ---------------------------------------------------------------------------
echo "Unassigning reserved IP..."
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  "$API/reserved_ips/$RESERVED_IP/actions" \
  -d '{"type":"unassign"}' > /dev/null
sleep 3

# ---------------------------------------------------------------------------
# 5. Delete the droplet
# ---------------------------------------------------------------------------
echo "Deleting droplet $DROPLET_ID..."
curl -s -X DELETE -H "$AUTH" "$API/droplets/$DROPLET_ID" > /dev/null

# ---------------------------------------------------------------------------
# 6. Save state for resume.sh
# ---------------------------------------------------------------------------
cat > "$STATE_FILE" <<EOF
SNAPSHOT_ID=$SNAPSHOT_ID
SNAPSHOT_NAME=$SNAP_NAME
RESERVED_IP=$RESERVED_IP
DROPLET_REGION=$(curl -s -H "$AUTH" "$API/reserved_ips/$RESERVED_IP" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['reserved_ip']['region']['slug'])")
PAUSED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo ""
echo "============================================"
echo "  Paused successfully!"
echo "============================================"
echo ""
echo "  Snapshot: $SNAP_NAME ($SNAPSHOT_ID)"
echo "  Reserved IP: $RESERVED_IP (kept, unassigned)"
echo "  State saved to: .pause-state"
echo ""
echo "  Droplet billing has stopped."
echo "  Snapshot cost: ~\$0.06/GB/month"
echo "  Reserved IP: free while unassigned"
echo ""
echo "  To resume: ./resume.sh"
echo "============================================"
