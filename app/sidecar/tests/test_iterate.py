"""#38 自动迭代：固件 step_result 用 mock（按 tools/dzstep.py 的 56 B 格式真编码再解码），另有 car_2wd 仿真端到端（dzctl 0.13.0）。"""
from __future__ import annotations

import json
import struct
import time

import pytest

from dzbench.agent import iterate as I
from dzbench.schema import Schema
from dzbench.session import LinkError, Session
from dzbench.stepproto import dzstep

PARAMS = [{"name": "kp", "type": "f32", "min": 0.0, "max": 2.0, "max_delta": 0.5},
          {"name": "ki", "type": "f32", "min": 0.0, "max": 20.0, "max_delta": 2.0}]


def result_bytes(it, h, *, os_=5.0, ss=1.0, settle=300, rise=120, mode=0, aborted=0, cause=0, n=100, usat=0.1):
    return struct.pack(dzstep.RESULT_FMT, 1, mode, aborted, cause, it, n, h, 1000, 3.0, 0.0, os_,
                       dzstep.NONE_U32 if rise is None else rise, dzstep.NONE_U32 if settle is None else settle,
                       ss, usat, 0.5, 0.06, 0, 0, 0)


class MockIO:
    """模拟板子：overshoot 随 kp 增大，ss 随 ki 减小；step 返回 dzstep 解码后的 step_result。"""

    def __init__(self, kp=1.6, ki=1.0, model=None, reject=None, abort_iters=(), bad_hash_iters=(), estop_at=None, clock=None):
        self.v = {"kp": kp, "ki": ki}
        self.model = model or (lambda v: (max(0.0, 40 * v["kp"] - 30), 3.0 / (1 + v["ki"])))
        self.reject, self.abort_iters, self.bad_hash = reject or {}, set(abort_iters), set(bad_hash_iters)
        self.estop_at, self.calls, self.writes, self._locked, self.clock = estop_at, [], [], False, clock

    def order(self):
        return ["kp", "ki"]

    def read_params(self):
        return dict(self.v)

    def locked(self):
        return self._locked

    def busy(self):
        return False

    def write(self, name, v):
        if self.reject.get(name) and self.reject[name](v):
            return {"status": "rejected", "reason": "step"}
        self.writes.append((name, v))
        self.v[name] = dzstep.f32(v)
        return {"status": "ok", "applied": self.v[name]}

    def step(self, it, ch, target, dur_ms):
        self.calls.append(it)
        if self.clock:
            self.clock[0] += 10.0
        if self.estop_at is not None and len(self.calls) >= self.estop_at:
            self._locked = True
            return dzstep.decode_step_result(result_bytes(it, 0, aborted=1, cause=1))
        h = I.params_hash(self.order(), self.v) ^ (1 if len(self.calls) in self.bad_hash else 0)
        if len(self.calls) in self.abort_iters:
            return dzstep.decode_step_result(result_bytes(it, h, aborted=1, cause=dzstep.ABORT_HOST_STOP))
        os_, ss = self.model(self.v)
        return dzstep.decode_step_result(result_bytes(it, h, os_=os_, ss=ss))


PLAN = {"ch": 0, "target": 3.0, "dur_ms": 1500, "abs_tol": 0.05, "params": PARAMS}


def run(io, sim=True, **kw):
    ev = []
    out = I.Iterator(io, PLAN, sim, emit=ev.append, **kw).run()
    return out, ev


def test_iter0_is_board_params_with_crc32():
    io = MockIO()
    out, ev = run(io)
    r0 = next(e for e in ev if e["type"] == "iterate.round")
    st = next(e for e in ev if e["type"] == "iterate.started")
    assert r0["iter"] == 0 and r0["params"] == {"kp": 1.6, "ki": 1.0} and st["start"] == r0["params"]
    assert r0["params_hash"] == f"{dzstep.params_hash([1.6, 1.0]):08x}" == st["start_hash"]   # 取 step_result 的 CRC32
    assert out["reason"] == "pass" and out["best"]["pass"]["all"]


def test_budget_exhausted_reports_best_and_gaps():
    io = MockIO(model=lambda v: (25.0 - 0.001 * len(io.calls), 5.0))   # 永远不达标、但一直微小改进
    clock = [0.0]
    io.clock = clock
    out, ev = run(io, now=lambda: clock[0])                     # 每轮 10 s → 180 s 预算在 20 轮之前用完
    assert out["reason"] == "budget_time"
    g = out["best"]["gaps"]
    assert g["overshoot"]["limit"] == 10.0 and g["overshoot"]["gap"] > 0 and g["ss_err"]["gap"] == pytest.approx(3.0)
    assert out["best"]["iter"] == max(r["iter"] for r in ev if r["type"] == "iterate.round") and out["rounds"] == 18


