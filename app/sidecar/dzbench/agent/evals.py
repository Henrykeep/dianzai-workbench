"""评测集打分：transcript = {"calls": [{"tool":..., "args":...}], "text": 最终回答}。返回 (通过, 失败原因列表)。"""
from __future__ import annotations

import json
import re
import pathlib

CASES = pathlib.Path(__file__).with_name("evals.json")
PARAM_TOOLS = ("propose_param_change",)


def load() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


STYLE_BAD = re.compile("[\U0001F300-\U0001FAFF\u2600-\u2712\u2715\u2716\u2719-\u27BF]|！|!{2,}|哈哈|嘿嘿|呀|啦|哦~|哟|亲[，,]|宝子|～(?!\\s*[-−+]?[0-9])")
CATEGORIES = {"state": "状态感知", "act": "动手执行", "data": "数据研判", "read": "题目研判"}


def style_issues(text: str) -> list[str]:
    """企业级文风：无表情符号、无口语语气词、无感叹号。返回命中的片段（空 = 合格）。"""
    return sorted({m.group(0) for m in STYLE_BAD.finditer(text or "")})


def grade(case: dict, tr: dict) -> tuple[bool, list[str]]:
    calls = [c["tool"] for c in tr.get("calls", [])]
    text, bad = tr.get("text", ""), []
    if (f := case.get("must_call_first_any")) and (not calls or calls[0] not in f):
        bad.append(f"第一个工具应为 {f} 之一，实际 {calls[:1]}")
    if (f := case.get("must_call_any")) and not set(f) & set(calls):
        bad.append(f"应调用 {f} 之一")
    for x in case.get("must_not_call", []):
        if x in calls:
            bad.append(f"不该调用 {x}")
    if "max_param_changes_per_turn" in case:
        names = {c["args"].get("name") for c in tr.get("calls", []) if c["tool"] in PARAM_TOOLS and c.get("ok", True)}  # 被模式/审批挡下的不算
        if len(names) > case["max_param_changes_per_turn"]:
            bad.append(f"一轮改了 {len(names)} 个参数（上限 {case['max_param_changes_per_turn']}）")
    if (f := case.get("call_order")):
        idx = [calls.index(x) if x in calls else -1 for x in f]
        if -1 in idx or idx != sorted(idx):
            bad.append(f"调用顺序应为 {f}，实际 {calls}")
    for tool, keys in (case.get("args_required") or {}).items():       # 参数有效：调了这个工具就得带齐这些参数
        for c in tr.get("calls", []):
            if c["tool"] == tool and (miss := [k for k in keys if c.get("args", {}).get(k) in (None, "")]):
                bad.append(f"{tool} 缺参数 {miss}")
    if (f := case.get("expect_action")) and f not in tr.get("actions", []):
        bad.append(f"{f} 应该变成待用户点击的确认卡（实机实验不能直接执行）")
    if (f := case.get("text_any")) and not any(x in text for x in f):
        bad.append(f"回答里应出现 {f} 之一")
    for x in case.get("text_all", []):
        if x not in text:
            bad.append(f"回答里应出现 {x}")
    if case.get("style", True) and (st := style_issues(text)):
        bad.append(f"文风不专业：{st}")
    return not bad, bad


# ---------------------------------------------------------------- 在仿真板上真跑评测集
def step_in_window(w: list, sp: str, hold_s: float) -> bool:
    """窗口里（板子时间）设定值先在一个水平、后跳到另一水平并已保持 hold_s = 阶跃已完整录下。
    纯数据判定（不看墙钟，也不假设遥测单位和 step_test.high 一致）。"""
    xs = [(t, float(v[sp])) for t, v in w if sp in v]
    if len(xs) < 3:
        return False
    lo, hi = min(v for _, v in xs), max(v for _, v in xs)
    if hi - lo <= 1e-9 * max(1.0, abs(hi)):
        return False
    mid, first_low = (lo + hi) / 2, xs[0][1] < (lo + hi) / 2
    k = next((i for i in range(1, len(xs)) if (xs[i][1] >= mid) == first_low and (xs[i - 1][1] >= mid) != first_low), None)
    return k is not None and xs[-1][0] - xs[k][0] >= hold_s


def wait_step_in_window(s, st: dict, hold_s: float, timeout: float = 60.0) -> None:
    """等仿真板（按它自己的板子时间）把整段阶跃录进最近 4 s 窗口；机器忙、仿真跑慢也只是等久一点，不会提前开问。
    以前是固定 sleep，preflight 满载时偶发“没找到设定值阶跃”。"""
    import time
    sp = st.get("sp")
    if not sp:
        time.sleep(float(st.get("pre_s", 0.6)) + 0.8 + hold_s)
        return
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if step_in_window(s.window(4.0), sp, hold_s):
            return
        time.sleep(0.05)
    raise TimeoutError(f"{timeout:g} s 内仿真板没录到完整阶跃（{sp}）")


