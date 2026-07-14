#!/usr/bin/env python3
"""Unified entry point for the packaged app.

No arguments -> launch the GUI (double-click friendly).
With arguments -> run the CLI.
"""
import sys


def main() -> int:
    if len(sys.argv) <= 1:
        from n2elite.gui import main as gui_main
        return gui_main()
    from n2elite.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
