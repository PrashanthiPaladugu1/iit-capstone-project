#!/usr/bin/env bash
# Run a project-code script with the same environment as the app (config/arpm.env, venv Python).
# Usage: bin/run_py.sh <script.py or -m module> [args...]     Example: bin/run_py.sh cli_chat.py "How is TCS?"
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
[ -x "$PYTHON" ] || die "Missing $PYTHON. Run config/setup.sh first."
[ $# -ge 1 ] || die "usage: bin/run_py.sh <script.py> [args...]"
cd "$CODE_DIR"
exec "$PYTHON" "$@"
