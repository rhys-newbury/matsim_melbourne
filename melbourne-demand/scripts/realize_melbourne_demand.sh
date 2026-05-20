#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v Rscript >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Rscript is required to realize the Melbourne demand project.
Install R, then restore the repo dependencies with renv before running this script.
EOF
  exit 1
fi

export MELBOURNE_SAMPLE_PERCENT="${MELBOURNE_SAMPLE_PERCENT:-0.1}"
export MELBOURNE_NUM_PLANS="${MELBOURNE_NUM_PLANS:-5000}"
export MELBOURNE_OUTPUT_DIR="${MELBOURNE_OUTPUT_DIR:-output}"

Rscript -e '
samplePercent <- as.numeric(Sys.getenv("MELBOURNE_SAMPLE_PERCENT", "5.0"))
numPlans <- as.integer(Sys.getenv("MELBOURNE_NUM_PLANS", "5000"))
outputDir <- Sys.getenv("MELBOURNE_OUTPUT_DIR", "output")
setwd("R")
source("makeExamplePopulation.R")
makeExamplePopulation(
  samplePercent = samplePercent,
  numPlans = numPlans,
  outputDir = outputDir,
  do.steps = c(TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE),z
  output_crs = 7899
)
'
