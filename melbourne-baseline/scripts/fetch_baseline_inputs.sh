#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p \
  scenario/v1/network/source \
  scenario/v1/demand/source

download() {
  local url="$1"
  local dest="$2"
  if [[ -f "$dest" ]]; then
    return 0
  fi
  curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 600 "$url" -o "$dest"
}

downloads=(
  "https://osf.io/download/nuh65/ scenario/v1/network/source/network.xml"
  "https://osf.io/download/6537e80f164d3210b6a5d938/ scenario/v1/network/source/network_netwalk.xml"
  "https://osf.io/download/6537e92628274510a9b867b2/ scenario/v1/network/source/transitSchedule.xml"
  "https://osf.io/download/6537e925282745108bb869e3/ scenario/v1/network/source/transitVehicles.xml"
  "https://osf.io/download/86q7z/ scenario/v1/demand/source/plan.xml.gz"
  "https://osf.io/download/zh8k3/ scenario/v1/demand/source/netwalk_plan.xml.gz"
)

for item in "${downloads[@]}"; do
  url="${item%% *}"
  dest="${item#* }"
  download "$url" "$dest"
done

cat <<'EOF'
Downloaded Melbourne baseline inputs into:
  scenario/v1/network/source
  scenario/v1/demand/source
EOF