def test_round_cap_hw_8():
    io = MockIO(model=lambda v: (25.0 - 0.001 * len(io.calls), 5.0))   # 一直微小改进，不会因“无改进”停
    out, ev = run(io, sim=False)
    assert out["reason"] == "budget_rounds" and max(e["iter"] for e in ev if e["type"] == "iterate.round") == 8


def test_aborted_and_hash_mismatch_do_not_take_a_number():
    io = MockIO(abort_iters={2}, bad_hash_iters={3})
    out, ev = run(io)
    rs = [e for e in ev if e["type"] == "iterate.round"]
    assert [r["why_invalid"] for r in rs[1:3]] == ["aborted", "hash_mismatch"] and rs[1]["abort_cause"] == "host_stop"
    assert rs[1]["iter"] == rs[2]["iter"] == rs[3]["iter"] == 1


def test_param_reject_changes_direction():
    io = MockIO(reject={"kp": lambda v: v < 1.6})               # 往下改 kp 被板子拒（step）
    out, ev = run(io)
    rj = [e for e in ev if e["type"] == "iterate.param_reject"]
    assert rj and rj[0]["name"] == "kp" and rj[0]["reason"] == "step"
    assert not any(n == "kp" and v < 1.6 for n, v in io.writes)


def test_estop_stops_and_no_more_writes():
    io = MockIO(model=lambda v: (25.0, 5.0), estop_at=3)
    out, ev = run(io)
    n = len(io.writes)
    assert out["reason"] == "estop" and n == len(io.writes)
    assert io.calls == [0, 1, 2]


def test_abs_mode_physical_units():
    r = dzstep.decode_step_result(result_bytes(0, 0, mode=1, os_=0.08, ss=0.03, rise=None))
    assert r["metric_mode"] == "abs" and r["rise_ms"] is None
    p = I.judge(r, 0.05)
    assert p["ss_err"] and p["overshoot"] is None and p["all"]
    assert I.gaps(dzstep.decode_step_result(result_bytes(0, 0, mode=1, ss=0.08)), 0.05)["ss_err"]["unit"] == "abs"


def test_card_has_range_max_delta_start_hash_budget():
    c = I.Iterator.card(PLAN, {"kp": 1.6, "ki": 1.0}, ["kp", "ki"], sim=False)
    assert c["params"][0] == {"name": "kp", "min": 0.0, "max": 2.0, "max_delta": 0.5, "start": 1.6}
    assert c["budget"] == {"time_s": 180.0, "rounds": 8, "where": "实机"} and c["start_hash"] == f"{dzstep.params_hash([1.6, 1.0]):08x}"


def test_hw_limits_within_max_delta_and_ratio():
    a, b = I.limits_for(PARAMS[0], 1.0, sim=False)
    assert a == pytest.approx(0.8) and b == pytest.approx(1.2)          # 量程 10% 比 ×0.7/×1.5 和 max_delta 都紧
    a, b = I.limits_for(PARAMS[1], 0.0, sim=False)
    assert (a, b) == (0.0, pytest.approx(0.4))                          # 0 起步 ≤ 量程 2%


# ---------------------------------------------------------------- Session：帧解码 / 校验 / 锁
def _sess():
    s = Session(emit=lambda e: None)
    s.schema = Schema({"hash": 1, "telemetry": {"id": 2, "fields": []}, "params": PARAMS,
                       "step": [{"sp": 0, "y": "spd_a", "range": 10, "abs_tol": 0.05}]})
    return s


def test_session_decodes_result_ack_reject():
    s = _sess()
    s._on_step(bytes([0, 0, 7, 0]))
    assert s.step_ack == {"status": "started", "ch": 0, "iter": 7}
    s._on_step(result_bytes(7, 0x1234))
    assert s.step_wait(7, 0.1)["params_hash"] == 0x1234
    assert s.step_wait(7, 0.05) is None


def test_session_param_write_rules():
    s = _sess()
    s.params = {"kp": 1.0}
    with pytest.raises(LinkError) as e:
        s.set_param("kp", 1.6)                                   # |Δ| 0.6 > max_delta 0.5：本地拒，不钳位
    assert e.value.code == "invalid_param" and e.value.extra["reject"] == "step"
    s.hb_status = dzstep.HB_ITER_BUSY
    with pytest.raises(LinkError) as e:
        s.set_param("kp", 1.2)
    assert e.value.code == "param_locked"
    s.hb_status, s.tx_locked = 0, True
    with pytest.raises(LinkError) as e:
        s.set_param("kp", 1.2)
    assert e.value.code == "param_locked"


def test_session_step_start_bad_dur():
    with pytest.raises(LinkError):
        _sess().step_start(0, 1, 3.0, 100)


