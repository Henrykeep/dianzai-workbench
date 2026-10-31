"""记住“上次连着哪个口、哪块板”：侧车被杀/崩溃后重启，自动连回那块板。

连上时写 $DZBENCH_HOME/last_session.json（不在仓库里），收到心跳后补上板子身份；
用户点“断开”或侧车正常退出（SIGTERM/Ctrl-C）时删掉 = 不再自动重连。
侧车启动时文件还在 = 上次不是正常退出 → Server 启动后先按原口重连，口没了就按板子身份重扫端口。
安全：自动重连只恢复链路，不解除急停（板子已因 1 s 没心跳自己急停并锁存，解除仍要人在界面点“解除急停”）。
"""
from __future__ import annotations

import json
import time

from . import snapshots


def _path():
    return snapshots.base_dir() / "last_session.json"


def _write(d: dict) -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def read() -> dict | None:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("port") else None
    except (OSError, ValueError):
        return None


def mark(port: str, baud: int, ident: tuple | None = None) -> None:
    if port.startswith("replay:"):
        return
    _write({"port": port, "baud": baud, "ident": list(ident) if ident else None, "t": time.time()})


def mark_board(port: str, board_uid: int | None, schema_hash: int | None) -> None:
    """收到第一帧心跳后补记板子身份（换口后靠它认回同一块板）。只更新同一个口的记录。"""
    d = read()
    if not d or d.get("port") != port:
        return
    if d.get("board_uid") == board_uid and d.get("schema_hash") == schema_hash:
        return
    d.update(board_uid=board_uid, schema_hash=schema_hash)
    _write(d)


def restore(d: dict) -> None:
    """自动重连失败时把记录放回去：下次重启还会再试（用户点“断开”才真正放弃）。"""
    _write({k: v for k, v in d.items() if k != "message"})


def clear() -> None:
    try:
        _path().unlink(missing_ok=True)
    except OSError:
        pass


def take_unclean() -> dict | None:
    """启动时调用一次：上次没有正常断开就返回那次的记录和给用户的话。记录留着，自动重连成功后会重写。"""
    d = read()
    if not d:
        return None
    d["message"] = (f"本地服务刚才意外退出，已经重新启动，正在自动连回 {d['port']}。板子应已因 1 秒没心跳自己急停；"
                    "确认车/机构安全后按“解除急停”")
    return d
