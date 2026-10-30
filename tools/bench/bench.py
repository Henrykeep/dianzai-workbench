#!/usr/bin/env python3
"""端到端基准（make bench）：每道题在 host-sim 仿真板上走 构建+连接 → 默认参数阶跃 →（可选）PID 清零继电起步并采纳 → 阶跃 → 验收评分。

只调用产品里现有的那一套（Session / AgentService.run_step_test / run_relay_tune / accept.accept_eval），
题目差异全在 cases.json 和 dzbench.json 的 step_tests 里。输出：stdout 表 + build/bench/results.{json,md}。

评分（每题 100 分）：连上并出遥测 10；阶跃指标有效 10；验收通过 40；超调 20（0%→20，≥50%→0 线性）；
调节时间 20（≤ t_max/3 满分，≥ t_max 0 分，线性）。总分 = 各题平均。跑一次约 1~2 分钟。
"""
from __future__ import annotations
import argparse, json, math, os, pathlib, re, subprocess, sys, tempfile, time

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app/sidecar"))
os.environ.setdefault("DZBENCH_HOME", tempfile.mkdtemp(prefix="dzbench-bench-"))

from dzbench.accept import accept_eval  # noqa: E402
from dzbench.agent.service import AgentService  # noqa: E402
from dzbench.agent_api import AgentTools  # noqa: E402
from dzbench.session import Session  # noqa: E402


