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
SCRIPT_OPS_ = _yaml.safe_load((_pl.Path(__file__).resolve().parents[3] / "docs/dev/entrypoints.yaml").read_text(encoding="utf-8"))["script_ops"]
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


# ------------------------------------------------------------------ fetch_deps / run_selftest / 当前项目
def _entries():
    return {a["id"]: a for a in _yaml.safe_load((_pl.Path(__file__).resolve().parents[3] / "docs/dev/entrypoints.yaml").read_text(encoding="utf-8"))["actions"]}


def test_fix_actions_fetch_deps_and_run_selftest_entries():
    e = _entries()
    assert P.FIX["missing_deps"] == "fetch_deps" and P.FIX["selftest_fail"] == "run_selftest"
    assert e["fetch_deps"].get("ready", True) is True and e["fetch_deps"]["ops"] == ["fetch_deps"]
    # 前端已接上（frontend-polish）：三个 op 从 script_ops 移到 actions，位置 page:tune，不用 dynamic
    assert e["run_selftest"].get("ready", True) is True and e["run_selftest"]["ops"] == ["run_selftest"] and "run_selftest" not in SCRIPT_OPS_
    assert not e["run_selftest"].get("dynamic") and e["run_selftest"]["at"] == "page:tune"   # 前端 99ae17c 把按钮挪到调参页
    assert P.FIX["params_not_saved"] == "params_flash" and e["params_flash"]["ops"] == ["save_params"] and e["params_flash"]["at"] == "page:tune"
    assert "save_params" not in SCRIPT_OPS_ and "set_run_mode" not in SCRIPT_OPS_


def test_fetch_deps_reuses_doctor_fixes(tmp_path):
    from dzbench import deps
    items = [{"id": "py_serial", "name": "pyserial（串口）", "level": "fail"},
             {"id": "pack", "name": "MSPM0 器件包（DFP）", "level": "fail"},
             {"id": "config", "name": "工程配置 dzbench.json", "level": "fail", "fix": "按提示改 JSON 语法"},
             {"id": "py_pyocd", "name": "pyOCD", "level": "warn"}]
    calls = []
    r = deps.fetch(items, str(tmp_path), runner=lambda c, cwd: calls.append(c) or {"cmd": " ".join(c), "rc": 0, "tail": ""})
    assert calls[0][-3:] == ["pip", "install", "pyserial"]
    assert calls[1][-1] == "m0pack" and str(calls[1][1]).replace("\\", "/").endswith("tools/fetch_third_party.sh")
    assert len(calls) == 2                                  # warn 项不装
    assert r["unresolved"] == [{"name": "工程配置 dzbench.json", "fix": "按提示改 JSON 语法"}] and r["ok"] is False


def test_server_fetch_deps_and_run_selftest(home, monkeypatch):
    from dzbench import deps, server as srv
    from dzbench.session import LinkError
    sv = srv.Server()
    seq = [[{"id": "py_serial", "name": "pyserial（串口）", "level": "fail"}], []]
    sv.progress._doctor = lambda: seq.pop(0) if seq else []
    monkeypatch.setattr(deps, "_run", lambda c, cwd: {"cmd": " ".join(c), "rc": 0, "tail": ""})
    monkeypatch.setattr(deps.fetch, "__defaults__", (deps._run,))
    r = asyncio.run(sv._op({"op": "fetch_deps"}))
    assert r["ok"] and len(r["ran"]) == 1
    assert sv.progress.deps == []                           # 装完重跑自检
    assert not any(b["code"] == "missing_deps" for b in sv.progress.snapshot()["blockers"])
    with pytest.raises(LinkError) as ei:
        asyncio.run(sv._op({"op": "run_selftest"}))
    assert ei.value.code == "no_board" and ei.value.fix and ei.value.fix_action == "connect"   # 未连接：原因 + 怎么解决 + 一键去连接
    sv.session.status = lambda: {"alive": True}
    with pytest.raises(LinkError) as ei:
        asyncio.run(sv._op({"op": "run_selftest"}))
    assert ei.value.code == "selftest_unreported" and "固件" in ei.value.fix   # 固件没报自检：不再是 not_ready
    sv.session.selftest = {"pass": True, "failed_items": [], "t": 1.0}
    assert asyncio.run(sv._op({"op": "run_selftest"}))["pass"] is True


def _selftest_server(monkeypatch, *, h=None, h_supported=False, hb=None, st=None):
    """run_selftest 四条路径共用：假会话（alive），'H' 的结果由 h 给出；记录广播。"""
    from dzbench import server as srv
    sv = srv.Server()
    sv.progress._doctor = lambda: []
    sent = []

    async def bc(ev):
        sent.append(ev)
    sv._broadcast = bc
    sv.progress.changed = lambda: {"type": "progress", "n": len(sent)}
    s = sv.session
    s.status = lambda: {"alive": True}
    s.h_supported = h_supported
    s.hb_status = hb
    s.selftest = st
    s.run_selftest = lambda: h
    return sv, sent


