# USBCommunicator Workspace Guidelines

## Project Overview
This repository implements a 100% local, zero-network Microsoft Teams presence monitor and USB CDC serial communication bridge (`115200` baud) driving a **Waveshare RP2040-Zero** (or Raspberry Pi Pico) running **MicroPython**, plus an accompanying LTspice-verified USB-C & LR7843 MOSFET hardware circuit design.

## Python & Tooling Environment
- **Virtual Environment**: Always use `.venv\Scripts\python.exe` and `.venv\Scripts\mpremote.exe` when executing Python scripts, tests, or `mpremote` commands on Windows.
- **Hardware Provisioning & Deployment**: Use [`flash_and_deploy_rp2040.py`](file:///D:/Git/USBCommunicator/flash_and_deploy_rp2040.py) to flash MicroPython UF2 firmware (when in `BOOTSEL` / `RPI-RP2` drive mode), auto-discover the COM port, deploy `rp2040/*.py`, and verify serial communication.
- **mpremote Wrapper**: [`connect_mpremote.py`](file:///D:/Git/USBCommunicator/connect_mpremote.py) auto-detects the RP2040 COM port via USB Vendor ID (`0x2E8A`, `0x239A`, `0x1B4F`).

## Architecture & Key Components
- **Microcontroller (`rp2040/`)**:
  - Target board: **Waveshare RP2040-Zero** (`WAVESHARE_RP2040_ZERO`, USB VID `0x2E8A`, onboard WS2812 RGB NeoPixel on `GPIO 16`). Also compatible with standard Raspberry Pi Pico (`LED` / `GPIO 25`).
  - Boot lifecycle: [`rp2040/boot.py`](file:///D:/Git/USBCommunicator/rp2040/boot.py) (runs `gc.collect()`) $\rightarrow$ [`rp2040/main.py`](file:///D:/Git/USBCommunicator/rp2040/main.py) (executes `code.py`) $\rightarrow$ [`rp2040/code.py`](file:///D:/Git/USBCommunicator/rp2040/code.py) (`UnifiedLED` abstraction + non-blocking `select.poll()` on `sys.stdin`).
- **Host Monitor (`host/`)**:
  - [`host/teams_detector.py`](file:///D:/Git/USBCommunicator/host/teams_detector.py): Combines `MSTeams_*.log` byte-offset tailing, Windows Registry `CapabilityAccessManager` mic/webcam timestamps, `ms-teams.exe` process scanning, and workstation lock detection.
  - [`host/teams_monitor.py`](file:///D:/Git/USBCommunicator/host/teams_monitor.py): Polls `TeamsDetector`, dispatches newline-terminated JSON payloads and 5-second heartbeats over serial (`--port auto`), and manages `HKCU\...\Run` startup registration.
  - [`host/test_teams_detector.py`](file:///D:/Git/USBCommunicator/host/test_teams_detector.py): Unit test suite (`.\.venv\Scripts\python.exe -m unittest discover -s host -p "test_*.py"`).
- **Standalone Executable (`dist/TeamsMonitor.exe`)**:
  - Built via [`build_exe.py`](file:///D:/Git/USBCommunicator/build_exe.py) (`.\.venv\Scripts\python.exe build_exe.py`).
  - **Port Contention Note**: If `TeamsMonitor.exe` or `teams_monitor.py` is running in the background, it holds an exclusive lock on the RP2040 COM port. Stop it before running `mpremote`, [`flash_and_deploy_rp2040.py`](file:///D:/Git/USBCommunicator/flash_and_deploy_rp2040.py), or [`host/host_communicator.py`](file:///D:/Git/USBCommunicator/host/host_communicator.py).
- **Hardware Simulation (`simulation/`)**:
  - [`simulation/verify_circuit.py`](file:///D:/Git/USBCommunicator/simulation/verify_circuit.py) runs LTspice in batch mode against [`simulation/usb_rp2040_lr7843.cir`](file:///D:/Git/USBCommunicator/simulation/usb_rp2040_lr7843.cir) and validates 10 electrical measurements.
