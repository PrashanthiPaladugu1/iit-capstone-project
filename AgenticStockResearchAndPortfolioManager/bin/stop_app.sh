#!/usr/bin/env bash
# Stop the Streamlit app.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

stop_pidfile "app" "$RUN_DIR/app.pid"
