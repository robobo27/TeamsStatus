"""
code.py - Primary firmware script running on the RP2040 microcontroller (MicroPython).

Architecture & Features:
  1. Universal Hardware Abstraction (UnifiedLED):
     - Automatically probes and initializes the onboard LED hardware.
     - Supports addressable RGB NeoPixels (WS2812 / WS2812B) on Waveshare RP2040-Zero (GPIO 16)
       or custom board pin definitions (`machine.Pin.board.NEOPIXEL`).
     - Supports single-color GPIO LEDs on standard Raspberry Pi Pico (named 'LED' pin or GPIO 25)
       and Adafruit Feather RP2040 (GPIO 13).
     - Drives an external PWM output on GPIO 15 (Right Header Pin 8, 1 kHz) for the
       D4184 / LR7843 MOSFET module and 18-LED White Strip ("On Air" indicator).

  2. Teams Presence Color Coding & External "On Air" PWM Strip (GPIO 15):
     - Available    -> Onboard: Gentle Green (0, 32, 0)           | External PWM (GP15): OFF (0%)
     - Busy         -> Onboard: Pulsing Red (12,0,0)<->(48,0,0)   | External PWM (GP15): Pulsing (10% <-> 30%)
     - In A Call    -> Onboard: Solid Red (48, 0, 0)              | External PWM (GP15): Solid ON (100%)
     - DoNotDisturb -> Onboard: Magenta / Purple (32, 0, 32)      | External PWM (GP15): Solid ON (100%)
     - Away / BRB   -> Onboard: Amber / Yellow (32, 20, 0)        | External PWM (GP15): OFF (0%)
     - Offline      -> Onboard: Off (subtle pulse every 3s)       | External PWM (GP15): OFF (0%)
     - Unknown      -> Onboard: Dim Cyan (0, 16, 32)              | External PWM (GP15): OFF (0%)

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

# External MOSFET / LED Strip PWM Configuration (Waveshare RP2040-Zero Right Pin 8 = GP15)
EXTERNAL_PWM_PIN = 15
EXTERNAL_PWM_FREQ_HZ = 1000
PWM_DUTY_FULL = 65535        # 100% duty cycle (16-bit)
PWM_DUTY_PULSE_HIGH = 19661  # 30% duty cycle during Busy pulse
PWM_DUTY_PULSE_LOW = 6554    # 10% duty cycle during Busy pulse
PWM_DUTY_OFF = 0             # 0% duty cycle (OFF)


class UnifiedLED:
    """
    Hardware abstraction layer for onboard LEDs and the external GPIO 15 PWM driver.
    
    Provides a consistent interface across boards featuring addressable RGB WS2812 NeoPixels
    (such as Waveshare RP2040-Zero) and boards with standard single-color GPIO LEDs
    (such as the official Raspberry Pi Pico / Pico W), plus hardware PWM on GPIO 15
    for driving the external D4184 / LR7843 MOSFET module and 18-LED White Strip.
    """

    def __init__(self, pwm_pin=EXTERNAL_PWM_PIN, pwm_freq=EXTERNAL_PWM_FREQ_HZ):
        """
        Initializes LED parameters, probes onboard LED hardware, and configures GPIO 15 PWM.
        """
        self.device = None
        self.is_neopixel = False
        self._state = False
        self.pwm = None
        self._pwm_duty = 0
        self.color_on = (0, 32, 0)      # Default gentle green when no specific color is passed
        self.color_ack = (0, 32, 32)    # Cyan flash used for interactive text message acknowledgment
        self._init_pwm(pwm_pin, pwm_freq)
        self._init_hardware()

    def _init_pwm(self, pwm_pin, pwm_freq):
        """
        Initializes hardware PWM on GPIO 15 for the external D4184 / LR7843 MOSFET module.
        """
        try:
            self.pwm = machine.PWM(machine.Pin(pwm_pin))
            self.pwm.freq(pwm_freq)
            self.pwm.duty_u16(PWM_DUTY_OFF)
            self._pwm_duty = PWM_DUTY_OFF
        except Exception:
            self.pwm = None

    def set_pwm_duty(self, duty_u16):
        """
        Sets the 16-bit PWM duty cycle (0-65535) on the external MOSFET / LED strip pin (GPIO 15).
        """
        if duty_u16 < 0:
            duty_u16 = 0
        elif duty_u16 > 65535:
            duty_u16 = 65535
        self._pwm_duty = duty_u16
        if self.pwm is not None:
            try:
                self.pwm.duty_u16(duty_u16)
            except Exception:
                pass

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

    def value(self, v=None, color=None, pwm_duty=None):
        """
        Gets or sets the current onboard LED state/color and optional external PWM duty cycle.

        Args:
            v (int/bool, optional): 1 / True for ON, 0 / False for OFF. If None, returns current state.
            color (tuple, optional): RGB tuple (R, G, B) with values 0-255 for NeoPixel devices.
            pwm_duty (int, optional): 16-bit PWM duty cycle (0-65535) for GPIO 15.

        Returns:
            int: Current state (1 or 0) if v is None.
        """
        if v is None:
            return 1 if self._state else 0

        self._state = bool(v)
        if pwm_duty is not None:
            self.set_pwm_duty(pwm_duty)
        elif not self._state:
            self.set_pwm_duty(PWM_DUTY_OFF)

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

    def on(self, color=None, pwm_duty=None):
        """
        Turns the onboard LED ON (optionally setting RGB color) and updates external PWM duty if provided.

        Args:
            color (tuple, optional): (R, G, B) tuple.
            pwm_duty (int, optional): 16-bit PWM duty cycle (0-65535) for GPIO 15.
        """
        self.value(1, color=color, pwm_duty=pwm_duty)

    def off(self):
        """
        Turns both the onboard LED and external GPIO 15 PWM OFF.
        """
        self.value(0, pwm_duty=PWM_DUTY_OFF)

    def __bool__(self):
        """
        Returns True if an onboard LED or external PWM driver was initialized, False otherwise.
        """
        return (self.device is not None) or (self.pwm is not None)


# Color palette for Microsoft Teams presence states (RGB format 0-255)
# Brightness is scaled conservatively to prevent overheating and harsh glare.
STATUS_COLORS = {
    "Available": (0, 32, 0),        # Solid Gentle Green
    "Busy": (48, 0, 0),             # Pulsing Red
    "InACall": (48, 0, 0),          # Solid Bright Red
    "InAMeeting": (48, 0, 0),       # Solid Bright Red
    "DoNotDisturb": (32, 0, 32),    # Magenta / Purple
    "Away": (32, 20, 0),            # Amber / Yellow
    "BeRightBack": (32, 20, 0),     # Amber / Yellow
    "Offline": (0, 0, 0),           # Off
    "NotRunning": (0, 0, 0),        # Off
    "Unknown": (0, 16, 32),         # Dim Cyan
}

# "On Air" External PWM Duty Cycles (GPIO 15 -> D4184/LR7843 -> 18-LED White Strip)
# Active only when Busy, DoNotDisturb, InACall, or InAMeeting; OFF otherwise.
STATUS_PWM_DUTY = {
    "Available": PWM_DUTY_OFF,        # OFF (0%)
    "Busy": PWM_DUTY_PULSE_HIGH,      # Pulsing 30% <-> 10% in animation loop
    "InACall": PWM_DUTY_FULL,         # Solid ON (100%)
    "InAMeeting": PWM_DUTY_FULL,      # Solid ON (100%)
    "DoNotDisturb": PWM_DUTY_FULL,    # Solid ON (100%)
    "Away": PWM_DUTY_OFF,             # OFF (0%)
    "BeRightBack": PWM_DUTY_OFF,      # OFF (0%)
    "Offline": PWM_DUTY_OFF,          # OFF (0%)
    "NotRunning": PWM_DUTY_OFF,       # OFF (0%)
    "Unknown": PWM_DUTY_OFF,          # OFF (0%)
}

# Initialize onboard LED + external GPIO 15 PWM controller
led = UnifiedLED()

# Set up non-blocking I/O poller on sys.stdin to detect incoming serial frames
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)

# Operational state variables
current_status = "Offline"
current_color = STATUS_COLORS["Offline"]
current_pwm_duty = STATUS_PWM_DUTY["Offline"]
last_heartbeat = time.ticks_ms()
call_pulse_state = False

print("USB CDC communication demo starting (MicroPython with Teams Status & GP15 On-Air PWM)...")

# Main microcontroller event and dispatch loop
while True:
    now = time.ticks_ms()

    # ---------------------------------------------------------
    # 1. Visual Animations & Periodic Heartbeat Processing
    # ---------------------------------------------------------
    if current_status == "Busy":
        # Pulsing animation when Busy (toggles every 600ms)
        # Onboard RGB pulses (48, 0, 0) <-> (12, 0, 0); External GP15 PWM pulses 30% <-> 10%.
        # Note: time.ticks_diff() handles 30-bit integer rollover safely in MicroPython.
        if time.ticks_diff(now, last_heartbeat) >= 600:
            last_heartbeat = now
            call_pulse_state = not call_pulse_state
            pulse_color = (48, 0, 0) if call_pulse_state else (12, 0, 0)
            pulse_pwm = PWM_DUTY_PULSE_HIGH if call_pulse_state else PWM_DUTY_PULSE_LOW
            if led:
                led.on(color=pulse_color, pwm_duty=pulse_pwm)
    elif current_status in ("Offline", "NotRunning"):
        # Gentle 20ms cyan blip on onboard LED every 3000ms when offline (external strip stays OFF)
        if time.ticks_diff(now, last_heartbeat) >= 3000:
            last_heartbeat = now
            if led:
                led.on(color=(0, 4, 8), pwm_duty=PWM_DUTY_OFF)
                time.sleep(0.02)
                led.off()
    else:
        # Solid status colors and PWM duty remain steadily illuminated without animation
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
                            current_pwm_duty = STATUS_PWM_DUTY.get(current_status, PWM_DUTY_OFF)

                            # Update onboard LED and external GP15 PWM state immediately
                            if current_status in ("Offline", "NotRunning"):
                                if led:
                                    led.off()
                            else:
                                if led:
                                    led.on(color=current_color, pwm_duty=current_pwm_duty)

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

                    # Flash acknowledgment sequence twice on both onboard LED and external PWM strip
                    if led:
                        for _ in range(2):
                            led.on(color=led.color_ack, pwm_duty=PWM_DUTY_FULL)
                            time.sleep(0.04)
                            led.off()
                            time.sleep(0.04)

                        # Restore prior status LED and external PWM state after ACK blinks complete
                        if current_status not in ("Offline", "NotRunning"):
                            led.on(color=current_color, pwm_duty=current_pwm_duty)

    # ---------------------------------------------------------
    # 3. CPU Yield / Loop Rate Throttling
    # ---------------------------------------------------------
    # Short 10ms sleep to conserve power and avoid pegged CPU utilization
    time.sleep(0.01)


