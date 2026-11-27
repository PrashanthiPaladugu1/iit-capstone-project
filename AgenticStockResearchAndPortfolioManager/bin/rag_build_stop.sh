#!/usr/bin/env bash
# Stop the background document index build safely. Finished files stay; run bin/rag_build_bg.sh again to continue.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
stop_pidfile "rag build" "$RUN_DIR/rag_build.pid"
