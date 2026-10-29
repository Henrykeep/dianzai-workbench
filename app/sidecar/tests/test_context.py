"""Agent 上下文：仓库地图（按 git 状态缓存）、按触发词加载知识、人接受后才写的项目记忆。"""
import subprocess

from agentfake import FakeLLM
from dzbench.agent import codemap, knowledge
from dzbench.agent.gateway import Gateway
from dzbench.agent.loop import AgentLoop


def git(r, *a):
    subprocess.run(["git", *a], cwd=r, check=True, capture_output=True)


def mk(tmp_path):
    r = tmp_path / "repo"
    (r / "firmware/algo/pid").mkdir(parents=True)
    (r / "apps/car").mkdir(parents=True)
    (r / "docs/agent-knowledge").mkdir(parents=True)
    (r / "firmware/algo/pid/pid.h").write_text("#ifndef PID_H\n#define PID_H\ntypedef struct { float kp; } pid_t;\n"
                                               "float pid_update(pid_t *p, float e);\n#endif\n")
    (r / "firmware/algo/pid/pid.c").write_text('#include "pid.h"\nfloat pid_update(pid_t *p, float e)\n{\n  return p->kp * e;\n}\n')
    (r / "apps/car/main.c").write_text('#include "pid.h"\nstatic pid_t g;\nvoid loop_step(void)\n{\n  pid_update(&g, 1.0f);\n}\n')
    (r / "apps/car/tool.py").write_text("LIMIT = 3\n\n\nclass Car:\n    def drive(self):\n        pass\n\n\ndef helper():\n    return 1\n")
    (r / "docs/agent-knowledge/stall.md").write_text("---\ntriggers: 堵转, Stall\n---\n堵转判据：负载高且速度近零。\n")
    (r / "docs/agent-knowledge/README.md").write_text("# 无触发词的说明文件\n")
    git(r, "init", "-q"); git(r, "add", "."); git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i")
    return r


def test_codemap_defs_rank_and_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DZBENCH_HOME", str(tmp_path / "home"))
    r = mk(tmp_path)
    t = codemap.tags(r)
    names = {n for _, n, _ in t["files"]["firmware/algo/pid/pid.h"]["defs"]}
    assert {"pid_t", "pid_update"} <= names and "PID_H" not in names
    assert {n for _, n, _ in t["files"]["apps/car/tool.py"]["defs"]} == {"LIMIT", "Car", "drive", "helper"}
    ranked = [f for f, _ in codemap.rank(t)]
    assert ranked.index("firmware/algo/pid/pid.h") < ranked.index("apps/car/main.c")   # 被引用的排前面
    assert codemap.rank(t, "helper")[0][0] == "apps/car/tool.py"                         # focus 生效
    assert len(list((tmp_path / "home/codemap").glob("*.json"))) == 1
    assert codemap.tags(r)["key"] == t["key"]                                           # 命中缓存
    (r / "apps/car/main.c").write_text("void other(void)\n{\n}\n")                      # 工作区一改，键就变
    assert codemap.cache_key(r) != t["key"]
    assert "pid_update" in codemap.render(r, max_chars=400)


def test_knowledge_triggers_once_per_conversation(tmp_path):
    r = mk(tmp_path)
    items = knowledge.load(r)
    assert [k["name"] for k in items] == ["stall.md"]
    seen = set()
    assert knowledge.match("电机STALL了", items, seen)[0]["body"].startswith("堵转判据")
    assert knowledge.match("又堵转了", items, seen) == []
    fake = FakeLLM([{"role": "assistant", "content": "好"}])
    lp = AgentLoop(fake, {}, knowledge=lambda text: knowledge.match(text, items, set()))
    lp.ask("左轮堵转怎么办")
    assert "[工作台知识 stall.md" in fake.seen[0][0][-1]["content"]


def test_memory_needs_accept(tmp_path):
    r = mk(tmp_path)

    def run(cmd, cwd):
        if cmd[0] == "git":
            p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
            return p.returncode, p.stdout + p.stderr
        return 0, "ok"
    gw = Gateway(r, runner=run)
    card = knowledge.propose_memory(gw, "左电机编码器方向反，已在 board.yaml 取反", "实测")
    assert knowledge.memory_text(r) == ""                       # 只是提议，没写
    lp = AgentLoop(FakeLLM([]), {}, memory=lambda: knowledge.memory_text(r))
    res = gw.decide(card["id"], True)
    assert res["status"] == "committed", gw.changes[card["id"]].log
    assert "编码器方向反" in knowledge.memory_text(r)
    assert "编码器方向反" not in lp.messages[0]["content"]
    lp.reset()                                                   # 新对话才进系统提示
    assert "编码器方向反" in lp.messages[0]["content"]
