"""预设 / 定时 / 触发发送（侧车里跑，界面关了也不乱发；急停后全部停用）。思路参考 SerialWeb 的快捷发送；代码自写。

预设：{name, kind: text|hex|cmd|data, payload, id?(data), eol?(text: "\\r\\n" 等)}
定时：start_timer(name, period_ms, count=0 表示一直发)
触发：add_trigger(name, field, op(> < >= <= ==), value, cooldown_ms)：遥测样本满足条件时发一次（上升沿触发，满足期间不重复）
"""
from __future__ import annotations

import json
import operator
import threading
import time

from . import snapshots
from .session import LinkError, Session

OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le, "==": lambda a, b: abs(a - b) < 1e-9}
MIN_PERIOD_MS = 10


def encode_preset(p: dict) -> tuple[str, bytes, int | None]:
    k, pl = p.get("kind", "text"), p.get("payload", "")
    if k == "text":
        return k, (pl + p.get("eol", "")).encode("utf-8"), None
    if k == "hex":
        try:
            return k, bytes.fromhex(pl.replace(" ", "").replace("0x", "")), None
        except ValueError as e:
            raise LinkError("bad_preset", f"HEX 写错了：{pl!r}", "两位一组，例如 A5 5A 01") from e
    if k == "cmd":
        if not pl or pl[0] == "R":
            raise LinkError("bad_preset", "命令预设不能为空，也不能是 R（解除急停只能人按）")
        return k, pl.encode()[:2], None
    if k == "data":
        try:
            return k, bytes.fromhex(pl.replace(" ", "")), int(p["id"])
        except (ValueError, KeyError) as e:
            raise LinkError("bad_preset", "DATA 预设需要 id 和 HEX 负载") from e
    raise LinkError("bad_preset", f"未知预设类型 {k}")


class Sender:
    def __init__(self, session: Session, emit=lambda e: None):
        self.s, self.emit = session, emit
        self.presets: dict[str, dict] = {}
        self.timers: dict[str, threading.Event] = {}
        self.triggers: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.load()
        session.on_sample = self._on_sample
        self._prev_emit = session.emit
        session.emit = self._wrap_emit

    # 急停 → 停掉全部定时与触发（不是暂停：解除后要人重新开）
    def _wrap_emit(self, e: dict) -> None:
        if e.get("type") == "tx_locked" and e.get("on"):
            self.stop_all("急停")
        self._prev_emit(e)

    def path(self):
        return snapshots.base_dir() / "presets.json"

    def load(self) -> None:
        p = self.path()
        self.presets = {x["name"]: x for x in json.loads(p.read_text(encoding="utf-8"))} if p.exists() else {}

    def save_preset(self, p: dict) -> list[dict]:
        encode_preset(p)                                    # 先校验
        self.presets[p["name"]] = p
        self.path().parent.mkdir(parents=True, exist_ok=True)
        self.path().write_text(json.dumps(list(self.presets.values()), ensure_ascii=False, indent=1), encoding="utf-8")
        return self.list()

    def delete_preset(self, name: str) -> list[dict]:
        self.presets.pop(name, None)
        self.path().write_text(json.dumps(list(self.presets.values()), ensure_ascii=False, indent=1), encoding="utf-8")
        return self.list()

    def list(self) -> list[dict]:
        return [p | {"timer": p["name"] in self.timers, "trigger": self.triggers.get(p["name"])} for p in self.presets.values()]

    def send(self, name: str) -> bool:
        p = self.presets.get(name)
        if not p:
            raise LinkError("no_preset", f"没有预设 {name}")
        k, data, id_ = encode_preset(p)
        self.s._check_tx()
        if k == "cmd":
            return self.s.cmd(chr(data[0]), data[1] if len(data) > 1 else None)
        if k == "data":
            return self.s.send_data(id_, data)
        return self.s.send_raw(data)

    def start_timer(self, name: str, period_ms: int, count: int = 0) -> dict:
        self.s._check_tx()
        if name not in self.presets:
            raise LinkError("no_preset", f"没有预设 {name}")
        if period_ms < MIN_PERIOD_MS:
            raise LinkError("bad_period", f"周期至少 {MIN_PERIOD_MS} ms")
        self.stop_timer(name)
        stop = threading.Event()
        self.timers[name] = stop

        def run():
            n = 0
            while not stop.wait(period_ms / 1000):
                try:
                    self.send(name)
                except LinkError as e:
                    self.emit(e.as_dict())
                    break
                n += 1
                if count and n >= count:
                    break
            with self.lock:
                if self.timers.get(name) is stop:
                    del self.timers[name]
            self.emit({"type": "sender", "presets": self.list()})
        threading.Thread(target=run, daemon=True).start()
        return {"name": name, "period_ms": period_ms, "count": count}

    def stop_timer(self, name: str) -> None:
        with self.lock:
            ev = self.timers.pop(name, None)
        if ev:
            ev.set()

    def add_trigger(self, name: str, field: str, op: str, value: float, cooldown_ms: int = 200) -> dict:
        self.s._check_tx()
        if name not in self.presets or op not in OPS:
            raise LinkError("bad_trigger", "预设不存在或比较符不对", "比较符用 > < >= <= ==")
        self.triggers[name] = {"field": field, "op": op, "value": float(value), "cooldown_ms": cooldown_ms, "armed": True, "last": 0.0, "fired": 0}
        return self.triggers[name]

    def remove_trigger(self, name: str) -> None:
        self.triggers.pop(name, None)

    def stop_all(self, why: str = "") -> None:
        for n in list(self.timers):
            self.stop_timer(n)
        self.triggers.clear()
        if why:
            self._prev_emit({"type": "sender", "presets": self.list(), "stopped": why})

    def _on_sample(self, v: dict) -> None:
        if self.s.tx_locked or not self.triggers:
            return
        now = time.monotonic()
        for name, tg in list(self.triggers.items()):
            x = v.get(tg["field"])
            if x is None:
                continue
            hit = OPS[tg["op"]](float(x), tg["value"])
            if hit and tg["armed"] and now - tg["last"] >= tg["cooldown_ms"] / 1000:
                tg["armed"], tg["last"] = False, now
                tg["fired"] += 1
                try:
                    self.send(name)
                except LinkError as e:
                    self._prev_emit(e.as_dict())
                self._prev_emit({"type": "sender", "presets": self.list(), "fired": name})
            elif not hit:
                tg["armed"] = True
