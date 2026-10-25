#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 VPS (Vultr). Run as root from the repo checkout at /opt/streetwise.
set -euo pipefail
cd /opt/streetwise
apt-get update && apt-get install -y python3-venv python3-pip nodejs npm caddy
id streetwise >/dev/null 2>&1 || useradd --system --home /opt/streetwise streetwise
python3 -m venv .venv && .venv/bin/pip install -r services/requirements.txt
python3 -m venv .venv-agents && .venv-agents/bin/pip install -r services/agents/requirements.txt
(cd streetwise-web && npm ci && npm run build)
./scripts/fetch_tiles.sh && (cd streetwise-web && npm run build)      # basemap into dist
[ -f .env ] || { cp .env.example .env; echo "Fill in /opt/streetwise/.env (PUBLIC_URL, ADMIN_TOKEN, BRIDGE_SECRET...) and re-run."; exit 1; }
chown -R streetwise:streetwise /opt/streetwise
cp deploy/streetwise-gateway.service deploy/streetwise-agents.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now streetwise-gateway
grep -q '^AGENT_RUNTIME=uagents' .env && systemctl enable --now streetwise-agents || true
cp deploy/Caddyfile /etc/caddy/Caddyfile && systemctl reload caddy
echo "Done. Check: curl -s https://<your-domain>/api/health"
