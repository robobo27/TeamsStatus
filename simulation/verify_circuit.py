"""
verify_circuit.py - Automated LTspice simulation runner and verifier
for the USB-C powered RP2040 and LR7843 LED driver circuit.
"""

import os
import subprocess
import sys
import re

LTSPICE_EXE = r"C:\Program Files\ADI\LTspice\LTspice.exe"
CIRCUIT_DIR = os.path.dirname(os.path.abspath(__file__))
NETLIST_FILE = os.path.join(CIRCUIT_DIR, "usb_rp2040_lr7843.cir")
LOG_FILE = os.path.join(CIRCUIT_DIR, "usb_rp2040_lr7843.log")
RAW_FILE = os.path.join(CIRCUIT_DIR, "usb_rp2040_lr7843.raw")


def run_ltspice_simulation():
    """Runs LTspice in batch mode on the circuit netlist."""
    if not os.path.isfile(LTSPICE_EXE):
        raise FileNotFoundError(f"LTspice executable not found at: {LTSPICE_EXE}")

    if not os.path.isfile(NETLIST_FILE):
        raise FileNotFoundError(f"Circuit netlist not found at: {NETLIST_FILE}")

    print(f"[1/3] Executing LTspice in batch mode: {NETLIST_FILE}")
    cmd = [LTSPICE_EXE, "-b", NETLIST_FILE]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0:
        print(f"Warning: LTspice returned non-zero exit code: {res.returncode}")

    if not os.path.isfile(LOG_FILE):
        raise FileNotFoundError(f"Simulation log not created: {LOG_FILE}")
    print(f"      Simulation finished. Log file: {LOG_FILE}")


def parse_measurements(log_path):
    """Parses .meas directives from the LTspice log file."""
    measurements = {}
    pattern = re.compile(r"^([a-zA-Z0-9_]+):\s+.*?=\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b", re.IGNORECASE)

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            match = pattern.match(line.strip())
            if match:
                name = match.group(1).lower()
                val = float(match.group(2))
                measurements[name] = val

    return measurements


def verify_specifications(meas):
    """Checks all electrical specifications against expected design criteria."""
    print("\n[2/3] Verifying electrical specifications against design targets:\n")
    tests = [
        {
            "name": "USB VBUS Supply Voltage",
            "key": "v_vbus_steady",
            "val": meas.get("v_vbus_steady"),
            "unit": "V",
            "min": 4.75,
            "max": 5.25,
            "desc": "USB 5.0V rail within standard tolerance"
        },
        {
            "name": "RP2040 3.3V Power Rail",
            "key": "v_3v3_rail",
            "val": meas.get("v_3v3_rail"),
            "unit": "V",
            "min": 3.20,
            "max": 3.40,
            "desc": "AP2112K LDO 3.3V supply for RP2040 IOVDD/VREG"
        },
        {
            "name": "USB-C CC1 Negotiation Voltage",
            "key": "v_cc1_negotiated",
            "val": meas.get("v_cc1_negotiated"),
            "unit": "V",
            "min": 0.25,
            "max": 2.04,
            "desc": "Type-C UFP 5.1k pull-down valid detection window"
        },
        {
            "name": "USB-C CC2 Negotiation Voltage",
            "key": "v_cc2_negotiated",
            "val": meas.get("v_cc2_negotiated"),
            "unit": "V",
            "min": 0.25,
            "max": 2.04,
            "desc": "Type-C UFP 5.1k pull-down valid detection window"
        },
        {
            "name": "LR7843 Gate ON Voltage (Vgs High)",
            "key": "vgs_high",
            "val": meas.get("vgs_high"),
            "unit": "V",
            "min": 4.50,
            "max": 5.10,
            "desc": "Optocoupler successfully charges gate to ~5V"
        },
        {
            "name": "LR7843 Gate OFF Voltage (Vgs Low)",
            "key": "vgs_low",
            "val": meas.get("vgs_low"),
            "unit": "V",
            "min": -0.10,
            "max": 0.50,
            "desc": "Pull-down ensures MOSFET fully cut off (< Vth=1.8V)"
        },
        {
            "name": "White LED ON Current",
            "key": "i_led_on",
            "val": meas.get("i_led_on"),
            "unit": "A",
            "min": 0.010,
            "max": 0.025,
            "desc": "Nominal 15-20 mA current for bright white LED illumination"
        },
        {
            "name": "White LED OFF Leakage Current",
            "key": "i_led_off",
            "val": meas.get("i_led_off"),
            "unit": "A",
            "min": -1e-6,
            "max": 10e-6,
            "desc": "Dark off-state leakage < 10 uA"
        },
        {
            "name": "LR7843 Saturation Voltage (Vds ON)",
            "key": "vds_on",
            "val": meas.get("vds_on"),
            "unit": "V",
            "min": -0.01,
            "max": 0.01,
            "desc": "Ultra-low Rds(on) ensures negligible conduction drop"
        },
        {
            "name": "LR7843 Average Conduction Power",
            "key": "p_mosfet_avg",
            "val": meas.get("p_mosfet_avg"),
            "unit": "W",
            "min": 0.0,
            "max": 0.010,
            "desc": "Power dissipation < 10 mW (runs completely cool)"
        }
    ]

    all_passed = True
    print(f"{'Check':<36} | {'Measured':<14} | {'Target Range':<18} | {'Status'}")
    print("-" * 80)
    for t in tests:
        val = t["val"]
        if val is None:
            status = "MISSING"
            val_str = "N/A"
            all_passed = False
        else:
            passed = (t["min"] <= val <= t["max"])
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_passed = False

            if abs(val) < 1e-3 and val != 0.0:
                val_str = f"{val*1e6:.2f} u{t['unit']}"
            elif abs(val) < 1.0 and val != 0.0 and t['unit'] == 'A':
                val_str = f"{val*1e3:.2f} m{t['unit']}"
            else:
                val_str = f"{val:.4f} {t['unit']}"

        min_s = f"{t['min']}" if t['min'] > 1e-4 else f"{t['min']*1e3}m"
        max_s = f"{t['max']}" if t['max'] > 1e-4 else f"{t['max']*1e3}m"
        range_s = f"[{min_s}, {max_s}] {t['unit']}"

        print(f"{t['name']:<36} | {val_str:<14} | {range_s:<18} | {status}")

    print("-" * 80)
    return all_passed


def main():
    print("=" * 80)
    print("   USB-C to RP2040 and LR7843 Circuit Verification Suite (LTspice)")
    print("=" * 80)

    try:
        run_ltspice_simulation()
        meas = parse_measurements(LOG_FILE)
        passed = verify_specifications(meas)

        print("\n[3/3] Verification Summary:")
        if passed:
            print(">>> ALL ELECTRICAL CHECKS PASSED SUCCESSFULLY! <<<")
            print("The circuit satisfies all USB Type-C, RP2040, and LR7843 specifications.\n")
            return 0
        else:
            print(">>> ONE OR MORE CHECKS FAILED! <<<\n")
            return 1
    except Exception as e:
        print(f"\nError during verification: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
