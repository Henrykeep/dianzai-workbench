"""progress.get / progress.changed：项目进度（只读推导）。"""
import asyncio
import time

import pytest

from dzbench import progress as P
from dzbench.session import Session

CONNECTED = {"board": "connected", "reason": None}


def facts(**kw):
    f = {"link": dict(CONNECTED), "schema_ok": True, "has_samples": True, "params_read": 5, "deps_missing": [],
         "estop": False, "estop_reason": None, "selftest_fail": None, "gains": {"kp": 1.0, "ki": 0.1},
         "params_saved": True, "tune_best": False, "mode": None}
    f.update(kw)
    return f


def check_schema(snap):
    assert set(snap) >= {"steps", "current", "next", "blockers"}
    assert [s["id"] for s in snap["steps"]] == [i for i, _t, _j in P.STEPS]
    assert [s["title"] for s in snap["steps"]] == ["读题", "工程", "仿真", "上板联调", "调参", "评分", "封箱"]
    assert [s["id"] for s in snap["steps"]] == ["req", "project", "sim", "bringup", "tune", "score", "seal"]
    for s in snap["steps"]:
        assert s["state"] in P.STATES
        assert set(s) <= {"id", "title", "state", "reason", "detail"}
        if s["state"] == "blocked":
            assert s["reason"] in P.BLOCKER_CODES and s["detail"]
    assert set(snap["next"]) == {"title", "action", "hint"}
    assert snap["current"] is None or snap["current"] in {s["id"] for s in snap["steps"]}
    for b in snap["blockers"]:
        assert b["code"] in P.BLOCKER_CODES and b["message"]
        assert b["fix_action"] and b["fix_action"] in P.ACTIONS
    assert snap["next"]["action"] in ENTRY_IDS or snap["next"]["action"] == ""


import pathlib as _pl, yaml as _yaml
ENTRY_IDS = {a["id"] for a in _yaml.safe_load((_pl.Path(__file__).resolve().parents[3] / "docs/dev/entrypoints.yaml").read_text(encoding="utf-8"))["actions"]}


def test_every_action_is_an_entrypoint():
    """next.action / fix_action 只能用入口规则表里已有的动作 id，不另造。"""
    assert set(P.ACTIONS) <= ENTRY_IDS, set(P.ACTIONS) - ENTRY_IDS
    assert set(P.FIX.values()) <= ENTRY_IDS and set(P.STEP_ACTION.values()) <= ENTRY_IDS


def test_journey_mapping_matches_bench_stages():
    """步骤与旅程图 / bench 阶段表对应；journey.yaml 在本分支存在时逐条核对 stage 名。"""
    import pathlib, yaml
    jy = pathlib.Path(__file__).resolve().parents[3] / "tools/bench/journey.yaml"
    if jy.exists():
        stages = {s["stage"] for s in yaml.safe_load(jy.read_text(encoding="utf-8"))["stages"]}
        assert {j for _i, _t, j in P.STEPS} <= stages


@pytest.mark.parametrize("code,kw", [
    ("no_board", {"link": {"board": "disconnected", "reason": "port_not_found"}}),
    ("missing_deps", {"deps_missing": ["pyserial（串口）"]}),
    ("gains_zero", {"gains": {"kp": 0.0, "ki": 0.0, "kd": 0.0}}),
    ("estop", {"estop": True, "estop_reason": "急停"}),
    ("selftest_fail", {"selftest_fail": "板子处于安全态（复位原因：看门狗）"}),
    ("params_not_saved", {"params_saved": False}),
])
def test_each_blocker_has_fix_action(code, kw):
    snap = P.derive(facts(**kw))
    check_schema(snap)
    b = next(b for b in snap["blockers"] if b["code"] == code)
    assert b["fix_action"] == P.FIX[code]
    assert snap["next"]["action"] == snap["blockers"][0]["fix_action"]
    blocked = {s["id"] for s in snap["steps"] if s["state"] == "blocked"}
    assert blocked & set(P.BLOCKS[code])


def test_params_not_saved_blocks_score_and_standalone():
    snap = P.derive(facts(params_saved=False, tune_best=True))
    score = next(s for s in snap["steps"] if s["id"] == "score")
    assert score["state"] == "blocked" and score["reason"] == "params_not_saved"
    assert P.standalone_blocker(snap)["fix_action"] == "params_flash"
    assert P.standalone_blocker(P.derive(facts(params_saved=True))) is None


def test_estop_uses_reason_text():
    snap = P.derive(facts(estop=True, estop_reason="第 1 路堵转"))
    assert "第 1 路堵转" in snap["blockers"][0]["message"]


