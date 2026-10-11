# USB-C Powered RP2040 and LR7843 White LED Driver Circuit Design & LTspice Verification

## 1. Executive Summary

This document specifies the circuit design, theory of operation, bill of materials (BOM), and LTspice verification for a USB Type-C powered system comprising:
1. **USB Type-C Upstream Facing Port (UFP)** with standard 5.1 kΩ configuration channel (CC) pull-down resistors for USB-PD / Type-C 5V negotiation.
2. **RP2040 Microcontroller** powered via a 5.0 V to 3.3 V low-dropout regulator (AP2112K-3.3) with USB 2.0 Full-Speed (12 Mbps) data lines ($D+$, $D-$) routed through 27 Ω termination resistors for bidirectional host communication.
3. **LR7843 Power MOSFET Module** driven by an RP2040 3.3 V GPIO / PWM output via an optocoupled gate drive (PC817/EL817) and an ultra-low $R_{DS(on)}$ N-channel MOSFET (IRLR7843).
4. **White LED Load** powered from the 5.0 V USB rail with a 100 Ω current-limiting resistor (nominal 15–20 mA forward current).

The circuit design is verified in **LTspice** (located at `C:\Program Files\ADI\LTspice\LTspice.exe`) using automated SPICE simulations for transient power-up, USB CC negotiation, LDO rail regulation, gate switching dynamics, and LED forward current.

---

## 2. Complete System Schematic Diagram

```
                                  +5.0V (VBUS)
                                      |
                      +---------------+-------------------------+
                      |               |                         |
               [CIN: 10uF + 100nF]    |                         |
                      |          [AP2112K LDO]            [R_BALLAST: 100R]
                     GND              |                         |
                                 +3.3V Rail                [WHITE LED]
                                      | (VCC_3V3)               |
                                      |                    (Anode -> Cathode)
+-----------------------+             |                         |
| USB-C Receptacle      |             |                         | (LOAD-)
|                       |             v                         v
| VBUS (A4,A9,B4,B9) ---+----> [RP2040 MCU]              [LR7843 MODULE]
| GND  (A1,A12,B1,B12) -+----> GND                       |              |
| CC1  (A5) ------------+----> R_CC1: 5.1k -> GND        | DC+  -> 5.0V |
| CC2  (B5) ------------+----> R_CC2: 5.1k -> GND        | DC-  -> GND  |
| D+   (A6,B6) ---------+----> R_TERM_DP: 27R -> USB_DP  | LOAD+ -> 5.0V|
| D-   (A7,B7) ---------+----> R_TERM_DM: 27R -> USB_DM  | LOAD- -> LED-|
| Shield / Case --------+----> GND                       | PWM+ <- GPIO |
+-----------------------+                                | PWM- <- GND  |
                                                         +--------------+
                                                                |
                                                               GND
```

### Module-Level Block Flow (Mermaid)

```mermaid
flowchart TD
    subgraph Host["Host PC / Charger"]
        USBC_HOST["USB-C Host Port\n5.0V VBUS, D+, D-, CC"]
    end

    subgraph Power["Power Distribution & Regulation"]
        VBUS["5.0V VBUS Rail\nC_bulk = 10uF, C_hf = 100nF"]
        LDO["3.3V LDO (AP2112K)\nDropout <= 250mV"]
        V33["3.3V System Rail\nRP2040 IOVDD / VREG_IN"]
    end

    subgraph MCU["RP2040 Controller Subsystem"]
        RP2040["Raspberry Pi RP2040\nCortex-M0+ Dual Core"]
        USB_TERM["USB Series Resistors\n27R on D+, 27R on D-"]
        GPIO["GPIO Output (Pin 16 / PWM)\n3.3V Logic Level"]
    end

    subgraph Driver["LR7843 MOSFET Module Subsystem"]
        OPTO["PC817 Optocoupler\nSeries Rin = 510R"]
        GATE_DRIVE["Gate Pull-Down (10k)\nPhototransistor Pull-Up to 5V"]
        MOSFET["IRLR7843 N-MOSFET\nVds=30V, Rds(on)=3.3mR"]
    end

    subgraph Load["White LED Subsystem"]
        BALLAST["Ballast Resistor\n100R, 1/4W"]
        WHITE_LED["White Indicator LED\nVf = 3.0V @ 15-20mA"]
    end

    USBC_HOST -->|VBUS 5.0V| VBUS
    USBC_HOST -->|D+ / D-| USB_TERM
    USB_TERM --> RP2040
    VBUS --> LDO
    LDO --> V33
    V33 --> RP2040
    RP2040 -->|PWM / 3.3V Signal| GPIO
    GPIO --> OPTO
    VBUS -->|5.0V Gate Rail| GATE_DRIVE
    OPTO --> GATE_DRIVE
    GATE_DRIVE --> MOSFET
    VBUS --> BALLAST
    BALLAST --> WHITE_LED
    WHITE_LED -->|Cathode to Drain| MOSFET
    MOSFET -->|Source to Ground| Power
```

