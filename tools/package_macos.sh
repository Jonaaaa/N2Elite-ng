#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ARCH="$(uname -m)"
NAME="N2Elite-ng-macOS-$ARCH"
STAGE="build/macos/package/$NAME"
APP="dist/macos/N2Elite-ng.app"
CLI="dist/macos/n2elite-ng-cli"

codesign --verify --deep --strict "$APP"
codesign --verify --strict "$CLI"
file "$APP/Contents/MacOS/N2Elite-ng" | grep -q "$ARCH"
file "$CLI" | grep -q "$ARCH"

rm -rf "$STAGE"
mkdir -p "$STAGE" dist/releases
ditto "$APP" "$STAGE/N2Elite-ng.app"
cp "$CLI" "$STAGE/n2elite-ng-cli"
cp docs/macos-README.txt "$STAGE/README.txt"
cp LICENSE THIRD_PARTY_NOTICES.md "$STAGE/"
ditto "$APP/Contents/Resources/licenses" "$STAGE/licenses"
git rev-parse HEAD > "$STAGE/SOURCE-COMMIT.txt"
codesign --verify --deep --strict "$STAGE/N2Elite-ng.app"

ditto -c -k --sequesterRsrc --keepParent "$STAGE" "dist/releases/$NAME.zip"
(
    cd dist/releases
    shasum -a 256 "$NAME.zip" > "$NAME.sha256"
)
echo "Packaged: $ROOT_DIR/dist/releases/$NAME.zip"
