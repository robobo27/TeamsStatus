"""
host/teams_monitor.py - Standalone Microsoft Teams local status monitor & USB serial dispatcher.

Purpose & Workflow:
  This script acts as the host-side background daemon connecting the local Microsoft
  Teams detection subsystem (`teams_detector.py`) with a physical microcontroller
  (e.g., Raspberry Pi Pico / Waveshare RP2040-Zero) over USB Serial (CDC).

Key Responsibilities:
  1. Initialize the `TeamsDetector` to track presence, mic/camera usage, process status, and workstation locking.
  2. Maintain a persistent USB serial connection to the RP2040 board on COM4 (or custom port).
  3. Poll for state changes and immediately transmit updated JSON telemetry over the serial interface.
  4. Send periodic keep-alive heartbeat frames (default: every 5.0s) so the microcontroller
     knows the host daemon is alive and can synchronize state even if a packet was dropped.
  5. Provide formatted, real-time terminal output with ASCII badges.
  6. Gracefully shut down upon Ctrl+C by sending an 'Offline' event to the board to turn off LEDs.
  7. Support standalone console-only mode (`--standalone` or `--no-serial`) when no hardware is attached.
  8. Manage Windows Startup registration (`--install-startup`, `--uninstall-startup`, `--startup-status`).
"""

import argparse
import io
import json
import os
import sys
import time
from typing import Optional
import winreg

# Graceful optional import of pySerial
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# Import TeamsDetector with fallback for direct vs module execution
try:
    from host.teams_detector import TeamsDetector, TeamsStatusEvent
except ImportError:
    from teams_detector import TeamsDetector, TeamsStatusEvent

# Windows Registry autorun key
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_APP_NAME = "USBCommunicator_TeamsMonitor"


class NullWriter:
    """Fallback stream writer that silently discards output when running without a console."""
    def write(self, text):
        pass
    def flush(self):
        pass


def attach_parent_console_if_available():
    """
    If running as a --noconsole GUI binary from an existing terminal/command prompt,
    attaches standard I/O to the parent console so CLI output is visible.
    When launched by Windows Startup or double-clicked, this silently fails
    leaving the process 100% invisible/windowless.
    """
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            import ctypes
            # ATTACH_PARENT_PROCESS = -1 (0xFFFFFFFF)
            ATTACH_PARENT_PROCESS = -1
            if ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
                sys.stdout = io.TextIOWrapper(
                    open(r"\\.\CONOUT$", "wt", encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                    line_buffering=True,
                )
                sys.stderr = io.TextIOWrapper(
                    open(r"\\.\CONOUT$", "wt", encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                    line_buffering=True,
                )
        except Exception:
            pass


class DualLogger:

    """Tee logger that writes to both the console stream and a persistent log file."""
    def __init__(self, console_stream, file_path: str):
        self.console = console_stream
        self.file = open(file_path, "a", encoding="utf-8", buffering=1)

    def write(self, text):
        if self.console:
            try:
                self.console.write(text)
            except Exception:
                pass
        try:
            self.file.write(text)
        except Exception:
            pass

    def flush(self):
        if self.console:
            try:
                self.console.flush()
            except Exception:
                pass
        try:
            self.file.flush()
        except Exception:
            pass


def get_startup_target_command(extra_args: str = "--port COM4") -> str:
    """
    Constructs the exact command string to register in Windows Startup.
    
    Handles both compiled PyInstaller .exe binaries and raw Python scripts.
    """
    clean_args = f" {extra_args.strip()}" if extra_args.strip() else ""
    if getattr(sys, "frozen", False):
        # Running as compiled PyInstaller standalone .exe
        target_path = sys.executable
        return f'"{target_path}"{clean_args}'
    else:
        # Running as raw Python script in virtual environment or system Python
        # Prefer pythonw.exe if available to run invisibly without a console window
        python_dir = os.path.dirname(sys.executable)
        pythonw_candidate = os.path.join(python_dir, "pythonw.exe")
        python_bin = pythonw_candidate if os.path.exists(pythonw_candidate) else sys.executable

        script_path = os.path.abspath(__file__)
        return f'"{python_bin}" "{script_path}"{clean_args}'


def install_startup(extra_args: str = "--port COM4") -> bool:
    """
    Registers the monitor daemon in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
    """
    cmd = get_startup_target_command(extra_args)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, STARTUP_APP_NAME, 0, winreg.REG_SZ, cmd)
        print("=" * 60)
        print("  Windows Startup Registration: SUCCESS")
        print("=" * 60)
        print(f"App Name : {STARTUP_APP_NAME}")
        print(f"Command  : {cmd}")
        print("\nStatus: The monitor is now registered to start automatically on Windows logon.")
        print("You can view and toggle it anytime in Task Manager -> 'Startup apps' tab.\n")
        return True
    except Exception as e:
        print(f"Error registering Windows startup key: {e}")
        return False


def uninstall_startup() -> bool:
    """
    Removes the monitor daemon from HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, STARTUP_APP_NAME)
        print(f"Successfully removed '{STARTUP_APP_NAME}' from Windows Startup.")
        return True
    except FileNotFoundError:
        print(f"Notice: '{STARTUP_APP_NAME}' is not currently registered in Windows Startup.")
        return True
    except Exception as e:
        print(f"Error removing Windows startup key: {e}")
        return False


def get_startup_status() -> Optional[str]:
    """
    Queries whether the monitor is currently registered in Windows Startup.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, STARTUP_APP_NAME)
            return val
    except FileNotFoundError:
        return None
    except Exception:
        return None


