"""
connect_mpremote.py - Helper script to launch mpremote targeting COM4 by default.

This script acts as a convenience wrapper around the `mpremote` command-line tool
(MicroPython Remote Control). It automatically locates the virtual environment's
mpremote executable (or falls back to the system PATH) and injects `connect COM4`
if no explicit connection target is specified in the arguments.

Usage Examples:
    python connect_mpremote.py repl             -> runs: mpremote connect COM4 repl
    python connect_mpremote.py fs ls            -> runs: mpremote connect COM4 fs ls
    python connect_mpremote.py connect COM5 repl -> runs: mpremote connect COM5 repl
"""

import os
import sys
import subprocess


def main():
    """
    Locates mpremote, injects default connection parameters if omitted,
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

    # If 'connect' was not specified, default to connecting over COM4
    if not has_connect:
        cmd = [mpremote_exe, "connect", "COM4"] + args
    else:
        cmd = [mpremote_exe] + args

    # Execute the command and exit with the return code of the child process
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()

