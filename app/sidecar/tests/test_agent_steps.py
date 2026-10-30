"""Agent 推进项目步 / 仿真调参一轮：脚本化大模型（不要 Key、不联网），并数人要点几下。

点击口径（docs/dev/agent-design.md §5）：一次“发消息”或一次“点按钮”记 1 下；拖文件/填路径不计（两边都一样要给）。
"""
import json
import os
import pathlib
import shutil
import subprocess
import time

import pytest
import yaml

from agentfake import FakeLLM, call
from dzbench.agent.offline import OfflineAssistant
from dzbench.agent.service import AgentService
from dzbench.agent_api import AgentTools
from dzbench.session import Session

REPO = pathlib.Path(__file__).resolve().parents[3]
TASK = "一、任务\n设计一个小车。\n二、要求\n1．基本要求\n(1) 小车 10 s 内行驶 2 m。（20 分）\n(2) 停车误差不大于 5 cm。（10 分）\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """临时工程仓库：工具/板卡软链到本仓库，examples/ build/ 是空的（Agent 的写入只落在这里）。"""
    import site
    monkeypatch.setenv("PYTHONUSERBASE", site.getuserbase())       # 换 HOME 后 pip --user 装的包（jsonschema）还要能找到
    monkeypatch.setenv("HOME", str(tmp_path / "home"))            # projflow 暂存区 ~/.dzbench/flow
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path / "dzhome"))
    r = tmp_path / "repo"; r.mkdir()
    for e in REPO.iterdir():
        if e.name not in ("examples", "build", ".git"):
            (r / e.name).symlink_to(e)
    (r / "examples").mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (tmp_path / "t.txt").write_text(TASK, encoding="utf-8")
    return r


def _svc(root, llm):
    ev = []
    s = Session(emit=ev.append)
    svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=root, llm=llm)
    return svc, ev


def _cards(ev):
    return [e for e in ev if e.get("type") == "agent_action"]


def test_scripted_model_drives_project_steps(repo, tmp_path):
    """真模型的剧本：看状态 → 预览读题 → 出确认卡。确认之前仓库不动；确认后自动备好下一步（方案）的卡。"""
    llm = FakeLLM([
        {"role": "assistant", "content": None, "tool_calls": [call("project_state", code="T1")]},
        {"role": "assistant", "content": None, "tool_calls": [call("flow_preview", step="req", code="T1", src=str(tmp_path / "t.txt"))]},
        {"role": "assistant", "content": None, "tool_calls": [call("flow_accept", step="req", code="T1")]},
        {"role": "assistant", "content": "【实测】读题拆出 2 个评分项，确认卡在右侧。"},
    ])
    svc, ev = _svc(repo, llm)
    clicks = 1
    out = svc.ask("新题 T1，题目在 " + str(tmp_path / "t.txt") + "，帮我把项目推下去")
    assert "2 个评分项" in out
    seen = json.loads(llm.seen[2][0][-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert seen["ok"] and len(seen["result"]["items"]) == 2                 # 预览结果（真跑 tools/req.py）回到了模型
    assert not (repo / "examples/T1/requirements.yaml").exists()              # 没点确认：仓库没动
    c = _cards(ev)[-1]; assert c["tool"] == "flow_accept"
    r = svc.action_decide(c["id"], True); clicks += 1
    assert (repo / "examples/T1/requirements.yaml").exists()
    assert r["next"]["next_step"] == "scheme" and r["next"]["action_id"]      # 方案的预览已跑好、卡已出
    r2 = svc.action_decide(r["next"]["action_id"], True); clicks += 1
    assert (repo / "examples/T1/scheme.yaml").exists()
    assert r2["next"]["next_step"] == "import"                               # 板子没导入：停在要工程路径
    # 项目页手动：读题 运行+确认、方案 运行+确认 = 4 下；Agent：1 句话 + 2 张卡 = 3 下，且方案这步不用再找按钮
    assert clicks == 3


def test_offline_assistant_project_playbook(repo, tmp_path):
    """没 Key：离线规则助手走同一套工具，认出新题号和题目路径，出确认卡；不编数字。"""
    svc, ev = _svc(repo, OfflineAssistant())
    out = svc.ask(f"推进项目 T2，题目 {tmp_path / 't.txt'}")
    assert "T2" in out and "确认卡" in out, out
    assert [c["tool"] for c in _cards(ev)] == ["project_apply"]
    assert not (repo / "examples/T2").exists()
    out = svc.ask("推进项目 T9")                                              # 缺题目：停下来要，不猜路径
    assert "需要你给我" in out and "src" in out, out


def test_project_state_counts_from_files(repo):
    from dzbench.agent.steptools import project_state
    d = repo / "examples/T3"; d.mkdir()
    (d / "requirements.yaml").write_text(yaml.safe_dump({"items": [{"id": 1, "evidence": [{"path": "x"}]}, {"id": 2}]}), encoding="utf-8")
    st = project_state(repo, "T3")
    assert st["req_items"] == 2 and st["items_with_evidence"] == 1 and st["next_step"] == "scheme"
    assert "T3" in project_state(repo)["projects"]


@pytest.mark.needs_sim
def test_sim_tuning_round_two_clicks(tmp_path, home):
    """仿真调参一轮：Agent 先做实验、按数据提议一个参数；人点“采纳”后自动做验证阶跃。共 2 下（问 + 采纳）。"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "hold_s": 1.2, "pre_s": 0.4, "y": "spd_a", "sp": "sp_a"}}), encoding="utf-8")
    ev = []
    s = Session(emit=ev.append); s.connect("sim:car_2wd", 115200, log=False)
    try:
        t0 = time.monotonic()
        while (s.schema_hash is None or not s.params) and time.monotonic() - t0 < 10:
            time.sleep(0.05)
        kp = s.params["kp"]
        llm = FakeLLM([
            {"role": "assistant", "content": None, "tool_calls": [call("run_step_test")]},
            {"role": "assistant", "content": None, "tool_calls": [call("propose_param_change", name="kp", value=kp * 1.2, reason="上升慢")]},
            {"role": "assistant", "content": "【实测】已提议 kp 加 20%。"},
        ])
        tools = AgentTools(s, ev.append)
        svc = AgentService(s, tools, ev.append, root=tmp_path, llm=llm)
        clicks = 1
        svc.ask("帮我调速度环")
        res = json.loads(llm.seen[1][0][-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
        assert res["ok"] and res["result"]["metrics"]["ok"]                    # 实验在仿真里直接跑（log 级）
        p = [e for e in ev if e.get("type") == "proposal"][-1]
        r = tools.decide(p["id"], True); clicks += 1
        assert r["status"] in ("ok", "clamped") and svc.verify_after_decide(p["id"], r)   # 服务端会接着跑验证阶跃
        v = svc.run_step_test()
        assert v["metrics"]["ok"] and len(svc.tune_context()["history"]) >= 2
        # 调参页手动：阶跃实验 → 规则建议 → 采纳 → 阶跃实验 = 4 下；Agent：问 + 采纳 = 2 下
        assert clicks == 2
    finally:
        s.disconnect()


def test_project_chain_one_card(repo, tmp_path):
    """一句话跑完项目：Agent 预览读题→方案→(从零新建)→分配→生成，只写暂存区；一张总确认卡写入。共 2 下（问 + 确认）。"""
    llm = FakeLLM([
        {"role": "assistant", "content": None, "tool_calls": [call("project_chain", code="T5", src=str(tmp_path / "t.txt"))]},
        {"role": "assistant", "content": None, "tool_calls": [call("project_apply", code="T5")]},
        {"role": "assistant", "content": "【实测】各步预览完成，总确认卡在右侧。"},
    ])
    svc, ev = _svc(repo, llm)
    clicks = 1
    svc.ask(f"新题 T5，题目在 {tmp_path / 't.txt'}")
    chain = json.loads(llm.seen[1][0][-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])["result"]
    print(json.dumps(chain, ensure_ascii=False, indent=1))
    assert chain["to_write"][:2] == ["req", "scheme"]
    assert not (repo / "examples/T5").exists()                                    # 没确认：仓库没动
    c = _cards(ev)[-1]; assert c["tool"] == "project_apply"
    r = svc.action_decide(c["id"], True); clicks += 1
    assert (repo / "examples/T5/requirements.yaml").exists() and (repo / "examples/T5/scheme.yaml").exists()
    assert (repo / "examples/T5/alloc").is_dir(), r
    # 项目页手动：每步 运行+确认 ×(读题/方案/新建/生成) ≥ 8 下；逐步卡 Agent 3+ 下；chain：2 下
    assert clicks == 2


@pytest.mark.needs_sim
def test_sim_autopilot_and_page_tools(tmp_path, home, monkeypatch):
    """仿真自动调参：一句话、0 张卡跑到护栏通过或 N 轮，报告最好一轮；联调/标定只读工具与页面同一函数。实机拒绝自动连跑。"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "hold_s": 1.2, "pre_s": 0.4, "y": "spd_a", "sp": "sp_a"}}), encoding="utf-8")
    ev = []
    s = Session(emit=ev.append); s.connect("sim:car_2wd", 115200, log=False)
    try:
        t0 = time.monotonic()
        while (s.schema_hash is None or not s.params) and time.monotonic() - t0 < 10:
            time.sleep(0.05)
        llm = FakeLLM([
            {"role": "assistant", "content": None, "tool_calls": [call("tune_autopilot", rounds=3)]},
            {"role": "assistant", "content": None, "tool_calls": [call("fft", field="spd_a", seconds=5), call("wave_measure", field="spd_a", ref="sp_a", seconds=5)]},
            {"role": "assistant", "content": "【实测】自动调参完成。"},
        ])
        tools = AgentTools(s, ev.append)
        svc = AgentService(s, tools, ev.append, root=tmp_path, llm=llm)
        svc.ask("帮我把速度环自动调好")
        res = json.loads(llm.seen[1][0][-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])["result"]
        print(json.dumps(res, ensure_ascii=False)[:800])
        assert res["rounds"] and res["best_round"] and "gains" in res["best_round"]
        assert len(res["rounds"]) <= 4 and not _cards(ev)                      # 仿真：没有一张卡
        for c in llm.seen[2][0][-2:]:
            assert '"ok": true' in c["content"], c["content"][:300]
        monkeypatch.setattr(AgentService, "sim", property(lambda self: False))
        with pytest.raises(Exception):
            svc.tune_autopilot(2)
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_sim_score_run_save_writeback(tmp_path, home):
    """评分：跑 3 次（仿真 log 级，不出卡）→ 存证据（卡）→ 回写（卡）。人点 2 下。"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tools").symlink_to(REPO / "tools"); (tmp_path / "schemas").symlink_to(REPO / "schemas") if (REPO / "schemas").exists() else None
    d = tmp_path / "examples/S1"; d.mkdir(parents=True)
    (d / "requirements.yaml").write_text(yaml.safe_dump({"problem": {"code": "S1"}, "items": [
        {"id": 1, "text": "速度阶跃 1.2 s 内稳定，误差 ≤ 0.3", "score": 10, "metrics": [{"name": "spd_err", "op": "<=", "value": 0.3}]}]},
        allow_unicode=True), encoding="utf-8")
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "hold_s": 1.2, "pre_s": 0.4, "y": "spd_a", "sp": "sp_a"}}), encoding="utf-8")
    ev = []
    s = Session(emit=ev.append); s.connect("sim:car_2wd", 115200, log=False)
    try:
        t0 = time.monotonic()
        while (s.schema_hash is None or not s.params) and time.monotonic() - t0 < 10:
            time.sleep(0.05)
        llm = FakeLLM([
            {"role": "assistant", "content": None, "tool_calls": [call("score_run", item="1", n=3, band=0.3)]},
            {"role": "assistant", "content": None, "tool_calls": [call("score_save", item="1")]},
            {"role": "assistant", "content": "【实测】3/3 通过，保存证据的卡在右侧。"},
        ])
        svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path, llm=llm)
        clicks = 1
        svc.ask("评分项 1 跑三遍留证据")
        r = json.loads(llm.seen[1][0][-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])["result"]
        print(r)
        assert len(r["runs"]) == 3 and r["result"] in ("pass", "partial", "fail")
        c = _cards(ev)[-1]; assert c["tool"] == "score_save"
        sv = svc.action_decide(c["id"], True); clicks += 1
        wb = svc.score_writeback("1", sv["result"]["dir"]); clicks += 1          # 回写也是一张卡（这里直接调执行体）
        print(wb)
        assert "evidence" in (d / "requirements.yaml").read_text(encoding="utf-8")
        # 评分页手动：跑 ×3 + 保存 + 回写预览 + 确认 = 6 下；Agent：问 + 保存卡 + 回写卡 = 3 下
        assert clicks == 3
    finally:
        s.disconnect()


