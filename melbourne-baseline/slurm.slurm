#!/bin/bash
#SBATCH --job-name=melbourne
#SBATCH --cpus-per-task=10
#SBATCH --mem=64G
#SBATCH --output=logs/melbourne-%j.out
#SBATCH --error=logs/melbourne-%j.err

set -euo pipefail

mkdir -p logs

apptainer exec \
  --pwd=/app \
  docker.sif \
  bash scripts/run_baseline_scenario.sh
