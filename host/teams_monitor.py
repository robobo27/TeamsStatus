# host/teams_monitor.py - Standalone Microsoft Teams local status monitor & USB serial dispatcher
import argparse
import json
import os
import sys
import time
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

try:
    from host.teams_detector import TeamsDetector, TeamsStatusEvent
except ImportError:
    from teams_detector import TeamsDetector, TeamsStatusEvent


def format_status_badge(status: str) -> str:
    """Return an ASCII-compatible formatted status string safe for all Windows code pages."""
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
    """Attempts to open serial connection to RP2040."""
    if not SERIAL_AVAILABLE:
        print("Warning: pyserial is not installed. Running in console-only mode.")
        return None

    try:
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print(f"Connected to Microcontroller on {port} @ {baudrate} baud.")
        return ser
    except serial.SerialException as e:
        print(f"Notice: Serial port {port} unavailable ({e}). Continuing in console-only mode.")
        return None


def send_serial_event(ser: Optional["serial.Serial"], event: TeamsStatusEvent):
    """Sends JSON status payload over serial link."""
    if ser is None or not ser.is_open:
        return

    payload = event.to_json() + "\n"
    try:
        ser.write(payload.encode("utf-8"))
        ser.flush()
    except Exception as e:
        print(f"Serial transmission error: {e}")


def main():
    # Configure UTF-8 stdout if supported by runtime environment
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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

    print("=" * 65)
    print("       Local Microsoft Teams Status Monitor (Zero-Network)")
    print("=" * 65)
    print(f"Log Dir       : {args.log_dir or 'Auto-detected (Local MSTeams package)'}")
    print(f"Poll Interval : {args.interval}s")
    print(f"Heartbeat     : {args.heartbeat}s")
    print(f"Serial Target : {'Disabled (Standalone)' if args.standalone else f'{args.port} @ {args.baudrate}'}")
    print("-" * 65)

    detector = TeamsDetector(log_dir=args.log_dir)

    ser: Optional["serial.Serial"] = None
    if not args.standalone:
        ser = open_serial_connection(args.port, args.baudrate)

    last_heartbeat_time = 0.0

    print("\nStarting monitor loop. Press Ctrl+C to exit.\n")

    try:
        while True:
            # Poll detector for status changes
            event = detector.poll_for_change()
            now = time.time()

            if event is not None:
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

                send_serial_event(ser, event)
                last_heartbeat_time = now
            elif args.heartbeat > 0 and (now - last_heartbeat_time) >= args.heartbeat:
                # Send periodic heartbeat keep-alive
                current_status = detector.get_status()
                send_serial_event(ser, current_status)
                last_heartbeat_time = now

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopping Teams Monitor...")
    finally:
        if ser is not None and ser.is_open:
            # Send an Offline event on exit before closing
            exit_event = detector.get_status()
            exit_event.status = "Offline"
            send_serial_event(ser, exit_event)
            ser.close()
            print("Serial connection closed.")


if __name__ == "__main__":
    main()
