#!/usr/bin/env bash
# One-shot setup for Agentic Research and Portfolio Maker on a fresh Linux VM (EC2).
# Intended for Ubuntu 22.04/24.04 and Amazon Linux 2023 (not yet run on a VM). Run as a normal user with sudo, not as root.
#
# Usage:
#   bash config/setup.sh                      # full setup
#   bash config/setup.sh --skip-models        # do not pull Ollama models
#   ARPM_MODELS="mistral:7b nomic-embed-text gemma4:12b" bash config/setup.sh
#
# Before running, copy the whole parent folder to the VM, e.g. with rsync, and EXCLUDE secrets:
#   rsync -av --exclude '.venv' --exclude '.DS_Store' \
#     --exclude 'screener-document-download/screener_auth.json' \
#     --exclude 'screener-document-download/secret' \
#     --exclude 'screener-document-download/logs' \
#     --exclude 'screener-document-download/download_tracker.txt' \
#     --exclude 'screener-document-download/downloaded_history.json' \
#     ./ ec2-user@<host>:~/AgenticStockResearchAndPortfolioManager/
#
# The script is safe to re-run.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Every path comes from config/paths.json. Edit that file, not this script.
eval "$(python3 "$ROOT/project-code/config.py" shell)" || { echo "ERROR: cannot read config/paths.json" >&2; exit 1; }
PYTHON_VERSION="3.12"
# mistral:7b about 4.4 GB, nomic-embed-text about 0.3 GB. Add gemma4:12b (about 7.7 GB, needs 16+ GB RAM) via ARPM_MODELS.
MODELS="${ARPM_MODELS:-mistral:7b nomic-embed-text}"
MIN_FREE_GB=60
PULL_MODELS=1

for arg in "$@"; do
  case "$arg" in
    --skip-models) PULL_MODELS=0 ;;
    -h|--help) sed -n '2,19p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

log()  { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Run as a normal user with sudo, not as root."
command -v sudo >/dev/null || die "sudo is required."

# ---------------------------------------------------------------- 1. checks
log "Checking the machine"
[ -d "$CODE_DIR" ]  || die "Missing $CODE_DIR. Copy the whole parent folder first."
[ -d "$DATA_ROOT" ] || warn "Missing $DATA_ROOT. The app needs it at run time (price files, Excel, PDFs)."
[ -f "$REQUIREMENTS_FILE" ] || die "Missing $REQUIREMENTS_FILE."

free_gb=$(df -Pk "$ROOT" | awk 'NR==2 {print int($4/1024/1024)}')
mem_gb=$(awk '/MemTotal/ {print int($2/1024/1024)}' /proc/meminfo)
echo "Free disk here: ${free_gb} GB. RAM: ${mem_gb} GB. CPUs: $(nproc)."
[ "$free_gb" -ge "$MIN_FREE_GB" ] || warn "Under ${MIN_FREE_GB} GB free. Data 15 GB + vector store up to 14 GB + models 5 to 13 GB need more. Grow the EBS volume."
[ "$mem_gb" -ge 8 ] || warn "Under 8 GB RAM. mistral:7b will not run well."
command -v nvidia-smi >/dev/null || warn "No NVIDIA GPU found. Ollama will run on CPU and answers will be slow. Use a g5/g6 instance for speed."

# ---------------------------------------------------------------- 2. system packages
log "Installing system packages"
if command -v apt-get >/dev/null; then
  sudo apt-get update -y
  # poppler-utils provides pdftotext, used for PDF extraction.
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates git build-essential poppler-utils zstd
elif command -v dnf >/dev/null; then
  # curl-minimal is already present on Amazon Linux 2023; do not install curl.
  sudo dnf install -y git gcc gcc-c++ make poppler-utils zstd tar
else
  die "Unsupported OS: need apt-get or dnf."
fi

# ---------------------------------------------------------------- 3. uv and Python
log "Installing uv"
if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || die "uv install failed."

log "Creating Python $PYTHON_VERSION virtual environment in project-code/.venv"
uv venv --python "$PYTHON_VERSION" --allow-existing "$VENV_DIR"
uv pip install --python "$VENV_DIR/bin/python" -r "$REQUIREMENTS_FILE"
"$VENV_DIR/bin/python" --version

# ---------------------------------------------------------------- 4. Ollama
log "Installing Ollama"
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
if command -v systemctl >/dev/null; then
  sudo systemctl enable --now ollama || warn "Could not enable the ollama service."
fi

log "Waiting for Ollama"
for _ in $(seq 1 30); do
  curl -fs http://localhost:11434/api/tags >/dev/null 2>&1 && break
  sleep 2
done
curl -fs http://localhost:11434/api/tags >/dev/null 2>&1 || warn "Ollama is not answering on port 11434. Start it with: sudo systemctl start ollama"

if [ "$PULL_MODELS" -eq 1 ]; then
  log "Pulling models: $MODELS"
  for m in $MODELS; do
    ollama pull "$m" || warn "Could not pull $m. Check the model name and try again."
  done
else
  log "Skipping model download (--skip-models)"
fi

# ---------------------------------------------------------------- 5. settings and folders
log "Writing settings"
mkdir -p "$DB_DIR" "$RUN_DIR" "$LOG_DIR"
if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE. Set ARPM_ADMIN_PASSWORD in it before starting the app."
else
  echo "Keeping existing $ENV_FILE"
fi

# ---------------------------------------------------------------- 6. verify
log "Verifying"
set -a; . "$ENV_FILE"; set +a
fail=0
[ -d "$DATA_ROOT" ] && echo "ok   data root: $DATA_ROOT" || { warn "data root not found: $DATA_ROOT"; fail=1; }
prices=$(ls "$PRICES_DIR"/*.csv 2>/dev/null | wc -l | tr -d ' ')
[ "$prices" = "50" ] && echo "ok   50 price files" || { warn "expected 50 price files, found $prices"; fail=1; }
"$VENV_DIR/bin/python" - <<'EOF' || fail=1
import importlib
for m in ("duckdb", "pandas", "mcp", "ollama", "langgraph", "streamlit", "plotly"):
    importlib.import_module(m)
print("ok   python packages import")
EOF
ollama list 2>/dev/null || warn "Could not list Ollama models."
[ -n "${ARPM_ADMIN_PASSWORD:-}" ] || warn "ARPM_ADMIN_PASSWORD is empty in $ENV_FILE."

# Secrets must not be on the VM unless you really need the downloader there.
[ ! -f "$DATA_ROOT/screener_auth.json" ] || warn "screener_auth.json is on this VM. Remove it unless you run the downloader here."
[ ! -d "$DATA_ROOT/secret" ] || warn "secret/ is on this VM. Remove it."

chmod +x "$ROOT"/bin/*.sh

cat <<EOF

Setup finished$( [ "$fail" -eq 0 ] || echo " with problems (see warnings above)" ).

Start:      $ROOT/bin/start_all.sh      (stop: bin/stop_all.sh, check: bin/status.sh)
Streamlit:  keep it on localhost and reach it with an SSH tunnel:
            ssh -L 8502:localhost:8502 <user>@<host>
Do not open port 8502 or 11434 to the internet in the security group.
EOF
exit "$fail"
