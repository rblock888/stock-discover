#!/usr/bin/env bash
# One-shot VPS deploy for stock-discover — idempotent, safe to re-run.
#
# Run ON the VPS as root:   bash deploy_vps.sh
# Or from your Mac:         ssh root@208.76.222.98 'bash -s' < scripts/deploy_vps.sh
#
# Does, in order:
#   1. SWAP        adds a 2G swapfile if none exists — the box previously froze
#                  hard (SSH banner-exchange timeouts) which is classic OOM
#                  thrashing on a small VPS with no swap
#   2. THROTTLE    caps systemd restart loops (a crash-looping `next start`
#                  restarting instantly forever is the likely original culprit)
#   3. CODE        clones or updates the repo, checks out feat/regime-dashboard
#   4. PYTHON      installs backend deps
#   5. NODE        ensures Node >= 20 (Next.js 16 requires >=20.9 — the same
#                  old-node failure we hit locally)
#   6. BUILD       npm ci + next build
#   7. SERVICES    installs/updates systemd units (PRESERVES an existing
#                  stock-api.service's Environment lines, e.g. FMP_API_KEY)
#   8. VERIFY      health-checks both ports before declaring success
set -euo pipefail

REPO_URL="https://github.com/rblock888/stock-discover.git"
BRANCH="feat/regime-dashboard"
APP_DIR=""

log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

# ── 1. swap ───────────────────────────────────────────────────────────────────
log "swap"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "added 2G swapfile"
else
  echo "swap already present: $(swapon --show --noheadings | head -1)"
fi
# don't swap eagerly — it's an OOM safety net, not working memory
sysctl -w vm.swappiness=10 >/dev/null
grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf

# ── 2. find or fetch the code ─────────────────────────────────────────────────
log "locate repo"
for d in /root/stock-discover /root/Stocks /opt/stock-discover /home/*/stock-discover; do
  if [ -d "$d/.git" ]; then APP_DIR="$d"; break; fi
done
if [ -z "$APP_DIR" ]; then
  APP_DIR="/root/stock-discover"
  git clone "$REPO_URL" "$APP_DIR"
fi
echo "repo: $APP_DIR"
cd "$APP_DIR"
git fetch origin
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"
echo "at commit: $(git rev-parse --short HEAD)"

# ── 3. python deps ────────────────────────────────────────────────────────────
log "python deps"
PY=python3
$PY -m pip install --quiet --upgrade pip
$PY -m pip install --quiet -r requirements.txt
$PY -m textblob.download_corpora >/dev/null 2>&1 || true

# ── 4. node >= 20 ─────────────────────────────────────────────────────────────
log "node"
NEED_NODE=1
if command -v node >/dev/null; then
  MAJOR=$(node -v | sed 's/v\([0-9]*\).*/\1/')
  [ "$MAJOR" -ge 20 ] && NEED_NODE=0
  echo "node $(node -v)"
fi
if [ "$NEED_NODE" = 1 ]; then
  echo "installing Node 20 (Next.js 16 needs >=20.9)"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
  echo "now: node $(node -v)"
fi

# ── 5. frontend build ─────────────────────────────────────────────────────────
log "frontend build"
cd "$APP_DIR/frontend"
npm ci --no-audit --no-fund
npm run build

# ── 6. systemd units ──────────────────────────────────────────────────────────
log "systemd units"
API_UNIT=/etc/systemd/system/stock-api.service
WEB_UNIT=/etc/systemd/system/stock-web.service

if [ ! -f "$API_UNIT" ]; then
  cat > "$API_UNIT" <<EOF
[Unit]
Description=Stock Discovery API
After=network.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$(command -v python3) -m uvicorn api:app --host 127.0.0.1 --port 8000
Restart=always
# Environment=FMP_API_KEY=...        <- add your keys here
# Environment=PUSHOVER_TOKEN=...
# Environment=PUSHOVER_USER=...
# Environment=TELEGRAM_BOT_TOKEN=...
# Environment=TELEGRAM_CHAT_ID=...

[Install]
WantedBy=multi-user.target
EOF
  echo "created $API_UNIT (ADD YOUR API KEYS to the Environment lines)"
else
  echo "keeping existing $API_UNIT (Environment lines preserved)"
fi

if [ ! -f "$WEB_UNIT" ]; then
  cat > "$WEB_UNIT" <<EOF
[Unit]
Description=Stock Discovery Frontend
After=network.target stock-api.service

[Service]
WorkingDirectory=$APP_DIR/frontend
ExecStart=$(command -v npm) run start -- -p 3001 -H 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  echo "created $WEB_UNIT"
fi

# restart-loop throttle for BOTH units (drop-in overrides — never touches the
# main unit files, so existing Environment= lines survive): a crashing service
# gets 5 tries per 5 minutes with 10s pauses, instead of pegging the CPU forever
for svc in stock-api stock-web; do
  mkdir -p "/etc/systemd/system/${svc}.service.d"
  cat > "/etc/systemd/system/${svc}.service.d/throttle.conf" <<'EOF'
[Unit]
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Restart=always
RestartSec=10
EOF
done

systemctl daemon-reload
systemctl enable stock-api stock-web >/dev/null 2>&1 || true
systemctl restart stock-api
sleep 3
systemctl restart stock-web

# ── 7. verify ─────────────────────────────────────────────────────────────────
log "verify"
sleep 5
for i in $(seq 1 12); do
  if curl -sf http://127.0.0.1:8000/api/health >/dev/null; then
    echo "backend  :8000  OK"
    break
  fi
  [ "$i" = 12 ] && { echo "backend FAILED — journalctl -u stock-api -n 50"; exit 1; }
  sleep 5
done
for i in $(seq 1 12); do
  if curl -sf -o /dev/null http://127.0.0.1:3001/; then
    echo "frontend :3001  OK"
    break
  fi
  [ "$i" = 12 ] && { echo "frontend FAILED — journalctl -u stock-web -n 50"; exit 1; }
  sleep 5
done
echo
echo "DEPLOYED $(git -C "$APP_DIR" rev-parse --short HEAD) — http://$(hostname -I | awk '{print $1}'):3001"
free -h | head -2
