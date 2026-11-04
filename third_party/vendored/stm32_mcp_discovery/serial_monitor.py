# Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b serial_monitor.py
"""
Serial port helpers for reading MCU UART logs.

Uses pyserial; all blocking I/O runs in a worker thread so the event loop
is never stalled.
"""

import asyncio
import time


class SerialError(Exception):
    """Raised for serial open / read failures."""


def _capture(port: str, baudrate: int, duration: float,
             max_bytes: int) -> bytes:
    """Blocking capture loop — run via asyncio.to_thread."""
    import serial

    try:
        ser = serial.Serial(port, baudrate, timeout=0.1)
    except serial.SerialException as e:
        raise SerialError(f"无法打开串口 {port} (@{baudrate}): {e}")

    chunks: list[bytes] = []
    received = 0
    end = time.time() + duration
    try:
        ser.reset_input_buffer()
        while time.time() < end and received < max_bytes:
            data = ser.read(min(4096, max_bytes - received))
            if data:
                chunks.append(data)
                received += len(data)
    except serial.SerialException as e:
        raise SerialError(f"串口读取失败: {e}")
    finally:
        ser.close()

    return b"".join(chunks)


async def capture(port: str, baudrate: int, duration: float,
                  max_bytes: int) -> str:
    """Capture serial output for `duration` seconds, decoded as UTF-8."""
    data = await asyncio.to_thread(
        _capture, port, baudrate, duration, max_bytes
    )
    text = data.decode("utf-8", errors="replace")
    return text if text.strip() else "(无数据收到)"


def _enumerate_ports() -> list[tuple[str, str]]:
    import serial.tools.list_ports as list_ports

    result = []
    for p in list_ports.comports():
        result.append((p.device, p.description or ""))
    return result


async def list_ports() -> list[tuple[str, str]]:
    """Return [(device, description), ...] of available serial ports."""
    return await asyncio.to_thread(_enumerate_ports)
