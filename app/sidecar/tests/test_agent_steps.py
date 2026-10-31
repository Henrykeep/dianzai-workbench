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
from dzbench.agent.service import AgentService
from dzbench.agent_api import AgentTools
from dzbench.session import Session

REPO = pathlib.Path(__file__).resolve().parents[3]
TASK = "一、任务\n设计一个小车。\n二、要求\n1．基本要求\n(1) 小车 10 s 内行驶 2 m。（20 分）\n(2) 停车误差不大于 5 cm。（10 分）\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """临时工程仓库：工具/板卡软链到本仓库，examples/ build/ 是空的。#29：Agent 的写入落在 $DZBENCH_HOME/projects（tmp_path/dzhome/projects）
    和 DZ_BOARDS_DIR（未设 = tmp_path/dzhome/boards），仓库只读。"""
    import site
    monkeypatch.setenv("PYTHONUSERBASE", site.getuserbase())       # 换 HOME 后 pip --user 装的包（jsonschema）还要能找到
    monkeypatch.setenv("HOME", str(tmp_path / "home"))            # projflow 暂存区 ~/.dzbench/flow
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path / "dzhome"))
    monkeypatch.delenv("DZ_BOARDS_DIR", raising=False)
    r = tmp_path / "repo"; r.mkdir()
    for e in REPO.iterdir():
        if e.name not in ("examples", "build", ".git"):
            (r / e.name).symlink_to(e)
    (r / "examples").mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (tmp_path / "t.txt").write_text(TASK, encoding="utf-8")
    return r


def _proj(tmp_path):
    return tmp_path / "dzhome" / "projects"


def _tree(root):
    """仓库树快照：不跟软链（软链本身算一项），记每个文件的大小和 mtime。"""
    out = {}
    for d, dirs, files in os.walk(root, followlinks=False):
        for n in dirs + files:
            q = pathlib.Path(d) / n
            st = q.lstat()
            out[str(q.relative_to(root))] = (st.st_mode, st.st_size if not q.is_dir() else 0, st.st_mtime_ns if not q.is_dir() else 0)
    return out


def _git_status():
    return subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO, capture_output=True, text=True).stdout


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
    assert not (_proj(tmp_path) / "T1/requirements.yaml").exists()           # 没点确认：没写
    c = _cards(ev)[-1]; assert c["tool"] == "flow_accept"
    r = svc.action_decide(c["id"], True); clicks += 1
    assert (_proj(tmp_path) / "T1/requirements.yaml").exists() and not (repo / "examples/T1").exists()
    assert r["next"]["next_step"] == "scheme" and r["next"]["action_id"]      # 方案的预览已跑好、卡已出
    r2 = svc.action_decide(r["next"]["action_id"], True); clicks += 1
    assert (_proj(tmp_path) / "T1/scheme.yaml").exists()
    assert r2["next"]["next_step"] == "import"                               # 板子没导入：停在要工程路径
    # 项目页手动：读题 运行+确认、方案 运行+确认 = 4 下；Agent：1 句话 + 2 张卡 = 3 下，且方案这步不用再找按钮
    assert clicks == 3


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
    assert not (_proj(tmp_path) / "T5").exists()                                  # 没确认：没写
    c = _cards(ev)[-1]; assert c["tool"] == "project_apply"
    r = svc.action_decide(c["id"], True); clicks += 1
    pd = _proj(tmp_path) / "T5"
    assert (pd / "requirements.yaml").exists() and (pd / "scheme.yaml").exists() and not (repo / "examples/T5").exists()
    assert (pd / "alloc").is_dir(), r
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
        assert len(res["rounds"]) <= 4                                          # 仿真：过程中不出卡，只在收尾出一张“采用最好参数”（#53）
        assert [c["tool"] for c in _cards(ev)] == ["iterate_apply_best"] and res["best_card"] == _cards(ev)[0]["id"]
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
        pd = tmp_path / "projects" / "S1"                                       # 内置/仓库里的 examples/S1 只读：写回落到工程根目录
        assert "evidence" in (pd / "requirements.yaml").read_text(encoding="utf-8")
        assert "evidence" not in (d / "requirements.yaml").read_text(encoding="utf-8") and pathlib.Path(sv["result"]["dir"]).is_relative_to(pd)
        # 评分页手动：跑 ×3 + 保存 + 回写预览 + 确认 = 6 下；Agent：问 + 保存卡 + 回写卡 = 3 下
        assert clicks == 3
    finally:
        s.disconnect()


UVX = """<?xml version="1.0"?>
<Project><Targets><Target><TargetName>T</TargetName><TargetOption><TargetArmAds><Cads><VariousControls>
<Define>USE_HAL_DRIVER</Define><IncludePath>../Core/Inc</IncludePath></VariousControls></Cads>
<Aads><VariousControls><Define></Define><IncludePath></IncludePath></VariousControls></Aads></TargetArmAds></TargetOption>
    <Groups>
      <Group>
        <GroupName>App</GroupName>
      </Group>
    </Groups></Target></Targets></Project>