def _wait(cond, t=60.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _lin(x, good, bad):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.0
    return max(0.0, min(1.0, (bad - x) / (bad - good))) if bad != good else float(x <= good)


def step(svc, s, st, acc, csv=None):
    r = svc.run_step_test()
    m = r["metrics"]
    hold, pre = float(st.get("hold_s", 1.5)), float(st.get("pre_s", 0.6))
    w = s.window(hold + pre * 0.5)
    t = [a for a, _ in w]; y = [float(v[st["y"]]) for _, v in w]; sp = [float(v[st["sp"]]) for _, v in w]
    if csv:
        csv.write_text("t_s,sp,y\n" + "".join(f"{a:.4f},{b:.6g},{c:.6g}\n" for a, b, c in zip(t, sp, y)))
    a = accept_eval(t, y, sp, acc) or {"pass": False, "why": "数据太少", "total": math.nan}
    return m, a


def score(link, m, a, acc):
    tmax = float(acc.get("t_max_s", 2.0))
    parts = {"link": 10.0 * link, "metrics": 10.0 * bool(m and m.get("ok")), "accept": 40.0 * bool(a and a["pass"]),
             "overshoot": 20.0 * _lin(m.get("overshoot_pct") if m and m.get("ok") else None, 0.0, 50.0),
             "settling": 20.0 * _lin(m.get("settling_s") if m and m.get("ok") else None, tmax / 3, tmax)}
    return round(sum(parts.values()), 1), {k: round(v, 1) for k, v in parts.items()}


def flow(p, out, journey):
    """按真实队伍从拿题到封箱的全过程（journey.yaml）逐阶段记：工作台是否支持、本次是否由基准无人值守完成、要人做什么。
    auto_if 指向的阶段真跑通了才算 auto；其余支持但没跑的算 human，不支持的算 0（uncovered）；用例声明的 na 不计入分母。"""
    st, na = out["stages"], p.get("na") or {}
    ok = {"build_link": st.get("build_link", {}).get("ok"), "relay": (st.get("relay") or {}).get("ok"), "default_step": "default_step" in st}
    steps = []
    for j in journey:
        if j["stage"] in na:
            mode, note = "na", na[j["stage"]]
        elif j["support"] == "none":
            mode, note = "uncovered", j.get("human", "")
        elif ok.get(j.get("auto_if")):
            mode, note = "auto", j.get("where", "")
        else:
            mode, note = "human", j.get("human", "")
        steps.append({"stage": j["stage"], "support": j["support"], "mode": mode, "note": note})
    n_auto = sum(x["mode"] == "auto" for x in steps); n_app = sum(x["mode"] != "na" for x in steps)
    return {"steps": steps, "auto": n_auto, "applicable": n_app, "ratio": round(n_auto / max(1, n_app), 3)}


def _case_src(p):
    return ROOT / (p.get("src") or (f"apps/{p['app']}" if (ROOT / "apps" / p["app"]).is_dir() else f"examples/{p['app']}"))


def readiness(p, items, out_dir):
    """脱机就绪：工程源码里有没有对应调用；“自测留数据”看基准是否把阶跃原始数据存了档。"""
    src = _case_src(p)
    text = "\n".join(f.read_text(errors="replace") for f in src.rglob("*.c"))
    res = [{"item": it["item"], "ok": (out_dir / f"{p['id']}.csv").exists() if it.get("bench") else bool(re.search(it["uses"], text))}
           for it in items]
    return {"items": res, "ok": sum(x["ok"] for x in res), "n": len(res)}


def _sloc(path):
    try:
        return sum(1 for ln in path.read_text(errors="replace").splitlines() if ln.strip() and not ln.strip().startswith("//"))
    except OSError:
        return 0


def reuse(p):
    """复用率 = 复用模块代码行 /（复用 + 本工程专用代码行），按这次仿真构建真正编进去的源文件（编译器 .d 依赖）统计。
    复用 = firmware/、apps/include/、ports/；专用 = 工程目录里除仿真对象模型以外的；生成的（build/）和仿真对象模型单列不计入比值。
    注意：按文件计，模块里没调用到的函数也算在内。"""
    src = _case_src(p)
    plant = [(src / x).resolve() for x in p.get("plant_files") or []]
    files = set()
    for d in (ROOT / "build/host-sim" / p["app"]).rglob("*.d"):
        txt = d.read_text(errors="replace").replace("\\\n", " ")
        for tok in txt.split()[1:]:
            if tok.endswith((".c", ".h")):
                q = (ROOT / tok).resolve() if not tok.startswith("/") else pathlib.Path(tok).resolve()
                files.add(q)
    cat = {"reused": 0, "case": 0, "plant": 0, "generated": 0}
    for f in files:
        try:
            rel = f.relative_to(ROOT.resolve())
        except ValueError:
            continue                                              # 系统头文件
        n = _sloc(f)
        if any(f == x or x in f.parents for x in plant):
            cat["plant"] += n
        elif f.is_relative_to(src.resolve()):
            cat["case"] += n
        elif rel.parts[0] == "build":
            cat["generated"] += n
        elif rel.parts[0] in ("firmware", "ports") or rel.as_posix().startswith("apps/include/"):
            cat["reused"] += n
    base = cat["reused"] + cat["case"]
    return {**cat, "ratio": round(cat["reused"] / base, 3) if base else None, "src": src.relative_to(ROOT).as_posix()}


def run_problem(p, cfg, journey, out_dir):
    st = cfg["step_tests"][p.get("experiment") or p["app"]]
    acc = p["accept"]
    out = {"id": p["id"], "kind": p.get("kind", "project"), "title": p["title"], "app": p["app"], "stages": {}}
    (out_dir / f"{p['id']}.csv").unlink(missing_ok=True)
    t0 = time.monotonic()
    s = Session()
    try:
        s.connect(f"sim:{p['app']}")                       # 侧车自动 make BOARD=host-sim APP=...（构建 + 连接）
        link = _wait(lambda: s.schema and len(s.window(0.5)) > 5)
        out["stages"]["build_link"] = {"ok": bool(link), "s": round(time.monotonic() - t0, 1)}
        if not link:
            raise RuntimeError("仿真板没起来或没遥测")
        time.sleep(1.0)
        svc = AgentService(s, AgentTools(s, lambda e: None), lambda e: None)
        m, a = step(svc, s, st, acc, out_dir / f"{p['id']}.csv")
        out["stages"]["default_step"] = {"metrics": m, "accept": a}
        if p.get("tune") == "relay":
            names = st.get("gains") or {}
            for k in names.values():
                s.set_param(k, 0.0)                         # “PID 全是 0”起步
            time.sleep(0.3)
            r = svc.run_relay_tune()
            out["stages"]["relay"] = {k: r.get(k) for k in ("ok", "ku", "pu", "cycles", "gains", "why", "reason")}
            if r.get("ok"):
                for k in ("kp", "ki", "kd"):
                    if names.get(k):
                        s.set_param(names[k], float(r["gains"][k]), verify=True)   # 相当于用户点“采纳”
                time.sleep(0.5)
                m, a = step(svc, s, st, acc, out_dir / f"{p['id']}.csv")
                out["stages"]["tuned_step"] = {"metrics": m, "accept": a}
            else:
                m, a = {"ok": False}, {"pass": False, "why": "继电起步失败"}
        out["score"], out["parts"] = score(link, m, a, acc)
        out["final"] = {"overshoot_pct": m.get("overshoot_pct"), "settling_s": m.get("settling_s"),
                        "pass": a["pass"], "why": a.get("why", "")}
    except Exception as e:  # noqa: BLE001
        out.setdefault("score", 0.0); out["error"] = f"{type(e).__name__}: {e}"
        out.setdefault("parts", {}); out.setdefault("final", {"pass": False, "why": out["error"]})
    finally:
        try:
            s.disconnect()
        except Exception:  # noqa: BLE001
            pass
    out["automation"] = flow(p, out, journey["stages"])
    out["readiness"] = readiness(p, journey["readiness"], out_dir)
    out["reuse"] = reuse(p)
    out["elapsed_s"] = round(time.monotonic() - t0, 1)
    return out


def _f(x, fmt="{:.2f}"):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else fmt.format(x)


def advice(r):
    """失败用例的通用建议（只看指标，不看是哪道题）。"""
    if r.get("error"):
        return f"先修运行错误：{r['error']}（本地 make BOARD=host-sim APP={r['app']} run 复现）"
    m = (r["stages"].get("tuned_step") or r["stages"].get("default_step") or {}).get("metrics") or {}
    if not m.get("ok"):
        return "阶跃实验无有效指标：检查 dzbench.json step_tests 的 y/sp 通道和 hold_s"
    if m.get("overshoot_pct", 0) > 20:
        return f"超调 {m['overshoot_pct']:.0f}%：降比例增益或加微分；可先试“无初值一键起步”（step_tests 加 relay）"
    if m.get("settling_s") is None:
        return "限时内没稳定：加积分消静差，或加长 hold_s 确认是否只是慢"
    return "到位后误差超带：检查静差/量化，必要时放宽 accept.band 并写明依据"


def table(res):
    rows = ["| 用例 | 类型 | 分数 | 验收 | 超调 % | 调节 s | AI 自动化 | 复用率 | 脱机就绪 | 说明 |", "|---|---|---:|---|---:|---:|---:|---:|---:|---|"]
    for r in res["problems"]:
        f, a, u = r["final"], r["automation"], r["reuse"]
        rows.append(f"| {r['id']} | {r.get('kind', '')} | {r['score']:.1f} | {'✓' if f.get('pass') else '✗'} | "
                    f"{_f(f.get('overshoot_pct'), '{:.1f}')} | {_f(f.get('settling_s'))} | {a['auto']}/{a['applicable']} = {a['ratio']:.0%} | "
                    f"{_f(u['ratio'], '{:.0%}')}（{u['reused']}/{u['reused'] + u['case']} 行） | {r['readiness']['ok']}/{r['readiness']['n']} | {f.get('why') or ''} |")
    rows.append(f"| **平均** | | **{res['total']:.1f}** | {res['passed']}/{len(res['problems'])} | | | {res['auto_ratio']:.0%} | {_f(res['reuse_ratio'], '{:.0%}')} | | |")
    rows.append("")
    rows += ["", "## 全流程覆盖（✓AI 自动 · 人=要人做 · 0=工作台未覆盖 · —不适用；表头 *=工作台仅部分支持）", "",
             "| 用例 | " + " | ".join(x["stage"] + ("*" if x["support"] == "partial" else "") for x in res["problems"][0]["automation"]["steps"]) + " |",
             "|---|" + "---|" * len(res["problems"][0]["automation"]["steps"])]
    sym = {"auto": "✓", "human": "人", "uncovered": "0", "na": "—"}
    rows += [f"| {r['id']} | " + " | ".join(sym[x["mode"]] for x in r["automation"]["steps"]) + " |" for r in res["problems"]]
    rows.append("")
    rows.append("需要人的步骤：" + "；".join(f"{r['id']}：" + "、".join(x["stage"] for x in r["automation"]["steps"] if x["mode"] == "human") for r in res["problems"]))
    rows += ["", "脱机就绪缺项：" + "；".join(f"{r['id']}：" + ("、".join(x["item"] for x in r["readiness"]["items"] if not x["ok"]) or "无")
                                          for r in res["problems"]), ""]
    rows.append("复用率按仿真构建实际编译的源文件计（host-sim 会编进整个模块库，所以是上限）；仿真对象模型和生成代码不计入。")
    bad = [r for r in res["problems"] if not r["final"].get("pass")]
    rows += ["", "## 未通过与建议", ""] + ([f"- **{r['id']}**：{r['final'].get('why') or '未通过'} → {advice(r)}" for r in bad] or ["- 无"])
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", help="只跑这些题 id")
    ap.add_argument("--out", default=str(ROOT / "build/bench"))
    ap.add_argument("--baseline", help="对比用的上一次 results.json")
    args = ap.parse_args()
    spec = json.loads((ROOT / "tools/bench/cases.json").read_text())
    probs = spec["cases"]
    journey = yaml.safe_load((ROOT / "tools/bench/journey.yaml").read_text())
    probs = [p for p in probs if not args.only or p["id"] in args.only]
    cfg = json.loads((ROOT / "dzbench.json").read_text())
    rev = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip())
    res = {"commit": rev + ("-dirty" if dirty else ""), "time": time.strftime("%Y-%m-%d %H:%M:%S %z"), "problems": []}
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    for p in probs:
        print(f"… {p['id']} {p['title']}", flush=True)
        res["problems"].append(run_problem(p, cfg, journey, out))
    res["total"] = round(sum(r["score"] for r in res["problems"]) / max(1, len(res["problems"])), 1)
    res["auto_ratio"] = round(sum(r["automation"]["ratio"] for r in res["problems"]) / max(1, len(res["problems"])), 3)
    rr = [r["reuse"]["ratio"] for r in res["problems"] if r["reuse"]["ratio"] is not None]
    res["reuse_ratio"] = round(sum(rr) / len(rr), 3) if rr else None
    res["passed"] = sum(bool(r["final"].get("pass")) for r in res["problems"])
    md = f"# make bench @ {res['commit']}（{res['time']}）\n\n" + table(res) + "\n"
    if args.baseline and pathlib.Path(args.baseline).exists():
        b = {r["id"]: r["score"] for r in json.loads(pathlib.Path(args.baseline).read_text())["problems"]}
        md += "\n对比基线：" + "，".join(f"{r['id']} {r['score'] - b[r['id']]:+.1f}" for r in res["problems"] if r["id"] in b) + "\n"
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    (out / "results.md").write_text(md)
    print(md); print(f"→ {out}/results.json, results.md")


if __name__ == "__main__":
    main()
