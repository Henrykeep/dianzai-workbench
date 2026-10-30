"""固件心跳上报（16 / 28 / 40 字节）→ link.state 快照字段与 progress 阻塞项；Agent 不能切换运行模式。"""
import struct

import pytest

from dzbench import progress as P
from dzbench._dzlink import HEARTBEAT, encode
from dzbench.session import Session

H = 0x1234ABCD
STANDALONE, ESTOP, UNSAVED = 1 << 14, 1 << 10, 1 << 16


def _hb(s, status: int, *, cause=None, selftest=None, phash=0xDEADBEEF, seq=[0]):
    p = struct.pack("<IIII", H, 7, 1, status)
    if cause is not None or selftest is not None:
        c, t, v = cause or (0, 0, 0.0)
        p += struct.pack("<IIf", c, t, v)
    if selftest is not None:
        p += struct.pack("<III", selftest[0], selftest[1], phash)
    seq[0] = (seq[0] + 1) & 0xFF
    s._on_bytes(encode(HEARTBEAT, 0, seq[0], p))


def _sess():
    s = Session()
    s.schema_hash = H                                   # 跳过按哈希找 schema
    s.link.last = {"board": "connected", "reason": None}
    return s


def _codes(snap):
    return {b["code"]: b for b in snap["blockers"]}


def test_len16_old_firmware_falls_back(home):
    s = _sess()
    _hb(s, 1)
    fw = s.fw_status()
    assert fw["selftest"] is None and fw["params_hash"] is None and fw["params_saved"] is None and fw["estop_cause"] is None
    assert fw["run_mode"]["mode"] == "tethered"
    snap = P.Progress(s).snapshot()
    assert "selftest_fail" not in _codes(snap) and "params_not_saved" not in _codes(snap)
    for k in P.FW_FIELDS:
        assert k in snap
    assert snap["selftest"] is None and snap["mode"] == "tethered"
    _hb(s, 4 | (1 << 8))                                # 旧固件：安全态 + 看门狗复位 → 沿用推断
    assert "安全态" in _codes(P.Progress(s).snapshot())["selftest_fail"]["message"]


def test_len28_estop_cause(home):
    s = _sess()
    _hb(s, 1 | ESTOP, cause=(2, 1500, 3.2))
    ec = s.fw_status()["estop_cause"]
    assert ec and ec["message_zh"]
    b = _codes(P.Progress(s).snapshot())["estop"]
    assert ec["message_zh"] in b["message"] and b["detail"]["cause_id"] == 2
    assert s.fw_status()["selftest"] is None            # 28 字节没有自检


def test_len40_selftest_and_params(home):
    s = _sess()
    _hb(s, 1 | STANDALONE | UNSAVED, selftest=(0b1010, 900), phash=0x0BADF00D)
    fw = s.fw_status()
    assert fw["run_mode"]["mode"] == "standalone" and fw["params_saved"] is False and fw["params_hash"] == "0badf00d"
    assert [i["key"] for i in fw["selftest"]["failed_items"]] == ["params", "sensor"]
    snap = P.Progress(s).snapshot()
    c = _codes(snap)
    assert c["selftest_fail"]["fix_action"] == "run_selftest" and len(c["selftest_fail"]["detail"]) == 2
    assert c["params_not_saved"]["fix_action"] == "params_flash"
    assert snap["mode"] == "standalone" and snap["params_hash"] == "0badf00d"
    _hb(s, 1, selftest=(0, 900))                        # 全部通过 + 已保存
    c = _codes(P.Progress(s).snapshot())
    assert "selftest_fail" not in c and "params_not_saved" not in c


def test_link_state_carries_fw_snapshot(home):
    s = _sess()
    _hb(s, 1 | STANDALONE, selftest=(0, 900))
    ls = s.link.update(0.0, port="sim:x", port_open=True, reconnecting=False, t_connect=0.0, last_frame=0.0,
                       mode=s.fw_status()["run_mode"]["mode"], fw=s.fw_status())
    assert ls["mode"] == "standalone" and ls["selftest"]["pass"] is True and ls["params_saved"] is True
    ls2 = s.link.update(0.1, port="sim:x", port_open=True, reconnecting=False, t_connect=0.0, last_frame=0.0)
    assert ls2 is not None and all(ls2[k] is None for k in P.FW_FIELDS)   # 快照变化立即推；没报 = null


def test_agent_cannot_switch_run_mode(home):
    from dzbench.agent.gateway import human_only_error
    from dzbench.agent.loop import TOOLS
    from dzbench.agent_api import AgentTools
    from dzbench.session import LinkError
    assert "set_run_mode" not in {t["name"] for t in TOOLS}
    e = human_only_error("set_run_mode")
    assert e["type"] == "agent_error" and e["fix_action"] == "precontest" and "封箱" in e["fix"]
    s = _sess()
    sent = []
    s._send = lambda *a: sent.append(a) or True
    with pytest.raises(LinkError) as ei:
        AgentTools(s, lambda e: None).call("set_run_mode", {"mode": "standalone", "confirmed": True})
    assert ei.value.code == "human_only" and not sent
    r = s.set_run_mode("standalone")                    # 界面 RPC 未确认 → needs_confirm 原样给界面，不发指令
    assert r["needs_confirm"] is True and not sent


def test_selftest_snapshot_at_hash_and_stale():
    import datetime
    from dzbench.session import Session
    s = Session()
    assert s.fw_status()["selftest"] is None
    s.selftest, s.params_hash = {"pass": True, "failed_items": [], "t": 1.0}, 0xAB
    s.selftest_at, s.selftest_ph = "2026-10-31T05:00:00+08:00", 0xAB
    for snap in (s.fw_status()["selftest"], s.status()["selftest"]):     # progress 与 link.state 同一份
        assert snap["at"] and datetime.datetime.fromisoformat(snap["at"]) and snap["params_hash_at"] == "000000ab" and snap["stale"] is False
    s.params_hash = 0xCD                                                  # 自检后改了参数 → 要重新自检
    assert s.fw_status()["selftest"]["stale"] is True and s.status()["selftest"]["stale"] is True


def test_selftest_h_ack_records_at_and_hash():
    import struct
    from dzbench.session import Session
    s = Session()
    s.params_hash = 0x1234
    s._send = lambda *a, **k: (setattr(s, "selftest_ack", struct.unpack_from("<I", b"H\x00\x00\x00\x00", 1)[0]) or True)
    s._check_tx = lambda: None
    s.run_selftest(wait_s=0.2)
    assert s.selftest_at and s.selftest_ph == 0x1234
