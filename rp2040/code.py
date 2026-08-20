"""
code.py - Primary firmware script running on the RP2040 microcontroller (MicroPython).

Architecture & Features:
  1. Universal Hardware Abstraction (UnifiedLED):
     - Automatically probes and initializes the onboard LED hardware.
     - Supports addressable RGB NeoPixels (WS2812 / WS2812B) on Waveshare RP2040-Zero (GPIO 16)
       or custom board pin definitions (`machine.Pin.board.NEOPIXEL`).
     - Supports single-color GPIO LEDs on standard Raspberry Pi Pico (named 'LED' pin or GPIO 25)
       and Adafruit Feather RP2040 (GPIO 13).

  2. Teams Presence Color Coding:
     - Available    -> Gentle Green (0, 32, 0)
     - Busy         -> Solid Red (32, 0, 0)
     - In A Call    -> Pulsing High-Visibility Red (12, 0, 0) <-> (48, 0, 0)
     - DoNotDisturb -> Magenta / Purple (32, 0, 32)
     - Away / BRB   -> Amber / Yellow (32, 20, 0)
     - Offline      -> LED Off with periodic subtle alive pulse every 3 seconds
     - Unknown      -> Dim Cyan (0, 16, 32)

  3. Non-Blocking USB CDC Communication:
     - Uses `select.poll()` on `sys.stdin` to check for incoming serial data without
       blocking LED animations or timing loops.
     - Safely parses JSON telemetry payloads from `teams_monitor.py` or interactive text
       from `host_communicator.py`.
     - Replies to host with structured acknowledgment strings via `sys.stdout`.
"""

import machine

# MicroPython conditional imports for standard libraries vs micro-optimized equivalents
try:
    import select
except ImportError:
    import uselect as select

try:
    import json
except ImportError:
    import ujson as json

import sys
import time


class UnifiedLED:
    """
    Hardware abstraction layer for onboard LEDs.
    
    Provides a consistent interface across boards featuring addressable RGB WS2812 NeoPixels
    (such as Waveshare RP2040-Zero) and boards with standard single-color GPIO LEDs
    (such as the official Raspberry Pi Pico / Pico W).
    """

    def __init__(self):
        """
        Initializes LED parameters and probes connected board hardware.
        """
        self.device = None
        self.is_neopixel = False
        self._state = False
        self.color_on = (0, 32, 0)      # Default gentle green when no specific color is passed
        self.color_ack = (0, 32, 32)    # Cyan flash used for interactive text message acknowledgment
        self._init_hardware()

    def _init_hardware(self):
        """
        Probes known hardware configurations in order of specificity.
        """
        # Step 1: Check for WS2812 NeoPixel (Waveshare RP2040-Zero / Matrix or board definition)
        try:
            import neopixel
            pin_obj = None

            # Check board-level symbolic pin mapping if exposed by the MicroPython port
            if hasattr(machine.Pin, "board") and hasattr(machine.Pin.board, "NEOPIXEL"):
                pin_obj = machine.Pin.board.NEOPIXEL
            else:
                # Check system machine string for Waveshare / Zero boards which route NeoPixel to GPIO 16
                import os
                uname = os.uname()
                if "zero" in uname.machine.lower() or "waveshare" in uname.machine.lower():
                    pin_obj = machine.Pin(16)

            if pin_obj is not None:
                # Instantiate single NeoPixel driver
                self.device = neopixel.NeoPixel(pin_obj, 1)
                self.is_neopixel = True
                self.off()
                return
        except Exception:
            pass

        # Step 2: Check for named 'LED' pin (Raspberry Pi Pico / Pico W / Pico 2)
        try:
            self.device = machine.Pin("LED", machine.Pin.OUT)
            self.is_neopixel = False
            self.off()
            return
        except Exception:
            pass

        # Step 3: Fallback GPIO pins (GPIO 25 for classic Pico, GPIO 13 for Adafruit Feather)
        for pin_num in (25, 13):
            try:
                import os
                # Avoid claiming GPIO 25 on RP2040-Zero where it may conflict with other peripherals
                if "zero" in os.uname().machine.lower():
                    break
                self.device = machine.Pin(pin_num, machine.Pin.OUT)
                self.is_neopixel = False
                self.off()
                return
            except Exception:
                pass

    def value(self, v=None, color=None):
        """
        Gets or sets the current LED state and color.

        Args:
            v (int/bool, optional): 1 / True for ON, 0 / False for OFF. If None, returns current state.
            color (tuple, optional): RGB tuple (R, G, B) with values 0-255 for NeoPixel devices.

        Returns:
            int: Current state (1 or 0) if v is None.
        """
        if v is None:
            return 1 if self._state else 0

        self._state = bool(v)
        if not self.device:
            return

        if self.is_neopixel:
            # For NeoPixels, apply RGB color tuple or clear to (0, 0, 0)
            c = (color or self.color_on) if self._state else (0, 0, 0)
            self.device[0] = c
            self.device.write()
        else:
            # For standard GPIO LEDs, drive pin high (1) or low (0)
            self.device.value(1 if self._state else 0)

    def on(self, color=None):
        """
        Turns the LED ON, optionally setting a specific RGB color on NeoPixel devices.

        Args:
            color (tuple, optional): (R, G, B) tuple.
        """
        self.value(1, color=color)

    def off(self):
        """
        Turns the LED OFF.
        """
        self.value(0)

    def __bool__(self):
        """
        Returns True if an LED device was successfully initialized, False otherwise.
        """
        return self.device is not None


