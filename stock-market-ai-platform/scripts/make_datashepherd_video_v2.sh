#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python}"

echo "Building updated Data Shepherd Engineering showcase videos..."
echo ""
echo "Optional presenter overrides:"
echo "  PRESENTER_IMAGE=/absolute/path/to/photo.png"
echo "  VOICE_FILE=/absolute/path/to/your_full_narration.wav"
echo ""

"$PYTHON_BIN" scripts/generate_datashepherd_video_v2.py

echo ""
echo "Finished. New videos are in:"
echo "  $ROOT/outputs/data_shepherd_showcase_v2_16x9.mp4"
echo "  $ROOT/outputs/data_shepherd_showcase_v2_linkedin_1x1.mp4"
