"""记住“上次连着哪个口”：侧车被杀/崩溃后重启，界面能告诉用户发生了什么并预选那个口。

连上时写 ~/.dzbench/last_session.json，用户点“断开”时删掉。侧车启动时文件还在 = 上次不是正常退出。
不自动重连：重启后的第一个动作交给人（板子此时已因心跳超时自己急停）。
"""
from __future__ import annotations

import json
import time

from . import snapshots


def _path():
    return snapshots.base_dir() / "last_session.json"


def mark(port: str, baud: int) -> None:
    if port.startswith("replay:"):
        return
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"port": port, "baud": baud, "t": time.time()}), encoding="utf-8")
    except OSError:
        pass


def clear() -> None:
    try:
        _path().unlink(missing_ok=True)
    except OSError:
        pass


def take_unclean() -> dict | None:
    """启动时调用一次：上次没有正常断开就返回那次的口和给用户的话，并删掉记录。"""
    p = _path()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    clear()
    d["message"] = (f"侧车刚才意外退出，已经重新启动。上次连的是 {d['port']}，板子应已因 1 秒没心跳自己急停。"
                    "确认车/机构安全后点“连接”，再按“解除急停 R”")
    return d
