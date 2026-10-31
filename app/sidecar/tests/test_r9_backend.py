"""r9 后端回归（#68 #69 #70 #71 #75、回起点）：每条去掉对应修复都会失败。"""
from __future__ import annotations

import struct
import pathlib
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
        assert v == "unknown" and "达标" not in zh
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
    for r in rs:                                    # 验收：无效轮指标是 null 不是 0，判定 unknown
        assert r["overshoot_pct"] is None and r["settle_ms"] is None and r["ss_err_pct"] is None and r["verdict"] == "unknown", r
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


# ---------------------------------------------------------------- 回起点：tol / 8 s / start_offset；阶跃时序由实测辨识推出
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
    o = types.SimpleNamespace(s=WinS(ys), PRE_TOL=0.1, RETURN_TIMEOUT_S=timeout, SETTLE_DT=S.AgentService.SETTLE_DT)
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


def test_step_timing_not_keyed_by_problem():
    """r10 #80：阶跃时序不再按板名查表；没探测过就是 {}，探测结果按端口缓存。"""
    o = types.SimpleNamespace(s=types.SimpleNamespace(port="sim:anything"))
    assert S.AgentService.step_override(o) == {}
    o._step_timing = {"sim:anything": {"hold_s": 2.5}}
    assert S.AgentService.step_override(o)["hold_s"] == 2.5
    assert not hasattr(S.AgentService, "STEP_OVERRIDES")


@pytest.mark.parametrize("K,L,T,noise,rate", [(1.0, 0.0, 0.3, 0.0, None), (2.5, 0.2, 1.0, 0.01, None),
                                              (0.04, 0.5, 4.0, 0.001, None), (1.0, 0.0, 0.05, 0.2, 70.0)])
def test_stepident_derives_timing_from_measurement(K, L, T, noise, rate):
    import math
    import numpy as np
    from dzbench.agent import stepident as SI
    rng = np.random.default_rng(7)
    dt, amp = 0.01, 40.0
    t = [i * dt for i in range(-100, 1500)]
    y, cur = [], 0.0
    for a in t:
        tgt = K * amp * (1 - math.exp(-(a - L) / T)) if a >= L else 0.0
        cur = min(tgt, cur + rate * dt) if rate else tgt
        y.append(cur + noise * rng.standard_normal())
    idt = SI.identify(t, y, 0.0, amp)
    assert idt["ok"] and idt["K"] == pytest.approx(K, rel=0.1)
    d = SI.derive(idt, 800.0, amp)
    assert d["step_target"] <= 800.0 and d["return_tol"] >= SI.NOISE_K * idt["sigma"] - 1e-9
    assert SI.HOLD_MIN <= d["hold_s"] <= SI.HOLD_MAX and d["hold_s"] >= min(L + 3 * T, SI.HOLD_MAX)
    if rate:      # 速度受限：保持时间要够走完正式幅度
        assert d["hold_s"] >= min(d["step_target"] * K / rate, SI.HOLD_MAX) * 0.9


def test_stepident_no_response_is_honest():
    from dzbench.agent import stepident as SI
    t = [i * 0.01 for i in range(-50, 300)]
    idt = SI.identify(t, [0.0] * len(t), 0.0, 10.0)
    assert idt["ok"] is False and "没有可分辨的响应" in idt["why_zh"] and SI.derive(idt, 100.0) == {}


# ---------------------------------------------------------------- 相对口径 ss_err % → px → cm；换算来源 phys / sim_nominal / 实机标定
def _ss_obj(tmp_path, sim, phys=None, nominal=None):
    f = {"name": "cam_x_px", "unit": "px"}
    step = [{"sp": 0, "y": "cam_x_px", "range": 800, "abs_tol": 6} | ({"phys": phys} if phys else {})]
    o = types.SimpleNamespace(s=types.SimpleNamespace(schema=types.SimpleNamespace(fields=[f], step=step), port="sim:2026H_ball" if sim else "hw:COM3"), sim=sim)
    o.step_cfg = lambda: {"y": "cam_x_px", "low": [0], "high": [60]} | ({"sim_nominal": nominal} if nominal else {})
    proj = tmp_path / "p"
    proj.mkdir(exist_ok=True)
    (proj / "requirements.yaml").write_text("items:\n  - id: '1'\n    metrics:\n      - {name: 稳态误差, op: '<=', value: 1, unit: cm}\n", "utf-8")
    o._project_path = lambda: str(proj)
    for n in ("_step_amp", "_unit_per", "_phys_per", "_sim_nominal_per", "_calibration_per"):
        setattr(o, n, (lambda f: lambda *a: f(o, *a))(getattr(S.AgentService, n)))
    o._pass_basis = S.AgentService._pass_basis
    return o, proj


