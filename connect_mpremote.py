"""
connect_mpremote.py - Helper script to launch mpremote targeting the connected RP2040.

This script acts as a convenience wrapper around the `mpremote` command-line tool
(MicroPython Remote Control). It automatically locates the virtual environment's
mpremote executable (or falls back to the system PATH) and auto-discovers the active
RP2040 COM port via USB Vendor ID (falling back to COM4) if no explicit connection
target is specified in the arguments.

Usage Examples:
    python connect_mpremote.py repl             -> runs: mpremote connect <AUTO_PORT> repl
    python connect_mpremote.py fs ls            -> runs: mpremote connect <AUTO_PORT> fs ls
    python connect_mpremote.py connect COM5 repl -> runs: mpremote connect COM5 repl
"""

import os
import sys
import subprocess


def detect_rp2040_port(default_port: str = "COM4") -> str:
    """
    Auto-discovers the COM port of a connected RP2040 / MicroPython device
    by matching known USB Vendor IDs (0x2E8A Raspberry Pi, 0x239A Adafruit, 0x1B4F SparkFun).
    Falls back to `default_port` if pyserial is unavailable or no matching VID is found.
    """
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            if p.vid in (0x2E8A, 0x239A, 0x1B4F):
                return p.device
        for p in ports:
            desc = f"{p.description} {p.hwid}".lower()
            if "u-blox" not in desc and any(k in desc for k in ("micropython", "rp2040", "pico")):
                return p.device
    except Exception:
        pass
    return default_port


def main():
    """
    Locates mpremote, injects auto-detected connection parameters if omitted,
    and forwards all command-line arguments to the subprocess.
    """
    # Determine the project root directory where .venv is expected to reside
    root = os.path.dirname(os.path.abspath(__file__))

    # Look for mpremote inside the local virtual environment on Windows
    mpremote_exe = os.path.join(root, ".venv", "Scripts", "mpremote.exe")

    # Fallback to system-wide executable if virtual environment binary is not present
    if not os.path.exists(mpremote_exe):
        mpremote_exe = "mpremote"

    # Extract user-supplied CLI arguments (excluding the script name itself)
    args = sys.argv[1:]

    # Check if the user already provided an explicit 'connect' sub-command
    has_connect = any(a == "connect" for a in args)

    # If 'connect' was not specified, auto-detect the RP2040 COM port (fallback COM4)
    if not has_connect:
        target_port = detect_rp2040_port("COM4")
        cmd = [mpremote_exe, "connect", target_port] + args
    else:
        cmd = [mpremote_exe] + args

    # Execute the command and exit with the return code of the child process
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()


