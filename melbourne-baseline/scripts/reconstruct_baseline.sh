#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

./scripts/bootstrap_baseline.sh
./scripts/fetch_baseline_inputs.sh

if [[ ! -f scenario/v1/network/network.xml && ! -f scenario/v1/network/network.xml.gz ]]; then
  cat <<'EOF'
Missing baseline network input.
Recover it from: scenario/v1/network/README.MD
EOF
  exit 2
fi

if [[ ! -f scenario/v1/demand/output-Sep10-01pct/8.xml/plan.xml && ! -f scenario/v1/demand/output-Sep10-01pct/8.xml/plan.xml.gz ]]; then
  cat <<'EOF'
Missing baseline demand input.
Recover it from: scenario/v1/demand/README.MD
EOF
  exit 2
fi

./scripts/normalize_baseline_inputs.sh
./scripts/run_baseline_scenario.sh
