"""
main.py - MicroPython main execution entry point for RP2040.

Execution Lifecycle:
  Following `boot.py`, MicroPython automatically executes `main.py` if present in root storage.

Design Decision:
  This file delegates primary application execution to `code.py`.
  This allows the primary application logic to be stored in `code.py` (matching common
  MicroPython/CircuitPython development patterns), enabling developers to overwrite or update
  `code.py` via `mpremote` without disturbing the board's entry point configuration.
"""

# Read and execute code.py in the global namespace
exec(open("code.py").read())

