"""内置 Agent：全部离线（假 LLM / 本地假 HTTP 服务），不需要网络和 Key。"""
import json

from dzbench.agent.untrusted import unwrap
import math
import os
import pathlib
import stat
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dzbench.agent import llm as llm_mod
from dzbench.agent import yamlpar
from dzbench.agent.gateway import Gateway, GatewayError, TRAILER
from dzbench.agent.loop import TOOLS, AgentLoop
from dzbench.agent.service import AgentService, guess_pairs
from dzbench.agent.tuning import step_metrics, tuning_hints
from dzbench.agent_api import AgentTools
from dzbench.schema import Schema
from dzbench.session import Session


def second_order(zeta, wn=10.0, T=3.0, dt=0.005, amp=2.0, t_step=0.5, gain=1.0):
    t, y, sp = [], [], []
    x, v = 0.0, 0.0
    for k in range(int(T / dt)):
        tk = k * dt
        r = amp if tk >= t_step else 0.0
        a = wn * wn * (gain * r - x) - 2 * zeta * wn * v
        v += a * dt
        x += v * dt
        t.append(tk); y.append(x); sp.append(r)
    return t, y, sp


# ---------------------------------------------------------------- 阶跃指标与规则
def test_metrics_underdamped_matches_theory():
    m = step_metrics(*second_order(0.3))
    theory = 100 * math.exp(-0.3 * math.pi / math.sqrt(1 - 0.09))     # 37.2%
    assert m.ok and abs(m.overshoot_pct - theory) < 2.0
    assert m.oscillations >= 2 and m.settling_s is not None and m.rise_s and m.rise_s < 0.2


def test_hints_overshoot_and_slow_and_sse():
    h = tuning_hints(step_metrics(*second_order(0.3)), {"kp": 1.0, "ki": 0.5}, "kp", "ki", None)
    assert any("Kp" in x.text for x in h) and h[0].changes["kp"] < 1.0
    h = tuning_hints(step_metrics(*second_order(1.5)), {"kp": 1.0, "ki": 0.5}, "kp", "ki", None)
    assert h[0].changes.get("kp", 0) > 1.0                                       # 过阻尼 → 加 Kp
    h = tuning_hints(step_metrics(*second_order(0.9, gain=0.9)), {"kp": 1.0, "ki": 0.5}, "kp", "ki", None)
    assert any("稳态误差" in x.text and x.changes.get("ki", 0) > 0.5 for x in h)


def test_hints_sustained_oscillation_and_no_step():
    h = tuning_hints(step_metrics(*second_order(0.02, T=2.0)), {"kp": 2.0, "ki": 1.0}, "kp", "ki", None)
    assert h[0].level == "warn" and h[0].changes["kp"] < 2.0 and h[0].changes["ki"] < 1.0
    t = [i * 0.01 for i in range(100)]
    m = step_metrics(t, [0.0] * 100, [1.0] * 100)
    assert not m.ok and "阶跃" in m.reason and tuning_hints(m, {})[0].level == "info"


def test_hints_good_response_without_settling_time():
    """窗口内没算出调节时间（settling_s=None）但响应良好：不能抛 TypeError（离线助手曾因此说“还没法分析”）。"""
    from dzbench.agent.tuning import StepMetrics
    m = StepMetrics(ok=True, rise_s=0.2, overshoot_pct=3.0, settling_s=None, sse_pct=0.5)
    h = tuning_hints(m, {"kp": 1.0}, "kp", None, None)
    assert any("调节时间" in x.text for x in h)


def test_guess_pairs():
    assert guess_pairs(["t_ms", "sp_a", "spd_a", "sp_b", "spd_b"]) == [("spd_a", "sp_a"), ("spd_b", "sp_b")]


# ---------------------------------------------------------------- yaml 写回
def test_yaml_rewrite_only_touches_default():
    src = ("params:\n  # 注释保留\n  - { name: kp,  type: float, default: 0.08, min: 0, max: 2, desc: 轮速 }\n"
           "  - { name: ki,  type: float, default: 1.5,  min: 0, max: 20 }\n")
    out, missing = yamlpar.rewrite(src, {"kp": 0.12, "zz": 1})
    assert missing == ["zz"] and "default: 0.12, min: 0" in out and out.count("\n") == src.count("\n")
    assert out.replace("0.12", "0.08") == src


