"""
flash_and_deploy_rp2040.py - Automated MicroPython firmware flasher & file deployer for RP2040.

Purpose & Workflow:
  Automates the complete onboarding and deployment process for a brand-new or existing
  RP2040 board (such as the Waveshare RP2040-Zero or Raspberry Pi Pico):

  1. BOOTSEL Detection & Firmware Flashing:
     - Checks if an `RPI-RP2` USB mass storage drive is mounted (indicating the board is
       in ROM UF2 bootloader / BOOTSEL mode and does not yet expose a COM port).
     - Automatically queries micropython.org for the latest release `.uf2` firmware for the
       selected board (`WAVESHARE_RP2040_ZERO` by default, or `RPI_PICO`), downloads it,
       and copies it to the `RPI-RP2` drive.
     - Waits for the microcontroller to reboot and enumerate as a USB CDC Serial port.

  2. Port Auto-Discovery:
     - Automatically scans active COM ports for RP2040 hardware Vendor IDs (0x2E8A, 0x239A, 0x1B4F)
       or allows an explicit `--port COMx` override.

  3. File Deployment (`mpremote`):
     - Uploads `rp2040/boot.py`, `rp2040/code.py`, and `rp2040/main.py` to the root filesystem
       of the board via `mpremote`.
     - Lists the remote filesystem contents to confirm integrity and performs a soft reset.

  4. Live Serial Verification:
     - Opens the COM port at 115200 baud, sends a test ping, and verifies the board's response.
"""

import argparse
import ctypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# Board firmware slugs on https://micropython.org/download/<BOARD>/
BOARD_SLUGS = {
    "rp2040-zero": "WAVESHARE_RP2040_ZERO",
    "pico": "RPI_PICO",
    "pico-w": "RPI_PICO_W",
    "pico2": "RPI_PICO2",
}

# Fallback release URL if live HTML scraping fails or offline cache is needed
FALLBACK_UF2_URLS = {
    "WAVESHARE_RP2040_ZERO": "https://micropython.org/resources/firmware/WAVESHARE_RP2040_ZERO-20260824-v1.29.0.uf2",
    "RPI_PICO": "https://micropython.org/resources/firmware/RPI_PICO-20260824-v1.29.0.uf2",
}

KNOWN_MICROCONTROLLER_VIDS = {
    0x2E8A,  # Raspberry Pi Foundation (RP2040-Zero, Pico, MicroPython CDC)
    0x239A,  # Adafruit
    0x1B4F,  # SparkFun
}


def find_bootsel_drive() -> Optional[str]:
    """
    Scans mounted Windows logical drives for a volume labeled 'RPI-RP2'
    containing 'INFO_UF2.TXT'.

    Returns:
        str or None: Root drive path (e.g., 'I:\\') if found, else None.
    """
    if sys.platform != "win32":
        return None

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            drive = f"{chr(65 + i)}:\\"
            # DRIVE_REMOVABLE is 2
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
            if drive_type == 2 or os.path.exists(os.path.join(drive, "INFO_UF2.TXT")):
                vol_buf = ctypes.create_unicode_buffer(261)
                ctypes.windll.kernel32.GetVolumeInformationW(
                    drive, vol_buf, ctypes.sizeof(vol_buf),
                    None, None, None, None, 0
                )
                if vol_buf.value.upper() == "RPI-RP2" or os.path.exists(os.path.join(drive, "INFO_UF2.TXT")):
                    return drive
    return None


