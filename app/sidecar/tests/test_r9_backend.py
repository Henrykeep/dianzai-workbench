"""r9 后端回归（#68 #69 #70 #71 #75、回起点）：每条去掉对应修复都会失败。"""
from __future__ import annotations

import struct
import threading
import time
import types

import pytest

from dzbench.agent import iterate as I
from dzbench.agent import service as S
from dzbench.session import LinkError, Session
from test_iterate import MockIO, PLAN, result_bytes
from dzbench.stepproto import dzstep


# ---------------------------------------------------------------- #68 无效阶跃 → 无效轮，绝不达标
@pytest.mark.parametrize("m,why", [({}, "empty_metrics"), ({"ok": True, "rise_s": None, "settling_s": 1.0, "overshoot_pct": 0.0}, "no_rise"),
                                   ({"ok": True, "rise_s": 0.3, "settling_s": 0.0, "overshoot_pct": 0.0}, "settle_zero"),
                                   ({"rise_ms": 120, "settle_ms": 0}, "settle_zero")])
def test_step_invalid(m, why):
    assert S.step_invalid(m) == why


def test_invalid_step_verdict_never_says_pass():
    for m in ({}, {"ok": True, "rise_s": None, "settling_s": 2.0, "overshoot_pct": 0.0}, {"ok": True, "rise_s": 0.5, "settling_s": 0.0}):
        v, zh = S.AgentService._verdict({"inside": True, "pass_basis": "按默认 2% 判定达标"}, {"reason": "pass"}, m)
        assert v == "invalid" and "达标" not in zh
    v, zh = S.AgentService._verdict({"inside": None, "pass_basis": "按默认 2% 判定达标"}, {"reason": "pass"}, {"ok": True, "rise_s": 0.5, "settling_s": 1.0})
    assert v == "unknown" and "达标" not in zh


def _svc_stub(ss_inside):
    o = types.SimpleNamespace(s=types.SimpleNamespace(schema=None), step_cfg=lambda: None, CMP_KEYS=S.AgentService.CMP_KEYS)
    o._ss_band = lambda m: {"inside": ss_inside}
    return o


def test_initial_pass_note_needs_valid_round0_and_inside():
    good = {"ok": True, "rise_s": 0.5, "settling_s": 1.0, "overshoot_pct": 1.0, "iae": 0.1}
    bad = dict(good, rise_s=None)
    for metrics, inside, want in ((good, True, True), (good, None, False), (bad, True, False)):
        stub = _svc_stub(inside)
        r = S.AgentService._compare(stub, {"iter": 0, "metrics": metrics, "passed": True}, {"iter": 0, "metrics": metrics})
        note = (r or {}).get("note_zh", "")
        assert ("初值已达标" in note) is want, (metrics, inside, note)


class NoRiseIO(MockIO):
    def step(self, it, ch, target, dur_ms):
        self.calls.append(it)
        h = I.params_hash(self.order(), self.v)
        return dzstep.decode_step_result(result_bytes(it, h, os_=0.0, ss=0.0, rise=None, settle=0))


def test_board_round_without_rise_is_invalid_not_pass():
    ev = []
    out = I.Iterator(NoRiseIO(), PLAN, True, emit=ev.append).run()
    rs = [e for e in ev if e["type"] == "iterate.round"]
    assert rs and all(not r["valid"] and r["why_invalid"] in ("no_rise", "settle_zero") for r in rs)
    assert out["reason"] != "pass"


# ---------------------------------------------------------------- #69 kp 不再每轮砍半；结束写回最好参数并回读
def test_search_step_is_relative_not_halving():
    io = MockIO(kp=1.6, ki=1.0, model=lambda v: (40 * v["kp"] - 30, 0.5))     # 超调随 kp 降低单调改善
    I.Iterator(io, PLAN, True, emit=lambda e: None, max_rounds=3).run()
    kp = [v for n, v in io.writes if n == "kp"]
    assert kp, io.writes
    assert kp[0] == pytest.approx(1.6 * (1 - I.STEP_FRAC), rel=1e-3)          # 旧实现：(1.6 + 0)/2 = 0.8
    assert all(b >= a * 0.5 + 1e-6 for a, b in zip([1.6] + kp, kp))


class FakeS:
    def __init__(self, locked=False):
        self.tx_locked, self.params, self.writes = locked, {"kp": 1.0, "ki": 2.0}, []

    def set_param(self, n, v, verify=False):
        self.writes.append((n, v, verify))
        self.params[n] = v
        return {"status": "ok", "applied": v, "readback": v}


