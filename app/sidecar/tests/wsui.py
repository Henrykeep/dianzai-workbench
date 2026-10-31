"""像界面一样驱动侧车：起一个真的 WebSocket 服务（或连已有的侧车进程），同步 rpc + 收推送事件。

界面（app/ui/src/main.ts、agent.ts）发的就是这些 op；测试按用户点按钮的顺序调用。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import socket
import threading
import time

from websockets.sync.client import connect as ws_connect


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerThread:
    """进程内的侧车（dzbench.server.Server），跑在后台事件循环里。"""
    def __init__(self, server=None):
        from dzbench.server import Server
        self.srv = server or Server()
        self.port = free_port()
        self.loop = asyncio.new_event_loop()
        self._task = None
        threading.Thread(target=self._run, daemon=True).start()
        wait_port(self.port)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self._task = self.loop.create_task(self.srv.serve("127.0.0.1", self.port))
        try:
            self.loop.run_until_complete(self._task)
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    def stop(self):
        try:
            self.srv.session.disconnect()
        finally:
            self.loop.call_soon_threadsafe(self._task.cancel)


def wait_port(port: int, t: float = 10.0) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"侧车端口 {port} 没起来")


class UI:
    """一个界面窗口。"""
    def __init__(self, port: int):
        self.ws = ws_connect(f"ws://127.0.0.1:{port}", max_size=2**22).__enter__()
        self.events: list[dict] = []
        self.rx_t: list[float] = []        # 与 events 一一对应的到达时刻（time.monotonic），测时延用
        self.replies: dict[int, dict] = {}
        self.cv = threading.Condition()
        self.rid = itertools.count(1)
        self.closed = False
        threading.Thread(target=self._rx, daemon=True).start()

    def _rx(self):
        try:
            while True:
                m = json.loads(self.ws.recv())
                with self.cv:
                    if m.get("type") == "reply":
                        self.replies[m["rid"]] = m
                    elif m.get("type") != "telem":
                        self.events.append(m)
                        self.rx_t.append(time.monotonic())
                    self.cv.notify_all()
        except Exception:  # noqa: BLE001
            pass
        with self.cv:
            self.closed = True
            self.cv.notify_all()

    def call(self, op: str, timeout: float = 20.0, **args) -> dict:
        """返回完整回复 {"ok", "data" | "error"}（error 里是给用户看的中文 message / fix）。"""
        rid = next(self.rid)
        self.ws.send(json.dumps({"op": op, "rid": rid, **args}))
        with self.cv:
            if not self.cv.wait_for(lambda: rid in self.replies or self.closed, timeout):
                raise TimeoutError(f"{op} 没有回复")
            if rid not in self.replies:
                raise ConnectionError("侧车断开")
            return self.replies.pop(rid)

    def ok(self, op: str, **args):
        r = self.call(op, **args)
        assert r["ok"], (op, r.get("error"))
        return r["data"]

    def wait(self, pred, timeout: float = 10.0, start: int = 0) -> dict:
        t_end = time.monotonic() + timeout
        with self.cv:
            while True:
                for e in self.events[start:]:
                    if pred(e):
                        return e
                left = t_end - time.monotonic()
                if left <= 0:
                    raise TimeoutError("没等到事件；最近的：" + json.dumps(self.events[-5:], ensure_ascii=False)[:800])
                self.cv.wait(min(left, 0.1))

    def mark(self) -> int:
        with self.cv:
            return len(self.events)

    def close(self):
        self.ws.close()
