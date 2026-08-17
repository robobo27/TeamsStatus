# code.py - Main script running on the RP2040 chip (MicroPython version)
import machine
try:
    import select
except ImportError:
    import uselect as select
import sys
import time

# Set up the onboard LED (usually "LED" on Pico/RP2040, pin 25 as fallback)
led = None
try:
    led = machine.Pin("LED", machine.Pin.OUT)
except Exception:
    try:
        led = machine.Pin(25, machine.Pin.OUT)
    except Exception:
        pass

# Set up poller to non-blockingly check for incoming serial data on stdin
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)

print("USB CDC communication demo starting (MicroPython)...")

last_heartbeat = time.ticks_ms()

while True:
    # Non-blocking periodic heartbeat blink every 2 seconds if LED is available
    now = time.ticks_ms()
    if led and time.ticks_diff(now, last_heartbeat) >= 2000:
        last_heartbeat = now
        led.value(1)
        time.sleep(0.02)
        led.value(0)

    # Check if there is data waiting on stdin
    events = poller.poll(0)
    if events:
        # Read incoming line from host
        line = sys.stdin.readline()
        if line:
            try:
                # Strip trailing whitespace and newlines
                message = line.strip()
                if message:
                    # Prepare response with standard \n (MicroPython converts \n to \r\n automatically over serial)
                    response = f"Hello World! RP2040 received: '{message}'\n"
                    
                    # Write response back to the host via stdout
                    sys.stdout.write(response)
                    
                    # Blink LED twice rapidly to signal message processed
                    if led:
                        for _ in range(2):
                            led.value(1)
                            time.sleep(0.04)
                            led.value(0)
                            time.sleep(0.04)
            except Exception as e:
                sys.stdout.write(f"ERROR: {str(e)}\n")

    # Short delay to prevent excessive CPU usage
    time.sleep(0.01)


