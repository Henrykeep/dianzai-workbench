"""连上时板子已经急停（bit10 一开始就是 1，没有上升沿）：第一帧心跳里的原因也要推出来（cause_zh 非空）；
latched.board_t_ms = 心跳尾部 t_ms（锁存时刻）；32 字节心跳的 clear_t_ms → cleared.board_t_ms，28 字节没有就不带。"""
import struct

from dzbench import latch
from dzbench.session import Session

H, UID = 0x1234ABCD, 0xC0FFEE
BIT10 = 1 << 10


def hb(w, cause=3, t_ms=12345, value=0.8, clear_t_ms=None):
    p = struct.pack("<IIII", H, UID, 7, w) + struct.pack("<IIf", cause, t_ms, value)
    return p + (struct.pack("<I", clear_t_ms) if clear_t_ms is not None else b"")


def rig(port="COM9"):
    ev = []
    s = Session(emit=ev.append)
    s.port, s.schema_hash = port, H
    return s, ev


def latched(ev):
    return [e for e in ev if e.get("type") == "estop" and e.get("state") == "latched"]


def test_fresh_connect_already_latched(home):
    s, ev = rig()
    s._on_heartbeat(hb(BIT10))
    ls = [e for e in latched(ev) if e.get("cause_zh") and e.get("cause")]
    assert ls and ls[-1]["cause"] == "stall" and "堵转" in ls[-1]["cause_zh"] and ls[-1]["board_t_ms"] == 12345
    assert s.status()["estop_cause"]["cause_zh"]


def test_restored_latch_already_latched_pushes_cause(home):
    """锁存按端口恢复（open 里 tx_locked + 已知原因），板子第一帧心跳 bit10=1、原因相同：以前什么都不推 → 界面 cause 为 null。"""
    s0, _ = rig()
    s0._on_heartbeat(hb(BIT10))                              # 上一次连接：锁存并持久化（带原因）
    rec = latch.get("COM9", None)
    assert rec and rec.get("cause")
    s, ev = rig()
    s.tx_locked, s.estop_source, s.estop_cause = True, rec["source"], rec["cause"]   # = Session.open 的恢复逻辑
    s._on_heartbeat(hb(BIT10))
    ls = latched(ev)
    assert len(ls) == 1 and ls[0]["cause"] == "stall" and ls[0]["cause_zh"] and ls[0]["board_t_ms"] == 12345
    s._on_heartbeat(hb(BIT10))                               # 只推一次
    assert len(latched(ev)) == 1


def test_clear_t_ms_by_length(home):
    for tail, want in ((None, None), (20000, 20000)):
        s, ev = rig("COM%d" % (7 if tail is None else 8))
        s._on_heartbeat(hb(BIT10))
        s.clear_pending_at = __import__("time").monotonic()
        s._on_heartbeat(hb(0, cause=0, t_ms=0, value=0.0, clear_t_ms=tail))
        cl = [e for e in ev if e.get("type") == "estop" and e.get("state") == "cleared"]
        assert len(cl) == 1 and cl[0].get("board_t_ms") == want and not s.tx_locked
