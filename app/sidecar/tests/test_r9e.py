"""r9e 回归：#93 依据写明仿真标称值、#100 只声明 plant: 的项目也能当仿真板、#101 清结果卡、#102 没有稳定轮就不给最好参数。
全部用随机 / 自编声明的对象，不用例题。"""
from __future__ import annotations

import random
from types import SimpleNamespace

from dzbench import ports
from dzbench.agent import iterate as I
from dzbench.agent import service as S
from test_iterate import PLAN, MockIO


def _plant_yaml(rng, name):
    return (f"name: {name}\nversion: 0.1.0\nplant:\n  order: {rng.randint(1, 3)}\n  gain: {rng.uniform(0.2, 5):.3f}\n"
            f"  tau_s: [{rng.uniform(0.05, 2):.3f}]\n  unit: zq\n")


def test_plant_only_project_is_sim_and_rescanned_with_app_name(tmp_path, monkeypatch):
    rng = random.Random(1031)
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DZBENCH_REPO", str(tmp_path / "repo"))
    monkeypatch.setattr(ports.shutil, "which", lambda x: "/usr/bin/" + x)
    monkeypatch.setattr(ports.os, "name", "posix")
    proj = tmp_path / "home" / "projects"
    (proj / "p_a").mkdir(parents=True)
    (proj / "p_a" / "app.yaml").write_text(_plant_yaml(rng, "随机对象甲"), "utf-8")
    sims = [p for p in ports.list_ports() if p["kind"] == "sim" and not p["port"].endswith("+hw")]
    assert [p["app"] for p in sims] == ["p_a"] and sims[0]["label"] == "仿真 · 随机对象甲" and sims[0]["app_name"] == "随机对象甲"
    (proj / "p_b").mkdir()                                            # 新建项目后不重启：下一次列端口就出现
    (proj / "p_b" / "app.yaml").write_text(_plant_yaml(rng, "随机对象乙"), "utf-8")
    labels = {p["label"] for p in ports.list_ports() if p["kind"] == "sim"}
    assert "仿真 · 随机对象乙" in labels
    (proj / "p_c").mkdir()                                            # 既没 plant: 也没 sim_setup.c → 不是仿真板
    (proj / "p_c" / "app.yaml").write_text("name: x\n", "utf-8")
    assert "p_c" not in ports.sim_apps()


def test_no_stable_round_gives_null_best_and_says_diverged():
    rng = random.Random(7)
    a = rng.uniform(60, 90)
    io = MockIO(kp=1.0, ki=1.0, model=lambda v: (a + 10 * v["kp"], 0.5))     # 随机对象：超调恒 > 40%
    ev = []
    out = I.Iterator(io, PLAN, True, emit=ev.append, max_rounds=4).run()
    assert out["best"] is None and out["message_zh"] == "发散，未找到稳定参数", out


def test_stable_round_still_kept_as_best():
    io = MockIO(kp=1.0, ki=1.0)
    out = I.Iterator(io, PLAN, True, emit=lambda e: None, max_rounds=3).run()
    assert out["best"] is not None and out["message_zh"] != "发散，未找到稳定参数"


def _svc():
    ev = []
    svc = SimpleNamespace(emit=ev.append, iter_result={"best_card": 1}, iter_thread=None, iterate_last=lambda: {"result": {"old": 1}},
                          RESULT_CLEARED_ZH=S.AgentService.RESULT_CLEARED_ZH)
    svc.clear_result = lambda r: S.AgentService.clear_result(svc, r)
    svc.current_run_id = lambda: S.AgentService.current_run_id(svc)
    return svc, ev


def test_reconnect_and_board_change_clear_result_and_emit():
    for prev, port, why in (("sim:p_a", "sim:p_a", "reconnect"), ("sim:p_a", "COM3", "board_change")):
        svc, ev = _svc()
        S.AgentService._on_connect(svc, port, prev)
        assert ev == [{"type": "result_reset", "run_id": svc.run_id, "reason": why, "message_zh": S.AgentService.RESULT_CLEARED_ZH[why]}]
        st = S.AgentService.iterate_status(svc)
        assert st["result"] is None and st["last"] is None and st["cleared"] is True


def test_iterate_start_clears_result():
    svc, ev = _svc()
    S.AgentService.clear_result(svc, "iterate_start")
    assert svc.iter_result is None and ev[0]["type"] == "result_reset" and ev[0]["reason"] == "iterate_start"


def test_session_connect_runs_hooks(monkeypatch):
    from dzbench.session import Session
    s = Session(emit=lambda e: None)
    seen = []
    s.connect_hooks = [lambda p, prev: seen.append((p, prev))]
    monkeypatch.setattr(s, "_connect", lambda port, baud, log: {"port": port})
    s.connect("sim:a"); s.connect("sim:b")
    assert seen == [("sim:a", None), ("sim:b", "sim:a")]
# #93 仿真标称值的精确文案由 test_ss_band.py 的 4 条断言覆盖（真 _ss_band，不是拼字符串）。
