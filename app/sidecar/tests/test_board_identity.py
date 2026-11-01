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


@pytest.mark.needs_sim
def test_heartbeat_tail_48_bytes_not_used_for_board_uid(home, monkeypatch):
    """fw-wdhash 2216f76 曾把 u64 board_uid64 追加进心跳（len 48），integration 59f1d0c 已撤回。后端从不依赖心跳里的 UID：
    board_uid 只从握手来；没握手时即使心跳带了 UID 也报未知 + 明确中文提示。"""
    monkeypatch.setenv("DZ_SIM_UID", "board-x")
    s = Session()
    try:
        s.connect("sim:car_2wd"); _up(s)
        st = s.status()
        assert st["board_uid"] is None and st["board_id_known"] is False
        assert st["board_id_message_zh"] == B.NO_UID_ZH
        assert s.schema is not None                      # len 48 心跳照常解析（只读前 40 字节）
    finally:
        s.disconnect()


# ---- dzctl 0.17.0 'I' 握手信息（DATA 0x7E {'I'} → 23 B 回包）----
import struct as _st

from dzbench._dzlink import DATA as _DATA, encode as _encode


def _info_frame(h, wd, sup, uid, rev=0x1234567):
    p = bytes([ord("I"), 1]) + _st.pack("<IIBIII", h, wd, 1 if sup else 0, uid & 0xFFFFFFFF, uid >> 32, rev)
    assert len(p) == 23
    return _encode(_DATA, 0x7E, 9, p)


def test_decode_info_layout():
    p = bytes([ord("I"), 1]) + _st.pack("<IIBIII", 0xA1B2C3D4, 1500, 1, 0x89ABCDEF, 0x01234567, 7)
    d = B.decode_info(p)
    assert d == {"info_ver": 1, "schema_hash": 0xA1B2C3D4, "wd_timeout_ms": 1500, "uid_supported": True,
                 "board_uid": 0x0123456789ABCDEF, "fw_rev": 7}
    assert B.parse_handshake(d)["board_uid"] == "0123456789abcdef"
    assert B.decode_info(p[:22]) is None and B.decode_info(b"H" + p[1:]) is None


@pytest.mark.needs_sim
def test_old_firmware_no_info_reply_reports_too_old(home):
    """当前仓库 host-sim 固件早于 dzctl 0.17.0、不回 'I'：2 s 后 board_uid null、uid_supported false、reason fw_too_old。"""
    ev = []
    s = Session()
    s.emit = ev.append
    try:
        s.connect("sim:car_2wd"); _up(s)
        assert s._info_asked                                   # 有效 40 B 心跳后发过一次 'I'
        t0 = time.monotonic()
        while s.status()["board_id_message_zh"] != B.OLD_FW_ZH and time.monotonic() - t0 < 6:
            time.sleep(0.05)
        st = s.status()
        assert st["board_uid"] is None and st["uid_supported"] is False and st["board_id_message_zh"] == "固件版本过旧，不支持板子识别"
        assert any(e.get("type") == "board_id" and e.get("reason") == "fw_too_old" for e in ev)
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_info_reply_stub_frame_through_real_parser(home):
    """'I' 回包（桩帧，按 18720ae 的布局编码）经真实 Parser 进来：报 16 位小写 hex + uid_supported，不触发过旧提示。"""
    s = Session()
    try:
        s.connect("sim:car_2wd"); _up(s)
        s._on_bytes(_info_frame(s.schema.hash, s.schema.wd_timeout_ms or 0, True, 0x0123456789ABCDEF))
        time.sleep(2.5)                                         # 越过 2 s 超时，确认不会被改成「过旧」
        st = s.status()
        assert st["board_uid"] == "0123456789abcdef" and st["uid_supported"] is True and st["board_id_message_zh"] is None
        assert st["schema_conflict"] is None and s.schema is not None
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_info_reply_wd_mismatch_same_hash_is_schema_conflict(home):
    """'I' 回包 schema_hash 与缓存一致但 wd_timeout_ms 不同 = 缓存的格式文件不是这块板的 → schema_conflict。"""
    ev = []
    s = Session()
    s.emit = ev.append
    try:
        s.connect("sim:car_2wd"); _up(s)
        sch = s.schema
        assert sch.wd_timeout_ms
        s._on_bytes(_info_frame(sch.hash, sch.wd_timeout_ms + 700, True, 0x0123456789ABCDEF))
        t0 = time.monotonic()
        while s.schema_conflict is None and time.monotonic() - t0 < 3:
            time.sleep(0.02)
        c = s.status()["schema_conflict"]
        assert c and c["reason"] == "schema_conflict" and c["fix_action"] == "clear_schema_cache"
        assert c["hash"] == f"{sch.hash:08X}" and c["board_uid"] == "0123456789abcdef" and len(c["files"]) == 1
        assert s.schema is None
        with pytest.raises(Exception) as ei:
            s.set_param(next(iter(sch.params)).name if hasattr(next(iter(sch.params)), "name") else list(sch.params)[0], 1.0)
        assert getattr(ei.value, "code", None) == "schema_conflict"
    finally:
        s.disconnect()


def test_info_not_sent_while_heartbeat_estop_bit_set(home):
    """旧固件（< 0.17.0）把未知单字节命令当新指令、会清 'R' 后的输出保持：心跳 bit10 置位时不发 'I'，清零后才发。"""
    from dzbench._dzlink import HEARTBEAT as _HB
    sent = []
    s = Session()
    s.emit = lambda e: None
    s._send = lambda kind, id_, payload=b"", check=False: sent.append((kind, id_, bytes(payload))) or True

    def hb(status):
        return _encode(_HB, 0, 1, _st.pack("<IIII", 0x1234, 0, 0, status) + bytes(24))
    s._on_bytes(hb(1 << 10))
    time.sleep(0.2)
    assert not s._info_asked and (_DATA, 0x7E, b"I") not in sent
    s.tx_locked = False
    s._on_bytes(hb(0))
    t0 = time.monotonic()
    while (_DATA, 0x7E, b"I") not in sent and time.monotonic() - t0 < 2:
        time.sleep(0.02)
    assert s._info_asked and sent.count((_DATA, 0x7E, b"I")) == 1
