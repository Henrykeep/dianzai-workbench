"""急停锁存的持久记录（缺口 #20）：按板子身份记住“急停后侧车已锁定发送”，断开重连、侧车重启都不解除。

存在 $DZBENCH_HOME/estop_latch.json（不在仓库里）。键：
- ``port:<端口>``：连上就能查（仿真板 sim:xxx、真串口 /dev/ttyUSB0、COM3）；
- ``uid:<芯片 ID 十六进制>``：心跳带上芯片 ID 后再查一次（板子换了口也认得出）。
只有人点“解除急停”（cmd R，界面）才 clear；重连只恢复通信和遥测，不重发任何运动指令或设定值。
"""
from __future__ import annotations

import json
import threading
import time

from . import snapshots

_lk = threading.Lock()


def _path():
    return snapshots.base_dir() / "estop_latch.json"


def _load() -> dict:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def keys(port: str | None, uid: int | None) -> list[str]:
    out = []
    if port and not port.startswith("replay:"):
        out.append("port:" + port.split("+")[0] if port.startswith("sim:") else "port:" + port)
    if uid:
        out.append(f"uid:{uid:08X}")
    return out


def set(port: str | None, uid: int | None, source: str, detail: str = "") -> None:  # noqa: A001
    ks = keys(port, uid)
    if not ks:
        return
    with _lk:
        d = _load()
        rec = {"source": source, "detail": detail, "t": time.time()}
        for k in ks:
            d[k] = rec
        _save(d)


def get(port: str | None, uid: int | None) -> dict | None:
    ks = keys(port, uid)
    if not ks:
        return None
    with _lk:
        d = _load()
    for k in ks:
        if k in d:
            return d[k]
    return None


def clear(port: str | None, uid: int | None) -> None:
    ks = keys(port, uid)
    if not ks:
        return
    with _lk:
        d = _load()
        if any(k in d for k in ks):
            for k in ks:
                d.pop(k, None)
            _save(d)
