---
name: rp2040-zero-workflow
description: >-
  Operational runbook for provisioning, flashing, deploying code, debugging USB serial COM ports,
  controlling the WS2812 RGB LED, and managing the Teams Status Monitor on the Waveshare RP2040-Zero
  in the TeamsStatus repository. Use this skill whenever interacting with the RP2040 hardware,
  troubleshooting BOOTSEL (RPI-RP2) or COM port issues, updating rp2040/*.py scripts, or testing serial telemetry.
---

# Waveshare RP2040-Zero & TeamsStatus Hardware Runbook

## 1. Diagnosing Hardware State (`BOOTSEL` Drive vs. USB CDC Serial Port)

An RP2040 board can be in one of two USB states:

1. **ROM UF2 Bootloader Mode (`BOOTSEL`)**:
   - **Symptoms**: No `COMx` serial port appears in Windows Device Manager; instead, a removable FAT drive labeled **`RPI-RP2`** (containing `INFO_UF2.TXT` and `INDEX.HTM`) is mounted.
   - **When this happens**: Brand-new factory boards with blank flash, or when plugged in while holding the physical `BOOTSEL` button (or after running `machine.bootloader()` in REPL).
   - **Resolution**: Flash the MicroPython `.uf2` firmware for the Waveshare RP2040-Zero (`WAVESHARE_RP2040_ZERO`).

2. **MicroPython Normal Run Mode (USB CDC Serial)**:
   - **Symptoms**: Enumerates as a USB Serial Device (`COM3`, `COM4`, etc.) with Raspberry Pi USB Vendor ID `0x2E8A` (e.g., `2e8a:101f` or `2e8a:0005`). The `RPI-RP2` drive is no longer mounted.
   - **Diagnostic Command**:
     ```powershell
     .\.venv\Scripts\mpremote.exe connect list
     ```

---

## 2. Avoiding Serial Port Contention (`PermissionError` / Access Denied)

Only one process on Windows can open a `COM` port at a time. Before running `mpremote`, [`flash_and_deploy_rp2040.py`](../../../flash_and_deploy_rp2040.py), or direct `pyserial` scripts:

1. **Check if `TeamsMonitor.exe` or `teams_monitor.py` is running**:
   ```powershell
   Get-Process -Name "TeamsMonitor" -ErrorAction SilentlyContinue
   ```
2. **Stop `TeamsMonitor.exe` temporarily if running**:
   ```powershell
   Stop-Process -Name "TeamsMonitor" -Force -ErrorAction SilentlyContinue
   ```
3. After finishing `mpremote` or deployment operations, restart `dist\TeamsMonitor.exe` if the user had it running in the background.

---

## 3. Automated Provisioning & Script Deployment

To flash firmware (if in `BOOTSEL` mode), auto-discover the COM port, upload all three scripts ([`rp2040/boot.py`](../../../rp2040/boot.py), [`rp2040/code.py`](../../../rp2040/code.py), [`rp2040/main.py`](../../../rp2040/main.py)), soft-reset, and verify live serial communication in a single step:

```powershell
.\.venv\Scripts\python.exe flash_and_deploy_rp2040.py
```

### Useful Flags for `flash_and_deploy_rp2040.py`
- `--port COM3` (or `auto`, the default): Target a specific COM port.
- `--board rp2040-zero` (default) or `--board pico`: Select which official MicroPython `.uf2` firmware to download when an `RPI-RP2` drive is detected.
- `--uf2 <path/to/firmware.uf2>`: Flash a specific local `.uf2` file instead of downloading.
- `--skip-verify`: Skip the post-reset `115200` baud serial ping check.

---

## 4. Manual File Operations & REPL via `connect_mpremote.py`

[`connect_mpremote.py`](../../../connect_mpremote.py) automatically discovers the connected RP2040 COM port via USB VID (`0x2E8A`, `0x239A`, `0x1B4F`):

```powershell
# List files on the RP2040 root filesystem
.\.venv\Scripts\python.exe connect_mpremote.py fs ls

# Copy a single updated file and soft-reset
.\.venv\Scripts\python.exe connect_mpremote.py cp rp2040/code.py :code.py
.\.venv\Scripts\python.exe connect_mpremote.py reset

# Re-enter UF2 BOOTSEL mode from software (without pressing physical buttons)
.\.venv\Scripts\python.exe connect_mpremote.py exec "import machine; machine.bootloader()"
```

> [!IMPORTANT]
> Because `main.py` executes `code.py` in an infinite `while True:` polling loop on boot, `mpremote` interrupts the running loop with `Ctrl-C` (raw REPL) to perform `fs` or `cp` operations. Always run `connect_mpremote.py reset` afterward so `main.py` $\rightarrow$ `code.py` resumes normal execution!

---

## 5. Testing Serial Telemetry & WS2812 RGB LED Colors

When `code.py` is running on the Waveshare RP2040-Zero, its onboard WS2812 NeoPixel (`GPIO 16`) responds to two newline-terminated (`\n`) serial protocols at **`115200` baud**:

### A. Plain-Text Ping
Sending any non-JSON line returns a greeting and double-blinks the LED in Cyan `(0, 32, 32)`:
```powershell
.\.venv\Scripts\python.exe -c "import serial, time; s = serial.Serial('COM3', 115200, timeout=2); time.sleep(0.2); s.write(b'ping\n'); print(s.readline().decode().strip()); s.close()"
```
Expected output:
```text
Hello World! RP2040 received: 'ping'
```

### B. Teams Status JSON Payload
Sending a JSON object updates the LED state and returns `OK: Teams status set to <Status>`:
```powershell
.\.venv\Scripts\python.exe -c "import serial, time; s = serial.Serial('COM3', 115200, timeout=2); time.sleep(0.2); s.write(b'{\"type\":\"teams_status\",\"status\":\"Available\",\"in_call\":false}\n'); print(s.readline().decode().strip()); s.close()"
```

| `status` Value | `in_call` | RP2040-Zero NeoPixel RGB (`GPIO 16`) | Visual Behavior |
| :--- | :--- | :--- | :--- |
| `"Available"` | `false` | `(0, 32, 0)` | Solid Gentle Green |
| `"Busy"` | `false` | `(32, 0, 0)` | Solid Red |
| `"InACall"` / `"InAMeeting"` (or `"Busy"` + `in_call: true`) | `true` | `(48, 0, 0)` $\leftrightarrow$ `(12, 0, 0)` | Pulsing Red (600ms cycle) |
| `"DoNotDisturb"` | `false` | `(32, 0, 32)` | Solid Magenta / Purple |
| `"Away"` / `"BeRightBack"` | `false` | `(32, 20, 0)` | Solid Amber / Yellow |
| `"Offline"` / `"NotRunning"` | `false` | `(0, 0, 0)` | Off (20ms dim cyan heartbeat blip every 3s) |

---

## 6. Rebuilding & Testing the Host Suite

1. **Run Host Unit Tests**:
   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s host -p "test_*.py"
   ```
2. **Run LTspice Hardware Circuit Verification**:
   ```powershell
   .\.venv\Scripts\python.exe simulation/verify_circuit.py
   ```
3. **Rebuild Standalone `dist\TeamsMonitor.exe`** (stop any running `TeamsMonitor` process first):
   ```powershell
   .\.venv\Scripts\python.exe build_exe.py
   ```