M5 = {"ss_err_pct": 5.0, "metric_mode": "rel", "target": 60.0, "start_y": 0.0}       # 5% × 60 px = 3 px = 0.5 cm
M20 = dict(M5, ss_err_pct=20.0)                                                       # 12 px = 2 cm


def test_ss_band_sim_uses_phys_first(tmp_path):
    o, _ = _ss_obj(tmp_path, True, phys={"unit": "cm", "per_unit": 6}, nominal={"from": "px", "to": "cm", "per": 0.5})
    r = S.AgentService._ss_band(o, M5)
    assert r["inside"] is True and r["conv_source"] == "phys" and r["converted"]["value"] == pytest.approx(0.5)
    assert "仿真标称" in r["note_zh"] and S.AgentService._ss_band(o, M20)["inside"] is False


def test_ss_band_sim_falls_back_to_sim_nominal(tmp_path):
    o, _ = _ss_obj(tmp_path, True, nominal={"from": "px", "to": "cm", "per": 1 / 6, "source": "sim_setup.c"})
    r = S.AgentService._ss_band(o, M5)
    assert r["inside"] is True and r["conv_source"] == "sim_nominal" and "仿真标称" in r["note_zh"]


def test_ss_band_hw_phys_is_not_a_calibration(tmp_path):
    o, proj = _ss_obj(tmp_path, False, phys={"unit": "cm", "per_unit": 6}, nominal={"from": "px", "to": "cm", "per": 1 / 6})
    r = S.AgentService._ss_band(o, M5)
    assert r["inside"] is None and r["conv_source"] is None and "待标定" in r["note_zh"]
    assert r["calib_initial_guess"]["per"] == pytest.approx(1 / 6)                  # phys 只当标定初值
    assert S.AgentService._verdict(r, {"reason": "pass"}, {"ok": True, "rise_s": 0.5, "settling_s": 1.0})[0] == "unknown"
    (proj / ".dz" / "calib").mkdir(parents=True)                                      # 有 #51 标定结果才判
    (proj / ".dz" / "calib" / "cam_x_px.json").write_text('{"from": "px", "to": "cm", "per": 0.2, "source": "O/±5 cm 实测"}', "utf-8")
    r = S.AgentService._ss_band(o, M5)
    assert r["inside"] is True and r["conv_source"] == "calibration"


def test_pass_basis_is_one_sentence_without_parentheses():
    P = S.AgentService._pass_basis
    outs = [P(None, None), P({"limit": 2, "unit": "%"}, True), P({"item": "B3", "source": "题目 B3：误差（绝对值） ≤ 1cm"}, None),
            P({"item": "B3", "source": "题目 B3：误差（绝对值） ≤ 1cm"}, True), P({"item": "B3", "source": "题目 B3：误差 ≤ 1cm"}, False)]
    assert outs[0] == "题目未给误差带，按默认 2% 判定"
    for t in outs:
        assert not any(c in t for c in "()（）"), t