def test_restore_best_writes_and_reads_back():
    ev = []
    svc = types.SimpleNamespace(s=FakeS(), emit=ev.append)
    res = {"best": {"iter": 2, "params": {"kp": 0.7, "ki": 1.5}}}
    out = S.AgentService._restore_best(svc, res)
    assert out["ok"] and svc.s.params == {"kp": 0.7, "ki": 1.5} and all(w[2] for w in svc.s.writes)
    assert out["readback"] == {"kp": 0.7, "ki": 1.5} and ev[-1]["type"] == "iterate.restored" and res["restored"] is out
    locked = types.SimpleNamespace(s=FakeS(locked=True), emit=ev.append)
    assert S.AgentService._restore_best(locked, dict(res))["skipped"] == "estop" and not locked.s.writes


# ---------------------------------------------------------------- #70 迭代全程（含两轮之间）setpoint_set → iter_busy
def test_setpoint_set_busy_for_whole_iteration():
    s = Session()
    started, release = threading.Event(), threading.Event()

    def owner():
        with s.iter_hold():
            started.set()
            release.wait(5)
    t = threading.Thread(target=owner)
    t.start()
    try:
        started.wait(5)
        assert s.iter_busy()                       # 不是板上 bit17，而是“两轮之间”
        with pytest.raises(LinkError) as e:
            s.setpoint_set("x", 1.0)
        assert e.value.code == "iter_busy" and e.value.extra["ok"] is False and e.value.extra["reason_zh"]
        assert t.is_alive()                        # 迭代线程没被打断
    finally:
        release.set()
        t.join()
    assert not s.iter_busy()


# ---------------------------------------------------------------- #71 被拒写参数：ok:false + reason + reason_zh + id
def test_param_set_op_rejected_is_ok_false():
    import asyncio
    from dzbench.server import Server
    rej = {"ok": False, "name": "pos_k", "id": 7, "requested": 9.0, "applied": 0.72, "status": "rejected",
           "reason": "range", "reason_zh": "超出允许范围"}
    sv = Server.__new__(Server)
    sv.session = types.SimpleNamespace(set_param=lambda n, v: rej)
    with pytest.raises(LinkError) as e:                 # 修复前：原样返回 → 外层回 ok:true
        asyncio.run(sv._op({"op": "param_set", "name": "pos_k", "value": 9.0}))
    x = e.value.extra
    assert x["ok"] is False and x["reason"] == "range" and x["reason_zh"] and x["id"] == 7 and x["name"] == "pos_k"


def test_reject_zh_covers_board_reasons():
    from dzbench import session as SS
    for k in ("range", "type", "state", "step", "busy", "unknown"):
        assert SS.REJECT_ZH.get(k)


# ---------------------------------------------------------------- 回起点：tol / 8 s / start_offset；2026H hold_s = 5（后端配置）
class WinS:
    def __init__(self, ys):
        self.ys, self.sent, self.schema = list(ys), [], None

    def send_data(self, i, b):
        self.sent.append(struct.unpack("<f", b)[0])
        return True

    def window(self, sec):
        y = self.ys.pop(0) if len(self.ys) > 1 else self.ys[0]
        return [(0.0, {"y": y, "sp": 0.0})]


def _stub(ys, port="sim:2026H_ball", timeout=0.6):
    o = types.SimpleNamespace(s=WinS(ys), PRE_TOL=0.1, RETURN_TIMEOUT_S=timeout)
    o.s.port = port
    o.step_override = lambda: S.AgentService.step_override(o) | {"return_timeout_s": timeout}
    o._return_tol = lambda st, span: S.AgentService._return_tol(o, st, span)
    return o


ST = {"id": 1, "fmt": "<f", "y": "y", "sp": "sp"}


def test_return_to_start_waits_until_within_tol():
    o = _stub([30.0] * 3 + [1.0] * 100)
    r = S.AgentService._settle_at_low(o, ST, [0.0], [60.0], 0.1)
    assert r["settled"] is True and r["tol"] == 6.0 and "start_offset" not in r


def test_return_to_start_timeout_marks_start_offset():
    o = _stub([25.0])
    t0 = time.monotonic()
    r = S.AgentService._settle_at_low(o, ST, [0.0], [60.0], 0.1)
    assert r["settled"] is False and r["start_offset"] == pytest.approx(25.0) and r["start_y"] == pytest.approx(25.0)
    assert time.monotonic() - t0 < 3


def test_2026h_hold_override_is_backend_owned():
    o = types.SimpleNamespace(s=types.SimpleNamespace(port="sim:2026H_ball"))
    assert S.AgentService.step_override(o)["hold_s"] == 5.0
    o2 = types.SimpleNamespace(s=types.SimpleNamespace(port="sim:motor_pos"))
    assert S.AgentService.step_override(o2) == {}
