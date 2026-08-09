#!/bin/bash
# OpenChimera v2 — One-Liner Bash Install
# Usage: curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v1/main/install.sh | bash

set -e

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "🐉 OpenChimera v2 Installer"
echo -e "${NC}"

# ── Check prerequisites ──
echo -e "${CYAN}→${NC} Checking prerequisites..."

if ! command -v git &> /dev/null; then
    echo -e "${RED}✗ Git not found. Install git first.${NC}"
    exit 1
fi

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}✗ Python not found. Install Python 3.11+ first.${NC}"
    exit 1
fi

PY_VERSION=$($PYTHON_CMD --version 2>&1)
echo -e "${GREEN}✓${NC} $PY_VERSION"

# ── Clone repo ──
INSTALL_DIR="$HOME/OpenChimera"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${CYAN}→${NC} Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull origin main --quiet
else
    echo -e "${CYAN}→${NC} Cloning OpenChimera to $INSTALL_DIR..."
    git clone https://github.com/fernandogarzaaa/OpenChimera_v1.git "$INSTALL_DIR" --quiet
    cd "$INSTALL_DIR"
fi

# ── Install Python deps ──
echo -e "${CYAN}→${NC} Installing Python dependencies (this may take 2-5 minutes)..."
if ! $PYTHON_CMD -m pip install -e ".[all]" --quiet 2>/dev/null; then
    echo -e "${YELLOW}⚠${NC} Full install failed, trying core only..."
    $PYTHON_CMD -m pip install -e "." --quiet
fi
echo -e "${GREEN}✓${NC} Python dependencies installed"

# ── Check Rust ──
if command -v cargo &> /dev/null; then
    echo -e "${CYAN}→${NC} Building Rust TUI..."
    cd "$INSTALL_DIR/crates/chimera-tui"
    if cargo build --release 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Rust TUI built"
    else
        echo -e "${YELLOW}⚠${NC} Rust TUI build failed"
    fi
    cd "$INSTALL_DIR"
else
    echo -e "${YELLOW}⚠${NC} Rust not found — TUI unavailable. Install from https://rustup.rs"
fi

# ── Create local config ──
if [ ! -f "$INSTALL_DIR/config/local.yaml" ]; then
    cat > "$INSTALL_DIR/config/local.yaml" << 'EOF'
# Local overrides — add your API keys here or use env vars
providers:
  openai:
    enabled: true
  anthropic:
    enabled: true
  groq:
    enabled: true
EOF
fi

# ── PATH setup ──
BIN_DIR="$INSTALL_DIR/venv/bin"
if [ -d "$BIN_DIR" ]; then
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        SHELL_CONFIG=""
        if [ -n "$ZSH_VERSION" ]; then
            SHELL_CONFIG="$HOME/.zshrc"
        elif [ -n "$BASH_VERSION" ]; then
            SHELL_CONFIG="$HOME/.bashrc"
        fi
        if [ -n "$SHELL_CONFIG" ]; then
            echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$SHELL_CONFIG"
            echo -e "${GREEN}✓${NC} Added to PATH in $SHELL_CONFIG"
        fi
    fi
fi

# ── Done ──
echo ""
echo -e "${GREEN}✅ OpenChimera v2 installed!${NC}"
echo ""
echo "Next steps:"
echo -e "  ${CYAN}openchimera onboard${NC}      # Run setup wizard"
echo -e "  ${CYAN}openchimera doctor${NC}       # Run diagnostics"
echo -e "  ${CYAN}openchimera serve${NC}        # Start API server"
echo -e "  ${CYAN}openchimera tui${NC}          # Launch Rust TUI"
echo -e "  ${CYAN}openchimera ask 'hello'${NC}  # One-off query"
echo ""

read -p "Run onboarding now? [Y/n] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    $PYTHON_CMD -m openchimera onboard
fi