---

## 3. Circuit Subsystems & Design Equations

### 3.1 USB-C Upstream Facing Port (UFP) Interface
- **Power Negotiation (CC1 & CC2)**:
  According to the USB Type-C Specification Section 4.5.1, any device acting as an Upstream Facing Port (UFP / power sink) must present separate $5.1\,\text{k}\Omega \pm 10\%$ pull-down resistors ($R_d$) to GND on pin `CC1` (A5) and pin `CC2` (B5).
  - When connected to a Type-C source (DFP), the host monitors the CC lines. The connected CC line forms a voltage divider with the host's pull-up resistor ($R_p = 36\,\text{k}\Omega$ for standard 500 mA / 900 mA power):
    $$V_{CC} = 5.0\,\text{V} \times \frac{5.1\,\text{k}\Omega}{36\,\text{k}\Omega + 5.1\,\text{k}\Omega} = 0.620\,\text{V}$$
  - A measured voltage in the window $0.25\,\text{V} \le V_{CC} \le 2.04\,\text{V}$ signals a valid connection, prompting the host to turn on the 5.0 V VBUS supply.
  - *Caution*: Never connect CC1 and CC2 together to a single 5.1 kΩ resistor. E-marked cables require independent detection.
- **USB 2.0 Data Line Termination**:
  - The RP2040 on-chip USB Full-Speed (12 Mbps) transceiver has an internal output impedance of approximately $18\,\Omega$.
  - To match the standard single-ended $45\,\Omega$ (differential $90\,\Omega$) transmission line impedance:
    $$R_{ext} = 45\,\Omega - 18\,\Omega = 27\,\Omega \pm 1\%$$
  - Place $R_1 = 27\,\Omega$ on $D+$ (USB_DP) and $R_2 = 27\,\Omega$ on $D-$ (USB_DM) as close to the RP2040 pins as possible.

### 3.2 5.0 V to 3.3 V Power Regulation
- **LDO Selection**: Diodes Inc. **AP2112K-3.3** (or Torex XC6206 / Richtek RT9193).
  - Input voltage: 5.0 V nominal from VBUS.
  - Output voltage: 3.3 V $\pm 1.5\%$.
  - Dropout voltage: $\le 250\,\text{mV}$ at 600 mA (easily satisfied with $5.0 - 3.3 = 1.7\,\text{V}$ headroom).
  - Maximum output current: 600 mA (RP2040 draws ~35 mA; plenty of margin).
- **Decoupling Capacitors**:
  - Input: $10\,\mu\text{F}$ 16V X7R ceramic capacitor + $100\,\text{nF}$ 0603 bypass cap.
  - Output: $10\,\mu\text{F}$ 10V X7R ceramic capacitor + $100\,\text{nF}$ 0603 bypass cap.

