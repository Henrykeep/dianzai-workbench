"""换板识别（r10，与嵌入式开发-2 约定的握手规格）：board_uid 只在握手里报一次（16 位小写十六进制 / null），另报 uid_supported。
固件的握手帧尚未推送：这里在真仿真板会话上把握手 dict 交给真解析器（Session.apply_handshake → board_ident.parse_handshake）。"""
import time

import pytest

from dzbench import board_ident as B
from dzbench.session import Session

UID_A, UID_B = 0x0123456789ABCDEF, 0xFEDCBA9876543210


def test_parse_handshake_formats_and_unknowns():
    assert B.parse_handshake({"board_uid": UID_A, "uid_supported": True})["board_uid"] == "0123456789abcdef"
    assert B.parse_handshake({"board_uid": "0x0123456789ABCDEF", "uid_supported": True})["board_uid"] == "0123456789abcdef"
    for d in ({"board_uid": UID_A, "uid_supported": False}, {"board_uid": 0, "uid_supported": True},
              {"uid_supported": True}, {}, None, {"board_uid": UID_A}):
        r = B.parse_handshake(d)
        assert r["board_uid"] is None and r["board_id_known"] is False and r["message_zh"] == B.NO_UID_ZH, (d, r)
    assert not B.same_board(None, None) and not B.same_board("a", None) and B.same_board("a", "a")


def _up(s):
    t0 = time.monotonic()
    while not (s.schema and len(s.params) == len(s.schema.params)) and time.monotonic() - t0 < 20:
        time.sleep(0.05)
    assert s.schema is not None


@pytest.mark.needs_sim
def test_two_boards_alternately_same_firmware(home):
    ev = []
    s = Session()
    s.emit = ev.append
    try:
        s.connect("sim:car_2wd"); _up(s)
        s.apply_handshake({"board_uid": UID_A, "uid_supported": True})
        st = s.status()
        assert st["board_uid"] == "0123456789abcdef" and st["uid_supported"] is True and st["board_id_message_zh"] is None
        sch_a = s.schema
        for uid, want in ((UID_B, "fedcba9876543210"), (UID_A, "0123456789abcdef"), (UID_B, "fedcba9876543210")):
            s.disconnect(); ev.clear()
            s.connect("sim:car_2wd")
            s.apply_handshake({"board_uid": uid, "uid_supported": True})
            ch = [e for e in ev if e.get("type") == "board_changed"]
            assert len(ch) == 1 and ch[0]["to"] == want, ev                   # 换板：推事件
            _up(s)
            assert s.schema_conflict is None and s.schema.d == sch_a.d        # 同一固件、同内容：不算冲突
            assert s.status()["board_uid"] == want
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_same_board_restart_keeps_uid_and_cache(home):
    ev = []
    s = Session()
    s.emit = ev.append
    try:
        s.connect("sim:car_2wd"); _up(s)
        s.apply_handshake({"board_uid": UID_A, "uid_supported": True})
        _up(s)
        s.disconnect(); ev.clear()
        s.connect("sim:car_2wd")
        s.apply_handshake({"board_uid": UID_A, "uid_supported": True})
        assert not [e for e in ev if e.get("type") == "board_changed"]
        _up(s)
        assert s.status()["board_uid"] == "0123456789abcdef"
        assert any(k[1] == "0123456789abcdef" for k in s._schema_cache)
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_unsupported_uid_never_same_board(home):
    ev = []
    s = Session()
    s.emit = ev.append
    try:
        s.connect("sim:car_2wd"); _up(s)
        s.apply_handshake({"board_uid": 0, "uid_supported": False})
        st = s.status()
        assert st["board_uid"] is None and st["uid_supported"] is False and st["board_id_known"] is False
        assert st["board_id_message_zh"] == B.NO_UID_ZH
        assert any(e.get("type") == "board_id" and e["message_zh"] == B.NO_UID_ZH for e in ev)
        assert not s._schema_cache                                            # 身份未知：不进按板缓存
        s.disconnect(); ev.clear()
        s.connect("sim:car_2wd")
        s.apply_handshake({"board_uid": 0, "uid_supported": False})           # 同样“未知”也不能当同一块板
        assert [e for e in ev if e.get("type") == "board_changed"]
        _up(s)
    finally:
        s.disconnect()
