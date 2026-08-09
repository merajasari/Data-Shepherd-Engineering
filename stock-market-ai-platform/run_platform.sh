#!/data/data/com.termux/files/usr/bin/bash

set -u

PROJECT_DIR="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"

LOG_DIR="$PROJECT_DIR/logs"
RUN_DIR="$PROJECT_DIR/run"

IEX_PID_FILE="$RUN_DIR/iex_stream.pid"
WEB_PID_FILE="$RUN_DIR/webapp.pid"

IEX_LOG="$LOG_DIR/iex_stream.log"
WEB_LOG="$LOG_DIR/webapp.log"

cd "$PROJECT_DIR" || exit 1

mkdir -p "$LOG_DIR"
mkdir -p "$RUN_DIR"

set -a
source .env
set +a


is_running() {

    local pid_file="$1"

    if [[ ! -f "$pid_file" ]]; then
        return 1
    fi

    local pid

    pid="$(
        cat "$pid_file"
    )"

    if [[ -z "$pid" ]]; then
        return 1
    fi

    kill -0 "$pid" \
        2>/dev/null
}


start_iex() {

    if is_running "$IEX_PID_FILE"; then

        echo "IEX stream already running."

        return
    fi

    rm -f "$IEX_PID_FILE"

    echo "Starting Tiingo IEX live stream..."

    PYTHONPATH=data-ingestion \
    python -u data-ingestion/iex_stream.py \
    >> "$IEX_LOG" 2>&1 &

    local pid=$!

    echo "$pid" \
        > "$IEX_PID_FILE"

    sleep 1

    if kill -0 "$pid" 2>/dev/null; then

        echo "IEX stream started."
        echo "PID: $pid"

    else

        echo "ERROR: IEX stream failed to start."

        rm -f "$IEX_PID_FILE"

        return 1
    fi
}


start_web() {

    if is_running "$WEB_PID_FILE"; then

        echo "Web app already running."

        return
    fi

    rm -f "$WEB_PID_FILE"

    echo "Starting Flask web application..."

    PYTHONPATH=. \
    python -u - <<'PY' \
    >> "$WEB_LOG" 2>&1 &

from webapp.app import app

app.run(
    host="0.0.0.0",
    port=5000,
    debug=False,
    use_reloader=False,
)

PY

    local pid=$!

    echo "$pid" \
        > "$WEB_PID_FILE"

    sleep 1

    if kill -0 "$pid" 2>/dev/null; then

        echo "Web app started."
        echo "PID: $pid"

    else

        echo "ERROR: Web app failed to start."

        rm -f "$WEB_PID_FILE"

        return 1
    fi
}


stop_process() {

    local name="$1"
    local pid_file="$2"

    if [[ ! -f "$pid_file" ]]; then

        echo "$name is not running."

        return
    fi

    local pid

    pid="$(
        cat "$pid_file"
    )"

    if ! kill -0 "$pid" 2>/dev/null; then

        echo "$name is not running."

        rm -f "$pid_file"

        return
    fi

    echo "Stopping $name..."

    kill "$pid" \
        2>/dev/null || true

    for _ in 1 2 3 4 5
    do

        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi

        sleep 1

    done

    if kill -0 "$pid" 2>/dev/null; then

        echo "$name did not stop gracefully."

        echo "Force stopping PID $pid..."

        kill -9 "$pid" \
            2>/dev/null || true
    fi

    rm -f "$pid_file"

    echo "$name stopped."
}


status_process() {

    local name="$1"
    local pid_file="$2"

    if is_running "$pid_file"; then

        local pid

        pid="$(
            cat "$pid_file"
        )"

        echo "$name: RUNNING (PID $pid)"

    else

        echo "$name: STOPPED"

        rm -f "$pid_file" \
            2>/dev/null || true
    fi
}


start_platform() {

    echo "=============================================="
    echo "DATA SHEPHERD ENGINEERING"
    echo "STOCK MARKET AI PLATFORM"
    echo "=============================================="

    start_iex
    start_web

    echo
    echo "Dashboard:"
    echo "http://127.0.0.1:5000"

    echo
    echo "Platform start complete."
}


stop_platform() {

    echo "Stopping Stock Market AI Platform..."

    stop_process \
        "IEX stream" \
        "$IEX_PID_FILE"

    stop_process \
        "Web app" \
        "$WEB_PID_FILE"
}


status_platform() {

    echo "=============================================="
    echo "STOCK MARKET AI PLATFORM STATUS"
    echo "=============================================="

    status_process \
        "IEX stream" \
        "$IEX_PID_FILE"

    status_process \
        "Web app" \
        "$WEB_PID_FILE"

    echo

    if pgrep -a crond >/dev/null 2>&1; then

        echo "Cron scheduler: RUNNING"

    else

        echo "Cron scheduler: STOPPED"
    fi

    echo

    echo "Dashboard:"
    echo "http://127.0.0.1:5000"
}


restart_platform() {

    stop_platform

    sleep 2

    start_platform
}


case "${1:-start}" in

    start)
        start_platform
        ;;

    stop)
        stop_platform
        ;;

    status)
        status_platform
        ;;

    restart)
        restart_platform
        ;;

    *)
        echo "Usage:"
        echo "./run_platform.sh start"
        echo "./run_platform.sh stop"
        echo "./run_platform.sh status"
        echo "./run_platform.sh restart"

        exit 1
        ;;
esac