# Color palette for Microsoft Teams presence states (RGB format 0-255)
# Brightness is scaled conservatively to prevent overheating and harsh glare.
STATUS_COLORS = {
    "Available": (0, 32, 0),        # Solid Gentle Green
    "Busy": (32, 0, 0),             # Solid Red
    "InACall": (48, 0, 0),          # Bright / Pulsing Red
    "InAMeeting": (48, 0, 0),       # Bright / Pulsing Red
    "DoNotDisturb": (32, 0, 32),    # Magenta / Purple
    "Away": (32, 20, 0),            # Amber / Yellow
    "BeRightBack": (32, 20, 0),     # Amber / Yellow
    "Offline": (0, 0, 0),           # Off
    "NotRunning": (0, 0, 0),        # Off
    "Unknown": (0, 16, 32),         # Dim Cyan
}

# Initialize onboard LED controller
led = UnifiedLED()

# Set up non-blocking I/O poller on sys.stdin to detect incoming serial frames
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)

# Operational state variables
current_status = "Offline"
current_color = STATUS_COLORS["Offline"]
last_heartbeat = time.ticks_ms()
call_pulse_state = False

print("USB CDC communication demo starting (MicroPython with Teams Status Support)...")

# Main microcontroller event and dispatch loop
while True:
    now = time.ticks_ms()

    # ---------------------------------------------------------
    # 1. Visual Animations & Periodic Heartbeat Processing
    # ---------------------------------------------------------
    if current_status in ("InACall", "InAMeeting"):
        # Pulsing Red animation when in an active voice/video call (toggles every 600ms)
        # Note: time.ticks_diff() handles 30-bit integer rollover safely in MicroPython.
        if time.ticks_diff(now, last_heartbeat) >= 600:
            last_heartbeat = now
            call_pulse_state = not call_pulse_state
            pulse_color = (48, 0, 0) if call_pulse_state else (12, 0, 0)
            if led:
                led.on(color=pulse_color)
    elif current_status in ("Offline", "NotRunning"):
        # Gentle 20ms cyan blip every 3000ms when offline to provide a subtle "heartbeat" indicator
        if time.ticks_diff(now, last_heartbeat) >= 3000:
            last_heartbeat = now
            if led:
                led.on(color=(0, 4, 8))
                time.sleep(0.02)
                led.off()
    else:
        # Solid status colors remain steadily illuminated without animation
        pass

    # ---------------------------------------------------------
    # 2. Non-blocking Serial Data Reception & Packet Handling
    # ---------------------------------------------------------
    # Poll stdin with a timeout of 0ms (returns immediately)
    events = poller.poll(0)
    if events:
        line = sys.stdin.readline()
        if line:
            message = line.strip()
            if message:
                is_json = False
                parsed_status = None

                # Protocol Branch A: JSON Payload from Teams Monitor Daemon
                # Format: {"type": "teams_status", "status": "Available", "in_call": false, ...}
                if message.startswith("{") and message.endswith("}"):
                    try:
                        data = json.loads(message)
                        if isinstance(data, dict) and ("status" in data or data.get("type") == "teams_status"):
                            is_json = True
                            parsed_status = data.get("status", "Unknown")
                            in_call = data.get("in_call", False)

                            # Promote status to 'InACall' if in a call and underlying status is Busy
                            if in_call and parsed_status == "Busy":
                                parsed_status = "InACall"

                            current_status = parsed_status
                            current_color = STATUS_COLORS.get(current_status, (0, 16, 32))

                            # Update LED state immediately
                            if current_status in ("Offline", "NotRunning"):
                                if led:
                                    led.off()
                            else:
                                if led:
                                    led.on(color=current_color)

                            # Return positive acknowledgment over USB CDC
                            response = f"OK: Teams status set to {current_status}\n"
                            sys.stdout.write(response)
                    except Exception as err:
                        sys.stdout.write(f"ERROR: JSON parse failed: {str(err)}\n")
                        is_json = False

                # Protocol Branch B: Plain Text / Interactive REPL Command
                # Used when testing manually via host_communicator.py or terminal emulator
                if not is_json:
                    response = f"Hello World! RP2040 received: '{message}'\n"
                    sys.stdout.write(response)

                    # Flash cyan acknowledgment sequence twice
                    if led:
                        for _ in range(2):
                            led.on(color=led.color_ack)
                            time.sleep(0.04)
                            led.off()
                            time.sleep(0.04)

                        # Restore prior status LED state after ACK blinks complete
                        if current_status not in ("Offline", "NotRunning"):
                            led.on(color=current_color)

    # ---------------------------------------------------------
    # 3. CPU Yield / Loop Rate Throttling
    # ---------------------------------------------------------
    # Short 10ms sleep to conserve power and avoid pegged CPU utilization
    time.sleep(0.01)