# ---------------------------------------------------------------- car_2wd 仿真（dzctl 0.13.0 真固件）
@pytest.mark.needs_sim
def test_car_2wd_step_result_e2e(home):
    s = Session()
    s.connect("sim:car_2wd")
    try:
        t0 = time.monotonic()
        while not (s.schema and len(s.params) == len(s.schema.params)) and time.monotonic() - t0 < 20:
            time.sleep(0.05)
        assert s.schema.step
        io = I.SessionIO(s)
        vals = io.read_params()
        a = s.step_start(0, 0, 3.0, 1500)
        assert a["status"] == "started"
        t1 = time.monotonic()
        while not s.iter_busy() and time.monotonic() - t1 < 1.2:   # 心跳节拍 ≤ 500 ms
            time.sleep(0.02)
        assert s.iter_busy()
        with pytest.raises(LinkError):
            s.set_param("kp", vals["kp"])                       # 实验中参数锁定
        r = s.step_wait(0, 4.0)
        assert r and not r["aborted"] and r["n"] >= 20
        assert r["params_hash"] == I.params_hash(io.order(), vals)   # 板上 CRC32 = 本地按参数表算的
        out = I.Iterator(io, {"ch": 0, "target": 3.0, "dur_ms": 1000, "abs_tol": 0.05,
                              "params": [dict(s.schema.params[s.schema.param_index["kp"]])]}, True, max_rounds=2).run()
        # #54：以前第 0 轮后自己这一步的 bit17 还没被心跳清掉 → reason=blocked、只跑 1 轮
        assert out["reason"] in ("pass", "budget_rounds", "no_improve"), out
        assert out["rounds"] >= 2 and out["best"]["iter"] >= 0, out
        s.step_start(0, 9, 3.0, 5000)
        s.step_stop()
        r = s.step_wait(9, 2.0)
        assert r["aborted"] and r["abort_cause"] == dzstep.ABORT_HOST_STOP
    finally:
        s.disconnect()


def test_step_result_clears_own_busy_without_waiting_heartbeat():
    """#54：固件在发 step_result 的同一拍清 bit17；侧车收到结果就不再算忙（不等下一帧心跳），外部新开的阶跃靠心跳重新置位。"""
    s = _sess()
    s.hb_status = I_BUSY = 1 << 17
    assert s.iter_busy()
    s._on_step(result_bytes(0, 0))
    assert not s.iter_busy()
    s.hb_status = I_BUSY                                     # 之后心跳又报忙 = 外部阶跃：照样挡
    assert s.iter_busy()


@pytest.mark.needs_sim
def test_agent_tuning_run_ends_with_best_params_card(home, tmp_path, monkeypatch):
    """#53：Agent 调参走 iterate_start（必经路径），一轮对话以“采用最好参数”卡收尾，不以提问结束；点卡把最好一轮参数写回板子。
    没有这张卡（或最终回复是问句）→ 本测试失败。"""
    from agentfake import FakeLLM, call
    from dzbench.agent import loop as loop_mod
    from dzbench.agent.service import AgentService
    from dzbench.agent_api import AgentTools
    assert "iterate_start" in loop_mod.SYSTEM and "不要以提问结束" in loop_mod.SYSTEM
    assert "iterate_start" in loop_mod.MODES["tune"]["prompt"]
    monkeypatch.setattr(AgentService, "ITER_ROUNDS", 3)
    s, ev = Session(), []
    s.connect("sim:car_2wd")
    try:
        t0 = time.monotonic()
        while not (s.schema and len(s.params) == len(s.schema.params)) and time.monotonic() - t0 < 20:
            time.sleep(0.05)
        llm = FakeLLM([{"content": "", "tool_calls": [call("iterate_start", target=3.0, dur_ms=1000, params=["kp"])]},
                       {"content": "迭代完成，最好一轮已找到。要不要我再继续调？", "tool_calls": []}])
        svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path, llm=llm)
        reply = svc.ask("把速度环调好")
        res = svc.iter_result
        assert res and res["reason"] != "error" and res.get("best_card"), res
        st = [e for e in ev if e.get("type") == "iterate.started"]
        assert len(st) == 1 and st[0]["limits"]["rounds"] == 3            # events.md：limits.rounds = 本次轮数上限 N（#62）
        assert sum(e.get("type") == "iterate.stopped" for e in ev) == 1
        assert 1 <= sum(e.get("type") == "iterate.round" for e in ev) <= 3
        cards = [e for e in ev if e.get("type") == "agent_action" and e["tool"] == "iterate_apply_best"]
        assert len(cards) == 1 and cards[0]["id"] == res["best_card"]
        assert cards[0]["preview"]["title"] == "采用最好参数"
        assert not reply.rstrip().endswith(("？", "?")) and "采用最好参数" in reply, reply
        seen = json.dumps(llm.seen[-1][0], ensure_ascii=False)
        assert "best_card" in seen                                   # 模型拿到的工具结果里有卡
        out = svc.action_decide(res["best_card"], True)
        assert out["status"] == "done"
        best = res["best"]["params"]
        assert all(abs(s.params[n] - v) < 1e-6 for n, v in best.items())
    finally:
        s.disconnect()
