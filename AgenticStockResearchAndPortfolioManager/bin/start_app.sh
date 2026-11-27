#!/usr/bin/env bash
# Start the Streamlit app (Chat tab and Admin tab) in the background.
# Listens on 127.0.0.1 only. On a VM, reach it with: ssh -L 8502:localhost:8502 <user>@<host>
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PIDFILE="$RUN_DIR/app.pid"

if pid_alive "$PIDFILE"; then
  info "app: already running (PID $(cat "$PIDFILE")) on port $APP_PORT."
  exit 0
fi
rm -f "$PIDFILE"

[ -x "$PYTHON" ] || die "Missing $PYTHON. Run config/setup.sh first."
[ -f "$APP_ENTRY" ] || die "Missing $APP_ENTRY. The Streamlit app is not written yet."
ollama_up || warn "Ollama is not answering at $OLLAMA_URL. Run bin/start_ollama.sh, or use bin/start_all.sh."
[ -n "${ARPM_ADMIN_PASSWORD:-}" ] || warn "ARPM_ADMIN_PASSWORD is empty. Set it in config/arpm.env before using the Admin tab."

cd "$CODE_DIR"
nohup perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' "$PYTHON" -m streamlit run "$APP_ENTRY" \
  --server.address 127.0.0.1 \
  --server.port "$APP_PORT" \
  --server.headless true \
  --browser.gatherUsageStats false \
  >> "$LOG_DIR/app.log" 2>&1 < /dev/null &
echo $! > "$PIDFILE"

if wait_for 30 app_up; then
  info "app: up at http://127.0.0.1:$APP_PORT (log: $LOG_DIR/app.log)."
else
  stop_pidfile "app" "$PIDFILE" >/dev/null
  die "app did not become healthy within 30 s. See $LOG_DIR/app.log."
fi
