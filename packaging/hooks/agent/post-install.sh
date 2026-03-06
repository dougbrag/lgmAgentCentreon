#!/usr/bin/env bash
set -euo pipefail

mkdir -p /etc/lgm-agent /var/log/lgm-agent
chmod 700 /etc/lgm-agent || true

if [ ! -f /etc/lgm-agent/config.json ] && [ -f /etc/lgm-agent/config.json.example ]; then
  cp /etc/lgm-agent/config.json.example /etc/lgm-agent/config.json
  chmod 600 /etc/lgm-agent/config.json || true
fi

service_started="no"

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
  systemctl enable lgm-agent || true
  if [ -f /etc/lgm-agent/config.json ] && [ -f /etc/lgm-agent/token.enc ] && [ -f /etc/lgm-agent/key.bin ]; then
    if systemctl restart lgm-agent || systemctl start lgm-agent; then
      service_started="yes"
    fi
  else
    echo "[lgm-agent] Config/token not fully present yet. Service enabled but not started." >&2
  fi
fi

echo "[lgm-agent] Installation completed successfully."
echo "[lgm-agent] Service enabled: yes"
if [ "$service_started" = "yes" ]; then
  echo "[lgm-agent] Service started: yes"
else
  echo "[lgm-agent] Service started: no"
  echo "[lgm-agent] Next steps: configure /etc/lgm-agent/config.json and create token/key files, then run: systemctl restart lgm-agent"
fi