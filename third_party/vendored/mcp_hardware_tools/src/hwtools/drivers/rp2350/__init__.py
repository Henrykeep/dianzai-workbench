# Source: github.com/lpender3672/mcp-hardware-tools@e13d9cd src/hwtools/drivers/rp2350/__init__.py
"""RP2350 (Raspberry Pi Pico 2) harness.

The harness firmware is Rust, under the repo's ``firmware/`` directory, flashed as
a UF2. :class:`SerialHarness` is the host-side driver speaking the firmware's
USB-CDC command contract.
"""

from hwtools.drivers.rp2350.serial_harness import SerialHarness, find_pico_port

__all__ = ["SerialHarness", "find_pico_port"]
