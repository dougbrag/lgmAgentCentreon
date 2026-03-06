#!/usr/bin/env bash
set -euo pipefail

BINARY_PATH="${1:-dist/lgm-receiver}"
AUTO_START="${2:-no}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

install -d -m 700 /etc/lgm-monitor
install -d -m 755 /var/lib/lgm-monitor
install -d -m 755 /var/log/lgm-monitor
install -m 0755 "${BINARY_PATH}" /usr/local/bin/lgm-receiver
install -m 0644 deploy/systemd/lgm-receiver.service /etc/systemd/system/lgm-receiver.service

if [ ! -f /etc/lgm-monitor/config.json ]; then
  install -m 0600 examples/receiver.config.json /etc/lgm-monitor/config.json
fi

systemctl daemon-reload
systemctl enable lgm-receiver

if [ "${AUTO_START}" = "start" ]; then
  systemctl restart lgm-receiver || systemctl start lgm-receiver
else
  echo "Receiver installed. Start manually after validating config and tokens."
fi
