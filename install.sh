#!/usr/bin/env bash
# OpenChimera one-liner install script (Linux/macOS)
set -e

# Check for Python 3.9+
if ! command -v python3 >/dev/null; then
  echo "Python 3 is required. Please install Python 3.9 or newer."; exit 1
fi
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [[ "$PYVER" < "3.9" ]]; then
  echo "Python 3.9+ required. Found $PYVER"; exit 1
fi

# Create venv if not exists
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install requirements
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
else
  echo "requirements.txt not found!"; exit 1
fi

# Post-install message
cat <<EOF

OpenChimera install complete!
To activate your environment:
  source .venv/bin/activate
To run OpenChimera:
  python run.py

For onboarding, run:
  python run.py onboard

EOF
