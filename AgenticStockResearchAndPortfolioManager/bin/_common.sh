#!/usr/bin/env bash
# Shared helpers for the bin/ scripts. Source it, do not run it.

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Every path comes from config/paths.json (via project-code/config.py, standard library only).
# Do not write paths in this script. Edit config/paths.json instead.
eval "$(python3 "$_HERE/project-code/config.py" shell)" || { echo "ERROR: cannot read config/paths.json" >&2; exit 1; }

if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi

mkdir -p "$RUN_DIR" "$LOG_DIR" "$DB_DIR"

OLLAMA_URL="${OLLAMA_HOST:-http://localhost:11434}"
APP_PORT="${ARPM_PORT:-8502}"
PYTHON="$VENV_DIR/bin/python"

info() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# pid_alive <pidfile>: true if the file exists and the process is running.
pid_alive() {
  [ -f "$1" ] || return 1
  local pid; pid="$(cat "$1" 2>/dev/null)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# stop_pidfile <name> <pidfile>: SIGTERM, wait up to 20 s, then SIGKILL.
stop_pidfile() {
  local name="$1" file="$2"
  if ! pid_alive "$file"; then
    rm -f "$file"
    info "$name: not running (no live PID file)."
    return 0
  fi
  local pid; pid="$(cat "$file")"
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    warn "$name did not stop in 20 s. Sending SIGKILL."
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$file"
  info "$name: stopped."
}

ollama_up() { curl -fs "$OLLAMA_URL/api/tags" >/dev/null 2>&1; }
app_up()    { curl -fs "http://127.0.0.1:$APP_PORT/_stcore/health" >/dev/null 2>&1; }

# wait_for <seconds> <command...>: poll until the command succeeds.
wait_for() {
  local secs="$1"; shift
  for _ in $(seq 1 "$secs"); do
    "$@" && return 0
    sleep 1
  done
  return 1
}
