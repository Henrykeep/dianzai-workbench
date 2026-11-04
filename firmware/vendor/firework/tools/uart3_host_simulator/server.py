#!/usr/bin/env python3
"""UART3 HTML host simulator for the freertos_firework firmware."""

from __future__ import annotations

import argparse
import errno
import glob
import json
import math
import os
import select
import socket
import termios
import threading
import time
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
DEFAULT_SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200
WAVEFORM_SAMPLE_COUNT = 128
SPECTRUM_POINT_COUNT = 128


def available_serial_ports() -> list[str]:
    """Return stable, sorted candidates without accepting arbitrary paths."""
    ports: list[str] = []
    for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
        ports.extend(glob.glob(pattern))
    return sorted(set(ports))


class UART3HostSimulator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tx_lock = threading.Lock()
        self._fd: int | None = None
        self._port: str | None = None
        self._reader_thread: threading.Thread | None = None
        self._rx_buffer = bytearray()
        self._next_log_id = 1
        self._logs: deque[dict[str, Any]] = deque(maxlen=240)
        self._last_key = "-"
        self._stats = {
            "wave_requests": 0,
            "component_requests": 0,
            "spectrum_requests": 0,
            "key_events": 0,
            "tx_frames": 0,
        }
        self._config: dict[str, Any] = {
            "auto_wave": True,
            "auto_components": True,
            "auto_spectrum": True,
            "wave_type": "sine",
            "wave_offset_v": 0.6,
            "wave_amplitude_v": 0.4,
            "wave_cycles": 4.0,
            "line_delay_ms": 2.0,
            "spectrum_max_frequency_hz": 500000.0,
            "spectrum_width_bins": 0.7,
            "spectrum_floor_v": 0.01,
            "components": [
                {"enabled": True, "frequency_hz": 10000.0,
                 "amplitude_v": 0.8},
                {"enabled": True, "frequency_hz": 50000.0,
                 "amplitude_v": 0.35},
                {"enabled": False, "frequency_hz": 100000.0,
                 "amplitude_v": 0.1},
            ],
        }
        self._log("info", "上位机服务已启动，等待连接 UART3")

    def _log(self, level: str, message: str) -> None:
        with self._lock:
            self._logs.append({
                "id": self._next_log_id,
                "time": time.strftime("%H:%M:%S"),
                "level": level,
                "message": message,
            })
            self._next_log_id += 1

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self._fd is not None,
                "port": self._port,
                "baud": SERIAL_BAUD,
                "last_key": self._last_key,
                "stats": dict(self._stats),
                "config": json.loads(json.dumps(self._config)),
                "logs": list(self._logs),
            }

    def update_config(self, incoming: dict[str, Any]) -> dict[str, Any]:
        allowed_wave_types = {"sine", "square", "triangle"}
        wave_type = str(incoming.get("wave_type", "sine"))
        if wave_type not in allowed_wave_types:
            raise ValueError("不支持的波形类型")

        config = {
            "auto_wave": bool(incoming.get("auto_wave", True)),
            "auto_components": bool(incoming.get("auto_components", True)),
            "auto_spectrum": bool(incoming.get("auto_spectrum", True)),
            "wave_type": wave_type,
            "wave_offset_v": self._bounded_float(
                incoming, "wave_offset_v", -32.0, 32.0),
            "wave_amplitude_v": self._bounded_float(
                incoming, "wave_amplitude_v", 0.0, 32.0),
            "wave_cycles": self._bounded_float(
                incoming, "wave_cycles", 0.01, 64.0),
            "line_delay_ms": self._bounded_float(
                incoming, "line_delay_ms", 0.0, 50.0),
            "spectrum_max_frequency_hz": self._bounded_float(
                incoming, "spectrum_max_frequency_hz", 1.0, 100000000.0),
            "spectrum_width_bins": self._bounded_float(
                incoming, "spectrum_width_bins", 0.1, 32.0),
            "spectrum_floor_v": self._bounded_float(
                incoming, "spectrum_floor_v", 0.0, 65.0),
        }

        components = incoming.get("components")
        if not isinstance(components, list) or len(components) > 3:
            raise ValueError("峰值分量必须是最多 3 项的数组")
        normalized_components: list[dict[str, Any]] = []
        for item in components:
            if not isinstance(item, dict):
                raise ValueError("峰值分量格式错误")
            frequency = float(item.get("frequency_hz", 0.0))
            amplitude = float(item.get("amplitude_v", 0.0))
            if not math.isfinite(frequency) or not (0.0 < frequency <=
                    config["spectrum_max_frequency_hz"]):
                raise ValueError("峰值频率必须大于 0 且不超过频谱上限")
            if not math.isfinite(amplitude) or not (0.0 <= amplitude <= 65.0):
                raise ValueError("峰值幅值必须在 0～65 V 范围内")
            normalized_components.append({
                "enabled": bool(item.get("enabled", True)),
                "frequency_hz": frequency,
                "amplitude_v": amplitude,
            })
        config["components"] = normalized_components

        with self._lock:
            self._config = config
        self._log("info", "参数已保存")
        return self.state()

    @staticmethod
    def _bounded_float(
            source: dict[str, Any], key: str, minimum: float,
            maximum: float) -> float:
        value = float(source.get(key))
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"{key} 超出允许范围 {minimum}～{maximum}")
        return value

    def connect(self, port: str) -> None:
        if port not in available_serial_ports():
            raise ValueError("串口不存在或不是 ttyACM/ttyUSB 设备")

        self.disconnect(log_event=False)
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            attributes = termios.tcgetattr(fd)
            attributes[0] = 0
            attributes[1] = 0
            attributes[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attributes[3] = 0
            attributes[4] = termios.B115200
            attributes[5] = termios.B115200
            attributes[6][termios.VMIN] = 0
            attributes[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attributes)
            termios.tcflush(fd, termios.TCIOFLUSH)
        except Exception:
            os.close(fd)
            raise

        with self._lock:
            self._fd = fd
            self._port = port
            self._rx_buffer.clear()
        thread = threading.Thread(
            target=self._reader_loop, args=(fd,), daemon=True,
            name="uart3-host-reader")
        with self._lock:
            self._reader_thread = thread
        thread.start()
        self._log("success", f"已连接 {port}，115200-8-N-1")

    def disconnect(self, log_event: bool = True) -> None:
        with self._lock:
            fd = self._fd
            thread = self._reader_thread
            self._fd = None
            self._port = None
            self._reader_thread = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        if log_event and fd is not None:
            self._log("warn", "串口已断开")

    def _reader_loop(self, fd: int) -> None:
        while True:
            with self._lock:
                if self._fd != fd:
                    return
            try:
                readable, _, _ = select.select([fd], [], [], 0.25)
                if not readable:
                    continue
                data = os.read(fd, 512)
                if data:
                    self._consume_received(data)
            except (OSError, ValueError) as exc:
                with self._lock:
                    active = self._fd == fd
                    if active:
                        self._fd = None
                        self._port = None
                        self._reader_thread = None
                if active:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    self._log("error", f"串口读取失败：{exc}")
                return

    def _consume_received(self, data: bytes) -> None:
        self._rx_buffer.extend(data)
        while True:
            delimiters = [
                index for index, value in enumerate(self._rx_buffer)
                if value in (0, 10, 13)
            ]
            if not delimiters:
                if len(self._rx_buffer) > 1024:
                    self._log("warn", "收到无结束符的超长数据，已清空")
                    self._rx_buffer.clear()
                return
            end = delimiters[0]
            token_bytes = bytes(self._rx_buffer[:end])
            del self._rx_buffer[:end + 1]
            token = token_bytes.decode("ascii", errors="replace")
            if token:
                self._handle_token(token)

    def _handle_token(self, token: str) -> None:
        with self._lock:
            config = json.loads(json.dumps(self._config))
        if token in {"sep1", "sep2"}:
            ready = "MODEL HIGH A READY" if token == "sep1" \
                else "MODEL HIGH AB READY"
            self._log("rx", f"RX  {token}")
            self._write_lines([ready], config["line_delay_ms"])
            self._log("tx", f"TX  {ready}")
        elif token in {"sweep", "sweep1"}:
            self._log("rx", f"RX  {token}")
            self._write_lines(
                ["SWEEP START avg=1", "SWEEP DONE type=0 points=496"],
                max(config["line_delay_ms"], 10.0))
            self._log("tx", "TX  SWEEP DONE type=0 points=496")
        elif token in {
                "lwavea1", "lwavea3", "lwaveb1", "lwaveb3",
                "lwave1", "lwave3"}:
            with self._lock:
                self._stats["wave_requests"] += 1
            self._log("rx", f"RX  {token}")
            if config["auto_wave"]:
                cycles = 3.0 if token.endswith("3") else 1.0
                self.send_waveform(framed=True, cycles=cycles)
        elif token in {"lafc", "lpfc"}:
            with self._lock:
                self._stats["wave_requests"] += 1
            self._log("rx", f"RX  {token}")
            if config["auto_wave"]:
                self.send_response_curve(phase=(token == "lpfc"))
        elif token in {"lspecta", "lspectb"}:
            with self._lock:
                self._stats["spectrum_requests"] += 1
            self._log("rx", f"RX  {token}")
            if config["auto_spectrum"]:
                self.send_spectrum(framed=True)
        elif token == "wave1":
            with self._lock:
                self._stats["wave_requests"] += 1
            self._log("rx", "RX  wave1\\0")
            if config["auto_wave"]:
                self.send_waveform()
        elif token == "components":
            with self._lock:
                self._stats["component_requests"] += 1
            self._log("rx", "RX  components\\0")
            if config["auto_components"]:
                self.send_components()
        elif token == "spectrum":
            with self._lock:
                self._stats["spectrum_requests"] += 1
            self._log("rx", "RX  spectrum\\0")
            if config["auto_spectrum"]:
                self.send_spectrum()
        elif len(token) == 1 and token in "123A456B789C*0#D":
            with self._lock:
                self._last_key = token
                self._stats["key_events"] += 1
            self._log("key", f"矩阵键盘：{token}")
        elif token:
            self._log("warn", f"未知 NUL 字符串：{token!r}")

    def _config_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._config))

    def _write_lines(self, lines: list[str], delay_ms: float) -> None:
        with self._tx_lock:
            with self._lock:
                fd = self._fd
            if fd is None:
                raise RuntimeError("串口尚未连接")
            for line in lines:
                data = f"{line}\r\n".encode("ascii")
                view = memoryview(data)
                while view:
                    try:
                        written = os.write(fd, view)
                        view = view[written:]
                    except BlockingIOError:
                        select.select([], [fd], [], 0.1)
                if delay_ms > 0.0:
                    time.sleep(delay_ms / 1000.0)
        with self._lock:
            self._stats["tx_frames"] += 1

    def send_waveform(
            self, framed: bool = False, cycles: float | None = None) -> None:
        config = self._config_snapshot()
        values: list[float] = []
        display_cycles = config["wave_cycles"] if cycles is None else cycles
        for index in range(WAVEFORM_SAMPLE_COUNT):
            phase = (
                2.0 * math.pi * display_cycles * index /
                WAVEFORM_SAMPLE_COUNT
            )
            if config["wave_type"] == "square":
                normalized = 1.0 if math.sin(phase) >= 0.0 else -1.0
            elif config["wave_type"] == "triangle":
                normalized = (2.0 / math.pi) * math.asin(math.sin(phase))
            else:
                normalized = math.sin(phase)
            value = config["wave_offset_v"] + \
                config["wave_amplitude_v"] * normalized
            if not -32.768 <= value <= 32.767:
                raise ValueError("波形超出固件 int16 mV 接收范围")
            values.append(value)
        lines = [f"{value:.5f}" for value in values]
        if framed:
            lines = ["start", *lines, "end"]
        self._write_lines(lines, config["line_delay_ms"])
        average = sum(values) / len(values)
        self._log(
            "tx",
            f"TX  波形 128 点：{min(values):.5f}～{max(values):.5f} V，"
            f"平均值 {average:.5f} V")

    def _enabled_components(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in config["components"] if item["enabled"]]

    def send_components(self) -> None:
        config = self._config_snapshot()
        components = self._enabled_components(config)
        lines = [str(len(components))]
        for item in components:
            lines.append(f"{item['frequency_hz']:.5f}")
            lines.append(f"{item['amplitude_v']:.5f}")
        self._write_lines(lines, config["line_delay_ms"])
        summary = ", ".join(
            f"{item['frequency_hz']:g} Hz/{item['amplitude_v']:g} V"
            for item in components) or "无峰值"
        self._log("tx", f"TX  峰值分量：{summary}")

    def send_spectrum(self, framed: bool = False) -> None:
        config = self._config_snapshot()
        components = self._enabled_components(config)
        maximum_frequency = config["spectrum_max_frequency_hz"]
        width = config["spectrum_width_bins"]
        floor = config["spectrum_floor_v"]
        values: list[float] = []
        for index in range(SPECTRUM_POINT_COUNT):
            value = floor
            for item in components:
                center = (
                    item["frequency_hz"] * (SPECTRUM_POINT_COUNT - 1) /
                    maximum_frequency
                )
                distance = (index - center) / width
                value += item["amplitude_v"] * math.exp(-0.5 * distance * distance)
            values.append(value)
        lines = [f"{value:.5f}" for value in values]
        if framed:
            lines = ["start", *lines, "end"]
        self._write_lines(lines, config["line_delay_ms"])
        peak_index = max(range(len(values)), key=values.__getitem__)
        peak_frequency = (
            peak_index * maximum_frequency / (SPECTRUM_POINT_COUNT - 1)
        )
        self._log(
            "tx", f"TX  频谱 128 点：离散主峰 {peak_frequency:.0f} Hz")

    def send_response_curve(self, phase: bool) -> None:
        config = self._config_snapshot()
        values: list[float] = []
        for index in range(WAVEFORM_SAMPLE_COUNT):
            normalized_frequency = index / (WAVEFORM_SAMPLE_COUNT - 1)
            if phase:
                value = -math.atan(4.0 * normalized_frequency)
            else:
                value = 1.0 / math.sqrt(
                    1.0 + (4.0 * normalized_frequency) ** 2)
            values.append(value)
        self._write_lines(
            ["start", *[f"{value:.5f}" for value in values], "end"],
            config["line_delay_ms"])
        self._log("tx", f"TX  {'相频' if phase else '幅频'}曲线 128 点")


