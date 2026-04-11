#!/bin/bash
set -e

echo "=== Stock Discovery VPS Setup ==="
echo ""

# Create API service
echo "[1/4] Creating API service..."
tee /etc/systemd/system/stock-api.service > /dev/null <<'SVC1'
[Unit]
Description=Stock Discovery API
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/stock-discover
Environment=FMP_API_KEY=UHNEG1MHwZufh0cPRCCxbdHMQfaPRQM1
ExecStart=/opt/stock-discover/venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC1

# Create frontend service
echo "[2/4] Creating frontend service..."
tee /etc/systemd/system/stock-frontend.service > /dev/null <<'SVC2'
[Unit]
Description=Stock Discovery Frontend
After=stock-api.service

[Service]
Type=simple
WorkingDirectory=/opt/stock-discover/frontend
ExecStart=/usr/bin/npx next start -p 3001
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
SVC2

# Start services
echo "[3/4] Starting services..."
systemctl daemon-reload
systemctl enable stock-api stock-frontend
systemctl start stock-api
sleep 2
systemctl start stock-frontend

# Check
echo "[4/4] Checking status..."
echo ""
systemctl is-active stock-api && echo "API: RUNNING on port 8000" || echo "API: FAILED"
systemctl is-active stock-frontend && echo "Frontend: RUNNING on port 3001" || echo "Frontend: FAILED"
echo ""
echo "=== Done ==="
echo "API:      http://208.76.222.98:8000/api/health"
echo "Frontend: http://208.76.222.98:3001"
echo ""
echo "Useful commands:"
echo "  journalctl -u stock-api -f        (API logs)"
echo "  journalctl -u stock-frontend -f   (Frontend logs)"
echo "  systemctl restart stock-api       (Restart API)"
echo "  systemctl restart stock-frontend  (Restart frontend)"