### 3.3 LR7843 MOSFET Module Subsystem
- **Module Overview**:
  The LR7843 module uses an **IRLR7843PBF** N-channel MOSFET driven by an on-board **PC817 / EL817** optocoupler.
  - $V_{DSS} = 30\,\text{V}$
  - $I_D = 161\,\text{A}$ (pulsed) / package continuous limit ~30–50 A.
  - $R_{DS(on)} = 3.3\,\text{m}\Omega$ at $V_{GS} = 4.5\,\text{V}$.
  - Threshold voltage $V_{GS(th)} = 1.4\,\text{V} - 2.3\,\text{V}$.
- **Input Optocoupler Drive**:
  - The module input consists of an on-board current limiting resistor ($R_{in} \approx 510\,\Omega$) in series with the PC817 infrared emitter diode ($V_F \approx 1.2\,\text{V}$).
  - When the RP2040 GPIO outputs a HIGH (3.3 V):
    $$I_F = \frac{V_{GPIO} - V_{F(opto)}}{R_{in}} = \frac{3.3\,\text{V} - 1.2\,\text{V}}{510\,\Omega} = 4.12\,\text{mA}$$
    This provides robust optocoupler activation well within the RP2040 GPIO current limit (up to 12 mA per pin).
- **Gate Drive & Discharge**:
  - The optocoupler phototransistor collector connects to the 5.0 V VBUS rail; its emitter connects to the MOSFET gate.
  - A $10\,\text{k}\Omega$ pull-down resistor on the module discharges the gate to 0 V when the optocoupler turns off.
  - When active, the gate is pulled up to:
    $$V_{GS} = V_{BUS} - V_{CE(sat)} \approx 5.0\,\text{V} - 0.05\,\text{V} = 4.95\,\text{V}$$
    At $V_{GS} \approx 4.95\,\text{V}$, the IRLR7843 is fully saturated into its lowest $R_{DS(on)}$ region ($3.3\,\text{m}\Omega$).

### 3.4 White LED Load & Ballast Resistor Calculation
- For a standard high-brightness white indicator LED:
  - Typical forward voltage: $V_F \approx 3.0\,\text{V}$ (range 2.8 V – 3.2 V).
  - Target forward current: $I_F = 15 - 20\,\text{mA}$.
  - Supply voltage: $V_{BUS} = 5.0\,\text{V}$.
  - MOSFET on-state drop: $V_{DS} = I_F \times R_{DS(on)} = 0.020\,\text{A} \times 0.0033\,\Omega \approx 66\,\mu\text{V} \approx 0\,\text{V}$.
  - Ballast resistor sizing:
    $$R_{BALLAST} = \frac{V_{BUS} - V_F - V_{DS}}{I_F} = \frac{5.0\,\text{V} - 3.0\,\text{V}}{0.020\,\text{A}} = 100\,\Omega$$
  - Power dissipation in resistor:
    $$P_{R} = I_F^2 \times R_{BALLAST} = (0.020)^2 \times 100 = 0.040\,\text{W} = 40\,\text{mW}$$
    A standard 1/4-Watt (250 mW) 0805 SMD or through-hole resistor operates at only 16% of its rating, remaining cool.
- *High-Power Alternative (1-Watt White LED)*:
  - $V_F \approx 3.2\,\text{V}$, $I_F = 300\,\text{mA}$.
  - $R_{BALLAST} = \frac{5.0 - 3.2}{0.300} = 6.0\,\Omega$.
  - Resistor power: $P_R = 0.3^2 \times 6.0 = 0.54\,\text{W}$ (use 1W or 2W rated resistor).

---

## 4. Bill of Materials (BOM)

