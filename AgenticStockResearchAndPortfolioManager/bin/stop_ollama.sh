#!/usr/bin/env bash
# Stop Ollama, but only if this project started it (PID file or systemd service on a VM).
# An Ollama you started some other way (for example the Mac menu-bar app) is not touched.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PIDFILE="$RUN_DIR/ollama.pid"

if pid_alive "$PIDFILE"; then
  stop_pidfile "ollama" "$PIDFILE"
elif command -v systemctl >/dev/null && systemctl is-active --quiet ollama 2>/dev/null; then
  info "ollama: stopping the systemd service."
  sudo systemctl stop ollama
  info "ollama: stopped."
elif ollama_up; then
  info "ollama: running, but not started by these scripts. Left running. Quit it from its own app or process."
else
  rm -f "$PIDFILE"
  info "ollama: not running."
fi
