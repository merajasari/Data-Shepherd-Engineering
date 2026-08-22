#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python scripts/generate_datashepherd_video_v7.py
