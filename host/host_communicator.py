"""
host_communicator.py - Host-side interactive terminal to communicate with MicroPython over USB Serial (CDC).

This script provides an interactive command-line interface (REPL-like tool) that allows
a user on a host computer (Windows/Linux/macOS) to send text or JSON messages to a
connected microcontroller running MicroPython (e.g., Raspberry Pi Pico, Waveshare RP2040-Zero)
via a USB serial (CDC) interface, and receive the microcontroller's response in real-time.

Key Features:
  - Scans and lists all active system serial ports without filtering by vendor IDs.
  - Defaults to COM4 (or accepts an explicit port / interactive selection).
  - Handles byte-level encoding (UTF-8) and newline delimiters (\n) expected by the firmware.
  - Implements a drain-loop response reader with timeout handling to capture multi-line responses.
  - Provides clear diagnostic messages and troubleshooting hints for serial conflicts.
"""

import argparse
import serial
import serial.tools.list_ports
import sys
import time

# Default communication parameters
DEFAULT_PORT = "COM4"
DEFAULT_BAUDRATE = 115200


def scan_ports():
    """
    Scans and prints all currently connected COM / serial ports on the host system.

    Returns:
        list[str]: A list of port device names (e.g., ['COM1', 'COM4']).
    """
    # Enumerate all available serial ports using pySerial's port discovery utility
    ports = sorted(serial.tools.list_ports.comports())
    print("Available Serial COM Ports:")
    if not ports:
        print("  [None detected]")
    for p in ports:
        # Display each device name along with its OS-provided hardware description
        desc = p.description if p.description else "No description"
        print(f"  - {p.device}: {desc}")
    return [p.device for p in ports]


def select_port(requested_port=None):
    """
    Determines the serial COM port to use based on CLI arguments, availability, or user input.

    Resolution Priority:
      1. Explicitly requested port from CLI arguments.
      2. DEFAULT_PORT ('COM4') if detected in active system ports.
      3. Interactive user prompt if other ports are active.
      4. Fallback to DEFAULT_PORT.

    Args:
        requested_port (str, optional): Port explicitly specified by the user via CLI.

    Returns:
        str: The chosen COM port string (e.g., 'COM4').
    """
    available = scan_ports()

    if requested_port:
        # Priority 1: User explicitly specified a port via command-line argument
        selected = requested_port
        print(f"\nUsing requested port: {selected}")
    elif DEFAULT_PORT in available:
        # Priority 2: Default port is active and ready on the system
        selected = DEFAULT_PORT
        print(f"\nAuto-selected target port: {selected} (found in available ports)")
    else:
        # Priority 3 & 4: Default port not detected in active list
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
    """
    Main interactive loop for the host-side communicator.
    
    Opens the serial connection, configures buffers, and enters a prompt loop
    allowing bidirectional message exchange with the MicroPython device.
    """
    # Configure command-line argument parsing
    parser = argparse.ArgumentParser(
        description="MicroPython Host Serial Communicator - Interactive USB CDC terminal"
    )
    parser.add_argument(
        "port",
        nargs="?",
        default=None,
        help=f"Serial COM port to connect to (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "-b",
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"Baud rate (default: {DEFAULT_BAUDRATE})",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("        MicroPython Host Serial Communicator")
    print("=" * 60)

    # Determine target port and baud rate
    selected_port = select_port(args.port)
    baudrate = args.baudrate

    print(f"\nConnecting to MicroPython device on {selected_port} at {baudrate} baud...")

    try:
        # Open serial port with a 1.0-second read timeout
        ser = serial.Serial(selected_port, baudrate=baudrate, timeout=1.0)

        # Clear any stale data remaining in OS-level UART/USB buffers from previous sessions
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        print(f"Connected successfully to {selected_port}!")
        print("Type a message/command and press Enter to send. Type 'exit' or press Ctrl+C to quit.\n")

        # Main interactive transmission REPL loop
        while True:
            try:
                user_msg = input(f"MicroPython [{selected_port}] > ")
            except (EOFError, KeyboardInterrupt):
                # Graceful handling of Ctrl+C or EOF (Ctrl+D / Ctrl+Z) in prompt
                print("\nExiting...")
                break

            # Check for termination keywords
            if user_msg.strip().lower() in ("exit", "quit"):
                break

            # Skip empty inputs
            if not user_msg:
                continue

            # Format message with trailing newline character (\n) as expected by the RP2040 readline() loop
            send_bytes = (user_msg.strip() + "\n").encode("utf-8")
            ser.write(send_bytes)
            ser.flush()  # Ensure all bytes are immediately pushed over the USB bus

            # Wait briefly (150ms) for the microcontroller to process the command and formulate its response
            time.sleep(0.15)

            # Read all response bytes returned by the microcontroller
            response_bytes = bytearray()
            while ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting)
                response_bytes.extend(chunk)
                # Short settling pause to catch multi-packet responses before concluding the read
                time.sleep(0.05)

            # Display response or notify if no reply was received within the timeout window
            if response_bytes:
                response_str = response_bytes.decode("utf-8", errors="replace").strip()
                print(f"Device Response <\n{response_str}")
            else:
                print("Warning: No response received (timeout).")

    except serial.SerialException as e:
        # Detailed error and troubleshooting guidance for common serial port conflicts
        print(f"\nSerial Connection Error: {e}")
        print("Troubleshooting checklist:")
        print(f" 1. Ensure the board is connected and recognized on {selected_port}.")
        print(" 2. Ensure no other application (mpremote, PuTTY, Thonny, VSCode Serial Monitor) is using the port.")
    except KeyboardInterrupt:
        print("\nExiting host communicator...")
    finally:
        # Guarantee that the serial port handle is safely closed upon exit
        if "ser" in locals() and ser.is_open:
            ser.close()
            print("Serial connection closed.")


if __name__ == "__main__":
    main()


