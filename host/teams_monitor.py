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
"""

import argparse
import json
import os
import sys
import time
from typing import Optional

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
    
    Parses CLI parameters, opens serial link (if enabled), polls detector,
    dispatches events, and handles heartbeat intervals.
    """
    # Reconfigure stdout for UTF-8 output if the host terminal allows it
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Configure command-line arguments
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
    args = parser.parse_args()

    # Display startup configuration banner
    print("=" * 65)
    print("       Local Microsoft Teams Status Monitor (Zero-Network)")
    print("=" * 65)
    print(f"Log Dir       : {args.log_dir or 'Auto-detected (Local MSTeams package)'}")
    print(f"Poll Interval : {args.interval}s")
    print(f"Heartbeat     : {args.heartbeat}s")
    print(f"Serial Target : {'Disabled (Standalone)' if args.standalone else f'{args.port} @ {args.baudrate}'}")
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

