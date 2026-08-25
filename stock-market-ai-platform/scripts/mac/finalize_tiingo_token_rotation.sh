#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIR:h:h}"
ENV_FILE="${PROJECT_ROOT}/.env"
ARCHIVE_DIR="${PROJECT_ROOT}/logs/archive"
V8_ERROR_LOG="${PROJECT_ROOT}/logs/v8_refresh.err.log"
V5_ERROR_LOG="${PROJECT_ROOT}/logs/v5_refresh.err.log"
SERVICE_LABEL="com.datashepherd.v8refresh"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[FAIL] Project virtual-environment Python is unavailable: ${PYTHON_BIN}" >&2
  exit 2
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[FAIL] .env is absent. Add the newly rotated Tiingo token first." >&2
  exit 2
fi

"${PYTHON_BIN}" - "${ENV_FILE}" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
match = re.search(r"(?m)^\\s*TIINGO_API_KEY\\s*=\\s*(?:['\"])?([^'\"#\\s]+)", text)
if not match or len(match.group(1).strip()) < 12:
    raise SystemExit("[FAIL] .env does not contain a usable TIINGO_API_KEY.")
print("[PASS] A Tiingo token is configured in .env (value not displayed).")
PY

mkdir -p "${ARCHIVE_DIR}"
chmod 700 "${ARCHIVE_DIR}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
for LOG_PATH in "${V8_ERROR_LOG}" "${V5_ERROR_LOG}"; do
  if [[ -s "${LOG_PATH}" ]]; then
    LOG_NAME="${LOG_PATH:t}"
    mv "${LOG_PATH}" "${ARCHIVE_DIR}/${LOG_NAME}.pre-rotation.${TIMESTAMP}"
    chmod 600 "${ARCHIVE_DIR}/${LOG_NAME}.pre-rotation.${TIMESTAMP}"
    echo "[PASS] Archived ${LOG_NAME} with owner-only permissions."
  fi
  : > "${LOG_PATH}"
  chmod 600 "${LOG_PATH}"
done

launchctl kickstart -k "gui/$(id -u)/${SERVICE_LABEL}"

echo "[PASS] Restarted ${SERVICE_LABEL}."
echo "Wait for one refresh cycle, then run:"
echo "  FEATURE_BACKEND=spark python -m ml.stock_scheduled_refresh_regression"
echo "No credential value was printed. Brokerage orders remain off."
