# -*- mode: python ; coding: utf-8 -*-
# Builds two single-file native binaries for the current OS:
#   n2elite-ng      -> windowed GUI app (NO console window on Windows), the double-click app
#   n2elite-ng-cli  -> console CLI / dispatcher (for terminals/scripting)
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("Crypto") + collect_submodules("serial")
DATAS = [
    ("n2elite/amiibo/amiibo_db.json", "n2elite/amiibo"),
    ("n2elite/assets/icon.png", "n2elite/assets"),
]
EXCLUDES = ["numpy", "pandas", "matplotlib", "PIL", "pytest"]
ICON = "n2elite/assets/icon.ico"

# --- Windowed GUI app -------------------------------------------------------
gui_a = Analysis(["run_gui.py"], pathex=["."], datas=DATAS, hiddenimports=hidden,
                 excludes=EXCLUDES, noarchive=False)
gui_pyz = PYZ(gui_a.pure)
gui_exe = EXE(
    gui_pyz, gui_a.scripts, gui_a.binaries, gui_a.datas, [],
    name="n2elite-ng", debug=False, strip=False, upx=False,
    console=False,          # no console window when double-clicked
    icon=ICON,
)

# --- Console CLI ------------------------------------------------------------
cli_a = Analysis(["run_n2elite.py"], pathex=["."], datas=DATAS, hiddenimports=hidden,
                 excludes=EXCLUDES, noarchive=False)
cli_pyz = PYZ(cli_a.pure)
cli_exe = EXE(
    cli_pyz, cli_a.scripts, cli_a.binaries, cli_a.datas, [],
    name="n2elite-ng-cli", debug=False, strip=False, upx=False,
    console=True,
    icon=ICON,
)
