#!/usr/bin/env bash
# Run the document index build in the background. Always adds --yes. Safe to run again: finished files are skipped.
# Example: bin/rag_build_bg.sh --tiers 1,2,3       Watch: tail -f runtime/logs/rag_build.log
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
PIDFILE="$RUN_DIR/rag_build.pid"
if pid_alive "$PIDFILE"; then
  info "rag build: already running (PID $(cat "$PIDFILE")). Log: $LOG_DIR/rag_build.log"
  exit 0
fi
[ -x "$PYTHON" ] || die "Missing $PYTHON. Run config/setup.sh first."
ollama_up || die "Ollama is not answering at $OLLAMA_URL. Run bin/start_ollama.sh first."
cd "$CODE_DIR"
printf '\n===== %s  rag_build %s =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_DIR/rag_build.log"
# perl setsid: a new session, so the job is not killed when the calling shell or tool call ends (macOS has no setsid command).
nohup perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' "$PYTHON" rag_build.py --yes "$@" >> "$LOG_DIR/rag_build.log" 2>&1 < /dev/null &
echo $! > "$PIDFILE"
info "rag build: started (PID $!). Log: $LOG_DIR/rag_build.log"
