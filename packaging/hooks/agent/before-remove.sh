#!/usr/bin/env bash
set -euo pipefail

if command -v systemctl >/dev/null 2>&1; then
  systemctl stop lgm-agent || true
  systemctl disable lgm-agent || true
  systemctl daemon-reload || true
fi
