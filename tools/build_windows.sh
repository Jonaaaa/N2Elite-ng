#!/usr/bin/env bash
# Build a standalone Windows n2elite-ng.exe from Linux using 64-bit Wine + a
# portable standalone Windows Python (astral-sh/python-build-standalone).
#
# This needs NO 32-bit Wine libraries and makes NO host system changes — it just
# downloads a self-contained Windows Python (with tkinter) into build/ and runs
# PyInstaller through Wine. Verified working; produces dist/windows/n2elite-ng.exe.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v wine >/dev/null 2>&1 || { echo "ERROR: wine (64-bit) is required."; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required."; exit 1; }

PYVER="${WINPY_VERSION:-3.12.13}"
PBS_TAG="${WINPY_TAG:-20260623}"
WORK="build/winpy"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PYVER}+${PBS_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz"

export WINEDEBUG=-all WINEARCH=win64 WINEPREFIX="$PWD/$WORK/wineprefix"

if [ ! -x "$WORK/python/python.exe" ]; then
    echo "Fetching portable Windows Python $PYVER…"
    mkdir -p "$WORK"
    curl -L --fail --max-time 300 "$PY_URL" -o "$WORK/winpy.tar.gz"
    tar xzf "$WORK/winpy.tar.gz" -C "$WORK"
    wineboot -i >/dev/null 2>&1 || true
fi

WPY="$WORK/python/python.exe"
echo "Wine Python: $(wine "$WPY" --version 2>&1)"
wine "$WPY" -m pip install -q -U pip pyinstaller pyserial pycryptodome
wine "$WPY" -m PyInstaller --noconfirm --clean \
    --distpath dist/windows --workpath build/windows-pyi n2elite.spec
echo "Built: dist/windows/n2elite-ng.exe"
