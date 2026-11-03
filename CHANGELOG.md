# Changelog

All notable changes to the **TeamsStatus** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.5.0] - 2026-11-02

### Added
- **External "On Air" LED Strip PWM Driver (`GPIO 15`)**:
  - Updated [`UnifiedLED`](file:///D:/Git/USBCommunicator/rp2040/code.py#L52-L211) in [`rp2040/code.py`](file:///D:/Git/USBCommunicator/rp2040/code.py) to initialize a `1000 Hz` hardware PWM output on `GPIO 15` (`Right Pin 8` on the Waveshare RP2040-Zero) for driving the external `LR7843` / `D4184` MOSFET module alongside the onboard WS2812 RGB NeoPixel (`GPIO 16`).
  - Implemented **"On Air" Call & Busy** lighting behavior:
    - `InACall` / `InAMeeting` / `DoNotDisturb`: Solid **100% ON** (`PWM_DUTY_FULL = 65535`).
    - `Busy`: Smooth **10%–30% pulsing** (`PWM_DUTY_PULSE_LOW = 6554` $\leftrightarrow$ `PWM_DUTY_PULSE_HIGH = 19661` every `600 ms`, paired with onboard NeoPixel Red pulsing `(12, 0, 0) <-> (48, 0, 0)`).
    - `Available` / `Away` / `BeRightBack` / `Offline` / `NotRunning` / `Unknown`: **OFF** (`0%`, `PWM_DUTY_OFF = 0`).
- **5 V 18-LED White Strip & `D4184` (`HW-532`) Hardware Design + Direct-Drive Guide**:
  - Updated [`docs/USB_C_RP2040_LR7843_CIRCUIT_DESIGN.md`](file:///D:/Git/USBCommunicator/docs/USB_C_RP2040_LR7843_CIRCUIT_DESIGN.md) to model the **18-LED white strip** ($6 \times 150\,\Omega$ parallel segments + onboard `M7` / `1N4007` series input diode, $I_{\text{strip}} = 53.13\,\text{mA}$ at $5.0\,\text{V}$), added a side-by-side comparison of the `LR7843` vs. `D4184` (`AOD4184A` + `EL817`) MOSFET trigger modules ([`docs/Screenshot_31-10-2026_94314_www.aliexpress.us.jpeg`](file:///D:/Git/USBCommunicator/docs/Screenshot_31-10-2026_94314_www.aliexpress.us.jpeg)), and simplified the wiring specification to a 5-wire module-to-module interconnect ($0$ external passive components required).
  - Added [`docs/USB_C_RP2040_LR7843_LED_STRIP_DESIGN.md`](file:///D:/Git/USBCommunicator/docs/USB_C_RP2040_LR7843_LED_STRIP_DESIGN.md) documenting an alternative direct-GPIO drive configuration (bypassing the series `M7` diode to run the LED strip at reduced brightness directly from `GP15` at $3.3\,\text{V}$ without the MOSFET module).
  - Updated [`simulation/usb_rp2040_lr7843.cir`](file:///D:/Git/USBCommunicator/simulation/usb_rp2040_lr7843.cir), [`simulation/usb_rp2040_lr7843.asc`](file:///D:/Git/USBCommunicator/simulation/usb_rp2040_lr7843.asc), and [`simulation/verify_circuit.py`](file:///D:/Git/USBCommunicator/simulation/verify_circuit.py) to simulate the 6-branch $150\,\Omega$ LED strip and series `M7` diode across all 10 automated LTspice verification checks.

### Fixed
- **Intermittent 10–30s Teams Presence Detection Lag**:
  - Fixed [`TeamsLogTailer._read_incremental()`](file:///D:/Git/USBCommunicator/host/teams_detector.py#L517-L561) in [`host/teams_detector.py`](file:///D:/Git/USBCommunicator/host/teams_detector.py) to read in binary mode and advance `self.file_pos` only up to the last complete newline (`\n`), preventing status lines split across `ms-teams.exe`'s 8 KB C++ stdio flush boundaries from being truncated and dropped.
  - Added [`BADGE_STATUS_PATTERN`](file:///D:/Git/USBCommunicator/host/teams_detector.py#L368-L371) (`ShowBadge` / `SetBadge` / `Setting badge ..., status <Status>`) and [`CLOUD_STATE_PATTERN`](file:///D:/Git/USBCommunicator/host/teams_detector.py#L361-L364) (`UserDataCloudState`) to capture the very first log line emitted during a Teams presence change, and updated [`normalize_status()`](file:///D:/Git/USBCommunicator/host/teams_detector.py#L82-L95) to normalize space/hyphen-separated status strings (`"Do not disturb"`, `"Be right back"`).
  - Reduced the default host polling interval in [`host/teams_monitor.py`](file:///D:/Git/USBCommunicator/host/teams_monitor.py) from `1.0s` to `0.5s`.
  - Added [`test_log_tailer_partial_line_and_badge_parsing`](file:///D:/Git/USBCommunicator/host/test_teams_detector.py#L79-L110) unit test in [`host/test_teams_detector.py`](file:///D:/Git/USBCommunicator/host/test_teams_detector.py).

### Changed
- **Repository Rename to `TeamsStatus`**:
  - Renamed project references from `USBCommunicator` to `TeamsStatus` across [`README.md`](file:///D:/Git/USBCommunicator/README.md), [`AGENTS.md`](file:///D:/Git/USBCommunicator/AGENTS.md), [`.agents/skills/rp2040-zero-workflow/SKILL.md`](file:///D:/Git/USBCommunicator/.agents/skills/rp2040-zero-workflow/SKILL.md), [`docs/WINDOWS_STARTUP_GUIDE.md`](file:///D:/Git/USBCommunicator/docs/WINDOWS_STARTUP_GUIDE.md), [`flash_and_deploy_rp2040.py`](file:///D:/Git/USBCommunicator/flash_and_deploy_rp2040.py), and [`host/teams_monitor.py`](file:///D:/Git/USBCommunicator/host/teams_monitor.py) (`STARTUP_APP_NAME = "TeamsStatus_TeamsMonitor"`).

---

## [1.4.0] - 2026-10-31

### Added
- **Automated RP2040 Provisioning & Deployment Script**:
  - Created [`flash_and_deploy_rp2040.py`](file:///D:/Git/USBCommunicator/flash_and_deploy_rp2040.py) to automate onboarding brand-new RP2040 boards in factory `BOOTSEL` mode (`RPI-RP2` USB drive) as well as updating existing boards.
  - Automatically resolves and downloads the latest official MicroPython `.uf2` firmware for `WAVESHARE_RP2040_ZERO` (or `RPI_PICO`), flashes the `RPI-RP2` drive, waits for USB CDC serial enumeration, deploys [`rp2040/boot.py`](file:///D:/Git/USBCommunicator/rp2040/boot.py), [`rp2040/code.py`](file:///D:/Git/USBCommunicator/rp2040/code.py), and [`rp2040/main.py`](file:///D:/Git/USBCommunicator/rp2040/main.py) via `mpremote`, soft-resets the board, and verifies live serial communication at `115200` baud.
- **Agent Workspace Customizations (Rule & Skill)**:
  - Added [`AGENTS.md`](file:///D:/Git/USBCommunicator/AGENTS.md) workspace rule documenting repository architecture, `.venv` tooling paths, Waveshare RP2040-Zero hardware specifics, and COM port lock awareness.
  - Added [`.agents/skills/rp2040-zero-workflow/SKILL.md`](file:///D:/Git/USBCommunicator/.agents/skills/rp2040-zero-workflow/SKILL.md) on-demand skill with an operational runbook for diagnosing `BOOTSEL` (`RPI-RP2`) vs. COM port enumeration, avoiding `PermissionError` port contention, deploying scripts, and testing WS2812 RGB LED status payloads.

### Changed
- **Automatic COM Port Discovery in `connect_mpremote`**:
  - Updated [`connect_mpremote.py`](file:///D:/Git/USBCommunicator/connect_mpremote.py), [`connect_mpremote.bat`](file:///D:/Git/USBCommunicator/connect_mpremote.bat), and [`connect_mpremote.ps1`](file:///D:/Git/USBCommunicator/connect_mpremote.ps1) to auto-detect the connected RP2040 COM port via USB Vendor ID (`0x2E8A`, `0x239A`, `0x1B4F`) instead of hardcoding `COM4`.
- **Documentation**:
  - Updated [`README.md`](file:///D:/Git/USBCommunicator/README.md) with `BOOTSEL` firmware flashing instructions, automated deployment usage, and troubleshooting guidance when an RP2040 mounts as an `RPI-RP2` drive without a COM port.

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