# ---------------------------------------------------------------- 网关（临时 git 仓库）
def git(root, *a):
    return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "apps/x").mkdir(parents=True)
    (r / "firmware").mkdir()
    (r / "apps/x/app.yaml").write_text("  - { name: kp, type: float, default: 0.08, min: 0, max: 2 }\n", encoding="utf-8")
    (r / "apps/x/main.c").write_text("int gain = 1;\nint other = 2;\n", encoding="utf-8")
    (r / "firmware/a.c").write_text("x\n", encoding="utf-8")
    (r / "secret.env").write_text("K=1\n", encoding="utf-8")
    git(r, "init", "-q"); git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "init", "--allow-empty")
    git(r, "add", "."); git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "files")
    return r


class Runner:
    def __init__(self, fail=()):
        self.cmds, self.fail = [], set(fail)

    def __call__(self, cmd, cwd):
        if cmd[0] == "git":
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr
        self.cmds.append(" ".join(cmd))
        return (1, "boom") if " ".join(cmd) in self.fail else (0, "ok")


def test_gateway_permissions(repo):
    g = Gateway(repo, runner=Runner())
    with pytest.raises(GatewayError, match="frozen"):
        g.propose_edit("firmware/a.c", "x", "y", "r")
    with pytest.raises(GatewayError) as e:
        g.read_file("secret.env")
    assert e.value.code == "denied"
    with pytest.raises(GatewayError) as e:
        g.read_file("../../etc/passwd")
    assert e.value.code == "outside_repo"
    with pytest.raises(GatewayError, match="2 次"):
        g.propose_edit("apps/x/main.c", "int ", "long ", "r")
    assert "firmware/a.c" in g.list_files() and "secret.env" not in g.list_files()


def test_gateway_accept_runs_gates_and_commits_then_rollback(repo):
    run = Runner()
    ev = []
    g = Gateway(repo, ev.append, runner=run)
    c = g.propose_edit("apps/x/main.c", "int gain = 1;", "int gain = 3;", "加大增益")
    assert c["status"] == "pending" and "+int gain = 3;" in c["diff"] and "make check" in c["gates"]
    assert "gain = 1" in (repo / "apps/x/main.c").read_text(encoding="utf-8"), "确认前不能落盘"
    r = g.decide(c["id"], True)
    assert r["status"] == "committed" and run.cmds == ["make check", "make test"]
    assert f"{TRAILER}: {c['id']}" in git(repo, "log", "-1", "--format=%B")
    assert g.history()[0]["commit"] == r["commit"]
    g.rollback(r["commit"])
    assert "gain = 1" in (repo / "apps/x/main.c").read_text(encoding="utf-8")
    with pytest.raises(GatewayError) as e:
        g.rollback(git(repo, "rev-list", "--max-parents=0", "HEAD").strip()[:7])
    assert e.value.code == "not_agent_commit"


def test_gateway_gate_failure_restores(repo):
    g = Gateway(repo, runner=Runner(fail={"make check"}))
    head = git(repo, "rev-parse", "HEAD")
    c = g.propose_yaml_params("apps/x/app.yaml", {"kp": 0.5}, "写回")
    assert c["layer"] == "config" and c["gates"] == ["make check"]
    r = g.decide(c["id"], True)
    assert r["status"] == "failed" and "boom" in r["log"]
    assert "default: 0.08" in (repo / "apps/x/app.yaml").read_text(encoding="utf-8") and git(repo, "rev-parse", "HEAD") == head


def test_gateway_refuses_dirty_or_stale(repo):
    g = Gateway(repo, runner=Runner())
    c = g.propose_edit("apps/x/main.c", "int gain = 1;", "int gain = 2;", "r")
    (repo / "apps/x/main.c").write_text("int gain = 1;\nint other = 9;\n", encoding="utf-8")      # 人手改了没提交
    r = g.decide(c["id"], True)
    assert r["status"] == "failed" and "未提交" in r["log"]
    with pytest.raises(GatewayError):
        g.decide(c["id"], True)


