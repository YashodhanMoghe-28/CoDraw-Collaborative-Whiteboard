#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Install Python 3.11 or newer, then run this script again."
    exit 1
fi

python3 -c '
import sys
if sys.version_info < (3, 11):
    sys.exit("Python 3.11 or newer is required.")
'

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "Setup complete. Run: bash start_mac.sh"