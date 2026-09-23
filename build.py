"""
build.py — run this once to produce dist/UPC_LP_Tool.exe
Usage:  python build.py
"""
import os
import subprocess
import sys

# Locate PyInstaller next to this Python installation
pyinstaller = os.path.join(
    os.path.dirname(sys.executable), "Scripts", "pyinstaller.exe"
)
if not os.path.exists(pyinstaller):
    # fallback — let PATH find it
    pyinstaller = "pyinstaller"

# Folders / files that must be bundled inside the .exe
added_data = [
    ("templates", "templates"),
    ("static",    "static"),
]

# Build the --add-data flags  (separator is ; on Windows, : on Mac/Linux)
sep = ";" if sys.platform == "win32" else ":"
data_flags = []
for src, dst in added_data:
    data_flags += ["--add-data", f"{src}{sep}{dst}"]

cmd = [
    pyinstaller,
    "--noconfirm",          # overwrite previous build without asking
    "--onefile",            # single .exe
    "--console",            # show console window (so user sees status)
    "--name", "UPC_LP_Tool",
    *data_flags,
    "launcher.py",
]

print("Building UPC_LP_Tool.exe …")
print(" ".join(cmd))
result = subprocess.run(cmd)

if result.returncode == 0:
    exe = os.path.join("dist", "UPC_LP_Tool.exe")
    print("\nBuild complete!")
    print(f"    Executable: {os.path.abspath(exe)}")
    print("\nShare 'dist/UPC_LP_Tool.exe' with your colleagues.")
    print("They just double-click it -- no Python required.")
else:
    print("\nBuild failed. Check the output above.")
    sys.exit(1)
