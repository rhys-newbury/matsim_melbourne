#!/bin/bash
#SBATCH --job-name=eqasim
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=10
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=logs/eqasim-%j.out
#SBATCH --error=logs/eqasim-%j.err

set -euo pipefail

mkdir -p logs

export WANDB_CACHE_DIR=/home/user

apptainer exec \
  docker.sif \
  uv run -m synpp \
    /eqasim/config.yml \
    --working-directory /tmp/eqasim-cache \
    --data_path /eqasim/data \
    --output_path /tmp/eqasim-output