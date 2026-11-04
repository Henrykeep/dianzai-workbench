"""换板识别（dzctl 0.17.0，fw-wdhash 592ea43 docs/dev/fw-handshake.md）：侧车发 DATA 0x7E {'I'}，23 B 回包报 board_uid / uid_supported。
真仿真板（integration 9e06f98 起 host-sim 回 'I'）：DZ_SIM_UID 模拟不同的板，DZ_SIM_UID_UNSUPPORTED=1 模拟读不到 UID。"""
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


def _connect_wait_id(s, port="sim:car_2wd", timeout=5.0):
    s.connect(port); _up(s)
    t0 = time.monotonic()
    while s._info is None and time.monotonic() - t0 < timeout:
        time.sleep(0.02)
    return s.status()


@pytest.mark.needs_sim
def test_real_sim_two_boards_alternately(home, monkeypatch):
    """同一份固件、两块板（DZ_SIM_UID）来回插：每次都推 board_changed，uid 不同，schema 同内容不算冲突。"""
    ev = []
    s = Session()
    s.emit = ev.append
    seen = {}
    try:
        for i, name in enumerate(("0x1111", "0x2222", "0x1111", "0x2222")):
            monkeypatch.setenv("DZ_SIM_UID", name)
            ev.clear()
            st = _connect_wait_id(s)
            assert st["uid_supported"] is True and st["board_id_message_zh"] is None
            assert len(st["board_uid"]) == 16 and st["board_uid"] == st["board_uid"].lower()
            seen.setdefault(name, st["board_uid"])
            assert seen[name] == st["board_uid"]                                     # 同一块板每次 uid 一样
            ch = [e for e in ev if e.get("type") == "board_changed"]
            if i:
                assert len(ch) == 1 and ch[0]["to"] == st["board_uid"], ev
            assert s.schema_conflict is None and s.schema is not None
            s.disconnect()
        assert seen["0x1111"] != seen["0x2222"]
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_real_sim_same_board_restart(home, monkeypatch):
    """同一块板断开重连（仿真进程重启）：uid 不变、不推 board_changed、按板缓存命中。"""
    monkeypatch.setenv("DZ_SIM_UID", "0x1111")
    ev = []
    s = Session()
    s.emit = ev.append
    try:
        a = _connect_wait_id(s)["board_uid"]
        s.disconnect(); ev.clear()
        b = _connect_wait_id(s)["board_uid"]
        assert a and a == b
        assert not [e for e in ev if e.get("type") == "board_changed"]
        assert any(k[1] == a for k in s._schema_cache)
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_real_sim_uid_unsupported_never_same_board(home, monkeypatch):
    """DZ_SIM_UID_UNSUPPORTED=1（回包 uid_supported=0）：board_uid null + 明确中文；重连也不当同一块板。"""
    monkeypatch.setenv("DZ_SIM_UID_UNSUPPORTED", "1")
    ev = []
    s = Session()
    s.emit = ev.append
    try:
        st = _connect_wait_id(s)
        assert s._info is not None and s._info["uid_supported"] is False
        assert st["board_uid"] is None and st["uid_supported"] is False and st["board_id_known"] is False
        assert st["board_id_message_zh"] == B.NO_UID_ZH == "此芯片暂不支持板子识别，换板检测不可用"
        assert any(e.get("type") == "board_id" and e.get("reason") == "uid_unsupported" for e in ev)
        assert not s._schema_cache
        s.disconnect(); ev.clear()
        _connect_wait_id(s)
        assert [e for e in ev if e.get("type") == "board_changed"]
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_real_sim_old_firmware_2s_timeout(home):
    """固件 < 0.17.0 不认 'I'（不回包）：仓库里已没有旧固件，故障注入 = 发出的 'I' 不上线（与旧固件忽略它等价），
    其余全走真仿真板：2 s 后 board_uid null、uid_supported false、reason fw_too_old、文案「固件版本过旧，不支持板子识别」。"""
    ev = []
    s = Session()
    s.emit = ev.append
    real_send = s._send
    s._send = lambda kind, id_, payload=b"", check=False: True if (id_ == 0x7E and bytes(payload) == b"I") else real_send(kind, id_, payload, check)
    try:
        s.connect("sim:car_2wd"); _up(s)
        t0 = time.monotonic()
        while not any(e.get("reason") == "fw_too_old" for e in ev) and time.monotonic() - t0 < 6:
            time.sleep(0.05)
        waited = time.monotonic() - t0
        st = s.status()
        assert s._info_asked and s._info is None
        assert st["board_uid"] is None and st["uid_supported"] is False
        assert st["board_id_message_zh"] == B.OLD_FW_ZH == "固件版本过旧，不支持板子识别"
        assert any(e.get("type") == "board_id" and e.get("reason") == "fw_too_old" for e in ev)
        assert waited < 4
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_heartbeat_is_40_bytes_and_never_carries_uid(home, monkeypatch):
    """心跳 40 B（0.16.0 的 48 B 已撤回）；board_uid 只来自 'I' 回包。"""
    monkeypatch.setenv("DZ_SIM_UID", "0x1111")
    s = Session()
    lens = []
    orig = s._on_heartbeat
    s._on_heartbeat = lambda p: (lens.append(len(p)), orig(p))[1]
    try:
        s.connect("sim:car_2wd"); _up(s)
        assert lens and set(lens) == {40}
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
                 "board_uid": 0x0123456789ABCDEF, "fw_rev": 7, "proto_ver": None}
    assert B.parse_handshake(d)["board_uid"] == "0123456789abcdef"
    assert B.decode_info(p[:22]) is None and B.decode_info(b"H" + p[1:]) is None


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
        assert c and c["reason"] == "schema_conflict" and c["fix_action"] == "reflash"   # 编译产物对 'I' 回包：板上固件不是这份编译产物 → 重烧，不是清缓存
        assert c["files"][0]["kind"] == "build"
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


def test_info_ask_interrupted_by_link_change_is_reasked():
    """'I' 问到一半链路换了（拔插 / 换口）：回到 idle、允许新链路重问；不留下永远未定的身份（高负载下曾被判 fw_estop_unsafe）。"""
    import threading
    import time as _t
    from dzbench.session import Session
    s = Session()
    s.tr, s.port = object(), "/dev/ttyFAKE"
    s._send = lambda *a, **k: None
    s._info_asked = True
    th = threading.Thread(target=s._ask_info)
    th.start()
    _t.sleep(0.1)
    assert s.ident_state == "asked"
    s.tr = object()                       # 新链路
    th.join(5)
    assert not th.is_alive()
    assert s.ident_state == "idle" and s._info_asked is False and s.fw_estop is None


def test_info_no_reply_needs_heartbeats_not_just_wall_clock(monkeypatch):
    """没回 'I' 的判定要求发出后已处理 INFO_NO_REPLY_HB 帧心跳：rx 线程被饿着（没心跳进来）时不靠墙钟误判旧固件。"""
    import threading
    import time as _t
    from dzbench import board_ident
    from dzbench.session import Session
    monkeypatch.setattr(board_ident, "INFO_TIMEOUT_S", 0.05)
    s = Session()
    s.tr, s.port = object(), "/dev/ttyFAKE"
    s._send = lambda *a, **k: None
    th = threading.Thread(target=s._ask_info, daemon=True)
    th.start()
    _t.sleep(0.4)
    assert s.ident_state == "asked" and s.fw_estop is None
    s._hb_after_ask = board_ident.INFO_NO_REPLY_HB
    th.join(5)
    assert s.ident_state == "no_reply" and s.fw_estop is not None and not s.fw_estop["safe"]
    s.tr = None
