#!/usr/bin/env bash
# Start Ollama (local LLM server). Safe to run twice.
# If Ollama is already answering (the Mac app, or the systemd service on a VM), it is left alone.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PIDFILE="$RUN_DIR/ollama.pid"

if ollama_up; then
  info "ollama: already running at $OLLAMA_URL."
  exit 0
fi
command -v ollama >/dev/null || die "ollama is not installed. Run config/setup.sh."

# On a VM where setup.sh installed the systemd service, use it.
if command -v systemctl >/dev/null && systemctl list-unit-files ollama.service >/dev/null 2>&1 \
   && systemctl list-unit-files | grep -q '^ollama.service'; then
  info "ollama: starting the systemd service."
  sudo systemctl start ollama
else
  info "ollama: starting 'ollama serve' in the background."
  nohup ollama serve >> "$LOG_DIR/ollama.log" 2>&1 &
  echo $! > "$PIDFILE"
fi

wait_for 30 ollama_up || die "ollama did not answer within 30 s. See $LOG_DIR/ollama.log."
info "ollama: up at $OLLAMA_URL."
