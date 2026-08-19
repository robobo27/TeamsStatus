# code.py - Main script running on the RP2040 chip (MicroPython version)
import machine
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
    """Unified LED driver supporting WS2812 NeoPixel RGB and standard GPIO LEDs."""

    def __init__(self):
        self.device = None
        self.is_neopixel = False
        self._state = False
        self.color_on = (0, 32, 0)      # Default gentle green
        self.color_ack = (0, 32, 32)    # Cyan for message ACK
        self._init_hardware()

    def _init_hardware(self):
        # 1. Check for NeoPixel on board definition or GPIO 16 (Waveshare RP2040-Zero / Matrix)
        try:
            import neopixel
            pin_obj = None
            if hasattr(machine.Pin, "board") and hasattr(machine.Pin.board, "NEOPIXEL"):
                pin_obj = machine.Pin.board.NEOPIXEL
            else:
                import os
                uname = os.uname()
                if "zero" in uname.machine.lower() or "waveshare" in uname.machine.lower():
                    pin_obj = machine.Pin(16)
            if pin_obj is not None:
                self.device = neopixel.NeoPixel(pin_obj, 1)
                self.is_neopixel = True
                self.off()
                return
        except Exception:
            pass

        # 2. Check for named "LED" pin (Raspberry Pi Pico / Pico W / Pico 2)
        try:
            self.device = machine.Pin("LED", machine.Pin.OUT)
            self.is_neopixel = False
            self.off()
            return
        except Exception:
            pass

        # 3. Check fallback GPIO pins (25 for Pico, 13 for Feather)
        for pin_num in (25, 13):
            try:
                import os
                if "zero" in os.uname().machine.lower():
                    break
                self.device = machine.Pin(pin_num, machine.Pin.OUT)
                self.is_neopixel = False
                self.off()
                return
            except Exception:
                pass

    def value(self, v=None, color=None):
        if v is None:
            return 1 if self._state else 0
        self._state = bool(v)
        if not self.device:
            return
        if self.is_neopixel:
            c = (color or self.color_on) if self._state else (0, 0, 0)
            self.device[0] = c
            self.device.write()
        else:
            self.device.value(1 if self._state else 0)

    def on(self, color=None):
        self.value(1, color=color)

    def off(self):
        self.value(0)

    def __bool__(self):
        return self.device is not None


# Color palette for Microsoft Teams presence states (RGB format 0-255)
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

# Set up poller to non-blockingly check for incoming serial data on stdin
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)

current_status = "Offline"
current_color = STATUS_COLORS["Offline"]
last_heartbeat = time.ticks_ms()
call_pulse_state = False

print("USB CDC communication demo starting (MicroPython with Teams Status Support)...")

while True:
    now = time.ticks_ms()

    # Dynamic status animation / heartbeat
    if current_status in ("InACall", "InAMeeting"):
        # Pulsing Red animation when in a call (every 600ms)
        if time.ticks_diff(now, last_heartbeat) >= 600:
            last_heartbeat = now
            call_pulse_state = not call_pulse_state
            pulse_color = (48, 0, 0) if call_pulse_state else (12, 0, 0)
            if led:
                led.on(color=pulse_color)
    elif current_status in ("Offline", "NotRunning"):
        # Gentle 20ms blip every 3 seconds when offline to indicate alive state
        if time.ticks_diff(now, last_heartbeat) >= 3000:
            last_heartbeat = now
            if led:
                led.on(color=(0, 4, 8))
                time.sleep(0.02)
                led.off()
    else:
        # Solid status color maintained
        pass

    # Check if serial data is waiting on stdin
    events = poller.poll(0)
    if events:
        line = sys.stdin.readline()
        if line:
            message = line.strip()
            if message:
                is_json = False
                parsed_status = None

                # Attempt JSON payload parsing
                if message.startswith("{") and message.endswith("}"):
                    try:
                        data = json.loads(message)
                        if isinstance(data, dict) and ("status" in data or data.get("type") == "teams_status"):
                            is_json = True
                            parsed_status = data.get("status", "Unknown")
                            in_call = data.get("in_call", False)
                            if in_call and parsed_status == "Busy":
                                parsed_status = "InACall"

                            current_status = parsed_status
                            current_color = STATUS_COLORS.get(current_status, (0, 16, 32))

                            if current_status in ("Offline", "NotRunning"):
                                if led:
                                    led.off()
                            else:
                                if led:
                                    led.on(color=current_color)

                            response = f"OK: Teams status set to {current_status}\n"
                            sys.stdout.write(response)
                    except Exception as err:
                        sys.stdout.write(f"ERROR: JSON parse failed: {str(err)}\n")
                        is_json = False

                # Fallback for plain text messages
                if not is_json:
                    response = f"Hello World! RP2040 received: '{message}'\n"
                    sys.stdout.write(response)

                    # Blink cyan ACK twice
                    if led:
                        for _ in range(2):
                            led.on(color=led.color_ack)
                            time.sleep(0.04)
                            led.off()
                            time.sleep(0.04)

                        # Restore current status LED
                        if current_status not in ("Offline", "NotRunning"):
                            led.on(color=current_color)

    # Short delay to prevent excessive CPU usage
    time.sleep(0.01)
