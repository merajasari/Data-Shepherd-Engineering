#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

mkdir -p outputs

echo "Building Data Shepherd Engineering promo videos..."
"$PYTHON" scripts/generate_datashepherd_video.py --format both

echo
echo "Finished. Videos are in:"
echo "  $ROOT/outputs/data_shepherd_landing_16x9.mp4"
echo "  $ROOT/outputs/data_shepherd_linkedin_1x1.mp4"
