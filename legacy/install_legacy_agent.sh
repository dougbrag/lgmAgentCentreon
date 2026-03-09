#!/usr/bin/env bash
set -euo pipefail

PREFIX="${1:-/usr/local/bin}"
ETC_DIR="${2:-/etc/lgm-agent}"
CRON_FILE="/etc/cron.d/lgm-agent-legacy"

install -d -m 755 "$PREFIX"
install -d -m 700 "$ETC_DIR"
install -d -m 755 /var/lib/lgm-agent-legacy
install -d -m 755 /var/log

install -m 755 legacy/lgm-agent-legacy.sh "$PREFIX/lgm-agent-legacy"

if [[ ! -f "$ETC_DIR/legacy.conf" ]]; then
  install -m 600 legacy/lgm-agent-legacy.conf "$ETC_DIR/legacy.conf"
fi

if [[ ! -f "$ETC_DIR/token" ]]; then
  echo "CHANGEME_AGENT_TOKEN" > "$ETC_DIR/token"
  chmod 600 "$ETC_DIR/token"
fi

cat > "$CRON_FILE" <<EOF
*/1 * * * * root $PREFIX/lgm-agent-legacy $ETC_DIR/legacy.conf
EOF
chmod 644 "$CRON_FILE"

echo "LGM legacy agent installed."
echo "1) Ajuste $ETC_DIR/legacy.conf"
echo "2) Substitua o token em $ETC_DIR/token"
echo "3) Rode um teste manual: $PREFIX/lgm-agent-legacy $ETC_DIR/legacy.conf"