| Designator | Description | Value / Part Number | Package | Qty | Purpose |
|---|---|---|---|---|---|
| **J1** | USB Type-C Receptacle (16-pin USB 2.0) | TYPE-C-31-M-12 / GCT USB4085 | SMD / Through-hole | 1 | Power & Data interface |
| **U1** | 3.3V Low-Dropout Linear Regulator | AP2112K-3.3TRG1 / RT9193-33 | SOT-23-5 | 1 | 5V to 3.3V regulation for RP2040 |
| **U2** | RP2040 Microcontroller (or Pico / RP2040-Zero) | RP2040 / Raspberry Pi Pico | QFN-56 / Module | 1 | USB CDC communication & PWM |
| **MOD1** | LR7843 MOSFET Control Module | Waveshare / Generic LR7843 Module | Pre-assembled PCB | 1 | Opto-isolated high-current switch |
| **D1** | Simple White LED (High-Brightness) | Cree C503C-WAN / Kingbright L-7113UWC | 5mm Through-hole / 0805 | 1 | Visual light output |
| **R_CC1, R_CC2** | CC Pull-down Resistors | $5.1\,\text{k}\Omega \pm 1\%$, 0.1W | 0603 / Through-hole | 2 | USB-C UFP power negotiation |
| **R_TERM_DP, R_TERM_DM** | USB Termination Resistors | $27\,\Omega \pm 1\%$, 0.1W | 0603 / Through-hole | 2 | USB 2.0 impedance matching |
| **R_BALLAST** | LED Current Limiting Resistor | $100\,\Omega \pm 5\%$, 0.25W | 0805 / Axial 1/4W | 1 | Sets LED current to ~15-20 mA |
| **C_IN1, C_OUT1** | Ceramic Decoupling Capacitors | $10\,\mu\text{F}$, 16V X7R | 0805 Ceramic | 2 | LDO input/output bulk stability |
| **C_IN2, C_OUT2** | High-Frequency Bypass Capacitors | $100\,\text{nF}$, 25V X7R | 0603 Ceramic | 2 | Noise suppression |
| **D_TVS** *(optional)* | USB ESD Protection Diode Array | USBLC6-2SC6 | SOT-23-6 | 1 | ESD protection on D+, D-, VBUS |

---

## 5. LTspice Simulation & Automated Verification

### 5.1 Verification Files Located in Workspace
All simulation assets have been built and verified in `simulation/`:
- **`simulation/usb_rp2040_lr7843.asc`**: Graphical LTspice schematic file. Open directly in LTspice GUI.
- **`simulation/usb_rp2040_lr7843.cir`**: SPICE netlist with models, transient directives, and `.meas` expressions.
- **`simulation/verify_circuit.py`**: Python automated verification runner and regression test suite.

### 5.2 Running the Automated Verification Suite
From PowerShell or Command Prompt, run:
```powershell
python D:\Git\USBCommunicator\simulation\verify_circuit.py
```

### 5.3 LTspice Simulation Results (Direct from Simulator)

The circuit was simulated using the LTspice engine (`LTspice 26.1.1` at `C:\Program Files\ADI\LTspice\LTspice.exe`). All 10 electrical parameters passed:

| Measurement Parameter | SPICE Node / Expression | Simulated Value | Target Specification | Status |
|---|---|---|---|---|
| **USB VBUS Supply Voltage** | `AVG(V(VBUS))` | **5.0000 V** | $4.75\,\text{V} - 5.25\,\text{V}$ | **PASS** |
| **RP2040 3.3V Power Rail** | `AVG(V(VCC_3V3))` | **3.2986 V** | $3.20\,\text{V} - 3.40\,\text{V}$ | **PASS** |
| **USB-C CC1 Voltage** | `AVG(V(CC1))` | **0.6204 V** | $0.25\,\text{V} - 2.04\,\text{V}$ | **PASS** |
| **USB-C CC2 Voltage** | `AVG(V(CC2))` | **0.6204 V** | $0.25\,\text{V} - 2.04\,\text{V}$ | **PASS** |
| **LR7843 Gate ON Voltage ($V_{GS}$)** | `MAX(V(FET_GATE))` | **4.9854 V** | $4.50\,\text{V} - 5.10\,\text{V}$ | **PASS** |
| **LR7843 Gate OFF Voltage ($V_{GS}$)** | `MIN(V(FET_GATE))` | **-0.58 µV** | $-0.10\,\text{V} - 0.50\,\text{V}$ | **PASS** |
| **White LED ON Current** | `MAX(I(R_BALLAST))` | **15.03 mA** | $10\,\text{mA} - 25\,\text{mA}$ | **PASS** |
| **White LED OFF Leakage** | `MIN(I(R_BALLAST))` | **0.11 µA** | $< 10\,\mu\text{A}$ | **PASS** |
| **LR7843 On-State Drop ($V_{DS}$)** | `MIN(V(LOAD_MINUS))` | **-79.76 µV** | $< 10\,\text{mV}$ | **PASS** |
| **LR7843 Conduction Dissipation** | `AVG(V(LOAD_MINUS)*Id(M))` | **3.84 µW** | $< 10\,\text{mW}$ | **PASS** |

