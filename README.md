# IBKR Webhook Relay

One-script deployment of a headless **Interactive Brokers Gateway** with two services: a **remote client** connected to the IB API (for future order placement), and a **Flex poller** that monitors trade confirmations and fires signed webhooks. Runs on a DigitalOcean droplet with browser-based 2FA via noVNC.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  DigitalOcean Droplet (s-1vcpu-2gb, $12/mo)             │
│                                                         │
│  ┌─────────────────┐   Docker    ┌────────────────────┐ │
│  │  ib-gateway      │  Network   │  remote-client     │ │
│  │  gnzsnz/ib-gw    │◄──────────►│  Python 3.11       │ │
│  │  API: 4003/4004  │            │  ib_async (future  │ │
│  │  VNC: 5900       │            │  order placement)  │ │
│  └────────┬─────────┘            └────────────────────┘ │
│           │                                             │
│  ┌────────▼─────────┐            ┌────────────────────┐ │
│  │  novnc            │            │  poller            │ │
│  │  Browser VNC      │            │  Flex Web Service  │ │
│  │  Port: 6080       │            │  → Webhook POST    │ │
│  └──────────────────┘            │  SQLite dedup      │ │
│                                  └────────────────────┘ │
│                                                         │
│  Firewall: SSH + noVNC from deployer IP only            │
│  IBKR API ports are internal-only (not exposed)         │
└─────────────────────────────────────────────────────────┘
```

Four containers in a single Docker network:

- **`ib-gateway`** — [`ghcr.io/gnzsnz/ib-gateway:stable`](https://github.com/gnzsnz/ib-gateway-docker). IBC automates login. VNC on port 5900 (raw), API on 4003 (live) / 4004 (paper).
- **`novnc`** — [`theasp/novnc`](https://hub.docker.com/r/theasp/novnc). Browser-based VNC proxy on port 6080 for completing 2FA.
- **`remote-client`** — Python image connected to IB Gateway via `ib_async`. Currently maintains a live connection; future: exposes an HTTP endpoint for placing orders.
- **`poller`** — Python image that polls the IBKR Flex Web Service every 10 minutes for trade confirmations and POSTs new fills to a webhook. Uses SQLite for deduplication. **Does not hold an IBKR session** — trade normally via web/mobile.

## Quick Start (Local Deploy)

### Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) installed
- A [DigitalOcean API token](https://cloud.digitalocean.com/account/api/tokens)
- An IBKR account (paper or live)

### Steps

```bash
# 1. Clone and configure
git clone https://github.com/OWNER/ibkr_relay.git
cd ibkr_relay
cp .env.example .env
# Edit .env with your values

# 2. Deploy
./deploy.sh

# 3. Complete 2FA
# Open the VNC URL printed by deploy.sh in your browser
# Log in and approve the 2FA prompt

# 4. Tear down when done
./destroy.sh
```

## GitHub Actions (Fork & Deploy)

For automated deployment without local Terraform:

1. Fork this repo
2. Create a [DO Spaces](https://cloud.digitalocean.com/spaces) bucket for Terraform state
3. Add these **GitHub Secrets**:

| Secret                  | Description                                   |
| ----------------------- | --------------------------------------------- |
| `DO_API_TOKEN`          | DigitalOcean API token                        |
| `TWS_USERID`            | IBKR username                                 |
| `TWS_PASSWORD`          | IBKR password                                 |
| `VNC_SERVER_PASSWORD`   | Password for browser VNC access               |
| `IBKR_FLEX_TOKEN`       | Flex Web Service token                        |
| `IBKR_FLEX_QUERY_ID`    | Trade Confirmation query ID                   |
| `TARGET_WEBHOOK_URL`    | Webhook destination (leave empty for dry-run) |
| `WEBHOOK_SECRET`        | HMAC-SHA256 signing key                       |
| `TRADING_MODE`          | `paper` or `live`                             |
| `POLL_INTERVAL_SECONDS` | Poll frequency (default: 600)                 |
| `TIME_ZONE`             | e.g. `America/New_York`                       |
| `SPACES_ACCESS_KEY`     | DO Spaces access key (for TF state)           |
| `SPACES_SECRET_KEY`     | DO Spaces secret key (for TF state)           |

4. Go to **Actions** → **Deploy IBKR Relay** → **Run workflow** → select `deploy`

## Configuration

All configuration is via environment variables in `.env`:

| Variable                | Required | Default            | Description                                 |
| ----------------------- | -------- | ------------------ | ------------------------------------------- |
| `DO_API_TOKEN`          | Yes      | —                  | DigitalOcean API token                      |
| `TWS_USERID`            | Yes      | —                  | IBKR account username                       |
| `TWS_PASSWORD`          | Yes      | —                  | IBKR account password                       |
| `TRADING_MODE`          | No       | `paper`            | `paper` or `live`                           |
| `VNC_SERVER_PASSWORD`   | Yes      | —                  | Password for noVNC browser access           |
| `IBKR_FLEX_TOKEN`       | Yes      | —                  | Flex Web Service token (from Client Portal) |
| `IBKR_FLEX_QUERY_ID`    | Yes      | —                  | Trade Confirmation Flex Query ID            |
| `TARGET_WEBHOOK_URL`    | No       | —                  | Webhook endpoint (empty = log-only dry-run) |
| `WEBHOOK_SECRET`        | Yes      | —                  | HMAC-SHA256 key for signing payloads        |
| `POLL_INTERVAL_SECONDS` | No       | `600`              | Flex poll interval (seconds)                |
| `TIME_ZONE`             | No       | `America/New_York` | Timezone (tz database format)               |

## Webhook Payload

When an order fills, the relay POSTs a JSON payload:

```json
{
  "event": "fill",
  "symbol": "AAPL",
  "secType": "STK",
  "exchange": "SMART",
  "action": "BOT",
  "quantity": 100.0,
  "price": 178.52,
  "time": "2026-04-01T14:30:00+00:00",
  "orderId": 42,
  "execId": "00018037.6...",
  "account": "DU12345"
}
```

The payload is signed with HMAC-SHA256. Verify using the `X-Signature-256` header:

```python
import hashlib, hmac

expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
assert header_value == f"sha256={expected}"
```

If `TARGET_WEBHOOK_URL` is empty, the relay logs the payload to stdout (dry-run mode) instead of sending it.

## Project Structure

```
├── deploy.sh              # Local deployment script
├── destroy.sh             # Teardown script
├── poll-now.sh            # Trigger an immediate Flex poll
├── .env.example           # Configuration template
├── .github/workflows/
│   └── deploy.yml         # GitHub Actions workflow
├── terraform/
│   ├── main.tf            # Droplet, firewall, SSH key, provisioners
│   ├── variables.tf       # Terraform variables
│   ├── outputs.tf         # Droplet IP, VNC URL, SSH key
│   ├── cloud-init.sh      # Docker install + repo clone (no secrets)
│   └── env.tftpl          # .env template for file provisioner
├── docker-compose.yml     # Container orchestration
├── remote-client/
│   ├── Dockerfile          # Python 3.11-slim image
│   ├── requirements.txt    # ib_async
│   └── client.py           # IB Gateway client (future: order placement)
└── poller/
    ├── Dockerfile          # Python 3.11-slim image
    ├── requirements.txt    # httpx
    └── poller.py           # Flex trade poller + webhook sender
```

## Key Design Decisions

- **No Firestore/GCP dependency** — all config via `.env` file for true portability
- **`ib_async`** (not `ib_insync`) — `ib_insync` is archived; `ib_async` is the maintained fork with the same API
- **IBKR API ports not externally exposed** — the relay connects over the Docker bridge network; no attack surface
- **Secrets via Terraform `file` provisioner** — transferred over SSH, not embedded in cloud-init `user_data` (which is readable from the DO metadata API)
- **SSH keypair auto-generated** — Terraform creates an ED25519 key and uploads it to DO; no user setup needed
- **Exponential backoff reconnection** — handles IBKR's daily gateway reset (~11:45 PM ET)
- **Flex Web Service for fill monitoring** — polls trade confirmations via REST, no session conflict with web/mobile trading
- **SQLite deduplication** — each fill's `transactionID` is stored; only new fills trigger webhooks

## Flex Web Service Setup

Before deploying, create an Activity Flex Query in IBKR Client Portal:

1. Log in to [Client Portal](https://portal.interactivebrokers.com)
2. Go to **Reporting** → **Flex Queries**
3. Under **Activity Flex Query**, click **+** to create a new query
4. Set **Period** to **Last 7 Days** (covers missed fills if the droplet was down)
5. In **Sections**, enable **Trades** and select the execution fields you want
6. Set **Format** to **XML**
7. Save and note the **Query ID** (use as `IBKR_FLEX_QUERY_ID`)
8. Go to **Flex Web Service Configuration** → enable and get the **Current Token** (use as `IBKR_FLEX_TOKEN`)

> **Why Activity instead of Trade Confirmation?** Trade Confirmation queries are locked to "Today" only. Activity queries support a configurable lookback period, so if the droplet is offline for a few days the first poll after restart will catch all missed fills. The SQLite dedup prevents double-sending.

## On-Demand Poll

Trigger an immediate poll without waiting for the next interval:

```bash
./poll-now.sh
```

Or directly on the droplet:

```bash
ssh -i ~/.ssh/ibkr-relay root@<DROPLET_IP> \
  'cd /opt/ibkr-relay && docker compose exec -T poller python poller.py --once'
```

## SSH Access

The SSH key is saved automatically during deployment. To SSH into the droplet:

```bash
ssh -i ~/.ssh/ibkr-relay root@<DROPLET_IP>
```

## Live Logs

To stream poller logs in real-time (useful for checking fill deliveries):

```bash
ssh -i ~/.ssh/ibkr-relay root@<DROPLET_IP> 'cd /opt/ibkr-relay && docker compose logs -f poller'
```

To stream remote client logs:

```bash
ssh -i ~/.ssh/ibkr-relay root@<DROPLET_IP> 'cd /opt/ibkr-relay && docker compose logs -f webhook-relay'
```

## Security

- Firewall restricts SSH (22) and noVNC (6080) to the deployer's IP only
- IBKR API ports are Docker-internal — never exposed to the internet
- Webhook payloads are HMAC-SHA256 signed
- No credentials stored in the repository
- VNC requires a password

## Current Status

- [x] Terraform infrastructure (droplet, firewall, SSH key)
- [x] Docker Compose orchestration (4 containers)
- [x] Remote client connected to IB Gateway
- [x] Flex poller with SQLite dedup + webhook delivery
- [x] On-demand poll script (`poll-now.sh`)
- [x] Local deploy/destroy scripts
- [x] GitHub Actions workflow
- [x] Dry-run mode (log payloads when no webhook URL)
- [ ] Remote client HTTP API for order placement
- [ ] Health monitoring / alerting
- [ ] Webhook endpoint (poller runs in dry-run mode until configured)
