#!/usr/bin/env bash
# HootRoute on a fresh Ubuntu 24.04 VPS (Vultr: Cloud Compute, 2 GB RAM or more). Run as root:
#
#   git clone https://github.com/StayJagrat/HootRoute.git /opt/hootroute
#   cp deploy/env.production.example /opt/hootroute/.env   # then fill in the keys (scp your local .env values, never paste them in chat)
#   bash /opt/hootroute/deploy/setup_vps.sh hootroute.example.com     # or: bash deploy/setup_vps.sh auto   (uses <ip>.sslip.io, no domain needed)
#
# Re-running is safe: it updates the code's dependencies, rebuilds the web app and restarts the service.
set -euo pipefail
APP=/opt/hootroute
DOMAIN="${1:-}"
cd "$APP"
[ -n "$DOMAIN" ] || { echo "usage: setup_vps.sh <domain> | auto"; exit 2; }
if [ "$DOMAIN" = "auto" ]; then
  IP=$(curl -fsS https://api.ipify.org); DOMAIN="${IP//./-}.sslip.io"; echo "Using $DOMAIN (sslip.io resolves it to $IP)"
fi

# ---------------------------------------------------------------- packages: Python 3.12, Node 20, Caddy (official repo), firewall
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3-venv python3-pip git curl ufw debian-keyring debian-archive-keyring apt-transport-https gnupg
if ! command -v node >/dev/null || [ "$(node -v | cut -c2- | cut -d. -f1)" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs
fi
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y && apt-get install -y caddy
fi
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

# 2 GB swap on small instances: the engine holds the city graph in memory and the web build needs headroom
if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 3500 ] && ! swapon --show | grep -q swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------------------------------------------------------------- configuration must exist before the web build (Vite bakes VITE_* in)
[ -f .env ] || { cp deploy/env.production.example .env; chmod 600 .env; echo "Created $APP/.env from the template. Fill it in, then re-run."; exit 1; }
chmod 600 .env
set_env() { grep -q "^$1=" .env && sed -i "s#^$1=.*#$1=$2#" .env || echo "$1=$2" >> .env; }
set_env HOOTROUTE_ENV production
set_env PUBLIC_URL "https://$DOMAIN"
set_env CORS_ORIGINS "https://$DOMAIN"
grep -q '^ADMIN_TOKEN=.\{16,\}' .env || set_env ADMIN_TOKEN "$(openssl rand -hex 24)"
grep -q '^BRIDGE_SECRET=.\{16,\}' .env || set_env BRIDGE_SECRET "$(openssl rand -hex 24)"

# ---------------------------------------------------------------- app
id hootroute >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin hootroute
python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r services/requirements.txt
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "services/api")
from hootroute_api.settings import Settings
problems = Settings().problems()
if problems: sys.exit("Refusing to deploy:\n - " + "\n - ".join(problems))
print("production settings OK")
PY
(cd web && npm ci --no-audit --no-fund && npm run build)
mkdir -p data && chown -R hootroute:hootroute "$APP"

cp deploy/hootroute-gateway.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable hootroute-gateway && systemctl restart hootroute-gateway
grep -q '^AGENT_RUNTIME=uagents' .env && { python3 -m venv .venv-agents && .venv-agents/bin/pip install -q -r services/agents/requirements.txt \
  && cp deploy/hootroute-agents.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now hootroute-agents; } || true

sed "s/hootroute.example.com/$DOMAIN/" deploy/Caddyfile > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

# ---------------------------------------------------------------- wait for the engine to load the city, then check from outside
for i in $(seq 1 60); do curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; sleep 2; done
curl -fsS http://127.0.0.1:8000/api/health | python3 -c "import json,sys; d=json.load(sys.stdin); print('gateway:', {k: d.get(k) for k in ('ok','claude','apify','tts','production')})"
echo "Done. Open https://$DOMAIN  (first HTTPS request can take ~20 s while Caddy gets the certificate)"
