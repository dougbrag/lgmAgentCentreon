#!/usr/bin/env bash
set -euo pipefail

if command -v systemctl >/dev/null 2>&1; then
  systemctl stop lgm-receiver || true
  systemctl disable lgm-receiver || true
  systemctl daemon-reload || true
fi
