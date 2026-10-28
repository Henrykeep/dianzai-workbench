"""传输层：统一成 open / read(超时) / write / close，后台线程读、回调交字节。"""
from __future__ import annotations

import os
import pathlib
import subprocess
import threading
import time
from typing import Callable

ROOT = pathlib.Path(__file__).resolve().parents[3]
SIM_PREFIX = "sim:"


class Transport:
    name = "?"

    def start(self, on_bytes: Callable[[bytes], None], on_error: Callable[[str], None]) -> None:
        self._on_bytes, self._on_error = on_bytes, on_error
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._loop, name=f"rx-{self.name}", daemon=True)
        self._th.start()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                b = self.read()
                if b:
                    self._on_bytes(b)
        except Exception as e:  # noqa: BLE001 —— 线程里任何异常都要交给 UI，而不是悄悄死掉
            if not self._stop.is_set():
                self._on_error(str(e))

    def read(self) -> bytes:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self._stop.set()


class SerialTransport(Transport):
    def __init__(self, device: str, baud: int):
        from .ports import open_serial  # 延迟导入：仿真/回放不需要 pyserial
        self.name = device
        self.ser = open_serial(device, baud, timeout=0.02, write_timeout=0.2)

    def read(self) -> bytes:
        return self.ser.read(self.ser.in_waiting or 1)

    def write(self, data: bytes) -> None:
        self.ser.write(data)

    def close(self) -> None:
        super().close()
        self.ser.close()


def sim_elf(app: str) -> pathlib.Path:
    exe = ".exe" if os.name == "nt" else ""
    return ROOT / "build" / "host-sim" / app / f"{app}.elf{exe}"


class SimTransport(Transport):
    """仿真板：运行 host-sim 编出的应用（./app.elf --stream），stdin/stdout 当作 LINK 串口。"""

    def __init__(self, app: str, speed: float = 1.0, build: bool = True):
        self.name = SIM_PREFIX + app
        elf = sim_elf(app)
        if build:
            r = subprocess.run(["make", "-s", "BOARD=host-sim", f"APP={app}"], cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1"})
            if r.returncode != 0:
                raise RuntimeError(f"编译仿真板失败（make BOARD=host-sim APP={app}）：\n{r.stderr[-800:]}")
        if not elf.exists():
            raise RuntimeError(f"找不到仿真程序 {elf}：在仓库根目录运行 make BOARD=host-sim APP={app}")
        self.proc = subprocess.Popen([str(elf), "--stream", str(speed)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, bufsize=0)

    def read(self) -> bytes:
        b = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(64)
        if not b:
            err = self.proc.stderr.read().decode(errors="replace")
            raise RuntimeError(f"仿真板已退出（code {self.proc.poll()}）{err[-300:]}")
        return b

    def write(self, data: bytes) -> None:
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def close(self) -> None:
        super().close()
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=1)
        except Exception:  # noqa: BLE001
            self.proc.kill()


class LoopbackTransport(Transport):
    """测试用：写进去的字节交给 peer 回调，read 从队列取。"""

    def __init__(self):
        self.name = "loopback"
        self.rx = bytearray()
        self.tx = bytearray()
        self.lock = threading.Lock()

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.rx += data

    def read(self) -> bytes:
        with self.lock:
            b, self.rx = bytes(self.rx), bytearray()
        if not b:
            time.sleep(0.005)
        return b

    def write(self, data: bytes) -> None:
        with self.lock:
            self.tx += data


def open_transport(port: str, baud: int) -> Transport:
    if port.startswith(SIM_PREFIX):
        return SimTransport(port[len(SIM_PREFIX):])
    return SerialTransport(port, baud)