"""


def test_project_chain_includes_keil_inject(repo, tmp_path):
    """导入真工程：①–⑤ + Keil 注入仍是一张卡（自动找 MDK-ARM/*.uvprojx）；确认后 .uvprojx 有 dz/ 组且留 .bak。点 2 下。"""
    pj = tmp_path / "Car"; shutil.copytree(REPO / "tools/testdata/real/projects/Bldc - 副本 (6)", pj)
    uv = pj / "MDK-ARM" / "Bldc.uvprojx"
    llm = FakeLLM([
        {"role": "assistant", "content": None, "tool_calls": [call("project_chain", code="T6", src=str(tmp_path / "t.txt"), project=str(pj), name="t6car")]},
        {"role": "assistant", "content": None, "tool_calls": [call("project_apply", code="T6")]},
        {"role": "assistant", "content": "【实测】预览完成。"},
    ])
    svc, ev = _svc(repo, llm)
    svc.ask("新题 T6，工程在 " + str(pj)); clicks = 1
    chain = json.loads(llm.seen[1][0][-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])["result"]
    assert chain["to_write"][-1] == "keil", chain
    assert "dz/" not in uv.read_text(encoding="utf-8")                           # 没确认：工程没动
    cs = _cards(ev); assert len(cs) == 1 and cs[0]["tool"] == "project_apply"
    assert any("Keil" in "".join(s["facts"]) for s in cs[0]["preview"]["steps"]), cs[0]["preview"]
    r = svc.action_decide(cs[0]["id"], True); clicks += 1
    assert "<GroupName>dz/" in uv.read_text(encoding="utf-8"), str(r)[-600:]
    assert (uv.parent / "Bldc.uvprojx.bak").exists() and clicks == 2
    # 再生成：dz/ 之外的手改保留；dz/ 组里的手改 → 停下要用户选 合并/保留
    t = uv.read_text(encoding="utf-8").replace("<Groups>", "<Groups>\n        <Group><GroupName>MyDrv</GroupName></Group>", 1)
    uv.write_text(t, encoding="utf-8")
    r2 = svc.project_chain("T6", project=str(pj), name="t6car")
    assert r2["to_write"] == ["keil"], r2
    svc.project_apply("T6")
    assert "<GroupName>MyDrv</GroupName>" in uv.read_text(encoding="utf-8")       # 手改活下来
    t = uv.read_text(encoding="utf-8"); i = t.index("<GroupName>dz/")
    uv.write_text(t[:i] + "<GroupName>dz/hand" + t[i + len("<GroupName>dz/"):], encoding="utf-8")
    edited = uv.read_text(encoding="utf-8")
    r3 = svc.project_chain("T6", project=str(pj), name="t6car")
    assert r3["stopped_at"] == "keil" and "手改" in r3["steps"][-1]["why"], r3
    svc.project_chain("T6", project=str(pj), name="t6car", hand_edit="keep"); svc.project_apply("T6")
    assert uv.read_text(encoding="utf-8") == edited                               # 选“保留”：一个字节不动
    svc.project_chain("T6", project=str(pj), name="t6car", hand_edit="merge"); svc.project_apply("T6")
    assert "dz/hand" not in uv.read_text(encoding="utf-8") and "MyDrv" in uv.read_text(encoding="utf-8")
    assert (tmp_path / "dzhome" / "boards" / "t6car" / "board.yaml").exists() and not (REPO / "boards" / "t6car").exists()   # 导入的板落在 DZ_BOARDS_DIR


@pytest.mark.needs_sim
def test_quick_start_one_sentence_e2e(repo, tmp_path):
    """一句话起项目：输入“两轮车速度环，STM32F1” → 一张卡（方案 + 引脚表）→ 用户只点一次确认 →
    写入项目、连仿真板、一键起步调参、评分。"""
    tree0, git0 = _tree(repo), _git_status()
    svc, ev = _svc(repo, FakeLLM([]))
    try:
        r = svc.quick_start("两轮车速度环，STM32F1")
        assert r["spec"]["kind"] == "speed" and r["spec"]["mcu"] == "stm32f103c8t6", r
        assert r["action_id"] and not (repo / "examples" / r["spec"]["code"]).exists(), r["chain"]
        cs = _cards(ev); assert len(cs) == 1 and cs[0]["tool"] == "project_apply"
        pv = cs[0]["preview"]
        assert any(x["k"] == "pin" for s in pv["steps"] for x in s["changes"]), pv               # 卡上有引脚表
        assert any(s["title"] for s in pv["steps"]) and "调参" in pv["after"]
        out = svc.action_decide(r["action_id"], True)["result"]                                 # 唯一一次点击
        print("QUICK", json.dumps({"tune": {k: out["tune"][k] for k in ("final", "best_round", "passed")}, "score": {k: out["score"].get(k) for k in ("result", "item")}}, ensure_ascii=False))
        code = r["spec"]["code"]
        pd = _proj(tmp_path) / code
        assert (pd / "requirements.yaml").exists() and (pd / "alloc").is_dir()
        assert out["sim"] == "sim:car_2wd" and out["tune"]["rounds"] and out["tune"]["best_round"], out
        assert out["score"].get("result") in ("pass", "partial", "fail"), out["score"]
        assert len(_cards(ev)) == 1                                                             # 全程只有这一张卡
    finally:
        svc.s.disconnect()
    assert _tree(repo) == tree0                                                                 # #29：quick_start 后仓库树不变
    assert _git_status() == git0                                                                # 真仓库（软链目标）也没多 / 改一个文件
    with pytest.raises(Exception):
        svc.quick_start("做一个温度报警器")


def test_same_pending_card_not_duplicated(repo):
    """真模型 e2e：quick_start 出了 project_apply 卡后模型又调 project_apply → 第二张卡。挂着的同一操作只出一张。"""
    svc, ev = _svc(repo, FakeLLM([]))
    a = svc.gate("project_apply", {"code": "X"}, lambda: None)
    b = svc.gate("project_apply", {"code": "X"}, lambda: None)
    assert a["action_id"] == b["action_id"] and len(_cards(ev)) == 1


H_SENT = "2026 年 H 题车载平衡滚球：STM32 主控通过舵机调整平板倾角，让小球稳定在中心并按要求运动，从新建工程做到仿真跑通并调好参数。"


@pytest.mark.needs_sim
def test_user_flow_2026H_fresh_project_memory_and_best_card(repo, tmp_path, monkeypatch):
    """#55 / #39 / #53 用户主线（r8 user-main 原话）：一句话开局 → 例题只读（project_open / flow_accept 例题被拒）→ quick_start
    自动选最近的例题新建项目目录（不出卡，只记审计，回复首句「已基于 X 新建 Y，可更换」）→ 设为当前项目、连 2026H 仿真、
    自动迭代 → “采用最好参数”卡（稳态误差按仿真标称几何换成题目单位 cm 判 inside，写明 pass_basis）。
    记忆按 新项目 + 板子 记（不是 _none），第 0 轮带 params_hash；再开局一次落另一个新目录，例题目录始终不动。"""
    from dzbench import project as project_mod
    from dzbench.agent.journal import project_slug
    (repo / "examples" / "2026H_ball").symlink_to(REPO / "examples" / "2026H_ball")
    monkeypatch.setattr(AgentService, "ITER_ROUNDS", 3)
    ex_tree = _tree(REPO / "examples" / "2026H_ball")
    llm = FakeLLM([
        {"role": "assistant", "content": None, "tool_calls": [call("project_open", code="2026H_ball")]},
        {"role": "assistant", "content": None, "tool_calls": [call("flow_accept", step="req", code="2026H_ball")]},
        {"role": "assistant", "content": None, "tool_calls": [call("quick_start", text=H_SENT)]},
        {"role": "assistant", "content": "已出新建项目确认卡。", "tool_calls": []},
    ])
    svc, ev = _svc(repo, llm)
    try:
        svc.s.connect("sim:motor_pos", log=False)                                 # r9q (b)：已连着别的仿真板也要换到例题自己的板
        reply = svc.ask(H_SENT)
        seen = json.dumps([m for m, _ in llm.seen], ensure_ascii=False)
        assert seen.count("example_readonly") >= 2, "例题必须只读：project_open / flow_accept 都要被拒"
        cs = _cards(ev)
        assert "project_fork" not in [c["tool"] for c in cs], cs               # 开局自动选最近的例题建项目，不出卡
        fk = next(e for e in ev if e.get("type") == "project_forked")
        code, out = fk["project"], {"path": fk["path"], "sim": svc.s.port, "best_card": (svc.iter_result or {}).get("best_card")}
        assert code != "2026H_ball" and fk["example"] == "2026H_ball" and code.isascii()
        assert fk["message_zh"] == f"已基于 2026H_ball 新建 {code}，可更换"
        assert reply.startswith(fk["message_zh"]), reply                      # 回复第一句说明基于哪个例题、可更换
        pd = _proj(tmp_path) / code
        assert pd.is_dir() and (pd / "requirements.yaml").exists() and out["path"] == str(pd)
        assert project_mod.current()["name"] == code
        assert out["sim"] == "sim:2026H_ball", out
        assert "sim_board: sim:2026H_ball" in (pd / "project.yaml").read_text("utf-8")   # 项目钉住自己的仿真板
        assert code == "2026h-ball", code                                         # r9q (c)：干净 HOME 第一个没有 -2
        assert "PDF" not in reply, reply                                          # r9q (f)
        evs = [e["type"] for e in ev if str(e.get("type", "")).startswith("iterate.")]
        assert evs[0] == "iterate.started" and evs.count("iterate.stopped") == 1 and "iterate.round" in evs, evs   # r9q (a)
        assert out.get("best_card"), out                                        # 有板上阶跃走 iterate，没有（2026H 例题固件）走 tune_autopilot，都出卡
        assert [c["tool"] for c in _cards(ev)][-1] == "iterate_apply_best"      # 以“采用最好参数”卡收尾
        bc = _cards(ev)[-1]
        se = bc["args"]["ss_err"]                                                 # 卡上：实测稳态误差 + 题目误差带出处 + 是否在带内
        assert se["measured"] >= 0 and se["band"]["source"].startswith("题目 B") and se["band"]["unit"] == "cm"
        assert isinstance(se["inside"], bool) and "仿真标称换算，未实机标定" in se["note_zh"], se   # 仿真：px → cm 用仿真自己的几何
        assert se["converted"]["unit"] == "cm" and se["converted"]["value"] == pytest.approx(se["measured"] / 6, rel=1e-4), se
        assert se["pass_basis"].startswith("按默认 2% 判定达标，另对照题目 B"), se
        cmp_ = bc["args"]["compare"]                                             # 初值轮 vs 最好一轮并排，每项单独 value + unit
        assert cmp_ and bc["preview"]["compare"] == cmp_ and cmp_["round0"]["metrics"] and cmp_["best"]["metrics"], cmp_
        assert all(isinstance(r["value"], float) and isinstance(r["unit"], str) for r in cmp_["round0"]["metrics"] + cmp_["best"]["metrics"])
        assert {"key": "overshoot_pct", "unit": "%"}.items() <= next(r for r in cmp_["best"]["metrics"] if r["key"] == "overshoot_pct").items()
        if cmp_["unchanged"]:
            assert "第0轮最好" not in cmp_["note_zh"] and cmp_["note_zh"].startswith("初值"), cmp_
        else:
            assert cmp_["note_zh"].startswith(f"第 {cmp_['best']['iter']} 轮比初值好"), cmp_
        st = next(e for e in ev if e.get("type") == "iterate.stopped")
        assert st["pass_basis"] == se["pass_basis"], st                         # 停止事件和卡上写同一条依据
        assert bc["preview"]["ss_err"] == se
        mem = svc.memory()
        assert mem.project == project_slug(str(pd)) and mem.project != "_none" and mem.key, (mem.project, mem.key)
        rows = [r for r in mem.load() if r.get("kind") in ("round", "manual_step")]
        assert rows and all(r.get("params_hash") for r in rows), rows           # 第 0 轮起每轮都有 hash
        r2 = svc.quick_start(H_SENT)                                             # 再开局：又一个新目录
        assert r2["spec"]["code"] not in (code, "2026H_ball")
    finally:
        svc.s.disconnect()
    assert _tree(REPO / "examples" / "2026H_ball") == ex_tree                    # 例题一字未动
