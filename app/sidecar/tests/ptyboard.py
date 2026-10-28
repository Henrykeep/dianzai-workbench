"""“真串口”仿真板：host-sim 固件 ↔ Linux 伪终端（pty），侧车用 pyserial 当 USB 串口打开。

能做用户在赛场上会遇到的事：拔线（unplug）/插回（replug，同名口）、往线上灌乱码（inject）、
换固件重启（restart，给假 pyOCD 用）。板子在拔线/侧车崩溃时照常运行，测试从 board_* 看它自己的状态。
只在 POSIX 上可用。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time
import tty

from dzbench._dzlink import DATA, HEARTBEAT, Parser
from dzbench.schema import Schema
from dzbench.transport import ROOT, sim_elf


def build_sim(app: str) -> pathlib.Path:
    subprocess.run(["make", "-s", "BOARD=host-sim", f"APP={app}"], cwd=ROOT, check=True, capture_output=True)
    return sim_elf(app)


def schema_of(app: str) -> Schema:
    return Schema(json.loads((ROOT / "build/host-sim" / app / "linkgen/link_schema.json").read_text(encoding="utf-8")))


class PtyBoard:
    def __init__(self, app: str, path: pathlib.Path):
        self.path = pathlib.Path(path)
        self.lock = threading.Lock()
        self.master: int | None = None
        self.slave: int | None = None
        self.board_hash: int | None = None
        self.board_telem: dict | None = None
        self.board_t = 0.0
        self.closed = False
        self._start(app)
        self.replug()

    # ---------------------------------------------------------------- 板子（固件进程）
    def _start(self, app: str) -> None:
        self.app, self.schema = app, schema_of(app)
        self.proc = subprocess.Popen([str(build_sim(app)), "--stream", "1.0"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.parser = Parser()
        threading.Thread(target=self._board_out, args=(self.proc,), daemon=True).start()

    def restart(self, app: str) -> None:
        """芯片复位并跑新固件（假探针烧录后调用）。串口线不动。"""
        old = self.proc
        self.board_hash = None
        self._start(app)
        old.kill()
        old.wait()

    def _board_out(self, proc) -> None:
        while True:
            try:
                b = os.read(proc.stdout.fileno(), 4096)
            except (OSError, ValueError):
                return
            if not b:
                return
            for kind, id_, _seq, payload in self.parser.feed(b):
                if kind == HEARTBEAT and len(payload) >= 4:
                    self.board_hash = int.from_bytes(payload[:4], "little")
                elif kind == DATA and id_ == self.schema.telem_id:
                    v = self.schema.decode(payload)
                    if v:
                        self.board_telem, self.board_t = v, time.monotonic()
            with self.lock:
                m = self.master
            if m is not None:
                try:
                    os.write(m, b)
                except OSError:                       # 没人读（缓冲满）/ 线拔了：像 UART 一样丢掉
                    pass

    def _host_in(self, m: int) -> None:
        while True:
            try:
                b = os.read(m, 4096)
            except OSError:
                return
            if not b:
                return
            try:
                self.proc.stdin.write(b)
            except (OSError, ValueError):
                pass

    # ---------------------------------------------------------------- USB 线
    def replug(self) -> None:
        m, s = os.openpty()
        tty.setraw(s)
        os.set_blocking(m, True)
        with self.lock:
            self.master, self.slave = m, s
        if self.path.is_symlink() or self.path.exists():
            self.path.unlink()
        self.path.symlink_to(os.ttyname(s))
        threading.Thread(target=self._host_in, args=(m,), daemon=True).start()

    def unplug(self) -> None:
        with self.lock:
            m, s, self.master, self.slave = self.master, self.slave, None, None
        if self.path.is_symlink():
            self.path.unlink()
        for fd in (m, s):
            if fd is not None:
                os.close(fd)

    def inject(self, data: bytes) -> None:
        with self.lock:
            m = self.master
        if m is not None:
            os.write(m, data)

    def close(self) -> None:
        self.unplug()
        self.proc.kill()
        self.proc.wait()
