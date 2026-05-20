#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v mvn >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Maven is required to build the Melbourne baseline project.
Install Maven, then rerun this script.
EOF
  exit 1
fi

if ! command -v java >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Java is required. This project expects Java 25.
EOF
  exit 1
fi

java -version 2>&1 | head -n 1

mvn -q -DskipTests package
