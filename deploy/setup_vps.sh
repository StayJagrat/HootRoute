#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 VPS (Vultr). Run as root from the repo checkout at /opt/hootroute.
set -euo pipefail
cd /opt/hootroute
apt-get update && apt-get install -y python3-venv python3-pip nodejs npm caddy
id hootroute >/dev/null 2>&1 || useradd --system --home /opt/hootroute hootroute
python3 -m venv .venv && .venv/bin/pip install -r services/requirements.txt
python3 -m venv .venv-agents && .venv-agents/bin/pip install -r services/agents/requirements.txt
(cd web && npm ci && npm run build)
./scripts/fetch_tiles.sh && (cd web && npm run build)      # basemap into dist
[ -f .env ] || { cp .env.example .env; echo "Fill in /opt/hootroute/.env (PUBLIC_URL, ADMIN_TOKEN, BRIDGE_SECRET...) and re-run."; exit 1; }
chown -R hootroute:hootroute /opt/hootroute
cp deploy/hootroute-gateway.service deploy/hootroute-agents.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now hootroute-gateway
grep -q '^AGENT_RUNTIME=uagents' .env && systemctl enable --now hootroute-agents || true
cp deploy/Caddyfile /etc/caddy/Caddyfile && systemctl reload caddy
echo "Done. Check: curl -s https://<your-domain>/api/health"
