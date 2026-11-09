#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="N2Elite-ng"
APP_BUNDLE="$ROOT_DIR/dist/macos/$APP_NAME.app"
MODE="${1:-run}"
case "$MODE" in
    run|--debug|--logs|--telemetry|--verify) ;;
    *) echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2; exit 2 ;;
esac

pkill -x "$APP_NAME" >/dev/null 2>&1 || true
"$ROOT_DIR/tools/build_macos.sh"
case "$MODE" in
    --debug) exec lldb -- "$APP_BUNDLE/Contents/MacOS/$APP_NAME" ;;
    --logs|--telemetry)
        /usr/bin/open -n "$APP_BUNDLE"
        exec /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
        ;;
    --verify)
        /usr/bin/open -n "$APP_BUNDLE"
        sleep 3
        pgrep -x "$APP_NAME" >/dev/null
        echo "$APP_NAME is running."
        ;;
    run) /usr/bin/open -n "$APP_BUNDLE" ;;
esac
