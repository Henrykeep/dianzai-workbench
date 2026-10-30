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
        if m.get("state") in ("latched", "cleared"):
            return None                     # 固件锁存确认 / 解除：requested 那条已进时间线，解除另有 tx_locked 事件
        if m.get("state") == "requested":   # 统一事件：没有 sent/src，送达看 ok，来源看 source
            return ("estop", "急停，板子已锁存 → 确认安全后点“解除急停 R”" if m.get("ok") else "急停（未送达）", m.get("source") or "ui")
        if m.get("nolink"):
            return None                     # 没连板子：只弹提示，不进告警条（不是板子上发生的事）
        by = f"：{m['src']}" if m.get("src") else ""
        return ("estop", ("急停" + by + "，板子已锁存 → 确认安全后点“解除急停 R”") if m.get("sent") else ("急停" + by + "（未送达）"),
                m.get("source") or "ui")
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
        self.acked = -1                 # 告警条：已确认到的事件序号（侧车记，多窗口/刷新一致）

    def add(self, kind: str, text: str, log_t: float | None, plot_t: float | None, source: str | None = None) -> dict:
        with self.lk:
            e = {"type": "event", "i": self._n, "kind": kind, "text": text,
                 "log_t": None if log_t is None else round(log_t, 2),
                 "plot_t": None if plot_t is None else round(plot_t, 3)}
            if source:
                e["source"], e["detail"] = source, text
            self._n += 1
            self.ev.append(e)
            return e

    def ack(self, upto: int) -> int:
        with self.lk:
            self.acked = max(self.acked, min(int(upto), self._n - 1))
            return self.acked

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
