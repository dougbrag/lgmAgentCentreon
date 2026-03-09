#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${1:-/etc/lgm-agent/legacy.conf}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Config file not found: $CONFIG_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

LOG_FILE="${LOG_FILE:-/var/log/lgm-agent-legacy.log}"
STATE_DIR="${STATE_DIR:-/var/lib/lgm-agent-legacy}"
REGISTER_STATE_FILE="${REGISTER_STATE_FILE:-$STATE_DIR/registered}"
LOCK_FILE="${LOCK_FILE:-/var/run/lgm-agent-legacy.lock}"
OS_NAME="${OS_NAME:-linux}"
ROLE_LABEL="${ROLE_LABEL:-linux}"
ENV_LABEL="${ENV_LABEL:-production}"
VERIFY_TLS="${VERIFY_TLS:-true}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-10}"
TOKEN_FILE="${TOKEN_FILE:-/etc/lgm-agent/token}"

mkdir -p "$STATE_DIR"
touch "$LOG_FILE"

log() {
  printf '%s %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$1" >>"$LOG_FILE"
}

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "ERROR missing command: $1"
    exit 1
  fi
}

require_bin curl
require_bin awk
require_bin sed
require_bin date
require_bin hostname
require_bin df

if [[ ! -f "$TOKEN_FILE" ]]; then
  log "ERROR token file not found: $TOKEN_FILE"
  exit 1
fi

TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
if [[ -z "$TOKEN" ]]; then
  log "ERROR empty token in $TOKEN_FILE"
  exit 1
fi

if [[ -z "${RECEIVER_URL:-}" ]]; then
  log "ERROR RECEIVER_URL is empty"
  exit 1
fi

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log "WARN previous execution still running, skipping this cycle"
    exit 0
  fi
fi

escape_json() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

get_primary_ip() {
  local ip_addr
  if command -v ip >/dev/null 2>&1; then
    ip_addr="$(ip route get 1.1.1.1 2>/dev/null | awk 'NR==1{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
    if [[ -n "$ip_addr" ]]; then
      printf '%s' "$ip_addr"
      return
    fi
  fi
  ip_addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
  printf '%s' "${ip_addr:-127.0.0.1}"
}

get_cpu_usage() {
  local line1 line2 idle1 total1 idle2 total2 diff_idle diff_total
  line1="$(awk '/^cpu /{print $2,$3,$4,$5,$6,$7,$8,$9,$10,$11}' /proc/stat)"
  sleep 1
  line2="$(awk '/^cpu /{print $2,$3,$4,$5,$6,$7,$8,$9,$10,$11}' /proc/stat)"

  read -r -a a1 <<<"$line1"
  read -r -a a2 <<<"$line2"

  idle1=$((a1[3] + a1[4]))
  idle2=$((a2[3] + a2[4]))
  total1=0
  total2=0

  for v in "${a1[@]}"; do total1=$((total1 + v)); done
  for v in "${a2[@]}"; do total2=$((total2 + v)); done

  diff_idle=$((idle2 - idle1))
  diff_total=$((total2 - total1))

  if [[ "$diff_total" -le 0 ]]; then
    printf '0.0'
    return
  fi
  awk -v di="$diff_idle" -v dt="$diff_total" 'BEGIN { printf "%.1f", (100 * (dt - di) / dt) }'
}

get_memory_usage() {
  awk '
    /^MemTotal:/ {t=$2}
    /^MemAvailable:/ {a=$2}
    END {
      if (t <= 0) { printf "0.0"; exit }
      printf "%.1f", ((t-a)*100)/t
    }' /proc/meminfo
}

get_disk_usage() {
  df -P / | awk 'NR==2 {gsub("%","",$5); printf "%.1f", $5}'
}

get_load1() {
  awk '{printf "%.2f", $1}' /proc/loadavg
}

get_uptime_seconds() {
  awk '{printf "%d", $1}' /proc/uptime
}

http_post() {
  local endpoint="$1"
  local payload="$2"
  local tls_flag
  tls_flag=""
  if [[ "$VERIFY_TLS" != "true" ]]; then
    tls_flag="--insecure"
  fi

  curl -sS $tls_flag \
    --max-time "$TIMEOUT_SECONDS" \
    -H "Content-Type: application/json" \
    -H "X-Agent-Token: $TOKEN" \
    -X POST \
    --data "$payload" \
    "${RECEIVER_URL}${endpoint}"
}

HOSTNAME_VALUE="$(hostname -s 2>/dev/null || hostname)"
IP_VALUE="$(get_primary_ip)"
HOST_ESCAPED="$(escape_json "$HOSTNAME_VALUE")"
IP_ESCAPED="$(escape_json "$IP_VALUE")"

if [[ ! -f "$REGISTER_STATE_FILE" ]]; then
  register_payload="{\"host\":\"$HOST_ESCAPED\",\"ip\":\"$IP_ESCAPED\",\"os\":\"$OS_NAME\",\"labels\":{\"role\":\"$ROLE_LABEL\",\"environment\":\"$ENV_LABEL\"}}"
  if http_post "/register" "$register_payload" >/dev/null; then
    touch "$REGISTER_STATE_FILE"
    log "INFO register success host=$HOSTNAME_VALUE ip=$IP_VALUE"
  else
    log "ERROR register failed host=$HOSTNAME_VALUE"
  fi
fi

CPU_USAGE="$(get_cpu_usage)"
MEM_USAGE="$(get_memory_usage)"
DISK_USAGE="$(get_disk_usage)"
LOAD1="$(get_load1)"
UPTIME_SECONDS="$(get_uptime_seconds)"
TIMESTAMP="$(date +%s)"

metrics_payload="{\"host\":\"$HOST_ESCAPED\",\"timestamp\":$TIMESTAMP,\"metrics\":{\"cpu\":$CPU_USAGE,\"memory\":$MEM_USAGE,\"disk\":$DISK_USAGE,\"load1\":$LOAD1,\"uptime\":$UPTIME_SECONDS,\"hostname\":\"$HOST_ESCAPED\",\"ip\":\"$IP_ESCAPED\"}}"

if http_post "/ingest" "$metrics_payload" >/dev/null; then
  log "INFO ingest success host=$HOSTNAME_VALUE cpu=$CPU_USAGE mem=$MEM_USAGE disk=$DISK_USAGE load1=$LOAD1"
else
  log "ERROR ingest failed host=$HOSTNAME_VALUE"
fi