def format_status_badge(status: str) -> str:
    """
    Returns an ASCII-compatible formatted status badge string safe across all Windows console code pages.

    Args:
        status (str): The synthesized status string (e.g., 'Available', 'Busy', 'InACall').

    Returns:
        str: Formatted bracketed badge string (e.g., '[* AVAILABLE]', '[! IN A CALL]').
    """
    symbols = {
        "Available": "[* AVAILABLE]",
        "Busy": "[# BUSY]",
        "InACall": "[! IN A CALL]",
        "DoNotDisturb": "[- DO NOT DISTURB]",
        "Away": "[~ AWAY]",
        "BeRightBack": "[~ BE RIGHT BACK]",
        "Offline": "[. OFFLINE]",
        "NotRunning": "[x NOT RUNNING]",
        "Unknown": "[? UNKNOWN]",
    }
    return symbols.get(status, f"[{status.upper()}]")


def open_serial_connection(port: str, baudrate: int) -> Optional["serial.Serial"]:
    """
    Attempts to establish and configure a serial connection to the RP2040 microcontroller.

    Args:
        port (str): Serial COM port identifier (e.g., 'COM4').
        baudrate (int): Baud rate for UART communication (default: 115200).

    Returns:
        serial.Serial or None: An active serial handle, or None if unavailable/unsupported.
    """
    if not SERIAL_AVAILABLE:
        print("Warning: pyserial is not installed. Running in console-only mode.")
        return None

    try:
        # Open port with 1.0s timeout
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
        # Flush initial buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print(f"Connected to Microcontroller on {port} @ {baudrate} baud.")
        return ser
    except serial.SerialException as e:
        # Fall back to console-only mode if the COM port cannot be opened
        print(f"Notice: Serial port {port} unavailable ({e}). Continuing in console-only mode.")
        return None


def send_serial_event(ser: Optional["serial.Serial"], event: TeamsStatusEvent):
    """
    Serializes a TeamsStatusEvent to JSON and transmits it across the serial link.

    Format:
      `{"type": "teams_status", "status": "...", ...}\n`

    Args:
        ser (serial.Serial, optional): Open serial connection object.
        event (TeamsStatusEvent): Status event object to transmit.
    """
    if ser is None or not ser.is_open:
        return

    # Encode JSON line ending with newline character (\n)
    payload = event.to_json() + "\n"
    try:
        ser.write(payload.encode("utf-8"))
        ser.flush()  # Force byte transmission over USB CDC
    except Exception as e:
        print(f"Serial transmission error: {e}")


