# -*- mode: python ; coding: utf-8 -*-
"""Native macOS app bundle plus a standalone terminal CLI."""
from importlib.metadata import distribution
from pathlib import Path
import sysconfig

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

hidden = collect_submodules("Crypto") + collect_submodules("serial")
datas = [
    ("n2elite/amiibo/amiibo_db.json", "n2elite/amiibo"),
    ("n2elite/assets/icon.png", "n2elite/assets"),
    ("LICENSE", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
    ("tools/macos-licenses", "licenses"),
    (str(Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"), "licenses/CPython"),
]
datas += copy_metadata("pyserial") + copy_metadata("pycryptodome")
for package in ("pycryptodome", "PyInstaller"):
    metadata = distribution(package)
    for file in metadata.files or []:
        if ".dist-info/licenses/" in str(file):
            relative = str(file).split(".dist-info/licenses/", 1)[1]
            datas.append((str(metadata.locate_file(file)), str(Path("licenses") / package / Path(relative).parent)))
excludes = ["numpy", "pandas", "matplotlib", "PIL", "pytest"]

gui_a = Analysis(
    ["run_gui.py"], pathex=["."], datas=datas, hiddenimports=hidden,
    excludes=excludes, noarchive=False,
)
gui_pyz = PYZ(gui_a.pure)
gui_exe = EXE(
    gui_pyz, gui_a.scripts, [], exclude_binaries=True,
    name="N2Elite-ng", console=False, debug=False, strip=False, upx=False,
)
gui_collect = COLLECT(
    gui_exe, gui_a.binaries, gui_a.datas,
    name="N2Elite-ng", strip=False, upx=False,
)
app = BUNDLE(
    gui_collect, name="N2Elite-ng.app", icon="build/macos/N2Elite-ng.icns",
    bundle_identifier="io.github.jonaaaa.n2elite-ng", version="1.0.0",
    info_plist={
        "CFBundleDisplayName": "N2Elite-ng",
        "CFBundleShortVersionString": "1.0.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
    },
)

cli_a = Analysis(
    ["run_n2elite.py"], pathex=["."], datas=datas, hiddenimports=hidden,
    excludes=excludes, noarchive=False,
)
cli_pyz = PYZ(cli_a.pure)
cli_exe = EXE(
    cli_pyz, cli_a.scripts, cli_a.binaries, cli_a.datas, [],
    name="n2elite-ng-cli", console=True, debug=False, strip=False, upx=False,
)
