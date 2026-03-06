#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-1.0.0}"
OUT_DIR="${2:-artifacts}"
TARGETS="${3:-deb,rpm}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build/linux"
DIST_DIR="${ROOT_DIR}/dist"
PKG_ROOT="${BUILD_DIR}/pkgroot"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need_cmd python3
need_cmd fpm

rm -rf "${BUILD_DIR}" "${DIST_DIR}/lgm-agent" "${DIST_DIR}/lgm-receiver"
mkdir -p "${BUILD_DIR}" "${OUT_DIR}"

pushd "${ROOT_DIR}" >/dev/null

chmod +x scripts/bootstrap_agent.sh scripts/bootstrap_receiver.sh \
  packaging/hooks/agent/post-install.sh packaging/hooks/agent/before-remove.sh \
  packaging/hooks/receiver/post-install.sh packaging/hooks/receiver/before-remove.sh

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt pyinstaller >/dev/null

pyinstaller --noconfirm --clean --onefile --name lgm-agent \
  --distpath "${DIST_DIR}" --workpath "${BUILD_DIR}/agent" --specpath "${BUILD_DIR}/spec" \
  agent/lgm_agent.py

pyinstaller --noconfirm --clean --onefile --name lgm-receiver \
  --distpath "${DIST_DIR}" --workpath "${BUILD_DIR}/receiver" --specpath "${BUILD_DIR}/spec" \
  receiver/lgm_receiver.py

rm -rf "${PKG_ROOT}"
mkdir -p "${PKG_ROOT}/agent/usr/local/bin" \
         "${PKG_ROOT}/agent/etc/lgm-agent" \
         "${PKG_ROOT}/agent/etc/systemd/system" \
         "${PKG_ROOT}/receiver/usr/local/bin" \
         "${PKG_ROOT}/receiver/etc/lgm-monitor" \
         "${PKG_ROOT}/receiver/etc/systemd/system"

install -m 0755 "${DIST_DIR}/lgm-agent" "${PKG_ROOT}/agent/usr/local/bin/lgm-agent"
install -m 0644 "examples/agent.config.json" "${PKG_ROOT}/agent/etc/lgm-agent/config.json.example"
install -m 0644 "deploy/systemd/lgm-agent.service" "${PKG_ROOT}/agent/etc/systemd/system/lgm-agent.service"

install -m 0755 "${DIST_DIR}/lgm-receiver" "${PKG_ROOT}/receiver/usr/local/bin/lgm-receiver"
install -m 0644 "examples/receiver.config.json" "${PKG_ROOT}/receiver/etc/lgm-monitor/config.json.example"
install -m 0644 "deploy/systemd/lgm-receiver.service" "${PKG_ROOT}/receiver/etc/systemd/system/lgm-receiver.service"

IFS=',' read -r -a target_list <<< "${TARGETS}"
for target in "${target_list[@]}"; do
  case "${target}" in
    deb|rpm) ;;
    *)
      echo "Unsupported package target: ${target}. Use deb, rpm or deb,rpm." >&2
      exit 1
      ;;
  esac

  fpm -s dir -t "${target}" -n lgm-agent -v "${VERSION}" \
    --description "LGM Monitoring Agent" \
    --url "https://example.com/lgm" \
    --after-install packaging/hooks/agent/post-install.sh \
    --before-remove packaging/hooks/agent/before-remove.sh \
    -C "${PKG_ROOT}/agent" .

  fpm -s dir -t "${target}" -n lgm-receiver -v "${VERSION}" \
    --description "LGM Receiver Server" \
    --url "https://example.com/lgm" \
    --after-install packaging/hooks/receiver/post-install.sh \
    --before-remove packaging/hooks/receiver/before-remove.sh \
    -C "${PKG_ROOT}/receiver" .
done

mv ./*.deb ./*.rpm "${OUT_DIR}/" 2>/dev/null || true

echo "Packages generated in ${OUT_DIR}:"
ls -1 "${OUT_DIR}"/* || true

popd >/dev/null