def test_run_selftest_no_board(home, monkeypatch):
    from dzbench import server as srv
    from dzbench.session import LinkError
    sv = srv.Server()
    sv.progress._doctor = lambda: []
    with pytest.raises(LinkError) as ei:
        asyncio.run(sv._op({"op": "run_selftest"}))
    assert ei.value.code == "no_board" and ei.value.fix_action == "connect"


def test_run_selftest_h_ack_mask(home, monkeypatch):
    from dzbench.session import selftest_dict
    d = selftest_dict(0b101, 1)                              # u32 小端失败掩码：bit0、bit2 失败
    sv, sent = _selftest_server(monkeypatch, h={"ok": d["pass"], "mask": 5, "failed_items": d["failed_items"], "message_zh": "x"})
    r = asyncio.run(sv._op({"op": "run_selftest"}))
    assert r["source"] == "H" and r["pass"] is False and r["selftest"]["mask"] == 5 and len(r["failed_items"]) == 2
    assert sent and sent[-1]["type"] == "progress"           # 刷新进度


def test_run_selftest_h_timeout(home, monkeypatch):
    from dzbench.session import LinkError
    sv, sent = _selftest_server(monkeypatch, h={"ok": None, "mask": None, "failed_items": []}, h_supported=True,
                                st={"pass": True, "failed_items": []})
    with pytest.raises(LinkError) as ei:
        asyncio.run(sv._op({"op": "run_selftest"}))
    assert ei.value.code == "selftest_timeout"               # 回过 'H' 的板子这次没回：不拿旧结果冒充
    assert sent and sent[-1]["type"] == "progress"


def test_run_selftest_old_fw_heartbeat(home, monkeypatch):
    sv, sent = _selftest_server(monkeypatch, h={"ok": None, "mask": None, "failed_items": []}, hb=1 << 11)
    r = asyncio.run(sv._op({"op": "run_selftest"}))           # 旧固件不回 'H'：读心跳 bit11（上电自检）
    assert r["source"] == "heartbeat" and r["pass"] is False and r["selftest"]["from"] == "hb_bit11"
    assert sent and sent[-1]["type"] == "progress"
    sv, sent = _selftest_server(monkeypatch, h=None, hb=0, st={"pass": True, "failed_items": [], "t": 1.0})
    r = asyncio.run(sv._op({"op": "run_selftest"}))           # 有逐项上电自检结果时优先用它
    assert r["source"] == "heartbeat" and r["pass"] is True and sent


def test_session_h_ack_parses_u32_le():
    import struct
    from dzbench.session import Session
    s = Session()
    s._send = lambda *a, **k: (setattr(s, "selftest_ack", struct.unpack_from("<I", b"H\x04\x00\x00\x00", 1)[0]) or True)
    s._check_tx = lambda: None
    r = s.run_selftest(wait_s=0.2)
    assert r["mask"] == 4 and r["ok"] is False and s.h_supported


def test_current_project_persist_hello_and_req(home, monkeypatch):
    from dzbench import project, server as srv
    root = home / "repo"
    (root / "examples" / "demo").mkdir(parents=True)
    sv = srv.Server()
    monkeypatch.setattr(sv.svc.gw, "root", root)
    sv.progress._doctor = lambda: []
    h = asyncio.run(sv._op({"op": "hello"}))
    assert h["project"] is None
    snap = asyncio.run(sv._op({"op": "progress.get"}))
    assert snap["project"] is None and snap["steps"][0]["state"] == "doing"
    with pytest.raises(Exception):                          # 暂存区预览会因缺题目失败，但“打开项目”已记下
        asyncio.run(sv._op({"op": "flow_preview", "step": "req", "code": "demo"}))
    want = {"path": str(root / "examples" / "demo"), "name": "demo"}
    sv2 = srv.Server()                                      # 模拟侧车重启：从 $DZBENCH_HOME 恢复
    sv2.progress._doctor = lambda: []
    assert asyncio.run(sv2._op({"op": "hello"}))["project"] == want
    s = asyncio.run(sv2._op({"op": "progress.get"}))
    assert s["project"] == want and s["steps"][0]["state"] == "doing"     # 没有 requirements.yaml
    (root / "examples" / "demo" / "requirements.yaml").write_text("items: []\n", encoding="utf-8")
    assert asyncio.run(sv2._op({"op": "progress.get"}))["steps"][0]["state"] == "doing"   # 空评分项不算
    (root / "examples" / "demo" / "requirements.yaml").write_text("items:\n  - {id: a, text: 速度误差}\n", encoding="utf-8")
    s = asyncio.run(sv2._op({"op": "progress.get"}))
    assert s["steps"][0]["state"] == "done" and s["steps"][0]["id"] == "req"
    assert project.set_current(root, "../x") is None                       # 非法题号不记
    assert str(project._path()).startswith(str(home))
