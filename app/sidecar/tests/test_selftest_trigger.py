"""重跑自检（0x48）：侧车发 'H' → 板回 {0x48, u32 mask LE} → 按自检项注册表解码 → 刷新快照 / 进度。
仿真板（host-sim）用 DZ_SIM_SELFTEST_FAIL 注入失败项；另测超时、旧固件退回、未连接，以及存参 / 切模式的字节编码。"""
import struct
import time

import pytest

from dzbench import progress as P
from dzbench._dzlink import HEARTBEAT, encode
from dzbench.session import DATA, ID_CMD, LinkError, Session


def _wait(pred, t=20.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _up(app="car_2wd"):
    s = Session()
    s.connect("sim:" + app)
    assert _wait(lambda: s.status()["alive"] and s.schema and s.status().get("selftest")), s.status()
    return s


def _codes(s):
    s.link_state()
    return {b["code"]: b for b in P.Progress(s).snapshot()["blockers"]}


@pytest.mark.needs_sim
@pytest.mark.parametrize("app", ["car_2wd", "motor_pos"])
def test_trigger_pass(app, home, tmp_path, monkeypatch):
    monkeypatch.setenv("DZ_SIM_NVM", str(tmp_path / "nvm.bin"))
    monkeypatch.delenv("DZ_SIM_SELFTEST_FAIL", raising=False)
    s = _up(app)
    try:
        r = s.run_selftest()
        assert r["ok"] is True and r["mask"] == 0 and r["failed_items"] == [] and r["source"] == "trigger", r
        assert s.fw_status()["selftest"]["pass"] is True
        assert "selftest_fail" not in _codes(s)
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_trigger_failures_decode_and_estop_cause(home, tmp_path, monkeypatch):
    monkeypatch.setenv("DZ_SIM_NVM", str(tmp_path / "nvm.bin"))
    monkeypatch.setenv("DZ_SIM_SELFTEST_FAIL", "0x18")          # code 4 传感器 + code 5 电源
    s = _up("car_2wd")
    try:
        assert _wait(lambda: s.fw_status()["estop_cause"] is not None, 5.0)
        ec = s.fw_status()["estop_cause"]
        assert ec["cause"] == "selftest" and ec["cause_id"] == 7, ec          # 上电自检不过 → 急停原因 SELFTEST
        b = _codes(s)
        assert b["estop"]["fix_action"] == "estop_clear" and ec["message_zh"] in b["estop"]["message"], b
        r = s.run_selftest()                                                   # 急停锁存时也允许（只读）
        assert r["mask"] == 0x18 and r["ok"] is False, r
        assert [(i["code"], i["key"]) for i in r["failed_items"]] == [(4, "sensor"), (5, "power")], r
        assert all(i["message_zh"] for i in r["failed_items"])
        st = s.fw_status()["selftest"]
        assert st["pass"] is False and [i["code"] for i in st["failed_items"]] == [4, 5]
        assert (s.link_state() or s.link.last)["selftest"]["failed_items"][0]["key"] == "sensor"
        assert s.cmd("R")                                                      # 'R' 解除急停
        assert _wait(lambda: "急停" not in (s.status().get("hb_flags") or []), 5.0), s.status()
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_trigger_timeout_is_retryable(home, tmp_path, monkeypatch):
    monkeypatch.setenv("DZ_SIM_NVM", str(tmp_path / "nvm.bin"))
    monkeypatch.delenv("DZ_SIM_SELFTEST_FAIL", raising=False)
    s = _up("car_2wd")
    try:
        assert s.run_selftest()["ok"] is True                                  # 本次连接里板子答过 'H'
        real = s._send
        sent = []

        def drop_h(kind, id_, payload=b""):
            if kind == DATA and id_ == ID_CMD and payload == b"\x48":
                sent.append(payload)
                return True                                                    # 模拟丢帧：板子收不到
            return real(kind, id_, payload)
        monkeypatch.setattr(s, "_send", drop_h)
        with pytest.raises(LinkError) as ei:
            s.run_selftest(wait_s=0.2)
        e = ei.value
        assert e.code == "selftest_timeout" and e.message and e.fix and e.as_dict()["retryable"] is True
        assert len(sent) == 2                                                  # 重发一次
        monkeypatch.setattr(s, "_send", real)
        assert s.run_selftest()["ok"] is True                                  # 重试成功
    finally:
        s.disconnect()


class _Tr:
    def __init__(self):
        self.out = []

    def write(self, b):
        self.out.append(bytes(b))


def _fake(h_reply=None):
    s = Session()
    s.tr = _Tr()
    s.status = lambda: {"alive": True}
    return s


def _payloads(s):
    from dzbench._dzlink import Parser
    p, out = Parser(), []
    for f in s.tr.out:
        out += [x for x in p.feed(f)]
    return [(k, i, bytes(pl)) for k, i, _, pl in out]


def test_old_firmware_falls_back_to_reported(home):
    s = _fake()
    with pytest.raises(LinkError) as ei:
        s.run_selftest(wait_s=0.05)
    assert ei.value.code == "selftest_unreported"
    s.selftest = {"pass": False, "failed_items": [{"code": 3, "key": "nvm", "message_zh": "flash 存储区不可用"}], "t": 0.1}
    r = s.run_selftest(wait_s=0.05)
    assert r["source"] == "reported" and r["ok"] is False and r["mask"] is None and "上电自检" in r["message_zh"]


def test_not_connected(home):
    with pytest.raises(LinkError) as ei:
        Session().run_selftest()
    assert ei.value.code == "not_connected"


def test_command_encodings(home):
    s = _fake()
    s.selftest = {"pass": True, "failed_items": [], "t": 0.1}
    s.run_selftest(wait_s=0.01, resend=0)
    s.save_params(wait_s=0.01)
    s.set_run_mode("standalone", confirmed=True, wait_s=0.01)
    s.set_run_mode("tethered", confirmed=True, wait_s=0.01)
    assert s.set_run_mode("standalone")["needs_confirm"] is True          # 未确认不发
    pl = [p for k, i, p in _payloads(s) if k == DATA and i == ID_CMD]
    assert pl == [b"\x48", b"\x57", b"\x4d\x01\xa5", b"\x4d\x00\xa5"], pl


def test_reply_decode_from_frame(home):
    s = Session()
    s._on_bytes(encode(DATA, ID_CMD, 1, b"\x48" + struct.pack("<I", 0x11)))
    assert s.selftest_ack == 0x11
