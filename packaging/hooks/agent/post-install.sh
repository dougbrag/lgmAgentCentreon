#!/usr/bin/env bash
set -euo pipefail

mkdir -p /etc/lgm-agent /var/log/lgm-agent
chmod 700 /etc/lgm-agent || true

if [ ! -f /etc/lgm-agent/config.json ] && [ -f /etc/lgm-agent/config.json.example ]; then
  cp /etc/lgm-agent/config.json.example /etc/lgm-agent/config.json
  chmod 600 /etc/lgm-agent/config.json || true
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
  systemctl enable lgm-agent || true
  if [ -f /etc/lgm-agent/config.json ] && [ -f /etc/lgm-agent/token.enc ] && [ -f /etc/lgm-agent/key.bin ]; then
    systemctl restart lgm-agent || systemctl start lgm-agent || true
  else
    echo "[lgm-agent] Config/token not fully present yet. Service enabled but not started." >&2
  fi
fi
