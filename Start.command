#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "Install Python 3.11 or newer from https://www.python.org/downloads/macos/ and reopen this file."
    exit 1
fi
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
if ! cmp -s requirements.txt .venv/brickprint-requirements.txt; then
    .venv/bin/python -m pip install -r requirements.txt
    cp requirements.txt .venv/brickprint-requirements.txt
fi
exec .venv/bin/python -m brickprint "$@"