def main():
    """
    Main entry point and execution loop for the Teams Monitor daemon.
    
    Parses CLI parameters, handles startup registration, opens serial link (if enabled),
    polls detector, dispatches events, and handles heartbeat intervals.
    """
    # If run as a GUI/windowless binary from a terminal, attach to caller console
    attach_parent_console_if_available()

    parser = argparse.ArgumentParser(
        description="Local Microsoft Teams Status Monitor (Zero Network / Zero Graph API)"
    )
    parser.add_argument(
        "-p",
        "--port",
        default="COM4",
        help="Target USB Serial COM port for RP2040 (default: COM4)",
    )
    parser.add_argument(
        "-b",
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baud rate (default: 115200)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "-H",
        "--heartbeat",
        type=float,
        default=5.0,
        help="Periodic serial heartbeat interval in seconds (default: 5.0, 0 to disable)",
    )
    parser.add_argument(
        "-s",
        "--standalone",
        "--no-serial",
        action="store_true",
        help="Run in standalone console-only mode without opening a serial port",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Custom path to Microsoft Teams logs directory",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="File path to save monitor diagnostic logs (ideal for background execution)",
    )
    # Startup management CLI arguments
    parser.add_argument(
        "--install-startup",
        nargs="?",
        const="--port COM4",
        default=None,
        help="Register this application in Windows Startup (HKCU\\...\\Run) with optional arguments",
    )
    parser.add_argument(
        "--uninstall-startup",
        action="store_true",
        help="Remove this application from Windows Startup (HKCU\\...\\Run)",
    )
    parser.add_argument(
        "--startup-status",
        action="store_true",
        help="Check whether this application is currently configured in Windows Startup",
    )
    args = parser.parse_args()

    # -------------------------------------------------------------
    # Handle Windows Startup Management CLI Commands First
    # -------------------------------------------------------------
    if args.startup_status:
        current = get_startup_status()
        if current:
            print("=" * 60)
            print("  Windows Startup Status: ENABLED")
            print("=" * 60)
            print(f"Registry Key : HKCU\\{STARTUP_REG_KEY}")
            print(f"Entry Name   : {STARTUP_APP_NAME}")
            print(f"Command      : {current}")
        else:
            print("=" * 60)
            print("  Windows Startup Status: DISABLED")
            print("=" * 60)
            print(f"'{STARTUP_APP_NAME}' is not registered in HKCU\\{STARTUP_REG_KEY}.")
            print("To enable auto-start, run with: --install-startup")
        sys.exit(0)

    if args.uninstall_startup:
        uninstall_startup()
        sys.exit(0)

    if args.install_startup is not None:
        install_startup(args.install_startup)
        sys.exit(0)

    # -------------------------------------------------------------
    # Configure stdout/stderr Stream Safety (Headless / pythonw / .exe)
    # -------------------------------------------------------------
    if args.log_file:
        # User specified a log file: tee output to file and console (if available)
        logger = DualLogger(sys.stdout, args.log_file)
        sys.stdout = logger
        sys.stderr = logger
    elif sys.stdout is None:
        # Running under pythonw.exe or PyInstaller --noconsole without explicit log file
        sys.stdout = NullWriter()
        sys.stderr = NullWriter()
    elif sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Display startup configuration banner
    print("=" * 65)
    print("       Local Microsoft Teams Status Monitor (Zero-Network)")
    print("=" * 65)
    print(f"Log Dir       : {args.log_dir or 'Auto-detected (Local MSTeams package)'}")
    print(f"Poll Interval : {args.interval}s")
    print(f"Heartbeat     : {args.heartbeat}s")
    print(f"Serial Target : {'Disabled (Standalone)' if args.standalone else f'{args.port} @ {args.baudrate}'}")
    if args.log_file:
        print(f"Logging To    : {args.log_file}")
    print("-" * 65)

    # Instantiate detector
    detector = TeamsDetector(log_dir=args.log_dir)

    # Establish serial connection if not in standalone mode
    ser: Optional["serial.Serial"] = None
    if not args.standalone:
        ser = open_serial_connection(args.port, args.baudrate)

    last_heartbeat_time = 0.0

    print("\nStarting monitor loop. Press Ctrl+C to exit.\n")

    try:
        while True:
            # Poll detector for any newly detected state changes
            event = detector.poll_for_change()
            now = time.time()

            if event is not None:
                # Format detailed console status line
                badge = format_status_badge(event.status)
                call_info = " [In Call]" if event.in_call else ""
                mic_info = " [Mic Active]" if event.mic_active else ""
                cam_info = " [Cam Active]" if event.camera_active else ""
                lock_info = " [PC Locked]" if event.is_locked else ""

                print(
                    f"[{time.strftime('%H:%M:%S')}] {badge:20} Status: {event.status:12} "
                    f"(Raw: {event.availability}){call_info}{mic_info}{cam_info}{lock_info}",
                    flush=True,
                )

                # Transmit event to RP2040 microcontroller
                send_serial_event(ser, event)
                last_heartbeat_time = now
            elif args.heartbeat > 0 and (now - last_heartbeat_time) >= args.heartbeat:
                # Send periodic heartbeat frame to keep microcontroller state refreshed
                current_status = detector.get_status()
                send_serial_event(ser, current_status)
                last_heartbeat_time = now

            # Sleep for the configured poll interval
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopping Teams Monitor...")
    finally:
        # Graceful cleanup: inform the microcontroller that the monitor is shutting down
        if ser is not None and ser.is_open:
            exit_event = detector.get_status()
            exit_event.status = "Offline"
            send_serial_event(ser, exit_event)
            ser.close()
            print("Serial connection closed.")


if __name__ == "__main__":
    main()


