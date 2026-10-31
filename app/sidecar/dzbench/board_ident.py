"""板子身份（换板指纹）：从固件握手读 board_uid（64 位 FNV-1a 的 MCU 唯一 ID）与 uid_supported。

规格（与嵌入式开发-2 约定，r10）：board_uid 只在握手里报一次，不在心跳里；握手同时报 uid_supported(bool)。
- 报给界面：board_uid = 16 位小写十六进制或 null；uid_supported = bool。
- uid_supported 为 false、board_uid 缺 / 为 0 → board_uid = null，并显式提示 NO_UID_ZH；这种板子永远不和缓存里的任何板子算同一块。
固件握手帧尚未推送时，侧车按本规格实现；握手 dict 来自哪种帧由 Session.apply_handshake 的调用方决定。
"""
from __future__ import annotations

NO_UID_ZH = "此芯片暂不支持板子识别，换板检测不可用"


def _as_int(v) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        t = v.strip().lower()
        t = t[2:] if t.startswith("0x") else t
        try:
            return int(t, 16) if t else None
        except ValueError:
            return None
    return None


def parse_handshake(d: dict | None) -> dict:
    """握手 dict → {board_uid, uid_supported, board_id_known, message_zh}。"""
    d = d or {}
    sup = d.get("uid_supported") is True
    v = _as_int(d.get("board_uid"))
    uid = f"{v & 0xFFFFFFFFFFFFFFFF:016x}" if sup and v else None
    return {"board_uid": uid, "uid_supported": sup, "board_id_known": uid is not None,
            "message_zh": None if uid else NO_UID_ZH}


def same_board(a: str | None, b: str | None) -> bool:
    """未知身份（None）永远不算同一块板。"""
    return a is not None and b is not None and a == b
