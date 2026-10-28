"""Agent 评测一键运行：真大模型 × 仿真板 × 评测集，重复 N 次出打分报告（JSON + Markdown）。

    python -m dzbench.agent.evalrun                 # 用 Agent 设置里的模型（或环境变量 DZBENCH_API_KEY）
    python -m dzbench.agent.evalrun --repeat 3 --ports sim:car_2wd,sim:2026H_ball
    python -m dzbench.agent.evalrun --offline       # 只跑离线规则助手（对照组，不要 Key）

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

DEFAULT_PORTS = ("sim:car_2wd", "sim:2026H_ball")


def summarize(runs: list[dict], meta: dict) -> dict:
    """runs: [{"port", "rep", "id", "ok", "why", "calls", "mode", "text"}] → 报告。纯函数，方便测试。"""
    by_case = defaultdict(list)
    for r in runs:
        by_case[r["id"]].append(r)
    cases = []
    for cid, rs in by_case.items():
        why = sorted({w for r in rs for w in r["why"]})
        cases.append({"id": cid, "passed": sum(r["ok"] for r in rs), "total": len(rs), "why": why})
    modes = sorted({r["mode"] for r in runs})
    n_ok = sum(r["ok"] for r in runs)
    valid = meta.get("offline") or modes == ["llm"]
    return {"meta": meta, "valid": bool(valid), "modes": modes, "passed": n_ok, "total": len(runs),
            "score": round(n_ok / len(runs), 3) if runs else 0.0, "cases": cases, "runs": runs}


def to_markdown(rep: dict) -> str:
    m = rep["meta"]
    L = [f"# Agent 评测报告 {m['started']}", "",
         f"- 模型：{m['model']}（{m['provider']}）" if not m.get("offline") else "- 模型：离线规则助手（对照组）",
         f"- 板：{', '.join(m['ports'])}；每例重复 {m['repeat']} 次；用时 {m['seconds']:.0f} s",
         f"- **总分 {rep['passed']}/{rep['total']} = {rep['score']:.0%}**", ""]
    if not rep["valid"]:
        L += ["> ⚠ 本次有回合退回了离线助手（模式：" + "/".join(rep["modes"]) + "），**不能当大模型成绩**。检查 Key / 网络 / 额度。", ""]
    L += ["| 用例 | 通过 | 失败原因 |", "|---|---|---|"]
    for c in rep["cases"]:
        L.append(f"| {c['id']} | {c['passed']}/{c['total']} | {'；'.join(c['why']) or ''} |")
    L += ["", "用例含义见 `app/sidecar/dzbench/agent/evals.json`；评分规则见 `evals.grade`。大模型有随机性，看通过率，不看单次。"]
    return "\n".join(L) + "\n"


def main(argv=None, llm=None, run_sim=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dzbench.agent.evalrun")
    ap.add_argument("--ports", default=",".join(DEFAULT_PORTS))
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--only", default="", help="只跑这些用例 id，逗号分隔")
    ap.add_argument("--out", default="", help="报告目录（默认 ~/.dzbench/evals/<时间>）")
    ap.add_argument("--offline", action="store_true", help="跑离线规则助手当对照组")
    a = ap.parse_args(argv)
    run_sim = run_sim or evals.run_sim

    cfg = llm_mod.load_config()
    if a.offline:
        from .offline import OfflineAssistant
        llm = OfflineAssistant()
    elif llm is None:
        if not cfg.get("api_key") and cfg.get("provider") != "ollama":
            print("没有配置大模型 Key：在工作台 Agent 设置里填，或 export DZBENCH_API_KEY=…（只在本机）。"
                  "想先看对照组：加 --offline。", file=sys.stderr)
            return 2
        llm = llm_mod.OpenAICompat(cfg)

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
    meta = {"started": started, "ports": ports, "repeat": a.repeat, "offline": a.offline,
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


if __name__ == "__main__":
    sys.exit(main())