def resolve_latest_uf2_url(board_slug: str) -> str:
    """
    Queries micropython.org/download/<board_slug>/ to find the latest stable .uf2 release link.
    Falls back to a known working release URL if parsing fails.
    """
    page_url = f"https://micropython.org/download/{board_slug}/"
    try:
        req = urllib.request.Request(page_url, headers={"User-Agent": "USBCommunicator-Deployer/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # Match stable release UF2 links (excluding '-preview')
        matches = re.findall(rf'href="(/resources/firmware/{re.escape(board_slug)}-[0-9]+-v[0-9.]+\.uf2)"', html)
        if matches:
            return f"https://micropython.org{matches[0]}"
    except Exception as exc:
        print(f"[!] Warning: Could not query latest firmware index ({exc}). Using fallback URL.")

    if board_slug in FALLBACK_UF2_URLS:
        return FALLBACK_UF2_URLS[board_slug]
    raise RuntimeError(f"Could not determine UF2 firmware URL for board '{board_slug}'.")


def download_and_flash_uf2(bootsel_drive: str, board_key: str, custom_uf2: Optional[str] = None) -> None:
    """
    Downloads (or uses a local) MicroPython .uf2 firmware image and copies it to the RPI-RP2 drive.
    """
    info_path = os.path.join(bootsel_drive, "INFO_UF2.TXT")
    if os.path.exists(info_path):
        with open(info_path, "r", encoding="utf-8", errors="ignore") as f:
            info_text = f.read().strip().replace("\r\n", " | ").replace("\n", " | ")
            print(f"[*] Detected UF2 Bootloader on {bootsel_drive} ({info_text})")
    else:
        print(f"[*] Detected RPI-RP2 drive at {bootsel_drive}")

    if custom_uf2:
        uf2_path = os.path.abspath(custom_uf2)
        if not os.path.exists(uf2_path):
            raise FileNotFoundError(f"Custom UF2 file not found: {uf2_path}")
        print(f"[*] Using local UF2 file: {uf2_path}")
    else:
        board_slug = BOARD_SLUGS.get(board_key, board_key)
        uf2_url = resolve_latest_uf2_url(board_slug)
        filename = os.path.basename(uf2_url)
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "firmware")
        os.makedirs(cache_dir, exist_ok=True)
        uf2_path = os.path.join(cache_dir, filename)

        if os.path.exists(uf2_path) and os.path.getsize(uf2_path) > 100_000:
            print(f"[*] Using cached firmware: {uf2_path}")
        else:
            print(f"[*] Downloading MicroPython firmware from:\n    {uf2_url}")
            urllib.request.urlretrieve(uf2_url, uf2_path)
            print(f"[+] Downloaded {os.path.getsize(uf2_path):,} bytes -> {uf2_path}")

    dest_file = os.path.join(bootsel_drive, os.path.basename(uf2_path))
    print(f"[*] Flashing firmware to {dest_file} ...")
    shutil.copyfile(uf2_path, dest_file)
    print("[+] Firmware copied! Waiting for RP2040 to reboot and enumerate USB Serial port...")


def detect_rp2040_com_port(preferred_port: Optional[str] = None, timeout: float = 15.0) -> Optional[str]:
    """
    Polls active serial ports until an RP2040 USB CDC device appears or timeout expires.
    """
    if not SERIAL_AVAILABLE:
        return preferred_port if (preferred_port and preferred_port.lower() != "auto") else None

    deadline = time.time() + timeout
    while time.time() <= deadline:
        ports = list(serial.tools.list_ports.comports())

        if preferred_port and preferred_port.lower() != "auto":
            for p in ports:
                if p.device.upper() == preferred_port.upper():
                    return p.device

        for p in ports:
            if p.vid in KNOWN_MICROCONTROLLER_VIDS:
                return p.device

        for p in ports:
            desc = f"{p.description} {p.hwid} {p.manufacturer or ''} {p.product or ''}".lower()
            if "u-blox" in desc or "bluetooth" in desc:
                continue
            if any(k in desc for k in ("micropython", "rp2040", "pico")):
                return p.device

        time.sleep(0.5)

    return None


def get_mpremote_cmd() -> str:
    """Locates the mpremote executable in .venv or system PATH."""
    root = os.path.dirname(os.path.abspath(__file__))
    venv_exe = os.path.join(root, ".venv", "Scripts", "mpremote.exe")
    if os.path.exists(venv_exe):
        return venv_exe
    return "mpremote"


def deploy_files(port: str) -> None:
    """
    Uploads rp2040/boot.py, rp2040/code.py, and rp2040/main.py using mpremote and resets the board.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    mpremote = get_mpremote_cmd()
    files_to_copy = ["boot.py", "code.py", "main.py"]

    print(f"[*] Deploying rp2040/ application scripts to {port} via mpremote...")
    for fname in files_to_copy:
        src = os.path.join(root, "rp2040", fname)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Missing source file: {src}")
        cmd = [mpremote, "connect", port, "cp", src, f":{fname}"]
        res = subprocess.run(cmd, cwd=root)
        if res.returncode != 0:
            raise RuntimeError(f"mpremote failed copying {fname} to {port} (exit code {res.returncode})")

    print(f"[*] Verifying remote filesystem on {port}:")
    subprocess.run([mpremote, "connect", port, "fs", "ls"], cwd=root, check=True)

    print(f"[*] Performing soft reset on {port}...")
    subprocess.run([mpremote, "connect", port, "reset"], cwd=root, check=True)


def verify_serial_ping(port: str, baudrate: int = 115200) -> bool:
    """
    Opens the serial port, sends a test 'ping' command, and validates the RP2040 response.
    """
    if not SERIAL_AVAILABLE:
        print("[!] pyserial not available; skipping live serial ping verification.")
        return True

    print(f"[*] Verifying live serial communication on {port} @ {baudrate} baud...")
    time.sleep(1.0)  # Allow board to finish rebooting into main.py -> code.py
    try:
        with serial.Serial(port, baudrate, timeout=2.5) as ser:
            ser.reset_input_buffer()
            ser.write(b"ping\n")
            ser.flush()
            reply = ser.readline().decode("utf-8", errors="replace").strip()
            if reply:
                print(f"[+] Device Response < {reply}")
                return True
            else:
                print("[!] No response received within timeout.")
                return False
    except Exception as exc:
        print(f"[!] Serial verification error on {port}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automated MicroPython UF2 Flasher & Script Deployer for RP2040."
    )
    parser.add_argument(
        "-p", "--port",
        default="auto",
        help="Target COM port (e.g., COM3, COM4) or 'auto' for automatic USB VID/PID discovery (default: auto).",
    )
    parser.add_argument(
        "-b", "--board",
        default="rp2040-zero",
        choices=list(BOARD_SLUGS.keys()),
        help="Target RP2040 board model when downloading MicroPython UF2 firmware (default: rp2040-zero).",
    )
    parser.add_argument(
        "--uf2",
        default=None,
        help="Optional path to a local .uf2 firmware file to flash instead of downloading.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip live serial ping test after deploying files.",
    )
    args = parser.parse_args()

    print("=" * 68)
    print(" RP2040 MicroPython Firmware Flasher & Application Deployer")
    print("=" * 68)

    # Step 1: Check if board is in BOOTSEL mode (mounted as RPI-RP2 drive)
    bootsel_drive = find_bootsel_drive()
    if bootsel_drive:
        try:
            download_and_flash_uf2(bootsel_drive, args.board, args.uf2)
        except Exception as exc:
            print(f"[ERROR] Firmware flashing failed: {exc}")
            return 1
        # Wait briefly for Windows to unmount the drive and enumerate the USB CDC port
        time.sleep(3.0)
    else:
        print("[*] No RPI-RP2 BOOTSEL drive detected; assuming MicroPython is already flashed.")

    # Step 2: Discover the RP2040 COM port
    port = detect_rp2040_com_port(preferred_port=args.port, timeout=15.0)
    if not port:
        print(
            "\n[ERROR] Could not find an active RP2040 COM port nor an RPI-RP2 BOOTSEL drive.\n"
            "  - Ensure your USB-C cable supports data transfer (not a charge-only cable).\n"
            "  - If the board is brand new or unresponsive, hold BOOTSEL while plugging it in."
        )
        return 1

    print(f"[+] Connected RP2040 detected on port: {port}")

    # Step 3: Upload rp2040/{boot.py, code.py, main.py} and reset
    try:
        deploy_files(port)
    except Exception as exc:
        print(f"[ERROR] File deployment failed: {exc}")
        return 1

    # Step 4: Verify live serial communication
    if not args.skip_verify:
        verify_serial_ping(port)

    print("\n[+] RP2040 provisioning and deployment complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
