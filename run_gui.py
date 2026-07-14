#!/usr/bin/env python3
"""Windowed GUI entry point (no console window on Windows)."""
import sys

from n2elite.gui import main

if __name__ == "__main__":
    sys.exit(main())
