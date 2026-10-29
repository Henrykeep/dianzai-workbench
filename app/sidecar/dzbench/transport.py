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
        if hasattr(self, "_stop"):                  # 没 start() 过（打开后立刻关）也能关
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


AS_HW = "+hw"     # 端口后缀：仿真板“当实板”，用来端到端测确认卡 / pre-arm 检查


def sim_elf(app: str) -> pathlib.Path:
    exe = ".exe" if os.name == "nt" else ""
    return ROOT / "build" / "host-sim" / app / f"{app}.elf{exe}"


class SimTransport(Transport):
    """仿真板：运行 host-sim 编出的应用（./app.elf --stream），stdin/stdout 当作 LINK 串口。"""

    def __init__(self, app: str, speed: float = 1.0, build: bool = True):
        self.name = SIM_PREFIX + app
        app = app.removesuffix(AS_HW)          # sim:xxx+hw：同一个仿真程序，只是风险分级按实板走
        if (who := os.environ.get("DZBENCH_TEST_NO_SIM")):     # 仅测试用：conftest 给没标 needs_sim 的测试设上（子进程侧车也能拦住）
            raise RuntimeError(f"{who} 起了仿真板却没标 @pytest.mark.needs_sim（Windows CI 会挂）")
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


RTT_PREFIX = "rtt:"


class RttTransport(Transport):
    """SEGGER RTT 当串口用（端口名 rtt:<pyOCD 目标>[@探针序列号]，如 rtt:mspm0g3507）。
    API 按 pyOCD 源码 pyocd/debug/rtt.py 核对（2026-10 主干）：RTTControlBlock.from_target(target, address, size)
    → start() 在 RAM 里找 "SEGGER RTT" 控制块 → up_channels[i].read() 非阻塞读、down_channels[i].write(data)。
    与 `pyocd rtt` 子命令一样：连上后 target.resume()（pyOCD 默认连接会停核）。
    【仿真】fakepyocd 测过；【未测】真探针。固件侧需要把 LINK 输出到 RTT 通道 0（本仓库固件尚未提供 RTT 版 LINK）。"""

    def __init__(self, spec: str, address: int | None = None, size: int | None = None, channel: int = 0):
        try:
            from pyocd.core.helpers import ConnectHelper  # type: ignore
            from pyocd.debug.rtt import RTTControlBlock  # type: ignore
        except ImportError as e:
            raise RuntimeError("RTT 需要 pyOCD（含 pyocd.debug.rtt）：pip install -U pyocd") from e
        from .flash import M0_PACK, find_pack
        target, _, probe = spec.partition("@")
        self.name = RTT_PREFIX + spec
        pack = find_pack(target)
        if target.lower().startswith("mspm0") and not pack:
            raise RuntimeError(f"找不到 MSPM0 器件包 {M0_PACK}：运行 tools/fetch_third_party.sh m0pack 或设 DZBENCH_PACK")
        kw = {"pack": str(pack)} if pack else {}
        self.sess = ConnectHelper.session_with_chosen_probe(unique_id=probe or None, target_override=target, blocking=False, **kw)
        if self.sess is None:
            raise RuntimeError("没找到调试探针：插上 DAPLink/XDS110/ST-Link")
        self.sess.open()
        try:
            t = self.sess.target
            cb = RTTControlBlock.from_target(t, address=address, size=size)
            cb.start()
            if len(cb.up_channels) <= channel:
                raise RuntimeError(f"RTT 只有 {len(cb.up_channels)} 个上行通道")
            self.up = cb.up_channels[channel]
            self.down = cb.down_channels[channel] if len(cb.down_channels) > channel else None
            t.resume()
        except Exception as e:
            self.sess.close()
            if type(e).__name__ == "RTTError":
                raise RuntimeError(f"RAM 里没找到 RTT 控制块（固件没启用 RTT？）：{e}") from e
            raise

    def read(self) -> bytes:
        b = bytes(self.up.read())
        if not b:
            time.sleep(0.005)                       # 轮询：没数据别空转
        return b

    def write(self, data: bytes) -> None:
        if self.down is None:
            raise RuntimeError("RTT 没有下行通道：只能看不能发")
        n = 0
        while n < len(data):
            n += self.down.write(data[n:], blocking=True)

    def close(self) -> None:
        super().close()
        self.sess.close()


def open_transport(port: str, baud: int) -> Transport:
    if port.startswith(SIM_PREFIX):
        return SimTransport(port[len(SIM_PREFIX):])
    if port.startswith(RTT_PREFIX):
        return RttTransport(port[len(RTT_PREFIX):])
    return SerialTransport(port, baud)
