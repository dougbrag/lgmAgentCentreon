#!/usr/bin/env bash
set -euo pipefail

mkdir -p /etc/lgm-monitor /var/lib/lgm-monitor /var/log/lgm-monitor
chmod 700 /etc/lgm-monitor || true

if [ ! -f /etc/lgm-monitor/config.json ] && [ -f /etc/lgm-monitor/config.json.example ]; then
  cp /etc/lgm-monitor/config.json.example /etc/lgm-monitor/config.json
  chmod 600 /etc/lgm-monitor/config.json || true
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
  systemctl enable lgm-receiver || true
  if [ -f /etc/lgm-monitor/config.json ]; then
    systemctl restart lgm-receiver || systemctl start lgm-receiver || true
  fi
fi
