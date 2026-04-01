#!/usr/bin/env bash
set -euo pipefail

# Sync .env to the droplet and restart affected containers.
#
# Usage:
#   ./sync-env.sh              # push .env + restart all services
#   ./sync-env.sh gateway      # push .env + restart only ib-gateway (credentials)
#   ./sync-env.sh poller       # push .env + restart only poller
#   ./sync-env.sh gateway poller  # restart specific services

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/.env"

SSH_KEY="${SSH_KEY:-$HOME/.ssh/ibkr-relay}"
DROPLET_IP="${DROPLET_IP:?Set DROPLET_IP in .env or environment}"
REMOTE_DIR="/opt/ibkr-relay"

echo "Pushing .env to droplet..."
scp -i "$SSH_KEY" "$SCRIPT_DIR/.env" "root@${DROPLET_IP}:${REMOTE_DIR}/.env"

if [[ $# -eq 0 ]]; then
  # No args: restart all services
  echo "Restarting all services..."
  ssh -i "$SSH_KEY" "root@${DROPLET_IP}" \
    "cd ${REMOTE_DIR} && docker compose up -d --force-recreate"
else
  # Map friendly names to docker-compose service names
  declare -A SERVICE_MAP=(
    [gateway]=ib-gateway
    [ib-gateway]=ib-gateway
    [novnc]=novnc
    [vnc]=novnc
    [caddy]=caddy
    [relay]=webhook-relay
    [webhook-relay]=webhook-relay
    [poller]=poller
  )

  SERVICES=()
  for arg in "$@"; do
    svc="${SERVICE_MAP[$arg]:-}"
    if [[ -z "$svc" ]]; then
      echo "Unknown service: $arg"
      echo "Valid names: gateway, novnc, caddy, relay, poller"
      exit 1
    fi
    SERVICES+=("$svc")
  done

  echo "Restarting: ${SERVICES[*]}..."
  ssh -i "$SSH_KEY" "root@${DROPLET_IP}" \
    "cd ${REMOTE_DIR} && docker compose up -d --force-recreate ${SERVICES[*]}"
fi

echo "Done."
