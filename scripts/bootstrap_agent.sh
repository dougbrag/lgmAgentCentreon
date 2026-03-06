#!/usr/bin/env bash
set -euo pipefail

BINARY_PATH="${1:-dist/lgm-agent}"
AUTO_START="${2:-no}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

install -d -m 700 /etc/lgm-agent
install -d -m 755 /var/log/lgm-agent
install -m 0755 "${BINARY_PATH}" /usr/local/bin/lgm-agent
install -m 0644 deploy/systemd/lgm-agent.service /etc/systemd/system/lgm-agent.service

if [ ! -f /etc/lgm-agent/config.json ]; then
  install -m 0600 examples/agent.config.json /etc/lgm-agent/config.json
fi

systemctl daemon-reload
systemctl enable lgm-agent

if [ "${AUTO_START}" = "start" ]; then
  systemctl restart lgm-agent || systemctl start lgm-agent
else
  echo "Agent installed. Start manually after creating token/key files."
fi
