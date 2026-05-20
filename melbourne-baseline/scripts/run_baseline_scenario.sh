#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

jar_file="target/baseline-project-1.0-SNAPSHOT.jar"

if [[ ! -f "$jar_file" ]]; then
  ./scripts/bootstrap_baseline.sh
fi

if [[ ! -f scenario/v1/network/network.xml ]]; then
  echo "Missing scenario/v1/network/network.xml. Run ./scripts/normalize_baseline_inputs.sh first." >&2
  exit 1
fi

if [[ ! -f scenario/v1/demand/output-Sep10-01pct/8.xml/plan.xml ]]; then
  echo "Missing scenario/v1/demand/output-Sep10-01pct/8.xml/plan.xml. Run ./scripts/normalize_baseline_inputs.sh first." >&2
  exit 1
fi

java -jar "$jar_file" scenario/v1 config.xml true