class SimulatorRequestHandler(SimpleHTTPRequestHandler):
    simulator: UART3HostSimulator
    server_version = "UART3HostSimulator/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(Path(__file__).parent), **kwargs)

    def log_message(self, format_string: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise ValueError("请求内容过大")
        if length == 0:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON 请求必须是对象")
        return payload

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send_json({"ok": True})
        elif self.path == "/api/ports":
            self._send_json({"ports": available_serial_ports()})
        elif self.path == "/api/state":
            self._send_json(self.simulator.state())
        else:
            super().do_GET()

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/connect":
                self.simulator.connect(str(payload.get("port", "")))
            elif self.path == "/api/disconnect":
                self.simulator.disconnect()
            elif self.path == "/api/config":
                self.simulator.update_config(payload)
            elif self.path == "/api/send/waveform":
                self.simulator.send_waveform()
            elif self.path == "/api/send/components":
                self.simulator.send_components()
            elif self.path == "/api/send/spectrum":
                self.simulator.send_spectrum()
            else:
                self._send_json(
                    {"ok": False, "error": "接口不存在"},
                    HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, "state": self.simulator.state()})
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            self.simulator._log("error", str(exc))
            self._send_json(
                {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)


def open_browser_when_ready(url: str) -> None:
    time.sleep(0.35)
    webbrowser.open(url, new=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="UART3 HTML host simulator")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--serial-port", default=DEFAULT_SERIAL_PORT)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://{HOST}:{args.http_port}/"

    simulator = UART3HostSimulator()
    SimulatorRequestHandler.simulator = simulator
    try:
        server = ThreadingHTTPServer((HOST, args.http_port), SimulatorRequestHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            if args.open_browser:
                webbrowser.open(url, new=2)
            return 0
        raise

    if args.serial_port in available_serial_ports():
        try:
            simulator.connect(args.serial_port)
        except OSError as exc:
            simulator._log("error", f"自动连接失败：{exc}")
    if args.open_browser:
        threading.Thread(
            target=open_browser_when_ready, args=(url,), daemon=True).start()

    print(f"UART3 host simulator: {url}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        simulator.disconnect(log_event=False)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