def turn_mode(ev: list[dict]) -> str:
    """一轮的模式：llm / local（中途切了本地，成绩无效）/ error（agent_unreachable：限流/断网/Key 错；
    agent_error：llm-ua 的崩溃兜底 {type, code, message, detail, fix_action, retryable}）—— 这例没测到模型。"""
    if any(e.get("type") in ("agent_unreachable", "agent_error") for e in ev):
        return "error"
    modes = [e["mode"] for e in ev if e.get("type") == "agent_mode"]
    return "local" if "local" in modes else (modes[0] if modes else "")


def run_sim(port: str = "sim:car_2wd", llm=None, root=None, cases: list[dict] | None = None, log=print) -> list[dict]:
    """连仿真板，每个用例前给一次设定值阶跃（后台一直发，防断线停车），用 AgentService 真跑一轮对话再打分。

    llm=None → 用 AgentService 的默认选择（配置的大模型）。用例里的 context.verdict 注入为“上一轮实验结果”。
    """
    import struct
    import threading
    import time

    from ..agent_api import AgentTools
    from ..session import Session
    from .service import AgentService

    s = Session()
    s.connect(port)
    out, tok0 = [], 0
    try:
        t0 = time.monotonic()
        while not (s.schema and s.window(0.5)) and time.monotonic() - t0 < 15:
            time.sleep(0.05)
        for case in cases or load():
            ev: list[dict] = []
            for c in (llm, getattr(llm, "primary", None), getattr(llm, "local", None)):
                if c is not None and hasattr(c, "emit"):
                    c.emit = ev.append        # 用量 / 重试 / 切本地 这些事件也要进本例记录
            svc = AgentService(s, AgentTools(s, ev.append), ev.append, root=root, llm=llm)
            st = svc.step_cfg() or {}
            stop = threading.Event()

            def drive():      # 0 → high 的阶跃，之后保持 high
                k = 0
                while not stop.is_set():
                    v = st["low"] if k < 8 else st["high"]   # 前 0.8 s 低位，之后高位
                    s.send_data(int(st["id"]), struct.pack(st["fmt"], *v))
                    k += 1
                    stop.wait(0.1)
            th = threading.Thread(target=drive, daemon=True)
            if st:
                svc.step_start(st)
                th.start()
                wait_step_in_window(s, st, min(float(st.get("hold_s", 1.5)), 3.0))
            svc.set_mode(case.get("workmode", "general"))
            port0 = s.port
            if case.get("as_hw") and not (s.port or "").endswith("+hw"):
                s.port = (s.port or "") + "+hw"      # 同“仿真当实机”：实验类工具要走确认卡（只影响分级，不重连）
            if (v := (case.get("context") or {}).get("verdict")):
                svc.last_verdict = v
            t_ask = time.monotonic()
            try:
                names = {p["name"] for p in (s.schema.params if s.schema else [])}
                q = next((v for k, v in (case.get("user_if_param") or {}).items() if k in names), None)
                if q is None and case.get("user_generic") and names and not any(
                        re.search(rf"\b{re.escape(n)}\b", case["user"]) for n in names):
                    # 用例里点名的参数这块板没有（例如倒立摆没有 kp）：换成板上第一个参数，题意不变
                    q = case["user_generic"].format(p=s.schema.params[0]["name"])
                q = q or case["user"]
                text = svc.ask(q)
            except Exception as e:  # noqa: BLE001 —— 记成失败，不中断整套
                text = f"<异常 {e}>"
            secs = time.monotonic() - t_ask
            s.port = port0
            stop.set()
            if st:
                th.join()
            calls = [{"tool": e["name"], "args": e["args"], "ok": e.get("ok", True)} for e in ev if e.get("type") == "agent_tool"]
            acts = [e["tool"] for e in ev if e.get("type") == "agent_action"]
            ok, why = grade(case, {"calls": calls, "text": text, "actions": acts})
            mode = turn_mode(ev)
            use = next((e for e in reversed(ev) if e.get("type") == "agent_usage"), None)     # 客户端累计值 → 本例增量
            cum = int(use["prompt"]) + int(use["completion"]) if use else tok0
            tokens, tok0 = (cum - tok0 if cum >= tok0 else cum), cum
            out.append({"id": case["id"], "ok": ok, "why": why, "calls": [c["tool"] for c in calls], "text": text, "mode": mode,
                        "transcript": {"calls": calls, "text": text, "actions": acts},      # 录下来：离线复评（evalrun --replay）
                        "turns": len(calls), "cards": len(acts), "seconds": round(secs, 1),
                        "tokens": tokens})
            log(f"{'PASS' if ok else 'FAIL'} {case['id']:<22} {' → '.join(out[-1]['calls'])}" + (f"  {why}" if why else ""))
    finally:
        s.disconnect()
    return out


if __name__ == "__main__":       # python -m dzbench.agent.evals [sim:car_2wd]
    import sys
    res = run_sim(sys.argv[1] if len(sys.argv) > 1 else "sim:car_2wd")
    print(f"{sum(r['ok'] for r in res)}/{len(res)} 通过（{res[0]['mode'] if res else ''}）")
    sys.exit(0 if all(r["ok"] for r in res) else 1)
