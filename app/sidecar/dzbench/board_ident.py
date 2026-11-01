"""板子身份（换板指纹）：从固件握手读 board_uid（64 位 FNV-1a 的 MCU 唯一 ID）与 uid_supported。

规格：fw-wdhash 592ea43 的 docs/dev/fw-handshake.md（dzctl 0.17.0）——侧车发 DATA 0x7E {'I'}，23 B 回包里报 board_uid64 与 uid_supported；不在心跳里。
- 报给界面：board_uid = 16 位小写十六进制或 null；uid_supported = bool。
- uid_supported 为 false、board_uid 缺 / 为 0 → board_uid = null，并显式提示 NO_UID_ZH；这种板子永远不和缓存里的任何板子算同一块。
"""
from __future__ import annotations

import struct

NO_UID_ZH = "此芯片暂不支持板子识别，换板检测不可用"
OLD_FW_ZH = "固件版本过旧，不支持板子识别"
INFO_CMD = b"I"            # DATA id=0x7E {'I'}（dzctl 0.17.0）
INFO_LEN = 23
INFO_TIMEOUT_S = 2.0

# fw_estop_unsafe：急停可被误清除的固件（dzctl < 0.18.0）或没有 'I' 回包 → 禁止一切驱动执行器的操作，只许读和烧录。
# 规格：fw-unknown-cmd 854b6a1 docs/dev/fw-handshake.md —— info_ver=2、27 B 回包，偏移 23 的 u32 proto_ver = major<<16|minor<<8|patch。
# fw_rev 仍是 git 短哈希，不能当版本用。全仓只此一处定义最低版本。
MIN_ESTOP_SAFE_PROTO = 0x00001200   # dzctl 0.18.0
INFO_LEN_V2 = 27
ESTOP_UNSAFE_ZH = "此固件存在急停可被误清除的问题，请重新烧录"


def proto_str(v: int | None) -> str | None:
    return None if v is None else f"{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"


def estop_safety(info: dict | None) -> dict:
    """{safe, reason, message_zh, fix_action, min_version, version}。没回包 / info_ver < 2 / proto_ver < 最低 → 不安全。"""
    ok_info = info is not None and not info.get("fw_too_old")
    pv = info.get("proto_ver") if ok_info and (info.get("info_ver") or 0) >= 2 else None
    safe = pv is not None and pv >= MIN_ESTOP_SAFE_PROTO
    return {"safe": safe, "reason": None if safe else "fw_estop_unsafe", "message_zh": None if safe else ESTOP_UNSAFE_ZH,
            "fix_action": None if safe else "reflash", "min_version": proto_str(MIN_ESTOP_SAFE_PROTO), "version": proto_str(pv)}


def decode_info(p: bytes) -> dict | None:
    """'I' 回包（dzctl 0.17.0，小端 23 B）：'I', u8 info_ver, u32 schema_hash, u32 wd_timeout_ms, u8 uid_supported,
    u32 uid_lo, u32 uid_hi, u32 fw_rev；info_ver=2（0.18.0，27 B）再加 u32 proto_ver。info_ver 以后只往后追加。不是 'I' 回包返回 None。"""
    if len(p) < INFO_LEN or p[0] != ord("I"):
        return None
    ver, h, wd, sup, lo, hi, rev = struct.unpack_from("<BIIBIII", p, 1)
    d = {"info_ver": ver, "schema_hash": h, "wd_timeout_ms": wd, "uid_supported": bool(sup),
         "board_uid": (hi << 32) | lo, "fw_rev": rev, "proto_ver": None}
    if ver >= 2 and len(p) >= INFO_LEN_V2:           # dzctl 0.18.0+：info_ver=2，27 B，偏移 23 u32 proto_ver
        d["proto_ver"] = struct.unpack_from("<I", p, INFO_LEN)[0]
    return d


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
    if d.get("fw_too_old"):          # 2 s 内没等到 'I' 回包（固件 < dzctl 0.17.0）
        return {"board_uid": None, "uid_supported": False, "board_id_known": False,
                "reason": "fw_too_old", "message_zh": OLD_FW_ZH}
    sup = d.get("uid_supported") is True
    v = _as_int(d.get("board_uid"))
    uid = f"{v & 0xFFFFFFFFFFFFFFFF:016x}" if sup and v else None
    return {"board_uid": uid, "uid_supported": sup, "board_id_known": uid is not None,
            "reason": None if uid else "uid_unsupported", "message_zh": None if uid else NO_UID_ZH}


def same_board(a: str | None, b: str | None) -> bool:
    """未知身份（None）永远不算同一块板。"""
    return a is not None and b is not None and a == b
