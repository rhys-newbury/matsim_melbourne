#!/usr/bin/env bash
set -euo pipefail

export RENV_PATHS_LIBRARY=/opt/renv/library
export RENV_PATHS_CACHE=/opt/renv/cache

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SAMPLE_PERCENT="${1:-0.1}"
NUM_PLANS="${2:-5000}"
OUTPUT_DIR="${3:-output}"

Rscript -e "
.libPaths('/opt/renv/library')

samplePercent <- as.numeric('$SAMPLE_PERCENT')
numPlans <- as.integer('$NUM_PLANS')
outputDir <- '$OUTPUT_DIR'

setwd('R')
source('makeExamplePopulation.R')

makeExamplePopulation(
  samplePercent = samplePercent,
  numPlans = numPlans,
  outputDir = outputDir,
  do.steps = c(TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE),
  output_crs = 7899
)
"