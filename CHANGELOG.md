# Changelog

All notable changes to the **USB Communicator** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] - 2026-10-10

### Added
- **USB-C Hardware Circuit Design**:
  - Engineered a complete schematic taking in a single USB-C connector to simultaneously power an RP2040 microcontroller and an LR7843 MOSFET module.
  - Implemented dual $5.1\,\text{k}\Omega \pm 1\%$ pull-down resistors on CC1 and CC2 for compliant USB Type-C UFP (Upstream Facing Port) 5.0 V power negotiation.
  - Added series $27\,\Omega \pm 1\%$ damping resistors on USB $D+$ and $D-$ data lines for RP2040 USB 2.0 Full-Speed (12 Mbps) impedance matching.
  - Sized and specified an AP2112K-3.3 low-dropout linear regulator (LDO) with $10\,\mu\text{F}$ input/output ceramic decoupling capacitors to step 5.0 V down to 3.3 V for the RP2040.
  - Integrated the LR7843 MOSFET module featuring PC817/EL817 optocoupler galvanic isolation, $510\,\Omega$ input drive resistance, $10\,\text{k}\Omega$ gate pull-down, and IRLR7843 N-channel HEXFET ($V_{DSS}=30\,\text{V}$, $R_{DS(on)}=3.3\,\text{m}\Omega$).
  - Configured simple white LED load ($V_F \approx 3.0\,\text{V}$) with a $100\,\Omega$ ballast resistor powered from 5.0 V VBUS, achieving nominal $15 - 20\,\text{mA}$ forward current.
- **LTspice Simulation & Verification Suite**:
  - Created graphical LTspice schematic [`simulation/usb_rp2040_lr7843.asc`](file:///D:/git/USBCommunicator/simulation/usb_rp2040_lr7843.asc) for interactive analysis in the LTspice GUI (`C:\Program Files\ADI\LTspice\LTspice.exe`).
  - Created self-contained SPICE netlist [`simulation/usb_rp2040_lr7843.cir`](file:///D:/git/USBCommunicator/simulation/usb_rp2040_lr7843.cir) with diode, optocoupler, and MOSFET subcircuits plus `.meas` directives.
  - Created automated Python test runner [`simulation/verify_circuit.py`](file:///D:/git/USBCommunicator/simulation/verify_circuit.py) that invokes LTspice in batch mode and verifies 10 electrical parameters (VBUS, 3.3V rail, CC negotiation, $V_{GS}$, $V_{DS}$, $I_{LED}$, off-state leakage, and dissipation).
- **Documentation**:
  - Published comprehensive engineering specification and BOM in [`docs/USB_C_RP2040_LR7843_CIRCUIT_DESIGN.md`](file:///D:/git/USBCommunicator/docs/USB_C_RP2040_LR7843_CIRCUIT_DESIGN.md).

### Changed
- Updated [`.gitignore`](file:///D:/git/USBCommunicator/.gitignore) to exclude binary LTspice simulation outputs (`*.raw`, `*.op.raw`, `*.db`, `*.net`, `*.log`).

---

## [1.2.0] - 2026-08-20

### Added
- **MicroPython Hardware Migration**:
  - Refactored [`rp2040/code.py`](file:///D:/git/USBCommunicator/rp2040/code.py) to use standard MicroPython libraries (`machine`, `select`/`uselect`, `sys`, `time`), replacing CircuitPython modules (`board`, `digitalio`, `usb_cdc`).
  - Added `UnifiedLED` hardware abstraction supporting WS2812 NeoPixels (Waveshare RP2040-Zero on GPIO 16) and single-color GPIO LEDs (Pico pin 'LED'/GPIO 25, Adafruit Feather GPIO 13).
  - Implemented non-blocking serial CDC reception on `sys.stdin` via `select.poll()`.

---

## [1.1.0] - 2026-08-20

### Added
- **Local Teams Detection Engine**:
  - Added [`host/teams_detector.py`](file:///D:/Git/USBCommunicator/host/teams_detector.py) with 100% offline detection combining log tailing, Windows CapabilityAccessManager registry tracking (microphone/camera active detection), Win32 Toolhelp32 process scanning, and desktop lock state.
- **Teams Monitor Dispatcher & Windows Startup**:
  - Added [`host/teams_monitor.py`](file:///D:/Git/USBCommunicator/host/teams_monitor.py) with hardware VID/PID auto-discovery, hot-plug reconnect loop, and telemetry serialization.
  - Added PyInstaller build automation ([`build_exe.py`](file:///D:/Git/USBCommunicator/build_exe.py) / [`build_exe.bat`](file:///D:/Git/USBCommunicator/build_exe.bat)) producing standalone executable `TeamsMonitor.exe`.
  - Added Windows Startup registration via `--install-startup` and `--uninstall-startup`.
- **Documentation**:
  - Added [`docs/WINDOWS_STARTUP_GUIDE.md`](file:///D:/Git/USBCommunicator/docs/WINDOWS_STARTUP_GUIDE.md).

---

## [1.0.0] - 2026-08-04

### Added
- Initial release of USB CDC serial communication framework between Windows and RP2040 microcontroller.
- Interactive terminal client [`host/host_communicator.py`](file:///D:/Git/USBCommunicator/host/host_communicator.py).