# ---------------------------------------------------------------- Agent 循环（假 LLM）
SCHEMA = {"version": 1, "hash": 1, "telemetry": {"id": 2, "fields": [{"name": "t_ms", "type": "u32"}]},
          "params": [{"name": "kp", "type": "f32", "min": 0, "max": 2, "default": 0.08}]}


from agentfake import FakeLLM, call  # noqa: E402


def test_agent_loop_only_proposes_and_cannot_estop(repo):
    s = Session()
    s.schema = Schema(SCHEMA)
    s.params = {"kp": 0.08}
    ev = []
    tools = AgentTools(s, ev.append)
    fake = FakeLLM([
        {"role": "assistant", "content": None, "tool_calls": [call("list_params"), call("propose_param_change", name="kp", value=99, reason="试试")]},
        {"role": "assistant", "content": None, "tool_calls": [call("estop"), call("propose_edit", path="firmware/a.c", search="x", replace="y", reason="r")]},
        {"role": "assistant", "content": "已提议把 kp 调到 2（上限）。"},
    ])
    svc = AgentService(s, tools, ev.append, root=repo, llm=fake, runner=Runner())
    out = svc.ask("车子太慢")
    assert out.startswith("已提议")
    prop = [e for e in ev if e["type"] == "proposal"]
    # 调参护栏（非仿真 = 实机档）：0.08 一步最多 ×1.5 → 0.12，而不是直接到上限 2；且还没生效
    assert prop and prop[0]["value"] == 0.12 and "护栏" in prop[0]["reason"] and s.params["kp"] == 0.08
    tool_msgs = [json.loads(unwrap(m["content"])) for m in fake.seen[-1][0] if m["role"] == "tool"]
    assert tool_msgs[2]["ok"] is False and "estop" in tool_msgs[2]["error"]
    assert tool_msgs[3]["ok"] is False and "frozen" in tool_msgs[3]["error"]
    assert not any("estop" in t["name"] for t in fake.seen[0][1])
    assert {t["name"] for t in TOOLS} >= {"step_analysis", "propose_edit"}


def test_agent_step_limit():
    loop = AgentLoop(FakeLLM([{"role": "assistant", "tool_calls": [call("list_params")]}] * 3), {"list_params": lambda: []}, max_steps=3)
    assert "步数用完" in loop.ask("hi")


# ---------------------------------------------------------------- LLM 客户端与配置
def test_config_key_local_and_masked(tmp_path, monkeypatch):
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path))
    monkeypatch.delenv("DZBENCH_API_KEY", raising=False)
    pub = llm_mod.save_config({"provider": "qwen", "api_key": "sk-1234567890abcd"})
    assert pub["has_key"] and pub["key_hint"] == "…abcd" and "api_key" not in pub
    assert pub["base_url"].startswith("https://dashscope")
    if os.name != "nt":
        assert stat.S_IMODE(llm_mod.config_path().stat().st_mode) == 0o600
    llm_mod.save_config({"model": "qwen-max", "api_key": ""})
    assert llm_mod.load_config()["api_key"] == "sk-1234567890abcd"