@pytest.mark.needs_sim
def test_offline_autotune_and_score_playbooks(tmp_path, home):
    """没 Key：离线助手一句话仿真自动调参（0 张卡）；一句话评分项跑 3 次 → 存证据卡 → 一句话回写卡。数字全来自工具结果。"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tools").symlink_to(REPO / "tools")
    d = tmp_path / "examples/S2"; d.mkdir(parents=True)
    (d / "requirements.yaml").write_text(yaml.safe_dump({"problem": {"code": "S2"}, "items": [
        {"id": 1, "text": "速度阶跃误差 ≤ 0.3", "score": 10, "metrics": [{"name": "spd_err", "op": "<=", "value": 0.3}]}]},
        allow_unicode=True), encoding="utf-8")
    (tmp_path / "dzbench.json").write_text(json.dumps({"step_test": {"kind": "data", "id": 1, "fmt": "<ff", "low": [0, 0],
        "high": [0.4, 0], "hold_s": 1.2, "pre_s": 0.4, "y": "spd_a", "sp": "sp_a"}}), encoding="utf-8")
    ev = []
    s = Session(emit=ev.append); s.connect("sim:car_2wd", 115200, log=False)
    try:
        t0 = time.monotonic()
        while (s.schema_hash is None or not s.params) and time.monotonic() - t0 < 10:
            time.sleep(0.05)
        svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path, llm=OfflineAssistant())
        out = svc.ask("仿真里自动调好，最多 3 轮")
        assert "仿真自动调参" in out and "第 1 轮" in out and not _cards(ev), out
        out = svc.ask("评分项 1 跑三遍留证据")
        assert "跑了 3 次" in out and "band=0.3" in out, out
        if "→ pass" in out:
            c = _cards(ev)[-1]; assert c["tool"] == "score_save"
            assert c["preview"]["title"].startswith("保存评分项") and len(c["preview"]["steps"]) == 3
            svc.action_decide(c["id"], True)
            out = svc.ask("回写评分项 1")
            c = _cards(ev)[-1]; assert c["tool"] == "score_writeback" and "evidence" in c["preview"]["steps"][0]["detail"], c["preview"]
            svc.action_decide(c["id"], True)
            assert "evidence" in (d / "requirements.yaml").read_text(encoding="utf-8")
    finally:
        s.disconnect()
