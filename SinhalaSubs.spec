# PyInstaller recipe for SinhalaSubs.exe
# Build:  .venv\Scripts\pyinstaller SinhalaSubs.spec --noconfirm
# Result: dist\SinhalaSubs\SinhalaSubs.exe  (a folder app: starts fast, no unpacking each run)

import re

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

__version__ = re.search(r'__version__ = "([^"]+)"', open("sinhalasubs/__init__.py", encoding="utf-8").read()).group(1)

datas = [("sinhalasubs/data", "sinhalasubs/data")]
datas += collect_data_files("imageio_ffmpeg", includes=["binaries/*"])      # ffmpeg.exe
datas += collect_data_files("faster_whisper")                               # voice-activity model
binaries = collect_dynamic_libs("ctranslate2")                              # Whisper's engine DLLs
hiddenimports = collect_submodules("google.genai") + ["sinhalasubs.ui.about_dialog"]

# Windows "Details" tab of the .exe
version_file = "build/version_info.txt"
v = tuple(int(x) for x in __version__.split(".")) + (0,)
import os
os.makedirs("build", exist_ok=True)
with open(version_file, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'SinhalaSubs – captions for CapCut'),
      StringStruct('ProductName', 'SinhalaSubs'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('ProductVersion', '{__version__}'),
      StringStruct('OriginalFilename', 'SinhalaSubs.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""")

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "_pytest", "IPython", "matplotlib", "PySide6.QtTest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SinhalaSubs",
    icon="sinhalasubs/data/icon.ico",
    version=version_file,
    console=False,            # a window app: no black console box
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SinhalaSubs", upx=False)
