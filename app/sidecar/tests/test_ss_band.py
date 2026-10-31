"""最好参数卡 ss_err：仿真按仿真对象自己的标称几何换算到题目单位判 inside；实机不硬判（#51）；pass_basis 写明达标依据。"""
import json
import pathlib
import re
import types

import pytest

from dzbench.agent.service import AgentService

REPO = pathlib.Path(__file__).resolve().parents[3]
REQ = "items:\n  - id: B3\n    metrics:\n      - { name: 钢球误差绝对值, op: \"<=\", value: 1, unit: cm }\n"
CONV = json.loads((REPO / "dzbench.json").read_text("utf-8"))["step_tests"]["2026H_ball"]["sim_nominal"]


def _svc(tmp_path, sim, req=REQ, conv=CONV):
    (tmp_path / "requirements.yaml").write_text(req, "utf-8")
    svc = AgentService.__new__(AgentService)
    svc.s = types.SimpleNamespace(port="sim:2026H_ball" if sim else "COM3", replay=None, schema=types.SimpleNamespace(fields=[{"name": "cam_x_px", "unit": "px"}]))
    svc.step_cfg = lambda: {"y": "cam_x_px", **({"sim_nominal": conv} if conv else {})}
    svc._project_path = lambda: str(tmp_path)
    return svc


def test_sim_nominal_matches_sim_geometry():
    """换算系数取自仿真源码，不是另编的：dzbench.json 与 sim_setup.c 的 SIM_PX_PER_M 一致。"""
    c = (REPO / "examples/2026H_ball/io/sim_setup.c").read_text("utf-8")
    px_per_m = float(re.search(r"#define SIM_PX_PER_M\s+([0-9.]+)", c).group(1))
    assert CONV["px_per_m"] == px_per_m and CONV["per"] == pytest.approx(100.0 / px_per_m)


def test_sim_converts_and_judges(tmp_path):
    se = _svc(tmp_path, True)._ss_band({"sse": 3.0})                  # 3 px = 0.5 cm ≤ 1 cm
    assert se["unit"] == "px" and se["converted"] == {"value": pytest.approx(0.5), "unit": "cm",
                                                      "note_zh": se["converted"]["note_zh"]}
    assert se["inside"] is True and "仿真标称换算，未实机标定" in se["note_zh"]
    assert se["pass_basis"] == "按默认 2% 判定达标；另对照题目 B3：钢球误差绝对值 ≤ 1cm：在带内"
    out = _svc(tmp_path, True)._ss_band({"sse": 12.0})                 # 2 cm
    assert out["inside"] is False and out["pass_basis"].endswith("超出")


def test_hw_keeps_inside_null(tmp_path):
    se = _svc(tmp_path, False)._ss_band({"sse": 3.0})
    assert se["inside"] is None and "#51" in se["note_zh"] and "converted" not in se
    assert se["pass_basis"] == "按默认 2% 判定，题目误差带待标定"


def test_sim_without_geometry_and_no_band(tmp_path):
    se = _svc(tmp_path, True, conv=None)._ss_band({"sse": 3.0})
    assert se["inside"] is None and se["pass_basis"] == "按默认 2% 判定，题目误差带待标定"
    se = _svc(tmp_path, True, req="items: []\n")._ss_band({"ss_err_pct": 1.0})
    assert se["inside"] is True and se["pass_basis"] == "按默认 2% 判定（题目没写误差带）"


def test_compare_round0_best_value_unit(tmp_path):
    svc = _svc(tmp_path, True)
    r0 = {"iter": 1, "metrics": {"sse": 3.0, "overshoot_pct": 12.0, "iae": 80.0}, "passed": False}
    c = svc._compare(r0, {"iter": 3, "metrics": {"sse": 1.0, "overshoot_pct": 5.0, "iae": 40.0}})
    assert not c["unchanged"] and c["note_zh"].startswith("第 3 轮比初值好")
    assert c["round0"]["metrics"][0] == {"key": "sse", "value": 3.0, "unit": "px"}
    assert {"key": "overshoot_pct", "value": 5.0, "unit": "%"} in c["best"]["metrics"]
    assert {"key": "iae", "value": 40.0, "unit": "px·s"} in c["best"]["metrics"]
    same = svc._compare(r0 | {"passed": True}, {"iter": 1, "metrics": r0["metrics"]})
    assert same["unchanged"] and same["note_zh"] == "初值已达标，未改参"
    assert "第0轮最好" not in svc._compare(r0, {"iter": 1, "metrics": r0["metrics"]})["note_zh"]


def test_agent_state(monkeypatch):
    from dzbench.agent import llm as llm_mod
    svc = AgentService.__new__(AgentService)
    monkeypatch.setattr(llm_mod, "public_config", lambda: {"configured": False})
    st = svc.agent_state()
    assert st["state"] == "unconfigured" and st["fix_action"] == "configure_model"
    monkeypatch.setattr(llm_mod, "public_config", lambda: {"configured": True})
    assert svc.agent_state() == {"state": "ready"}
    svc._asking = 1
    assert svc.agent_state() == {"state": "busy"}


def test_proposal_source_enum():
    from dzbench.agent_api import AgentTools
    seen = []
    sch = types.SimpleNamespace(param_index={"kp": 0}, check=lambda n, v: v)
    t = AgentTools(types.SimpleNamespace(schema=sch, params={"kp": 1.0}), seen.append)
    t.propose_param_change("kp", 1.2, "x", "agent")
    t.propose_param_change("kp", 1.3, "x", "规则引擎")
    t.propose_param_change("kp", 1.4, "x", "继电起步")
    assert [p["source"] for p in seen] == ["llm", "rule_engine", "rule_engine"] and seen[1]["source_zh"] == "规则引擎"