### 5.4 How to View Waveforms Interactively in LTspice GUI
1. Open LTspice: `C:\Program Files\ADI\LTspice\LTspice.exe`.
2. Choose **File > Open** and browse to `D:\Git\USBCommunicator\simulation\usb_rp2040_lr7843.asc`.
3. Click the **Run** button (running person icon) on the toolbar.
4. Click on:
   - Node `V(VCC_3V3)` to observe the regulated 3.3V rail.
   - Node `V(GPIO_PIN)` to observe the 1 kHz 3.3V PWM control pulses.
   - Node `V(GATE)` to inspect the 0V to 4.98V optocoupled gate drive.
   - Component `I(R_BALLAST)` to see the 15.03 mA pulsed LED current.

---

## 6. Implementation & Wiring Guide

### Step 1: Connecting the USB-C Receptacle
1. Solder a $5.1\,\text{k}\Omega$ resistor between pin `CC1` (A5) and `GND`.
2. Solder a second $5.1\,\text{k}\Omega$ resistor between pin `CC2` (B5) and `GND`.
3. Solder a $27\,\Omega$ resistor in series between pin `D+` (A6/B6) and RP2040 pin `USB_DP`.
4. Solder a $27\,\Omega$ resistor in series between pin `D-` (A7/B7) and RP2040 pin `USB_DM`.
5. Connect `VBUS` (A4, A9, B4, B9) to the 5V power bus.
6. Connect `GND` (A1, A12, B1, B12) to the system common ground.

### Step 2: Connecting the RP2040
- **If using a Raspberry Pi Pico or RP2040-Zero**:
  - Connect USB-C `VBUS` (5.0V) to the board's `VSYS` / `VBUS` / `5V` pin.
  - Connect USB-C `GND` to board `GND`.
  - Connect GPIO 16 (or your selected GPIO) to the LR7843 module `PWM+`.
- **If using a discrete RP2040 chip**:
  - Connect USB-C `VBUS` to AP2112K LDO `VIN` with $10\,\mu\text{F}$ capacitor.
  - Connect AP2112K `VOUT` (3.3V) to RP2040 `IOVDD`, `VDD_USB`, and `VREG_IN`.
  - Place $1\,\mu\text{F}$ capacitor on `VREG_VOUT` to `GND`.

### Step 3: Connecting the LR7843 Module & White LED
1. Connect `PWM+` (or `SIG`) on the LR7843 module to RP2040 GPIO 16.
2. Connect `PWM-` (or `GND`) on the LR7843 module to RP2040 `GND`.
3. Connect `DC+` on the LR7843 module to 5.0V `VBUS`.
4. Connect `DC-` on the LR7843 module to `GND`.
5. Connect White LED **Anode** (+) through a $100\,\Omega$ resistor to `LOAD+` (or directly to 5V VBUS).
6. Connect White LED **Cathode** (-) directly to `LOAD-` (the Drain terminal of the LR7843).

### Step 4: MicroPython Software Control
In `rp2040/code.py`, add a PWM or digital output on GPIO 16 to drive the LED:
```python
import machine

# Initialize GPIO 16 as PWM output at 1 kHz frequency
led_pwm = machine.PWM(machine.Pin(16))
led_pwm.freq(1000)

# Turn ON at full brightness (100% duty cycle, 16-bit range 0-65535)
led_pwm.duty_u16(65535)

# Or set 50% brightness
led_pwm.duty_u16(32768)

# Turn OFF
led_pwm.duty_u16(0)
```
The optocoupled LR7843 will mirror the PWM duty cycle and smoothly dim or switch the white LED.
