"""
boot.py - MicroPython board startup script for RP2040.

Execution Lifecycle:
  In the MicroPython boot sequence, `boot.py` is the very first Python script executed
  when the microcontroller powers on or undergoes a soft/hard reset.
  It executes prior to `main.py` and before the interactive REPL becomes active.

Responsibilities:
  - Low-level system initialization.
  - Early-stage memory optimization and garbage collection cleanup.
"""

import gc

# Perform an initial garbage collection sweep to clean and defragment the heap
# before application modules (code.py / main.py) allocate memory structures.
gc.collect()