class CoarseClock:
    """Windows 样的时钟：读数按 15.625 ms 量化，sleep 向上取整到 tick 再多一 tick（虚拟时间，不真睡）。"""
    TICK = 0.015625

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return (self.t // self.TICK) * self.TICK

    def sleep(self, d):
        import math
        self.t += (math.ceil(d / self.TICK) + 1) * self.TICK


@pytest.mark.parametrize("rep", range(50))
def test_return_to_start_coarse_clock_windows(monkeypatch, rep):
    """Windows CI 复现：墙钟判“持续 0.3 s”+ 超时 → sleep 偏长时 settled=False。按拍数计时就与时钟无关。"""
    c = CoarseClock()
    monkeypatch.setattr(S, "time", types.SimpleNamespace(monotonic=c.monotonic, sleep=c.sleep, time=c.monotonic))
    o = _stub([30.0] * 3 + [1.0] * 100)
    r = S.AgentService._settle_at_low(o, ST, [0.0], [60.0], 0.1)
    assert r["settled"] is True and "start_offset" not in r, r
    o = _stub([25.0])
    r = S.AgentService._settle_at_low(o, ST, [0.0], [60.0], 0.1)
    assert r["settled"] is False and r["start_offset"] == pytest.approx(25.0)


# ---------------------------------------------------------------- r10：探测阶跃幅度受声明约束；急停覆盖探测阶段
def test_probe_amp_clamped_to_declared_range_or_minimal_with_reason():
    from dzbench.agent import stepident as SI
    a, why = SI.probe_amp(800.0)
    assert a == pytest.approx(800.0 * SI.PROBE_FRAC) and a <= 800.0 and why is None
    a, why = SI.probe_amp(None, sigma=0.0)
    assert a == SI.MIN_ABS and "没声明物理量程" in why
    assert SI.probe_amp(None, sigma=0.5)[0] == pytest.approx(SI.MIN_SNR * 0.5)
    assert SI.saturated([0.1, 0.99], 1.0) and not SI.saturated([0.5], 1.0) and not SI.saturated([5.0], None)


class ProbeS:
    """板上阶跃探测的假板：step_start 之后第 2 次查询时急停。"""
    def __init__(self, estop_at=2):
        self.port, self.tx_locked, self.n, self.estop_at, self.stopped = "sim:x", False, 0, estop_at, False
        self.schema = types.SimpleNamespace(step=[{"sp": 0, "y": "y", "u": "u", "u_max": 1.0, "range": 100.0}], d={})
        self.started = []

    def window(self, sec):
        return [(i * 0.01, {"y": 0.0, "u": 0.0}) for i in range(100)]

    def step_start(self, *a):
        self.started.append(a)

    def step_wait(self, it, timeout):
        self.n += 1
        if self.n >= self.estop_at:
            self.tx_locked = True
        return None

    def step_stop(self):
        self.stopped = True
        return True


def test_probe_aborts_on_estop(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda d: None)
    o = types.SimpleNamespace(s=ProbeS(), sim=True, PROBE_S=0.3, emit=lambda e: None)
    o._probe_wait = lambda t: S.AgentService._probe_wait(o, t)
    r = S.AgentService.measure_step_timing(o)
    assert r == {} and o.s.stopped and len(o.s.started) == 1
    assert o.s.started[0][2] == pytest.approx(100.0 * 0.05)          # 探测幅度 = 声明量程 × 5%
    assert "急停" in o._step_timing["sim:x#why"]["message_zh"] and o._step_timing["sim:x#why"]["fix_action"] == "estop_clear"


def test_probe_reads_sensor_range_max_step_and_handshake_limits(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda d: None)
    b = ProbeS()
    b.schema = types.SimpleNamespace(step=[{"sp": 0, "y": "y", "u": "u", "sensor_range": 720.0, "max_step": 20.0}],
                                     d={"limits": {"u_min": -1, "u_max": 1, "sat": 0.8, "range": 720}, "relay": True})
    o = types.SimpleNamespace(s=b, sim=True, PROBE_S=0.3, emit=lambda e: None)
    o._probe_wait = lambda t: S.AgentService._probe_wait(o, t)
    S.AgentService.measure_step_timing(o)
    assert b.started[0][2] == pytest.approx(min(720.0 * 0.05, 20.0))   # sensor_range × 5%，且不超 max_step


def test_relay_off_declared_refuses_relay_tune():
    o = types.SimpleNamespace(s=types.SimpleNamespace(schema=types.SimpleNamespace(d={"relay": False}, step=[])),
                              step_cfg=lambda: {"relay": {}})
    with pytest.raises(S.GatewayError) as e:
        S.AgentService.run_relay_tune(o)
    assert e.value.code == "relay_off" and e.value.fix


# ---------------------------------------------------------------- #107 / #109：随机对象的声明直接能起迭代（参数名、量程、容差全从握手 / 声明读）
@pytest.mark.parametrize("seed", list(range(0, 40, 3)) + [101, 202, 3008, 3009, 3010])
def test_iterate_plan_accepts_any_randplant_declaration(seed, tmp_path):
    import sys as _sys
    root = pathlib.Path(__file__).resolve().parents[3]
    _sys.path.insert(0, str(root / "tools"))
    import gen_link
    import randplant
    from dzbench.schema import Schema
    from dzbench.agent.iterate import Iterator
    p = randplant.gen(seed)
    (tmp_path / "app.yaml").write_text(randplant.app_yaml(p), "utf-8")
    spec, params, _ = gen_link.load(tmp_path / "app.yaml")
    assert not gen_link.check(spec, params), gen_link.check(spec, params)
    sch = Schema(gen_link.schema(spec, params))
    o = types.SimpleNamespace(s=types.SimpleNamespace(schema=sch), _gains=lambda: {}, _tunable=S.AgentService._tunable,
                              ABS_TOL_FRAC=S.AgentService.ABS_TOL_FRAC)
    st = sch.step[0]
    tgt = min(0.25 * float(st["sensor_range"]), float(st.get("max_step") or 1e9))
    plan = S.AgentService.iterate_plan(o, target=tgt)
    assert {q["name"] for q in plan["params"]} >= set(p["roles"].values()) - {None}
    assert plan["abs_tol"] == pytest.approx(0.01 * float(st["sensor_range"]))
    vals = {q["name"]: q.get("default", q.get("min", 0.0)) for q in sch.params}
    card = Iterator.card(plan, vals, [q["name"] for q in sch.params], True)
    assert card
    if st.get("max_step"):
        with pytest.raises(S.GatewayError) as e:
            S.AgentService.iterate_plan(o, target=float(st["max_step"]) * 1.5)
        assert e.value.code == "step_too_large" and "max_step" in e.value.message


# ---------------------------------------------------------------- #108：界面 / Agent 的 autotune 走 tuning.autotune（与 tunegate 同一份代码）
def test_autotune_run_uses_same_code_as_tunegate(monkeypatch):
    import sys as _sys
    root = pathlib.Path(__file__).resolve().parents[3]
    _sys.path.insert(0, str(root / "tools"))
    import tunegate_plant as TP
    from dzbench.schema import Schema
    from dzbench.tuning import autotune as AT
    case = TP.make(3008)
    board = TP.SimBoard(case["plant"], case["app"], 0)
    sch = Schema({"hash": 1, "telemetry": {"id": 2, "fields": [{"name": "y", "type": "f32"}]}, "params": [{"name": d["name"], "role": d["role"], "type": "f32", "min": d["min"], "max": d["max"],
                              "max_delta": d["max_delta"], "default": d["init"]} for d in case["app"]["params"]],
                  "step": [{"sp": 0, "y": "y", "u": "u", "u_max": case["link"]["u_max"], "sample_s": case["link"]["sample_s"],
                            "sensor_range": case["link"]["sensor_range"], "max_step": case["link"]["max_step"]}]})

    class Sess:
        schema, tx_locked, port = sch, False, "sim:randplant"
        params = board.read_params()

        def set_param(self, n, v):
            board.write_param(n, v); self.params[n] = v

        def step_start(self, ch, it, amp, dur_ms):
            t, r, y, u = board.step(amp, int(round(dur_ms / 1000 / case["link"]["sample_s"])))
            self.w = [(float(a), {"sp": float(b), "y": float(c), "u": float(d)}) for a, b, c, d in zip(t, r, y, u)]

        def step_wait(self, it, to):
            return {"iter": it}

        def window(self, s):
            return self.w

    calls = []
    real = AT.autotune
    monkeypatch.setattr(AT, "autotune", lambda *a, **k: calls.append(1) or real(*a, **k))
    o = S.AgentService.__new__(S.AgentService)
    o.s = Sess()
    r = o.autotune_run(case["spec"])
    assert calls and r.get("verdict") in ("pass", "fail")
    assert board.rejected == 0
