"""事件时间线：把侧车里已有的消息/操作结果归成几类事件，每条带 dzlog 时间和曲线时间（同心跳条）。

通用机制：不在各处埋点，而是在 server 唯一的出口（广播 + op 回复）上按下表分类；
新增一种事件 = 在表里加一行。会话内部才知道的（心跳丢失 = 板端看门狗该急停了、CRC 突增）由 Session 自己 mark。
"""
from __future__ import annotations

import collections
import threading

KINDS = ("connect", "param", "estop", "watchdog", "crc", "step", "agent")
KEEP = 2000


def from_broadcast(m: dict) -> tuple[str, str] | None:
    t = m.get("type")
    if t == "param":
        return "param", f"{m.get('name')} = {m.get('value')}" + ("" if m.get("status") in (None, "ok") else f"（{m.get('status')}）")
    if t == "estop":
        return "estop", "急停" + ("" if m.get("sent") else "（未送达）")
    if t == "reconnected":
        return "connect", f"自动重连 {m.get('port', '')}"
    if t == "tune_round":
        v, mt = m.get("verdict") or {}, m.get("metrics") or {}
        os_ = mt.get("overshoot_pct")
        return "step", "阶跃实验完成" + (f" · 超调 {os_:.1f}%" if isinstance(os_, (int, float)) else "") + (f" · {v['action']}" if v.get("action") else "")
    if t == "change" and m.get("status") == "applied":
        return "agent", f"采纳改动 #{m.get('id')} {m.get('title', '')}".rstrip()
    return None


def from_reply(op: str | None, data) -> tuple[str, str] | None:
    if op == "connect" and isinstance(data, dict):
        return "connect", f"连接 {data.get('port', '')}" + (f" @ {data['baud']}" if data.get("baud") else "")
    if op == "disconnect":
        return "connect", "断开"
    if op == "proposal_decide" and isinstance(data, dict) and data.get("status") == "applied":
        return "agent", f"采纳提议 {data.get('name', '')} = {data.get('applied', '')}".rstrip(" =")
    return None


class Timeline:
    def __init__(self, keep: int = KEEP):
        self.lk = threading.Lock()
        self.ev: collections.deque = collections.deque(maxlen=keep)
        self._n = 0

    def add(self, kind: str, text: str, log_t: float | None, plot_t: float | None) -> dict:
        with self.lk:
            e = {"type": "event", "i": self._n, "kind": kind, "text": text,
                 "log_t": None if log_t is None else round(log_t, 2),
                 "plot_t": None if plot_t is None else round(plot_t, 3)}
            self._n += 1
            self.ev.append(e)
            return e

    def history(self) -> list[dict]:
        with self.lk:
            return list(self.ev)


def crc_spike(cell: dict, recent: list[dict]) -> bool:
    """这一秒坏帧 ≥3 且 ≥ 前 30 秒平均的 3 倍（持续有干扰时不刷屏，只报突增）。"""
    c = cell.get("crc", 0)
    if c < 3:
        return False
    prev = [x.get("crc", 0) for x in recent[-30:]]
    avg = sum(prev) / len(prev) if prev else 0.0
    return c >= 3 * max(avg, 1.0)