def test_done_blocked_transitions():
    s0 = P.derive(facts(link={"board": "disconnected", "reason": None}, schema_ok=False, has_samples=False, params_read=0))
    st = {s["id"]: s["state"] for s in s0["steps"]}
    assert st["req"] == "doing" and st["sim"] == "blocked" and s0["current"] == "req"
    s1 = P.derive(facts(req_items=3, sim_board=True))
    st = {s["id"]: s["state"] for s in s1["steps"]}
    assert st["req"] == st["project"] == st["sim"] == "done"
    assert st["bringup"] == "doing" and s1["current"] == "bringup" and s1["blockers"] == []
    assert s1["next"]["action"] == "cal_polarity"
    s2 = P.derive(facts(req_items=3, tune_best=True, score_evidence=2, sealed=True))
    assert all(s["state"] == "done" for s in s2["steps"]) and s2["current"] is None
    s3 = P.derive(facts(req_items=3, estop=True))
    st = {s["id"]: s["state"] for s in s3["steps"]}
    assert st["tune"] == "blocked" and st["bringup"] == "blocked"


def test_mode_passthrough_in_link_state():
    from dzbench.linkstate import LinkState
    ls = LinkState()
    e = ls.update(0.1, port="p", port_open=True, reconnecting=False, t_connect=0.0, last_frame=0.05)
    assert e["mode"] is None
    e = ls.update(0.2, port="p", port_open=True, reconnecting=False, t_connect=0.0, last_frame=0.15, mode="standalone")
    assert e["mode"] == "standalone"
    e = ls.update(0.3, port="p", port_open=True, reconnecting=False, t_connect=0.0, last_frame=0.25, mode="bogus")
    assert e["mode"] is None


def test_params_saved_tracking():
    class Sch:
        params = [{"name": "kp", "default": 1.0}]
    s = Session()
    assert P._params_saved(s) is None
    s.schema, s.params = Sch(), {"kp": 1.0}
    assert P._params_saved(s) is True                     # 等于默认值：无需保存
    s.params["kp"], s.param_writes = 2.0, 1
    assert P._params_saved(s) is False
    s.flash_saved_writes = 1                              # 黑匣子：参数已存进 flash
    assert P._params_saved(s) is True
    s.param_writes = 2
    assert P._params_saved(s) is False


@pytest.mark.needs_sim
def test_sim_board_progress_and_push(home):
    """仿真板：未连接 → no_board；连上 → 烧录/模块完成；急停 → estop 阻塞；每次变化都推 progress.changed。"""
    s = Session()
    pg = P.Progress(s, None, lambda: [])
    pg.refresh_deps()
    s.link_state()
    e0 = pg.changed()
    assert e0["type"] == "progress.changed" and e0["blockers"][0]["code"] == "no_board"
    assert e0["blockers"][0]["fix_action"] == "connect"
    assert pg.changed() is None                           # 未变化不推
    s.connect("sim:car_2wd")
    try:
        end = time.monotonic() + 8
        snap = None
        while time.monotonic() < end:
            s.link_state()
            snap = pg.snapshot()
            st = {x["id"]: x["state"] for x in snap["steps"]}
            if st["sim"] == "done":
                break
            time.sleep(0.1)
        check_schema(snap)
        assert st["sim"] == "done" and st["bringup"] != "done"      # 仿真板不算实物上板
        assert not any(b["code"] == "no_board" for b in snap["blockers"])
        e1 = pg.changed()
        assert e1 and e1 != e0
        s.estop()
        s.link_state()
        e2 = pg.changed()
        b = next(b for b in e2["blockers"] if b["code"] == "estop")
        assert b["fix_action"] == "estop_clear" and "急停" in b["message"]
    finally:
        s.disconnect()


def test_server_op_and_agent_tool_same_interface(home, monkeypatch):
    from dzbench import server as srv
    from dzbench.agent import loop
    sv = srv.Server()
    sv.progress._doctor = lambda: [{"name": "pyserial（串口）", "level": "fail"}]
    r = asyncio.run(sv._op({"op": "progress.get", "refresh": True}))
    check_schema(r)
    codes = [b["code"] for b in r["blockers"]]
    assert codes[:2] == ["missing_deps", "no_board"]
    assert sv.svc.progress_get() == r                      # Agent 工具与 RPC 同一份结果
    assert "progress_get" in {t["name"] for t in loop.TOOLS}
    assert "progress_get" in loop._READ                   # 只读工具：所有模式可用
    assert "progress_get" in sv.svc.loop.handlers
