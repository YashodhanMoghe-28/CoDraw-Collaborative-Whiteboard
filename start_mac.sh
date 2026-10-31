#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "First run: bash setup_mac.sh"
    exit 1
fi

echo "Connect all laptops to the same Wi-Fi."
echo "Find your Mac's IP in System Settings > Network > Wi-Fi > Details > TCP/IP."
echo "Use a unique node ID on each laptop."

exec .venv/bin/python -u lan.py "$@"