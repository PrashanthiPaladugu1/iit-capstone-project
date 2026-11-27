#!/usr/bin/env bash
# Start everything in order: Ollama, then the app.
# The MCP servers (market-data, fundamentals, portfolio) are not separate processes. The app starts
# each one over stdio when it needs it, so there is nothing else to launch.
DIR="$(dirname "${BASH_SOURCE[0]}")"
"$DIR/start_ollama.sh" && "$DIR/start_app.sh"
