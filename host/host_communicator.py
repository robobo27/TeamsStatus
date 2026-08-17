# host_communicator.py - Host-side Python script to communicate with a MicroPython device via USB Serial / CDC
import argparse
import serial
import serial.tools.list_ports
import sys
import time

DEFAULT_PORT = "COM4"
DEFAULT_BAUDRATE = 115200


def scan_ports():
    """Scan and list all available COM ports without filtering by board vendor/manufacturer."""
    ports = sorted(serial.tools.list_ports.comports())
    print("Available Serial COM Ports:")
    if not ports:
        print("  [None detected]")
    for p in ports:
        desc = p.description if p.description else "No description"
        print(f"  - {p.device}: {desc}")
    return [p.device for p in ports]


def select_port(requested_port=None):
    """Determine the COM port to use, defaulting to COM4 with no board vendor assumptions."""
    available = scan_ports()

    if requested_port:
        selected = requested_port
        print(f"\nUsing requested port: {selected}")
    elif DEFAULT_PORT in available:
        selected = DEFAULT_PORT
        print(f"\nAuto-selected target port: {selected} (found in available ports)")
    else:
        print(f"\nDefault target port '{DEFAULT_PORT}' was not found in active ports list.")
        if available:
            print(f"Available ports: {', '.join(available)}")
            user_choice = input(f"Enter COM port to use (press Enter for default '{DEFAULT_PORT}'): ").strip()
            selected = user_choice if user_choice else DEFAULT_PORT
        else:
            selected = DEFAULT_PORT
            print(f"Proceeding with default port '{DEFAULT_PORT}'.")

    return selected


def main():
    parser = argparse.ArgumentParser(description="MicroPython Host Serial Communicator")
    parser.add_argument("port", nargs="?", default=None, help=f"Serial COM port to connect to (default: {DEFAULT_PORT})")
    parser.add_argument("-b", "--baudrate", type=int, default=DEFAULT_BAUDRATE, help=f"Baud rate (default: {DEFAULT_BAUDRATE})")
    args = parser.parse_args()

    print("=" * 60)
    print("        MicroPython Host Serial Communicator")
    print("=" * 60)

    selected_port = select_port(args.port)
    baudrate = args.baudrate

    print(f"\nConnecting to MicroPython device on {selected_port} at {baudrate} baud...")

    try:
        ser = serial.Serial(selected_port, baudrate=baudrate, timeout=1.0)

        # Clear initial buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        print(f"Connected successfully to {selected_port}!")
        print("Type a message/command and press Enter to send. Type 'exit' or press Ctrl+C to quit.\n")

        while True:
            try:
                user_msg = input(f"MicroPython [{selected_port}] > ")
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                break

            if user_msg.strip().lower() in ("exit", "quit"):
                break

            if not user_msg:
                continue

            # Send message formatted with newline (\n)
            send_bytes = (user_msg.strip() + "\n").encode("utf-8")
            ser.write(send_bytes)
            ser.flush()

            # Wait briefly for response and collect available data
            time.sleep(0.15)

            response_bytes = bytearray()
            while ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting)
                response_bytes.extend(chunk)
                time.sleep(0.05)

            if response_bytes:
                response_str = response_bytes.decode("utf-8", errors="replace").strip()
                print(f"Device Response <\n{response_str}")
            else:
                print("Warning: No response received (timeout).")

    except serial.SerialException as e:
        print(f"\nSerial Connection Error: {e}")
        print("Troubleshooting checklist:")
        print(f" 1. Ensure the board is connected to {selected_port}.")
        print(" 2. Ensure no other application (mpremote, PuTTY, Thonny, VSCode Serial Monitor) is using the port.")
    except KeyboardInterrupt:
        print("\nExiting host communicator...")
    finally:
        if "ser" in locals() and ser.is_open:
            ser.close()
            print("Serial connection closed.")


if __name__ == "__main__":
    main()