def test_openai_compat_against_local_fake_server(tmp_path, monkeypatch):
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got["auth"] = self.headers["Authorization"]
            got["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            code = 401 if "bad" in got["auth"] else 200
            body = {"choices": [{"message": {"role": "assistant", "content": "好"}}]} if code == 200 else {"error": "x"}
            self.send_response(code); self.end_headers(); self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/v1"
    c = llm_mod.OpenAICompat({"provider": "custom", "base_url": url, "model": "m", "api_key": "sk-ok"})
    assert c.chat([{"role": "user", "content": "hi"}], TOOLS[:1])["content"] == "好"
    assert got["auth"] == "Bearer sk-ok" and got["body"]["tools"][0]["function"]["name"] == "read_telemetry"
    with pytest.raises(llm_mod.LLMError) as e:
        llm_mod.OpenAICompat({"provider": "custom", "base_url": url, "model": "m", "api_key": "bad"}).chat([])
    assert "401" in e.value.message and "Key" in e.value.fix
    with pytest.raises(llm_mod.LLMError) as e:
        llm_mod.OpenAICompat({"provider": "deepseek", "base_url": "x", "model": "m"}).chat([])
    assert "Key" in e.value.message
    srv.shutdown()


def test_yaml_rewrite_keeps_numerically_equal():
    src = "  - { name: a, type: float, default: 5.0, min: 0 }\n  - { name: b, type: float, default: 1.5, min: 0 }\n"
    out, _ = yamlpar.rewrite(src, {"a": 5.0, "b": struct.unpack("<f", struct.pack("<f", 1.95))[0]})
    assert "default: 5.0," in out and "default: 1.95," in out


def test_agents_md_goes_into_system_prompt(repo):
    (repo / "AGENTS.md").write_text("规则：不写寄存器\n", encoding="utf-8")
    svc = AgentService(Session(), AgentTools(Session(), lambda e: None), lambda e: None, root=repo, llm=FakeLLM([]), runner=Runner())
    assert "不写寄存器" in svc.loop.messages[0]["content"]


def test_no_model_says_unreachable(home, tmp_path):
    """没配模型 / 连不上（本地也没有）→ 不编答案：发 agent_unreachable（界面给重试 + 设置），回答说明其它功能不受影响。"""
    from dzbench.agent import llm as llm_mod
    s = Session()
    ev = []
    svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=tmp_path)
    assert svc.llm() is None
    r = svc.ask("急停老是触发，帮我把急停关了")
    assert "还没接大模型" in r and ev[-1]["type"] == "agent_unreachable" and ev[-1]["text"].startswith("急停")

    class Down:
        def chat(self, *a):
            raise llm_mod.LLMError("连不上模型服务：timed out", "", down=True)
    svc._llm = Down()
    ev.clear()
    r = svc.ask("你好")
    assert "连不上" in r and ev[-1]["type"] == "agent_unreachable" and svc.loop.messages[-1]["role"] != "user"


def test_rollback_refuses_when_touched_file_dirty(repo):
    g = Gateway(repo, lambda e: None, runner=Runner())
    c = g.propose_edit("apps/x/main.c", "int gain = 1;", "int gain = 3;", "t")
    r = g.decide(c["id"], True)
    f = repo / "apps/x/main.c"
    f.write_text(f.read_text(encoding="utf-8") + "// 用户手改\n", encoding="utf-8")
    with pytest.raises(GatewayError) as e:
        g.rollback(r["commit"])
    assert e.value.code == "dirty" and "用户手改" in f.read_text(encoding="utf-8")


def test_yaml_writeback_counts_only_changed_and_refuses_noop(repo):
    g = Gateway(repo, runner=Runner())
    c = g.propose_yaml_params("apps/x/app.yaml", {"kp": 0.5}, "写回")
    assert "改 1 项" in c["title"]
    g.decide(c["id"], False)
    import re as _re
    cur = float(_re.search(r"name:\s*kp\b[^}]*default:\s*([-\d.eE+]+)", (repo / "apps/x/app.yaml").read_text(encoding="utf-8"))[1])
    with pytest.raises(GatewayError) as e:
        g.propose_yaml_params("apps/x/app.yaml", {"kp": cur}, "写回")
    assert e.value.code == "no_change"


def test_edit_miss_gives_closest_lines(repo):
    """aider find_similar_lines：search 差一点时把最像的原文回给模型；replace 已在文件里时直说。"""
    (repo / "apps/x/b.c").write_text("a();\nb();\nint gain = 1;\nc();\nd();\n", encoding="utf-8")
    g = Gateway(repo, runner=Runner())
    with pytest.raises(GatewayError) as e:
        g.propose_edit("apps/x/b.c", "b();\nint gain = 1 ;\nc();", "b();\nint gain = 3;\nc();", "r")
    assert "int gain = 1;" in e.value.fix and "没有找到" in e.value.message
    with pytest.raises(GatewayError) as e:
        g.propose_edit("apps/x/main.c", "int gainz = 9;", "int other = 2;", "r")
    assert "已经在" in e.value.fix
