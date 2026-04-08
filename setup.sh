#!/usr/bin/env bash
# OpenChimera — One-command setup for macOS / Linux
# Usage:  bash setup.sh
#
# This script:
#   1. Checks Python is installed (3.11+)
#   2. Creates a virtual environment
#   3. Installs all dependencies
#   4. Bootstraps workspace state
#   5. Runs diagnostics
#   6. Tells you the single command to start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

cat <<'BANNER'

   ___                    ____ _     _
  / _ \ _ __   ___ _ __  / ___| |__ (_)_ __ ___   ___ _ __ __ _
 | | | | '_ \ / _ \ '_ \| |   | '_ \| | '_ ` _ \ / _ \ '__/ _` |
 | |_| | |_) |  __/ | | | |___| | | | | | | | | |  __/ | | (_| |
  \___/| .__/ \___|_| |_|\____|_| |_|_|_| |_| |_|\___|_|  \__,_|
       |_|
                         Setup Wizard

BANNER

# ── Step 1: Check Python ─────────────────────────────────────────────────
echo -e "\033[33m[1/5] Checking Python...\033[0m"

PYTHON_CMD=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        major="${version%%.*}"
        minor="${version##*.}"
        if [ "${major:-0}" -ge 3 ] && [ "${minor:-0}" -ge 11 ]; then
            PYTHON_CMD="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo ""
    echo -e "\033[31m  Python 3.11+ is required but was not found.\033[0m"
    echo -e "\033[31m  Install it from https://www.python.org/downloads/\033[0m"
    echo ""
    exit 1
fi

echo -e "\033[32m  Found $($PYTHON_CMD --version 2>&1)\033[0m"

# ── Step 2: Create virtual environment ───────────────────────────────────
echo -e "\033[33m[2/5] Creating virtual environment...\033[0m"

if [ -f ".venv/bin/python" ]; then
    echo -e "\033[32m  Virtual environment already exists — reusing it\033[0m"
else
    "$PYTHON_CMD" -m venv .venv
    echo -e "\033[32m  Created .venv\033[0m"
fi

# ── Step 3: Install dependencies ─────────────────────────────────────────
echo -e "\033[33m[3/5] Installing dependencies (this may take a minute)...\033[0m"

.venv/bin/pip install --upgrade pip --quiet 2>/dev/null
.venv/bin/pip install -e . --quiet 2>/dev/null || {
    echo -e "\033[31m  Dependency install failed. Re-running with output:\033[0m"
    .venv/bin/pip install -e .
    exit 1
}
echo -e "\033[32m  All dependencies installed\033[0m"

# ── Step 4: Bootstrap workspace ──────────────────────────────────────────
echo -e "\033[33m[4/5] Bootstrapping workspace...\033[0m"

.venv/bin/python -c "
from core.bootstrap import bootstrap_workspace
r = bootstrap_workspace()
print(f'  Created {len(r[\"created_directories\"])} dirs, {len(r[\"created_files\"])} files')
" || echo -e "\033[33m  Bootstrap had issues but the server may still work.\033[0m"
echo -e "\033[32m  Workspace ready\033[0m"

# ── Step 5: Run diagnostics ─────────────────────────────────────────────
echo -e "\033[33m[5/6] Running diagnostics...\033[0m"

if [ -f .venv/bin/openchimera ]; then
    .venv/bin/openchimera doctor 2>&1 | sed 's/^/  /'
else
    .venv/bin/python run.py doctor 2>&1 | sed 's/^/  /'
fi

# ── Step 6: Interactive setup wizard ─────────────────────────────────────
echo ""
echo -e "\033[33m[6/6] Launching interactive setup wizard...\033[0m"
echo ""

.venv/bin/python -c "from core.setup_wizard import run_wizard; run_wizard()" || {
    echo -e "\033[33m  Wizard skipped. Run 'openchimera setup' to configure later.\033[0m"
}

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo -e "\033[32m  Setup complete!\033[0m"
echo ""
echo -e "\033[36m  To start OpenChimera:\033[0m"
echo ""
echo "    source .venv/bin/activate"
echo "    openchimera serve"
echo ""
echo -e "\033[36m  Then open http://127.0.0.1:7870/docs in your browser.\033[0m"
echo ""
