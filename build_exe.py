"""
build_exe.py - Standalone executable builder for TeamsMonitor using PyInstaller.

Usage:
    python build_exe.py              # Builds windowless (no console) TeamsMonitor.exe
    python build_exe.py --console    # Builds with console enabled for debugging
"""

import argparse
import os
import shutil
import subprocess
import sys


def find_pyinstaller() -> str:
    """Finds pyinstaller executable inside the virtual environment or system PATH."""
    root = os.path.dirname(os.path.abspath(__file__))
    venv_pyinstaller = os.path.join(root, ".venv", "Scripts", "pyinstaller.exe")
    if os.path.exists(venv_pyinstaller):
        return venv_pyinstaller
    return "pyinstaller"


def main():
    parser = argparse.ArgumentParser(description="Build standalone TeamsMonitor.exe via PyInstaller")
    parser.add_argument(
        "--console",
        action="store_true",
        help="Build with visible console window (default is --noconsole for silent background execution)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=True,
        help="Clean PyInstaller cache and remove temporary build directory before building",
    )
    args = parser.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    entry_script = os.path.join(root, "host", "teams_monitor.py")
    dist_dir = os.path.join(root, "dist")
    build_dir = os.path.join(root, "build")

    if not os.path.exists(entry_script):
        print(f"Error: Entry script not found at {entry_script}")
        sys.exit(1)

    pyinstaller_exe = find_pyinstaller()
    print("=" * 65)
    print("         Building Standalone TeamsMonitor.exe")
    print("=" * 65)
    print(f"PyInstaller : {pyinstaller_exe}")
    print(f"Entry Script: {entry_script}")
    print(f"Mode        : {'Console (Debug)' if args.console else 'No-Console / Silent (Background Startup)'}")
    print(f"Output Dir  : {dist_dir}")
    print("-" * 65)

    cmd = [
        pyinstaller_exe,
        "--name", "TeamsMonitor",
        "--onefile",
        "--paths", os.path.join(root, "host"),
        "--distpath", dist_dir,
        "--workpath", build_dir,
        "--specpath", root,
    ]

    if args.clean:
        cmd.append("--clean")

    if args.console:
        cmd.append("--console")
    else:
        cmd.append("--noconsole")

    cmd.append(entry_script)

    print(f"Executing: {' '.join(cmd)}\n")
    ret = subprocess.call(cmd)

    if ret == 0:
        exe_path = os.path.join(dist_dir, "TeamsMonitor.exe")
        size_mb = os.path.getsize(exe_path) / (1024 * 1024) if os.path.exists(exe_path) else 0
        print("\n" + "=" * 65)
        print("                BUILD SUCCESSFUL!")
        print("=" * 65)
        print(f"Executable : {exe_path}")
        print(f"Size       : {size_mb:.2f} MB")
        print("\nQuick Start Commands:")
        print("  1. Run monitor in background on Windows Startup:")
        print(f'     dist\\TeamsMonitor.exe --install-startup')
        print("  2. Check startup status:")
        print(f'     dist\\TeamsMonitor.exe --startup-status')
        print("  3. Disable startup:")
        print(f'     dist\\TeamsMonitor.exe --uninstall-startup')
        print("=" * 65)
    else:
        print("\n[ERROR] Build failed. See above output for error details.")
        sys.exit(ret)


if __name__ == "__main__":
    main()
