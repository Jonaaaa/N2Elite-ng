#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != Darwin ]]; then
    echo "Build this target on macOS; PyInstaller does not cross-compile." >&2
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    "${PYTHON:-python3.12}" -m venv .venv
fi
.venv/bin/python -c 'import tkinter, _tkinter' || {
    echo "The virtualenv needs Python with Tcl/Tk. Use a Tk-enabled Python 3.12." >&2
    exit 1
}
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-build-macos.txt
.venv/bin/python -m pip install --disable-pip-version-check --no-build-isolation --no-deps -e .

# Convert the project's existing icon using macOS tools.
ICONSET="build/macos/N2Elite-ng.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" n2elite/assets/icon.png \
        --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    retina=$((size * 2))
    sips -z "$retina" "$retina" n2elite/assets/icon.png \
        --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o build/macos/N2Elite-ng.icns
.venv/bin/python -m PyInstaller --noconfirm --clean \
    --distpath dist/macos --workpath build/macos/pyinstaller n2elite-macos.spec

codesign --verify --deep --strict dist/macos/N2Elite-ng.app
echo "Built: $ROOT_DIR/dist/macos/N2Elite-ng.app"
echo "CLI:   $ROOT_DIR/dist/macos/n2elite-ng-cli"
