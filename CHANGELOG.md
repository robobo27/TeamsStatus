# Changelog

All notable changes to the **TeamsStatus** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.7.0] - 2026-11-04

### Added
- **Taskbar Status Driver Priority & Signal Controls ([`host/system_tray.py`](host/system_tray.py), [`host/teams_detector.py`](host/teams_detector.py))**:
  - Added [`StatusPriorityConfig`](host/teams_detector.py#L628-L824) allowing users to reorder status drivers (`Move Up` / `Move Down`), toggle individual signals on or off, or apply 1-click presets (`Corporate Safe`, `Hardware First`, `Teams Log Only`, `Strict`) directly from the **`Priority & Signals (Top Wins)`** cascading submenu in the Windows Notification Area (System Tray) icon.
  - Persists user priority order and signal enable/disable settings in the Windows Registry (`HKCU\Software\TeamsStatus\PriorityConfig`) and triggers immediate state re-evaluation and RP2040 synchronization in [`host/teams_monitor.py`](host/teams_monitor.py#L502-L508).
- **Status Driver & Sensor Diagnostics in Tray Tooltip, Context Menu, and Console**:
  - Extended [`TeamsStatusEvent`](host/teams_detector.py#L118-L171) with `status_source`, `log_source`, and `meeting_count`.
  - Updated the System Tray hover tooltip, popup context menu, and console log output to display what is actively driving the status (`Driven By: ...`) alongside individual sensor states (`Teams Log`, `Meeting Size`, `Microphone`, `Camera`, and `Session`).
  - Added [`test_custom_priority_and_signal_toggles`](host/test_teams_detector.py#L291-L366) unit test in [`host/test_teams_detector.py`](host/test_teams_detector.py).

### Fixed
- **False `InACall` Status While `Available` on Corporate Microsoft Teams ([`host/teams_detector.py`](host/teams_detector.py))**:
  - Stopped treating `cross_cloud::meetingstore: meetings size: > 0` as a default active call trigger (`meeting_size` now defaults to disabled in `StatusPriorityConfig`), as corporate Teams caches scheduled Outlook/Exchange calendar entries in `meetingstore` for the Windows Taskbar JumpList even when not in a call.
  - Prevented explicit `Available` presence in Teams logs from being overridden to `InACall` under the default `Corporate Safe` priority order (`Teams Log Presence` ranked above `Microphone` / `Camera`), while still promoting `Busy` $\rightarrow$ `InACall` when active hardware capture (`mic_active` / `camera_active`) or explicit call log tokens (`InACall` / `InAMeeting` / `OnACall`) are present.
  - Tightened `NonPackaged` registry matching in [`WindowsHardwareTracker._is_capability_in_use()`](host/teams_detector.py#L322-L325) to match exact Teams executable filenames (`ms-teams.exe`, `msteams.exe`, `teams.exe`).

---

## [1.6.0] - 2026-11-03

### Added
- **Windows Notification Area (System Tray) Icon & "Stop" Menu ([`host/system_tray.py`](host/system_tray.py))**:
  - Added [`SystemTrayIcon`](host/system_tray.py#L283-L469) using pure Win32 `ctypes` (`Shell_NotifyIconW`, `CreateDIBSection`, `CreateIconIndirect`) with zero external dependencies.
  - Dynamically renders a 32×32 circular badge icon in the Windows notification area colored by live Teams presence (`Green` for `Available`, `Red` for `InACall`/`InAMeeting`/`DoNotDisturb`/`Busy`, `Amber` for `Away`/`BeRightBack`, and `Gray` for `Offline`/`NotRunning`).
  - Displays a live hover tooltip showing the active Teams status, `[ON AIR]` / `[PULSE]` state, and connected RP2040 COM port.
  - Added a click / right-click context menu displaying live status, RP2040 connection status, and a **`Stop TeamsMonitor`** action that signals [`host/teams_monitor.py`](host/teams_monitor.py) to send an `"Offline"` frame to the RP2040 (turning off the LED strip and NeoPixel), remove the tray icon, and terminate cleanly.
  - Added `--no-tray` CLI flag to [`host/teams_monitor.py`](host/teams_monitor.py#L404-L408) if headless execution without a tray icon is ever desired.
  - Rebuilt standalone executable [`dist/TeamsMonitor.exe`](dist/TeamsMonitor.exe) with the system tray icon and 8 KB log buffer lag fix bundled.

---

## [1.5.0] - 2026-11-02

### Added
- **External "On Air" LED Strip PWM Driver (`GPIO 15`)**:
  - Updated [`UnifiedLED`](rp2040/code.py#L52-L211) in [`rp2040/code.py`](rp2040/code.py) to initialize a `1000 Hz` hardware PWM output on `GPIO 15` (`Right Pin 8` on the Waveshare RP2040-Zero) for driving the external `LR7843` / `D4184` MOSFET module alongside the onboard WS2812 RGB NeoPixel (`GPIO 16`).
  - Implemented **"On Air" Call & Busy** lighting behavior:
    - `InACall` / `InAMeeting` / `DoNotDisturb`: Solid **100% ON** (`PWM_DUTY_FULL = 65535`).
    - `Busy`: Smooth **10%–30% pulsing** (`PWM_DUTY_PULSE_LOW = 6554` $\leftrightarrow$ `PWM_DUTY_PULSE_HIGH = 19661` every `600 ms`, paired with onboard NeoPixel Red pulsing `(12, 0, 0) <-> (48, 0, 0)`).
    - `Available` / `Away` / `BeRightBack` / `Offline` / `NotRunning` / `Unknown`: **OFF** (`0%`, `PWM_DUTY_OFF = 0`).
- **5 V 18-LED White Strip & `D4184` (`HW-532`) Hardware Design + Direct-Drive Guide**:
  - Updated [`docs/USB_C_RP2040_LR7843_CIRCUIT_DESIGN.md`](docs/USB_C_RP2040_LR7843_CIRCUIT_DESIGN.md) to model the **18-LED white strip** ($6 \times 150\,\Omega$ parallel segments + onboard `M7` / `1N4007` series input diode, $I_{\text{strip}} = 53.13\,\text{mA}$ at $5.0\,\text{V}$), added a side-by-side comparison of the `LR7843` vs. `D4184` (`AOD4184A` + `EL817`) MOSFET trigger modules ([`docs/Screenshot_31-10-2026_94314_www.aliexpress.us.jpeg`](docs/Screenshot_31-10-2026_94314_www.aliexpress.us.jpeg)), and simplified the wiring specification to a 5-wire module-to-module interconnect ($0$ external passive components required).
  - Added [`docs/USB_C_RP2040_LR7843_LED_STRIP_DESIGN.md`](docs/USB_C_RP2040_LR7843_LED_STRIP_DESIGN.md) documenting an alternative direct-GPIO drive configuration (bypassing the series `M7` diode to run the LED strip at reduced brightness directly from `GP15` at $3.3\,\text{V}$ without the MOSFET module).
  - Updated [`simulation/usb_rp2040_lr7843.cir`](simulation/usb_rp2040_lr7843.cir), [`simulation/usb_rp2040_lr7843.asc`](simulation/usb_rp2040_lr7843.asc), and [`simulation/verify_circuit.py`](simulation/verify_circuit.py) to simulate the 6-branch $150\,\Omega$ LED strip and series `M7` diode across all 10 automated LTspice verification checks.

### Fixed
- **Intermittent 10–30s Teams Presence Detection Lag**:
  - Fixed [`TeamsLogTailer._read_incremental()`](host/teams_detector.py#L517-L561) in [`host/teams_detector.py`](host/teams_detector.py) to read in binary mode and advance `self.file_pos` only up to the last complete newline (`\n`), preventing status lines split across `ms-teams.exe`'s 8 KB C++ stdio flush boundaries from being truncated and dropped.
  - Added [`BADGE_STATUS_PATTERN`](host/teams_detector.py#L368-L371) (`ShowBadge` / `SetBadge` / `Setting badge ..., status <Status>`) and [`CLOUD_STATE_PATTERN`](host/teams_detector.py#L361-L364) (`UserDataCloudState`) to capture the very first log line emitted during a Teams presence change, and updated [`normalize_status()`](host/teams_detector.py#L82-L95) to normalize space/hyphen-separated status strings (`"Do not disturb"`, `"Be right back"`).
  - Reduced the default host polling interval in [`host/teams_monitor.py`](host/teams_monitor.py) from `1.0s` to `0.5s`.
  - Added [`test_log_tailer_partial_line_and_badge_parsing`](host/test_teams_detector.py#L79-L110) unit test in [`host/test_teams_detector.py`](host/test_teams_detector.py).

### Changed
- **Repository Rename to `TeamsStatus`**:
  - Renamed project references from `USBCommunicator` to `TeamsStatus` across [`README.md`](README.md), [`AGENTS.md`](AGENTS.md), [`.agents/skills/rp2040-zero-workflow/SKILL.md`](.agents/skills/rp2040-zero-workflow/SKILL.md), [`docs/WINDOWS_STARTUP_GUIDE.md`](docs/WINDOWS_STARTUP_GUIDE.md), [`flash_and_deploy_rp2040.py`](flash_and_deploy_rp2040.py), and [`host/teams_monitor.py`](host/teams_monitor.py) (`STARTUP_APP_NAME = "TeamsStatus_TeamsMonitor"`).

---

## [1.4.0] - 2026-10-31

### Added
- **Automated RP2040 Provisioning & Deployment Script**:
  - Created [`flash_and_deploy_rp2040.py`](flash_and_deploy_rp2040.py) to automate onboarding brand-new RP2040 boards in factory `BOOTSEL` mode (`RPI-RP2` USB drive) as well as updating existing boards.
  - Automatically resolves and downloads the latest official MicroPython `.uf2` firmware for `WAVESHARE_RP2040_ZERO` (or `RPI_PICO`), flashes the `RPI-RP2` drive, waits for USB CDC serial enumeration, deploys [`rp2040/boot.py`](rp2040/boot.py), [`rp2040/code.py`](rp2040/code.py), and [`rp2040/main.py`](rp2040/main.py) via `mpremote`, soft-resets the board, and verifies live serial communication at `115200` baud.
- **Agent Workspace Customizations (Rule & Skill)**:
  - Added [`AGENTS.md`](AGENTS.md) workspace rule documenting repository architecture, `.venv` tooling paths, Waveshare RP2040-Zero hardware specifics, and COM port lock awareness.
  - Added [`.agents/skills/rp2040-zero-workflow/SKILL.md`](.agents/skills/rp2040-zero-workflow/SKILL.md) on-demand skill with an operational runbook for diagnosing `BOOTSEL` (`RPI-RP2`) vs. COM port enumeration, avoiding `PermissionError` port contention, deploying scripts, and testing WS2812 RGB LED status payloads.

### Changed
- **Automatic COM Port Discovery in `connect_mpremote`**:
  - Updated [`connect_mpremote.py`](connect_mpremote.py), [`connect_mpremote.bat`](connect_mpremote.bat), and [`connect_mpremote.ps1`](connect_mpremote.ps1) to auto-detect the connected RP2040 COM port via USB Vendor ID (`0x2E8A`, `0x239A`, `0x1B4F`) instead of hardcoding `COM4`.
- **Documentation**:
  - Updated [`README.md`](README.md) with `BOOTSEL` firmware flashing instructions, automated deployment usage, and troubleshooting guidance when an RP2040 mounts as an `RPI-RP2` drive without a COM port.

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
  - Created graphical LTspice schematic [`simulation/usb_rp2040_lr7843.asc`](simulation/usb_rp2040_lr7843.asc) for interactive analysis in the LTspice GUI (`LTspice.exe`).
  - Created self-contained SPICE netlist [`simulation/usb_rp2040_lr7843.cir`](simulation/usb_rp2040_lr7843.cir) with diode, optocoupler, and MOSFET subcircuits plus `.meas` directives.
  - Created automated Python test runner [`simulation/verify_circuit.py`](simulation/verify_circuit.py) that invokes LTspice in batch mode and verifies 10 electrical parameters (VBUS, 3.3V rail, CC negotiation, $V_{GS}$, $V_{DS}$, $I_{LED}$, off-state leakage, and dissipation).
- **Documentation**:
  - Published comprehensive engineering specification and BOM in [`docs/USB_C_RP2040_LR7843_CIRCUIT_DESIGN.md`](docs/USB_C_RP2040_LR7843_CIRCUIT_DESIGN.md).

### Changed
- Updated [`.gitignore`](.gitignore) to exclude binary LTspice simulation outputs (`*.raw`, `*.op.raw`, `*.db`, `*.net`, `*.log`).

---

## [1.2.0] - 2026-08-20

### Added
- **MicroPython Hardware Migration**:
  - Refactored [`rp2040/code.py`](rp2040/code.py) to use standard MicroPython libraries (`machine`, `select`/`uselect`, `sys`, `time`), replacing CircuitPython modules (`board`, `digitalio`, `usb_cdc`).
  - Added `UnifiedLED` hardware abstraction supporting WS2812 NeoPixels (Waveshare RP2040-Zero on GPIO 16) and single-color GPIO LEDs (Pico pin 'LED'/GPIO 25, Adafruit Feather GPIO 13).
  - Implemented non-blocking serial CDC reception on `sys.stdin` via `select.poll()`.

---

## [1.1.0] - 2026-08-20

### Added
- **Local Teams Detection Engine**:
  - Added [`host/teams_detector.py`](host/teams_detector.py) with 100% offline detection combining log tailing, Windows CapabilityAccessManager registry tracking (microphone/camera active detection), Win32 Toolhelp32 process scanning, and desktop lock state.
- **Teams Monitor Dispatcher & Windows Startup**:
  - Added [`host/teams_monitor.py`](host/teams_monitor.py) with hardware VID/PID auto-discovery, hot-plug reconnect loop, and telemetry serialization.
  - Added PyInstaller build automation ([`build_exe.py`](build_exe.py) / [`build_exe.bat`](build_exe.bat)) producing standalone executable `TeamsMonitor.exe`.
  - Added Windows Startup registration via `--install-startup` and `--uninstall-startup`.
- **Documentation**:
  - Added [`docs/WINDOWS_STARTUP_GUIDE.md`](docs/WINDOWS_STARTUP_GUIDE.md).

---

## [1.0.0] - 2026-08-04

### Added
- Initial release of USB CDC serial communication framework between Windows and RP2040 microcontroller.
- Interactive terminal client [`host/host_communicator.py`](host/host_communicator.py).
