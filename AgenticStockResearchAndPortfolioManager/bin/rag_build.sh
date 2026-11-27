#!/usr/bin/env bash
# Build or rebuild the document index (RAG), in the foreground. All options go to project-code/rag_build.py.
# Example: bin/rag_build.sh --estimate-only        See: bin/rag_build.sh --help
# For the long run use bin/rag_build_bg.sh, which runs it in the background and writes a log.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
[ -x "$PYTHON" ] || die "Missing $PYTHON. Run config/setup.sh first."
ollama_up || warn "Ollama is not answering at $OLLAMA_URL. Embedding needs it (run bin/start_ollama.sh) unless the embedding role uses another provider."
cd "$CODE_DIR"
exec "$PYTHON" rag_build.py "$@"
