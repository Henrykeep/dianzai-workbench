"""唯一的连接状态源：侧车按固定节拍推送 `link.state`，横幅、状态栏和 Agent 都只读它。

board 状态机（只看侧车自己的事实：串口是否打开、是否在重连、最近一帧合法帧的时间）：
  disconnected  没有打开任何端口（含主动断开）
  connecting    端口已打开，但本次连接还没收到合法帧
  connected     最近 LOST_AFTER_S 内收到过合法帧（心跳或遥测都算）
  lost          收到过帧后静默超过 LOST_AFTER_S，或传输层断开正在自动重连

判定用“任一合法帧”而不是只看心跳：板子心跳 500 ms 一帧，偶发 CRC 坏帧或 USB 突发延迟
就可能连丢 3 个心跳；遥测还在来就说明板子活着，不应报断开。

sidecar 字段：侧车能发出这条事件就说明它活着，恒为 "ok"。UI 侧规则：WebSocket 断开，
或超过 stale_after_ms 没收到新的 link.state，即视为 "unresponsive"，此时忽略 board 字段。
"""
from __future__ import annotations

import time

LOST_AFTER_S = 2.0        # 4 个板子心跳周期
PUSH_EVERY_S = 1.0        # 状态不变时的保活推送间隔
STALE_AFTER_MS = 3000     # UI 超过这么久没收到 link.state = 侧车无响应


def board_state(now: float, port_open: bool, reconnecting: bool, t_connect: float, last_frame: float) -> str:
    if reconnecting:
        return "lost"
    if not port_open:
        return "disconnected"
    if last_frame <= t_connect:
        return "connecting"
    return "connected" if now - last_frame <= LOST_AFTER_S else "lost"


class LinkState:
    """把 Session 的瞬时事实折算成 link.state；状态变化立即推送，不变时每 PUSH_EVERY_S 保活一次。"""

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._since_ms = 0
        self._pushed = 0.0
        self._seq = 0
        self.last: dict | None = None     # 最近一次推送的内容（hello 里给新连上的窗口）

    def update(self, now: float, *, port: str, port_open: bool, reconnecting: bool,
               t_connect: float, last_frame: float, reason: str = "") -> dict | None:
        board = board_state(now, port_open, reconnecting, t_connect, last_frame)
        if board == "lost" and not reason:
            reason = "transport_closed" if reconnecting else "no_frames"
        if board != "lost":
            reason = ""
        key = (board, port if board != "disconnected" else "", reason)
        changed = key != self._key
        if changed:
            self._key, self._since_ms = key, int(time.time() * 1000)
        if not changed and now - self._pushed < PUSH_EVERY_S:
            return None
        self._pushed = now
        self._seq += 1
        heard = board in ("connected", "lost") and last_frame > 0
        self.last = {"type": "link.state", "seq": self._seq, "sidecar": "ok", "board": board,
                "port": key[1] or None, "since": self._since_ms,
                "last_rx_ms": int((now - last_frame) * 1000) if heard else None,
                "reason": reason or None, "stale_after_ms": STALE_AFTER_MS}
        return self.last
