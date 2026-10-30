"""Agent 评测一键运行：真大模型 × 仿真板 × 评测集，重复 N 次出打分报告（JSON + Markdown）。

    python -m dzbench.agent.evalrun                 # 用 Agent 设置里的模型（或环境变量 DZBENCH_API_KEY）
    python -m dzbench.agent.evalrun --repeat 3 --ports sim:car_2wd,sim:2026H_ball
    DZBENCH_BASE_URL=… DZBENCH_MODEL=… DZBENCH_API_KEY=… python -m dzbench.agent.evalrun   # 任一 OpenAI 兼容服务/中转站
    python -m dzbench.agent.evalrun --replay tests/fixtures/agent_evals/<模型>.json        # 离线：拿录好的对话按当前评分规则重评（不要 Key）

退出码：0 全过；1 有失败；2 没配模型 / 中途退回离线（这次结果不算大模型成绩）。
报告默认写到 ~/.dzbench/evals/<时间>/report.{json,md}；Key 不进报告。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict

from . import evals
from . import llm as llm_mod

DEFAULT_PORTS = ("sim:car_2wd", "sim:2026H_ball")  # 快速默认；全部仿真对象：--ports all


def summarize(runs: list[dict], meta: dict) -> dict:
    """runs: [{"port", "rep", "id", "ok", "why", "calls", "mode", "text"}] → 报告。纯函数，方便测试。"""
    by_case = defaultdict(list)
    for r in runs:
        by_case[r["id"]].append(r)
    cases = []
    for cid, rs in by_case.items():
        why = sorted({w for r in rs for w in r["why"]})
        cases.append({"id": cid, "passed": sum(r["ok"] for r in rs), "total": len(rs), "why": why,
                      **{k: round(sum(r.get(k, 0) for r in rs) / len(rs), 1) for k in ("turns", "cards", "seconds", "tokens")}})
    modes = sorted({r["mode"] for r in runs})
    n_ok = sum(r["ok"] for r in runs)
    valid = modes == ["llm"]
    avg = {k: round(sum(r.get(k, 0) for r in runs) / len(runs), 1) if runs else 0 for k in ("turns", "seconds", "tokens")}
    cat = {c["id"]: c.get("category", "other") for c in evals.load()}
    by_cat: dict = {}
    for r in runs:
        k = by_cat.setdefault(cat.get(r["id"], "other"), {"passed": 0, "total": 0})
        k["passed"] += bool(r["ok"]); k["total"] += 1
    for k in by_cat.values():
        k["rate"] = round(k["passed"] / k["total"], 3)
    return {"meta": meta, "valid": bool(valid), "categories": by_cat, "modes": modes, "passed": n_ok, "total": len(runs), "avg": avg,
            "score": round(n_ok / len(runs), 3) if runs else 0.0, "cases": cases, "runs": runs}


def to_markdown(rep: dict) -> str:
    m = rep["meta"]
    L = [f"# Agent 评测报告 {m['started']}", "",
         f"- 模型：{m['model']}（{m['provider']}）",
         f"- 板：{', '.join(m['ports'])}；每例重复 {m['repeat']} 次；用时 {m['seconds']:.0f} s",
         f"- **总分 {rep['passed']}/{rep['total']} = {rep['score']:.0%}**；每例平均 {rep['avg']['turns']} 次工具调用、"
         f"{rep['avg']['seconds']} s、{rep['avg']['tokens']:.0f} token", ""]
    if rep.get("categories"):
        L += ["| 类别 | 通过 | 通过率 |", "|---|---|---|"] + [
            f"| {evals.CATEGORIES.get(k, k)} | {v['passed']}/{v['total']} | {v['rate']:.0%} |" for k, v in sorted(rep["categories"].items())] + [""]
    if not rep["valid"]:
        L += ["> ⚠ 本次有回合退回了离线助手（模式：" + "/".join(rep["modes"]) + "），**不能当大模型成绩**。检查 Key / 网络 / 额度。", ""]
    L += ["| 用例 | 通过 | 工具调用 | 确认卡 | 秒 | token | 失败原因 |", "|---|---|---|---|---|---|---|"]
    for c in rep["cases"]:
        L.append(f"| {c['id']} | {c['passed']}/{c['total']} | {c['turns']} | {c['cards']} | {c['seconds']} | {c['tokens']:.0f} | {'；'.join(c['why']) or ''} |")
    L += ["", "用例含义见 `app/sidecar/dzbench/agent/evals.json`；评分规则见 `evals.grade`。大模型有随机性，看通过率，不看单次。"]
    return "\n".join(L) + "\n"


def main(argv=None, llm=None, run_sim=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dzbench.agent.evalrun")
    ap.add_argument("--ports", default=",".join(DEFAULT_PORTS), help="逗号分隔；all = 所有能仿真的工程（apps/ 与 examples/ 下有 sim_setup.c 的）")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--only", default="", help="只跑这些用例 id，逗号分隔")
    ap.add_argument("--out", default="", help="报告目录（默认 ~/.dzbench/evals/<时间>）")
    ap.add_argument("--replay", default="", help="不连模型：读一份录好的 report.json，按当前评测集重新打分")
    a = ap.parse_args(argv)
    if a.replay:
        return replay(a.replay)
    run_sim = run_sim or evals.run_sim
    if a.ports.strip() == "all":
        from .. import ports as ports_mod
        a.ports = ",".join(f"sim:{n}" for n in ports_mod.sim_apps())

    cfg = llm_mod.load_config()
    if llm is None:
        if not cfg.get("api_key") and cfg.get("provider") != "ollama":
            print("没有配置大模型 Key：在工作台 Agent 设置里填，或 export DZBENCH_API_KEY=…（只在本机）。", file=sys.stderr)
            return 2
        llm = llm_mod.build(cfg | {"failover": False})   # 评测只测云端这个模型：断一次就切本地并一直用本地会让后面整批用例作废（v7 GLM 15/29 例）

    cases = evals.load()
    if a.only:
        want = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in want]
    ports = [p for p in a.ports.split(",") if p]
    started = time.strftime("%Y-%m-%d_%H%M%S")
    t0, runs = time.monotonic(), []
    for port in ports:
        for rep in range(a.repeat):
            print(f"== {port} 第 {rep + 1}/{a.repeat} 轮")
            for r in run_sim(port, llm=llm, cases=cases):
                runs.append({"port": port, "rep": rep} | r)
    meta = {"started": started, "ports": ports, "repeat": a.repeat,
            "provider": cfg.get("provider", ""), "model": getattr(llm, "name", "") or cfg.get("model", ""),
            "seconds": time.monotonic() - t0}
    rep = summarize(runs, meta)

    import pathlib
    from ..snapshots import base_dir
    out = pathlib.Path(a.out) if a.out else base_dir() / "evals" / started
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(to_markdown(rep), encoding="utf-8")
    print(f"\n总分 {rep['passed']}/{rep['total']} = {rep['score']:.0%}  报告：{out / 'report.md'}")
    if not rep["valid"]:
        print("⚠ 有回合退回了离线助手，这次不算大模型成绩。", file=sys.stderr)
        return 2
    return 0 if rep["passed"] == rep["total"] else 1


def run_bench(model: str | None = None, base_url: str | None = None, ports=DEFAULT_PORTS, repeat: int = 1,
              only: list[str] | None = None, out: str | None = None, replay_from: str | None = None) -> dict:
    """稳定入口（make bench 调这个）：跑评测集，返回报告 dict（含 score / categories / cases）。
    Key 只从环境（DZBENCH_API_KEY）或 Agent 设置读，不经参数，不进报告。replay_from=录好的 report.json → 离线复评，不连模型。"""
    import os
    if replay_from:
        return rescore(replay_from)
    if model:
        os.environ["DZBENCH_MODEL"] = model
    if base_url:
        os.environ["DZBENCH_BASE_URL"] = base_url
    import pathlib
    import tempfile
    o = out or tempfile.mkdtemp(prefix="dzbench-bench-")
    argv = ["--ports", ",".join(ports), "--repeat", str(repeat), "--out", o] + (["--only", ",".join(only)] if only else [])
    rc = main(argv)
    p = pathlib.Path(o) / "report.json"
    rep = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"valid": False}
    return rep | {"rc": rc, "out": o}


def rescore(path: str) -> dict:
    old = json.loads(open(path, encoding="utf-8").read())
    cases = {c["id"]: c for c in evals.load()}
    runs = [r | dict(zip(("ok", "why"), evals.grade(cases[r["id"]], r["transcript"])))
            for r in old["runs"] if r["id"] in cases and "transcript" in r]
    return summarize(runs, old["meta"])


def replay(path: str) -> int:
    """离线复评：录下的对话（transcript）× 当前 evals.json 规则 → 分数。改了评分规则/用例后不花钱就能看影响。"""
    old = json.loads(open(path, encoding="utf-8").read())
    cases = {c["id"]: c for c in evals.load()}
    runs = []
    for r in old["runs"]:
        if r["id"] in cases and "transcript" in r:
            ok, why = evals.grade(cases[r["id"]], r["transcript"])
            runs.append(r | {"ok": ok, "why": why})
    rep = summarize(runs, old["meta"])
    print(to_markdown(rep))
    return 0 if rep["passed"] == rep["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
