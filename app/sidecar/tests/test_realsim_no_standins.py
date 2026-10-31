"""r10：把 service / session / 测量相关的替身测试换成真 randplant 对象 → 真 host-sim 仿真板 → 真 Session + AgentService。
原来的假实现：test_r9_backend.FakeS（_restore_best）、test_r9_backend.ProbeS（measure_step_timing 探测幅度 / 急停中止）、
test_r9c.FakeSession（SessionIO.return_to_start）。只允许“透传包装”记录真实调用参数（照常调用真方法），不改任何返回值。"""
from __future__ import annotations

import contextlib
import pathlib
import sys
import threading
import time

import pytest

from dzbench.agent import iterate as I
from dzbench.agent import service as S
from dzbench.session import Session

pytestmark = pytest.mark.needs_sim
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "tools"))


@contextlib.contextmanager
def _board(seed: int, tag: str):
    import randplant
    from dzbench import paths
    from dzbench.agent_api import AgentTools
    p = randplant.gen(seed)
    p["name"] = f"{tag}-{seed}"
    randplant.write(p, paths.projects_dir() / p["name"])
    s, ev = Session(), []
    s.connect(f"sim:{p['name']}")
    try:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60 and not (s.schema and len(s.params) == len(s.schema.params) and len(s.window(0.5)) > 5):
            time.sleep(0.05)
        assert s.schema and s.schema.step, "仿真板起不来 / 没握手"
        svc = S.AgentService(s, AgentTools(s, lambda e: None), ev.append)
        yield p, s, svc, ev
    finally:
        s.disconnect()


def _spy(obj, name, log):
    real = getattr(obj, name)

    def wrap(*a, **k):
        log.append(a)
        return real(*a, **k)
    setattr(obj, name, wrap)


@pytest.mark.parametrize("seed", [3, 3008])
def test_restore_best_writes_and_reads_back_real(seed, home):
    with _board(seed, "restore") as (p, s, svc, ev):
        prm = [q for q in s.schema.params if q.get("type", "f32") == "f32" and q["max"] > q["min"]][:2]
        best = {}
        for q in prm:
            cur = float(s.params[q["name"]])
            md = float(q.get("max_delta") or (q["max"] - q["min"]))
            best[q["name"]] = round(min(q["max"], cur + 0.5 * min(md, q["max"] - cur)) if cur < q["max"] else cur - 0.5 * min(md, cur - q["min"]), 4)
        res = {"best": {"iter": 2, "params": best}}
        out = svc._restore_best(res)
        assert out["ok"], out
        for n, v in best.items():
            assert s.read_param(n) == pytest.approx(v, rel=1e-5, abs=1e-6)       # 板上真值
            assert out["readback"][n] == pytest.approx(v, rel=1e-5, abs=1e-6)
        assert ev[-1]["type"] == "iterate.restored" and res["restored"] is out
        s.estop("test")                                                        # 急停锁存：不写
        assert s.tx_locked
        out2 = svc._restore_best({"best": {"iter": 3, "params": {n: v for n, v in best.items()}}})
        assert out2["skipped"] == "estop" and not out2["readback"]


@pytest.mark.parametrize("seed", [3, 3010])
def test_probe_amp_from_declared_sensor_range_and_max_step_real(seed, home):
    """探测幅度 = 声明 sensor_range × 5%，且不超 max_step（都从握手 link.step 读，不按题号）。"""
    from dzbench.agent import stepident as SI
    with _board(seed, "probe") as (p, s, svc, ev):
        started = []
        _spy(s, "step_start", started)
        svc.measure_step_timing()
        assert started, "探测没发阶跃"
        st = s.schema.step[0]
        lo = min(float(st["sensor_range"]) * SI.PROBE_FRAC, float(st["max_step"]))
        amp = float(started[0][2])
        assert amp <= float(st["max_step"]) * (1 + 1e-6), (amp, st)            # 不超执行器能承受的单次最大阶跃
        assert amp >= lo * (1 - 1e-6), (amp, lo, st)                         # 声明量程 × 5%（噪声底高时只会更大，但仍受 max_step 约束）


def test_probe_aborts_on_estop_real(home):
    """探测进行中急停 → 探测中止、发停止、不缓存时序、写明原因与 fix_action=estop_clear。"""
    with _board(3, "probe-estop") as (p, s, svc, ev):
        started, stops = [], []
        _spy(s, "step_start", started)
        _spy(s, "step_stop", stops)
        box = {}
        th = threading.Thread(target=lambda: box.setdefault("r", svc.measure_step_timing()))
        th.start()
        t0 = time.monotonic()
        while not started and time.monotonic() - t0 < 10:
            time.sleep(0.01)
        assert started, "探测没发阶跃"
        time.sleep(0.05)
        s.estop("test")
        th.join(30)
        assert not th.is_alive()
        assert box["r"] == {} and len(started) == 1
        # 停止帧：本地先看到锁存就发 step_stop；固件先发了中止结果（急停时固件自己停阶跃）就不必再发。两种都不能把中止的数据当探测结果。
        assert stops or not s.iter_busy()
        why = svc._step_timing[f"{s.port}#why"]
        assert "急停" in why["message_zh"] and why["fix_action"] == "estop_clear"


def test_return_to_start_real(home):
    """SessionIO.return_to_start：目标就是当前位置 → 起点 = 目标 − 量程 × 25%，真板子回到起点；重跑同一轮回同一个起点。
    （换成真板后查出：randplant 声明只写 sensor_range，以前这里只认 range → 退不到起点、做 0 幅度阶跃。）"""
    with _board(3, "rts") as (p, s, svc, ev):
        io = I.SessionIO(s)
        y, slot, tol = io._y(0)
        assert y is not None and tol is not None
        now = io._y_now(y)
        sent = []
        _spy(s, "send_data", sent)
        back = io.return_to_start(0, 0, now)
        c = io._cfg(0)
        rng = float(c["range"] if c.get("range") is not None else c["sensor_range"])
        want = now - io.START_FRAC * rng if now - io.START_FRAC * rng >= -rng else now + io.START_FRAC * rng
        assert io.y0 == pytest.approx(want) and sent
        assert "start_offset" not in back and abs(back["start_y"] - io.y0) < tol, back
        assert back["step_amp"] >= back["step_tol"], back
        back2 = io.return_to_start(0, 0, now)
        assert io.y0 == pytest.approx(want) and back2["step_amp"] == pytest.approx(back["step_amp"], abs=2 * tol)


def test_iterate_start_parked_at_target_three_gains_distinct_metrics_real(home):
    """#94：板子停在目标上直接起迭代，三组不同 P 增益必须给出三组不同的真实阶跃指标（不是 3 个零幅度阶跃）。"""
    with _board(3, "parked") as (p, s, svc, ev):
        kp = next(n for r, n in p["roles"].items() if n and str(r).upper() == "P")
        q = s.schema.params[s.schema.param_index[kp]]
        cur = float(s.params[kp])
        io = I.SessionIO(s)
        y, slot, tol = io._y(0)
        target = io._y_now(y)                                   # 停在哪就拿哪当目标
        metrics = []
        for f in (0.8, 1.0, 1.25):
            v = min(float(q["max"]), max(float(q["min"]), cur * f))
            s.set_param(kp, v)
            r = io.step(len(metrics), 0, target, 1500)
            assert r["step_amp"] >= r["step_tol"], r              # 退到起点再跳：不是 0 幅度
            assert not r["aborted"], r
            metrics.append((r.get("rise_ms"), r.get("overshoot_pct"), r.get("settle_ms"), r.get("ss_err")))
        assert len(set(metrics)) == 3, metrics
