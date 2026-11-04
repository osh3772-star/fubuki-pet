#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -n "${FUBUKI_PYTHON:-}" ]; then
    PYTHON="$FUBUKI_PYTHON"
elif [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
elif python3 -c 'import PySide6' >/dev/null 2>&1 || python3 -c 'import PyQt5' >/dev/null 2>&1; then
    PYTHON=python3
elif /usr/bin/python3 -c 'import PyQt5' >/dev/null 2>&1; then
    PYTHON=/usr/bin/python3
else
    echo 'Install requirements.txt in a Python environment or set FUBUKI_PYTHON.' >&2
    exit 1
fi
exec "$PYTHON" launcher.py "$@"
