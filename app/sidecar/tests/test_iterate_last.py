"""前端用：最近迭代结果按 项目+板卡 落盘并由 iterate_status 还原；卡片 verdict（inside=null → unknown）；project_switch_example。"""
import types

import pytest

from dzbench.agent import service as service_mod
from dzbench.agent.gateway import GatewayError
from dzbench.agent.service import AgentService
from test_ss_band import _svc

RES = {"type": "iterate.stopped", "reason": "pass", "rounds": 3, "pass_basis": "x",
       "best": {"iter": 2, "params": {"kp": 1.0}, "params_hash": "h", "metrics": {"sse": 3.0}}}


def _card_svc(tmp_path, sim):
    svc = _svc(tmp_path, sim)
    svc.gate = lambda op, args, fn: {"action_id": 7, "args": args}
    svc._compare = lambda r0, b: None
    return svc


@pytest.mark.parametrize("sim,sse,want", [(True, 3.0, "pass"), (True, 12.0, "fail"), (False, 3.0, "unknown")])
def test_verdict(tmp_path, sim, sse, want):
    res = {**RES, "best": {**RES["best"], "metrics": {"sse": sse}}}
    assert _card_svc(tmp_path, sim)._best_card(res) == 7
    assert res["verdict"] == want and res["card"]["verdict"] == want and res["verdict_zh"]
    if want == "unknown":
        assert res["ss_err"]["inside"] is None and "各项指标均已达标" not in res["verdict_zh"]


def test_last_result_persisted_per_project_and_board(tmp_path):
    svc = _card_svc(tmp_path, True)
    res = dict(RES)
    res["best_card"] = svc._best_card(res)
    svc.iter_result = res
    svc._persist_last(res)
    fresh = _card_svc(tmp_path, True)                     # 模拟刷新 / 重启：内存里没有结果
    fresh.iter_result = None
    st = fresh.iterate_status()
    assert st["running"] is False and st["last"]["board"] == "sim:2026H_ball"
    r = st["result"]
    assert r["best_card"] == 7 and r["pass_basis"] == "x" and r["verdict"] == "pass" and r["ss_err"]["inside"] is True
    other = _card_svc(tmp_path, False)                    # 换块板：不串
    other.iter_result = None
    assert other.iterate_status()["last"] is None


def test_project_switch_example(tmp_path, monkeypatch):
    (tmp_path / "examples" / "2026H_ball").mkdir(parents=True)
    (tmp_path / "examples" / "2026H_ball" / "requirements.yaml").write_text("items: []\n", "utf-8")
    ev, audits = [], []
    svc = AgentService.__new__(AgentService)
    svc.gw = types.SimpleNamespace(root=tmp_path)
    svc.emit = ev.append
    svc.project_fork = lambda ex, code, name=None: {"project": code, "path": str(tmp_path / "p" / code)}
    monkeypatch.setattr(service_mod.steptools, "fresh_code", lambda root, ex: "2026h-ball")
    monkeypatch.setattr(service_mod.risk, "audit", lambda *a, **k: audits.append(a))
    out = svc.project_switch_example("2026H_ball")
    assert out["project"] == "2026h-ball" and ev[-1]["type"] == "project_forked" and ev[-1]["via"] == "project_switch_example"
    assert audits and audits[0][0] == "project_switch_example"
    for bad in ("../x", "nope"):
        with pytest.raises(GatewayError):
            svc.project_switch_example(bad)
