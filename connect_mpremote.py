# Helper script to run mpremote targeting COM4 by default
import os
import sys
import subprocess

def main():
    root = os.path.dirname(os.path.abspath(__file__))
    mpremote_exe = os.path.join(root, ".venv", "Scripts", "mpremote.exe")
    if not os.path.exists(mpremote_exe):
        mpremote_exe = "mpremote"

    args = sys.argv[1:]
    has_connect = any(a == "connect" for a in args)

    if not has_connect:
        cmd = [mpremote_exe, "connect", "COM4"] + args
    else:
        cmd = [mpremote_exe] + args

    sys.exit(subprocess.call(cmd))

if __name__ == "__main__":
    main()
