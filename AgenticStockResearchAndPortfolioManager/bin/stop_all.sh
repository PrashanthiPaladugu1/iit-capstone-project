#!/usr/bin/env bash
# Stop everything in reverse order: the app, then Ollama (only if this project started it).
DIR="$(dirname "${BASH_SOURCE[0]}")"
"$DIR/stop_app.sh"
"$DIR/stop_ollama.sh"
