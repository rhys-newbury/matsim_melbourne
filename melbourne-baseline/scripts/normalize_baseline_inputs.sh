#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

network_source="$(find scenario/v1/network/source scenario/v1/network -type f \( -name 'network.xml' -o -name 'network.xml.gz' \) 2>/dev/null | head -n 1 || true)"
transit_schedule_source="$(find scenario/v1/network/source scenario/v1/network -type f \( -name 'transitSchedule.xml' -o -name 'transitSchedule.xml.gz' \) 2>/dev/null | head -n 1 || true)"
transit_vehicles_source="$(find scenario/v1/network/source scenario/v1/network -type f \( -name 'transitVehicles.xml' -o -name 'transitVehicles.xml.gz' \) 2>/dev/null | head -n 1 || true)"
demand_source="$(find scenario/v1/demand/source scenario/v1/demand -type f \( -name 'plan.xml' -o -name 'plan.xml.gz' \) 2>/dev/null | head -n 1 || true)"

if [[ -z "$network_source" ]]; then
  cat >&2 <<'EOF'
No network input found under scenario/v1/network.
Download the baseline network files there first.
EOF
  exit 1
fi

if [[ -z "$demand_source" ]]; then
  cat >&2 <<'EOF'
No demand input found under scenario/v1/demand.
Download the baseline demand files there first.
EOF
  exit 1
fi

if [[ -z "$transit_schedule_source" ]]; then
  cat >&2 <<'EOF'
No transit schedule input found under scenario/v1/network.
Download the baseline transit schedule files there first.
EOF
  exit 1
fi

if [[ -z "$transit_vehicles_source" ]]; then
  cat >&2 <<'EOF'
No transit vehicles input found under scenario/v1/network.
Download the baseline transit vehicles files there first.
EOF
  exit 1
fi

mkdir -p scenario/v1/network scenario/v1/demand/output-Sep10-01pct/8.xml

normalize_xml() {
  local source="$1"
  local target="$2"
  if [[ "$source" == *.gz ]]; then
    gzip -dc "$source" | sed 's/bike/bicycle/g' > "$target"
  else
    sed 's/bike/bicycle/g' "$source" > "$target"
  fi
}

normalize_xml "$network_source" "scenario/v1/network/network.xml"
normalize_xml "$transit_schedule_source" "scenario/v1/network/transitSchedule.xml"
normalize_xml "$transit_vehicles_source" "scenario/v1/network/transitVehicles.xml"
normalize_xml "$demand_source" "scenario/v1/demand/output-Sep10-01pct/8.xml/plan.xml"

cat <<EOF
Normalized:
  network: scenario/v1/network/network.xml
  transit schedule: scenario/v1/network/transitSchedule.xml
  transit vehicles: scenario/v1/network/transitVehicles.xml
  demand:  scenario/v1/demand/output-Sep10-01pct/8.xml/plan.xml
EOF
