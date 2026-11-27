#!/usr/bin/env bash
# Show what is running. Exit code 0 only if both Ollama and the app are up.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

rc=0
if ollama_up; then
  info "ollama: UP at $OLLAMA_URL"
  command -v ollama >/dev/null && ollama list 2>/dev/null | sed 's/^/        /'
else
  info "ollama: DOWN"; rc=1
fi

if app_up; then
  info "app:    UP at http://127.0.0.1:$APP_PORT (PID $(cat "$RUN_DIR/app.pid" 2>/dev/null || echo '?'))"
else
  info "app:    DOWN"; rc=1
fi

info "logs:   $LOG_DIR"
exit "$rc"
