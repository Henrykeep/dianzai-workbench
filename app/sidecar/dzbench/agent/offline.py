"""离线规则助手：没填 API Key / 比赛现场没网时，“问 Agent”仍然可用。

它长得像一个 LLM（chat(messages, tools) → assistant message），但只按关键词识别意图、按固定剧本调工具、
用模板组织回答，所以和真 LLM 走同一个 AgentLoop：同一套工具白名单、风险分级、护栏、人工确认。
能力有限（只认常见几类问题），回答里会说明自己是离线规则；遇到认不出的问题就给出能问什么。
"""
from __future__ import annotations

import json
import re

from .untrusted import unwrap

NAME = "离线规则助手"

INTENTS = (   # 顺序即优先级
    ("estop", r"急停"),
    ("edit", r"(\.ya?ml|默认值|源码|代码).*(改|换|设)|(改|换|设).*(\.ya?ml|默认值)"),
    ("autotune", r"自动(调|整定)|一直调|调到(通过|达标)|连着调|autopilot"),
    ("score", r"评分项\s*[\w.-]+.*(跑|测|证据|回写)|回写评分|(跑|测).{0,6}(遍|次).*(证据|评分)"),
    ("hw", r"上车|实机|实板|真车|上板"),
    ("loss", r"跟丢|丢了|丢帧|丢线|掉线|信号断|没信号|传感器断"),
    ("sweep", r"扫频|带宽|频率响应|频响|bode|波特"),
    ("exp", r"(跑|做|来)一?(次|轮)?\s*阶跃"),
    ("project", r"项目|读题|赛题|导入工程|选方案|方案选型|资源分配|生成工程|评分项"),
    ("asym", r"不对称|上下不一样|正负不一样|四段"),
    ("result", r"结果|那轮|下一步|上一轮|这轮"),
    ("why", r"为什么|为啥|怎么回事|原因"),
    ("tune", r"超调|调好|调参|调一下|怎么调|太慢|跟不上|振荡|震荡|抖|稳态|响应|过冲|pid|PID|kp|ki|kd"),
)


# 改默认值时读多少个候选 app.yaml/project.yaml：曾是 12，仿真对象一多当前工程就被截掉（评测 edit_reads_first 失败）
MAX_READ = 48


def intent(text: str) -> str:
    for k, pat in INTENTS:
        if re.search(pat, text):
            return k
    return "overview"


def _call(i: int, name: str, args: dict | None = None) -> dict:
    return {"id": f"off{i}_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {}, ensure_ascii=False)}}


def _pct(v) -> str:
    return "—" if v is None else f"{v:.1f}%"


class OfflineAssistant:
    name = NAME

    # ------------------------------------------------------------ 协议
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        k = max(i for i, m in enumerate(messages) if m["role"] == "user")
        user, done = messages[k]["content"], {}
        steps = 0
        for m in messages[k + 1:]:
            if m["role"] == "assistant":
                steps += 1
            if m["role"] == "tool":
                try:
                    r = json.loads(unwrap(m["content"]).split("\n[工作台")[0])
                except ValueError:       # loop 把超长结果截断到 8000 字符
                    r = {"ok": False, "error": "工具结果太长被截断"}
                done.setdefault(m["tool_call_id"].split("_", 1)[1], []).append(r)
        calls = self.plan(intent(user), user, done, steps)
        if calls:
            return {"role": "assistant", "content": None, "tool_calls": [_call(steps, n, a) for n, a in calls]}
        return {"role": "assistant", "content": self.answer(intent(user), user, done)}

    @staticmethod
    def ok(done: dict, name: str):
        rs = done.get(name) or []
        return rs[-1]["result"] if rs and rs[-1].get("ok") else None

    @staticmethod
    def err(done: dict) -> str:
        for rs in done.values():
            for r in rs:
                if not r.get("ok"):
                    return r.get("error", "")
        return ""

    # ------------------------------------------------------------ 剧本：返回本步要调的工具，None = 该回答了
    def plan(self, it: str, user: str, done: dict, step: int):
        if it == "estop":
            return None
        if it == "edit":
            if step == 0:
                return [("list_params", {}), ("list_files", {"glob": "apps/*/app.yaml"}), ("list_files", {"glob": "examples/*/project.yaml"})]
            if step == 1:
                files = [f for r in done.get("list_files", []) if r.get("ok") for f in r["result"]]
                return [("read_file", {"path": f}) for f in files[:MAX_READ]] or None
            if step == 2 and (e := self._edit(user, done)):
                return [("propose_edit", e)]
            return None
        if it == "project":
            return self._project(user, done, step)
        if it == "autotune":                    # 仿真连跑到护栏通过；实机工具自己会拒绝（回答里讲怎么逐轮来）
            m = re.search(r"(\d+)\s*轮", user)
            return [("tune_autopilot", {"rounds": int(m.group(1)) if m else 6})] if step == 0 else None
        if it == "score":
            return self._score(user, done, step)
        if it in ("hw", "asym", "result"):
            if step == 0:
                return [("tune_context", {})]
            if step == 1 and it == "result":
                v = (self.ok(done, "tune_context") or {}).get("last_verdict") or {}
                st = v.get("steady") or {}
                if st and not st.get("steady") and st.get("reason") in ("still_drifting", "warming_up"):
                    return [("observe", {"reason": f"上一轮实验结束时还没稳（{st.get('reason')}），本轮不改参数"})]
                return [("run_step_test", {})]
            return None
        if it == "why":
            return [("read_telemetry", {"seconds": 3})] if step == 0 else None
        if it == "loss":
            return [("read_telemetry", {"seconds": 2})] if step == 0 else None
        if it == "sweep":       # 少几个频点：离线对照组只验证流程（实机要点确认卡）
            return [("run_sweep_test", {"n": 5})] if step == 0 else None
        if it == "exp":
            return [("run_step_test", {})] if step == 0 else None
        if it == "tune":
            if step == 0:
                return [("tune_context", {}), ("step_analysis", {})]
            if step == 1 and (p := self._pick(done)):
                return [("propose_param_change", p)]
            return None
        return [("read_telemetry", {"seconds": 2}), ("list_params", {})] if step == 0 else None

    def _project(self, user: str, done: dict, step: int):
        """项目推进剧本：看状态 → 下一步预览（只写暂存区）→ 预览通过就出“确认写入”卡。缺人给的输入就停下来问。"""
        if step == 0:
            return [("project_state", {})]
        code = self._code(user, done)
        if not code:
            return None
        if step == 1:
            return [("project_state", {"code": code})]
        st = (done.get("project_state") or [{}])[-1].get("result") or {}
        nxt, args = st.get("next_step"), {"code": code}
        if not nxt:
            return None
        if nxt == "req":
            if not (m := re.search(r"(\S+\.(?:pdf|txt))", user, re.I)):
                return None
            args["src"] = m.group(1)
        if nxt == "import":
            if not (m := re.search(r"((?:[A-Za-z]:)?[\\/][^\s，。]+)", user)):
                return None
            args["project"] = m.group(1)
        if step == 2 and nxt == "req":          # 有题目文件：一次把剩下各步全预览，出一张总确认卡
            return [("project_chain", args)]
        ch = self.ok(done, "project_chain")
        if step == 3 and ch:
            return [("project_apply", {"code": code})] if ch.get("to_write") else None
        if step == 2:
            return [("flow_preview", {"step": nxt, **args})]
        pv = self.ok(done, "flow_preview")
        if step == 3 and pv and not pv.get("rc"):
            return [("flow_accept", {"step": nxt, "code": code} | ({"name": pv["name"]} if pv.get("name") else {}))]
        return None

    def _score(self, user: str, done: dict, step: int):
        """评分剧本：看评分项 → 跑 N 次（band 只取评分项原文里 ≤/< 的那个数）→ 全过才出“存证据”卡；“回写”单独一句。"""
        m = re.search(r"评分项\s*([\w.-]+)", user)
        item = m.group(1) if m else None
        if "回写" in user:
            return [("score_writeback", {"item": item})] if step == 0 and item else None
        if step == 0:
            return [("score_items", {})]
        its = (self.ok(done, "score_items") or {}).get("items") or []
        it = next((x for x in its if x["id"] == item), None)
        if step == 1 and it:
            n = re.search(r"(\d+|[一二三四五六七八九十])\s*(遍|次|轮)", user)
            cn = "一二三四五六七八九十"
            k = (int(n.group(1)) if n.group(1).isdigit() else cn.index(n.group(1)) + 1) if n else 3
            args = {"item": item, "n": k}
            lim = next((x for x in it["metrics"] if x.get("op") in ("<=", "<") and isinstance(x.get("value"), (int, float))), None)
            if not it.get("accept") and not any(x.get("accept") for x in it["metrics"]) and lim:
                args["band"] = lim["value"]
            return [("score_run", args)]
        r = self.ok(done, "score_run")
        if step == 2 and r and r.get("result") == "pass":
            return [("score_save", {"item": item})]
        return None

    def _code(self, user: str, done: dict) -> str | None:
        ps = ((done.get("project_state") or [{}])[0].get("result") or {}).get("projects") or []
        hit = next((c for c in sorted(ps, key=len, reverse=True) if c in user), None)
        m = re.search(r"(?:项目|题号|赛题)\s*([A-Za-z0-9][\w-]*)", user)      # 新题：仓库里还没有这个目录
        return hit or (m.group(1) if m else None)

    def _pick(self, done: dict):
        """规则建议里的第一项，一轮只改一个参数；被证明变差的方向由护栏拒绝（错误会回到回答里）。"""
        a = self.ok(done, "step_analysis")
        if not a or not a["metrics"].get("ok"):
            return None
        for h in a["hints"]:
            for k, v in (h.get("changes") or {}).items():
                self.prop = {"name": k, "value": v, "reason": "离线规则：" + h["text"]}
                return self.prop
        return None

    def _edit(self, user: str, done: dict):
        m = re.search(r"([A-Za-z_]\w*)\s*(?:的)?\s*默认值?\s*(?:改|换|设)成?\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", user)
        if not m:
            return None
        name, val = m.group(1), m.group(2)
        board = {p["name"] for p in (self.ok(done, "list_params") or [])}
        row = re.compile(rf"^(\s*-\s*\{{[^}}]*\bname:\s*{re.escape(name)}\b[^}}]*\bdefault:\s*)(-?[\w.+-]+)", re.M)
        best = None
        for c in done.get("read_file", []):
            if not c.get("ok"):
                continue
            txt = c["result"]
            hit = row.search(txt)
            if hit:
                score = sum(bool(re.search(rf"\bname:\s*{re.escape(b)}\b", txt)) for b in board)
                if best is None or score > best[0]:
                    best = (score, txt, hit)
        if not best or (board and best[0] < len(board) / 2):
            return None            # 找不到，或找到的文件不是当前板子跑的工程（参数表对不上）：不乱改
        # read_file 结果里没有路径：按读取顺序对回 list_files
        files = [f for r in done.get("list_files", []) if r.get("ok") for f in r["result"]][:MAX_READ]
        idx = [c["result"] if c.get("ok") else None for c in done.get("read_file", [])].index(best[1])
        line = best[1][best[2].start():best[1].index("\n", best[2].start())]
        new = line[:best[2].end(1) - best[2].start()] + val + line[best[2].end(2) - best[2].start():]
        return {"path": files[idx], "search": line, "replace": new, "reason": f"按你的要求把 {name} 默认值改成 {val}"}

    # ------------------------------------------------------------ 回答模板
    def answer(self, it: str, user: str, done: dict) -> str:
        head = f"（{NAME}：没有大模型时按固定规则回答，能力有限）\n"
        hw = "待实板确认：仿真/离线结论 ≠ 实机；上车先低速、手放急停，电池电压和电机温度在正常范围再加速。"
        e = self.err(done)
        if it == "estop":
            return head + ("急停我不能关，也不会帮你绕过——这是硬规则。急停老是触发，先断电，再按这个顺序查：\n"
                           "1. 急停按键/接线是否接触不良（插头、杜邦线）；2. 断线停车超时 cmd_timeout_ms 是否太短（链路丢包会触发）；\n"
                           "3. 电池电压是否掉到 vbat_min 以下；4. 看状态栏触发原因和遥测 state 通道。查到原因后再上电。")
        if it == "edit":
            pe = self.ok(done, "propose_edit")
            if pe:
                return head + f"【源码】已读当前文件，只改了一行，diff 在右侧卡片：确认后会跑 make check，通过才 git 提交，随时可回滚。"
            return head + "没能定位要改的那一行" + (f"（{e}）" if e else "") + "：要么格式认不出（请写成“把 app.yaml 里 kp 默认值改成 0.1”），" \
                          "要么当前板子跑的工程里没有这个参数" + \
                          (f"（板上参数：{'、'.join(p['name'] for p in (self.ok(done, 'list_params') or [])[:8])}）。" if self.ok(done, "list_params") else "。")
        if it == "project":
            return head + self._project_answer(user, done, e)
        if it == "autotune":
            r = self.ok(done, "tune_autopilot")
            if not r:
                return head + f"没能自动连跑（{e}）。实机每改一次参数都要你点采纳：问我“帮我调一下”，一轮一轮来。"
            b = r.get("best_round") or {}
            rows = "；".join(f"第 {x['round']} 轮 {'、'.join(f'{k}→{v:.4g}' for k, v in (x.get('change') or {}).items()) or '基线'} → {x['action']}" for x in r["rounds"] if x.get("round"))
            return head + f"【实测】仿真自动调参 {len([x for x in r['rounds'] if x.get('round')])} 轮：{rows}。\n" + \
                ("护栏判定通过。" if r.get("passed") else f"没到通过（{r.get('final')}），已回到最好一轮。") + \
                (f"最好是第 {b.get('round')} 轮：{'、'.join(f'{k}={v:.4g}' for k, v in (b.get('gains') or {}).items())}，"
                 f"超调 {_pct((b.get('metrics') or {}).get('overshoot_pct'))}。" if b else "") + "\n" + hw
        if it == "score":
            if "回写" in user:
                w = self.ok(done, "score_writeback")
                return head + ("回写卡在上面：看 diff，点“执行”才写 requirements.yaml。" if w else f"没法回写（{e}）。先让我跑完并存好证据。")
            r = self.ok(done, "score_run")
            if not r:
                return head + (f"没跑成（{e}）。" if e else "告诉我评分项编号（例如“评分项 1 跑三遍留证据”）。")
            if r.get("status") == "pending_human_click":
                return head + "实机评分要你在上面的卡上点“执行”（检查实验前项目）。"
            rows = "；".join(f"第 {x['n']} 次 {'✓' if x['pass'] else '✗ ' + (x.get('why') or '')}" for x in r["runs"])
            s = head + f"【实测】评分项 {r['item']} 跑了 {len(r['runs'])} 次（判据 band={r['spec'].get('band')}）：{rows}。最差一次算数 → {r['result']}。"
            if r["result"] == "pass":
                return s + "\n存证据的卡在上面；存好后说“回写评分项 " + r["item"] + "”。"
            return s + "\n没全过，不存证据、不回写。先去调参，再来跑。"
        if it == "loss":
            return head + "【实测】已看最近 2 s 遥测。传感器/视觉信号丢失时的数据不能拿来调参：先把信号找回来" \
                          "（目标回到视野、线回到传感器下、链路恢复），状态栏里的信号状态恢复正常后再做阶跃。这一轮不改参数。"
        if it in ("exp", "sweep"):
            tool = "run_step_test" if it == "exp" else "run_sweep_test"
            r = self.ok(done, tool)
            if r and r.get("status") == "pending_human_click":
                return head + "这是实机实验：确认卡已发到右侧，检查实验前项目后点“执行”才会跑（2 分钟内有效）。跑完再问我结果。"
            if not r:
                return head + "实验没跑成" + (f"（{e}）" if e else "") + "。"
            if it == "sweep":
                return head + f"【实测】闭环扫频 {len(r.get('points', []))} 个频点：带宽 {(r.get('summary') or {}).get('bandwidth_hz')} Hz，" \
                              f"谐振峰 {(r.get('summary') or {}).get('peak_db', 0):.1f} dB。点数少，细看用上方“扫频”按钮。这一轮不改参数。"
            m = r.get("metrics") or {}
            return head + f"【实测】阶跃：超调 {_pct(m.get('overshoot_pct'))}，稳态误差 {_pct(m.get('sse_pct'))}。"
        if it == "why":
            t = self.ok(done, "read_telemetry") or {}
            if not t.get("n"):
                return head + "还没有遥测数据：先连接板子（或仿真板）再问。"
            rows = [(k, v) for k, v in t.items() if isinstance(v, dict) and k != "t_ms" and not re.match(r"(sp|set|target|ref)(_|$)", k)]
            pairs = self._lr(rows)
            out = [head + f"【实测】最近 {t['seconds']:.1f} s：" + "；".join(f"{k} 均值 {v['mean']:.3g}" for k, v in rows[:6])]
            if pairs:
                (a, va), (b, vb) = pairs
                d = (va["mean"] - vb["mean"]) / (abs(vb["mean"]) or 1) * 100
                out.append(f"【实测】{a} 与 {b} 只差 {abs(d):.1f}%，这段数据里看不出哪边慢；在出问题的工况下再问我。" if abs(d) < 1 else
                           f"【实测】{a} 比 {b} {'高' if d > 0 else '低'} {abs(d):.1f}%。")
            out.append("【推断】两边差异常见原因：一侧机械阻力大/轮胎打滑、电机或编码器参数（极数、减速比、方向）不一致、"
                       "两轮共用一组 PID 但对象不同。建议分别给两轮做一次阶跃（分析阶跃），比较上升时间和稳态误差再决定是否分开调。")
            return "\n".join(out)
        ctx = self.ok(done, "tune_context") or {}
        v = ctx.get("last_verdict") or {}
        if it == "hw":
            h = ctx.get("history") or []
            return head + (f"【实测】仿真里已跑 {len(h)} 轮阶跃。" if h else "【实测】还没有阶跃实验记录。") + \
                "\n可以上车，但先做这几项" + hw + "\n建议：上车后用同样的阶跃实验再跑一轮，参数先存快照，变差就一键回滚。"
        if it == "asym":
            if (v.get("asymmetry") or {}).get("asymmetric"):
                return head + "【实测】四段阶跃上下不对称。【推断】这通常是静摩擦/死区或重力这类单方向的力，" \
                              "优先加前馈或静摩擦补偿（起步给一个固定偏置），而不是硬拧 PID。\n" + hw
            return head + "【实测】还没有四段实验结果，或者上下基本对称。先在 dzbench.json 设 step_test.segments=4 跑一轮。"
        if it == "result":
            if self.ok(done, "observe"):
                return head + f"【实测】上一轮实验结束时还没稳（{(v.get('steady') or {}).get('reason')}），这一轮不改参数。" \
                              "先把 step_test.hold_s 加长，再跑一轮看。\n" + hw
            r = self.ok(done, "run_step_test")
            if r and r.get("status") == "pending_human_click":
                return head + "实机阶跃需要你在右侧动作卡上点“执行”。跑完再问我结果。"
            if r:
                vv, m = r["verdict"], r["metrics"]
                return head + f"【实测】刚跑了一轮：超调 {_pct(m.get('overshoot_pct'))}，稳态误差 {_pct(m.get('sse_pct'))}，" \
                              f"程序判定 {vv.get('action')}。下一步：问我“帮我调速度环”，我按规则只改一个参数。\n" + hw
            return head + "没拿到实验结果" + (f"（{e}）" if e else "") + "。\n" + hw
        if it == "tune":
            a = self.ok(done, "step_analysis")
            if not a:
                return head + "还没法分析" + (f"：{e}" if e else "") + "。先连接板子（或仿真板），给一个设定值阶跃，再问我。"
            m = a["metrics"]
            if not m.get("ok"):
                lv = (self.ok(done, "tune_context") or {}).get("last_verdict")
                if lv:      # 刚跑过阶跃实验、过几秒才问：按那轮结果走，不让人重做
                    return head + f"最近 5 s 里没有阶跃，但第 {lv.get('round')} 轮阶跃实验已判定“{ {'continue': '继续', 'done': '达标', 'rollback': '变差', 'stop': '停止'}.get(lv.get('action'), lv.get('action'))}”。" \
                                  "点上方“规则建议”，按那轮结果给下一项参数（仍要你点采纳）；或者现在问我（阶跃后 5 s 内）。"
                return head + f"最近 5 s 里没找到有效阶跃（{m.get('reason')}）。点上方“阶跃实验”自动做一次（或手动给设定值一个台阶），再问我。"
            s = (f"【实测】{a['y']} 跟随 {a['sp']}：超调 {_pct(m.get('overshoot_pct'))}，稳态误差 {_pct(m.get('sse_pct'))}，"
                 f"上升 {m.get('rise_s') or 0:.3f} s，振荡 {m.get('oscillations')} 次。")
            p = self.ok(done, "propose_param_change")
            if p:
                s += f"\n建议这一轮只改一个：{self.prop['name']} → {p.get('value', self.prop['value']):.4g}（右侧卡片点“采纳”才下发，护栏会限幅）。改完再给一个阶跃，看超调/稳态有没有变好。"
            else:
                s += ("\n护栏没同意这次改动：" + e + "。先保持，再观察一轮。") if e else \
                     ("\n规则：" + " ".join(h["text"] for h in a["hints"]) if a["hints"] else "\n规则没有要改的参数。") + "这轮不改参数，在实车工况下再给一个阶跃看看。"
            return head + s + "\n" + hw
        t = self.ok(done, "read_telemetry") or {}
        ps = self.ok(done, "list_params") or []
        st = f"【实测】板上 {len(ps)} 个参数，最近 {t.get('seconds', 0):.1f} s 有 {t.get('n', 0)} 个样本。" if t.get("n") else "还没连上板子（或没有数据）：先选串口 / 仿真板点“连接”。"
        return head + st + "\n我离线能做：看阶跃调 PID（“超调好大怎么办”）、解释左右差异（“为什么左轮慢”）、改 yaml 默认值、上车前检查。要更灵活的对话，在 ⚙ 里填一个大模型 Key。"

    def _project_answer(self, user: str, done: dict, e: str) -> str:
        code = self._code(user, done)
        if not code:
            ps = ((done.get("project_state") or [{}])[0].get("result") or {}).get("projects") or []
            return "【实测】仓库里的项目：" + ("、".join(ps) or "（还没有）") + "。告诉我题号（例如“推进项目 " + (ps[0] if ps else "2026X") + "”），" \
                   "新题就连题目 PDF 路径一起给我。"
        st = (done.get("project_state") or [{}])[-1].get("result") or {}
        s = f"【实测】{code}：" + "，".join(f"{k}{'✓' if v else '—'}" for k, v in (st.get("steps") or {}).items())
        s += f"；评分项 {st.get('req_items', 0)} 条，已有证据 {st.get('items_with_evidence', 0)} 条。"
        nxt = st.get("next_step")
        if not nxt:
            return s + "\n五步都走完了。下一步去烧录页编译烧录；评分页按评分项逐条留证据。"
        ch, ap = self.ok(done, "project_chain"), self.ok(done, "project_apply")
        if ch:
            rows = []
            for x in ch.get("steps") or []:
                extra = {"req": lambda: f"拆出 {x.get('items')} 个评分项", "scheme": lambda: f"主控 {x.get('mcu')}",
                         "scratch": lambda: f"从零新建 {x.get('label')}", "import": lambda: f"导入板 {x.get('board')}",
                         "alloc": lambda: "资源分配", "gen": lambda: f"生成 {x.get('files')} 个文件" + (f"，缺子系统 {'、'.join(x['missing'])}" if x.get("missing") else "")}
                rows.append(("✓ " if x.get("ok") else "✗ ") + x["step"] + "：" + (extra.get(x["step"], lambda: "")() if x.get("ok") else f"{x.get('why')} {x.get('fix', '')}"))
            s += "\n" + "\n".join(rows)
            if ap and ap.get("status") == "pending_human_click":     # 细节都在卡片上，回答只说结论和下一步
                bad = [x for x in ch.get("steps") or [] if x.get("missing")]
                return f"【实测】{code}：{len(ch['to_write'])} 步都预览好了（只在暂存区）。看一眼上面的确认卡，点“执行”一次写入。" + \
                    (f"\n注意：缺子系统 {'、'.join(bad[0]['missing'])}，写入后要新建。" if bad else "")
            return s + ("\n停在 " + ch["stopped_at"] if ch.get("stopped_at") else "")
        pv, acc = self.ok(done, "flow_preview"), self.ok(done, "flow_accept")
        if acc and acc.get("status") == "pending_human_click":
            files = "、".join(list((pv or {}).get("files") or {})[:6])
            return s + f"\n下一步 {nxt} 的预览已跑通（暂存区" + (f"：{files}" if files else "") + "），确认卡在右侧：点“执行”才写进仓库，写完我会自动把再下一步的预览备好。"
        if pv:
            return s + f"\n下一步 {nxt} 预览没通过（rc={pv.get('rc')}），输出末尾：\n" + (pv.get("out_tail") or "")[-400:]
        if e:
            return s + f"\n下一步 {nxt} 没跑成：{e}"
        return s + f"\n下一步是 {nxt}，需要你给我 {st.get('next_needs') or '更多信息'}（直接把路径发我）。"

    @staticmethod
    def _lr(rows):
        d = dict(rows)
        for a, b in (("_a", "_b"), ("_l", "_r"), ("left", "right")):
            for k in d:
                if k.endswith(a) and k[: -len(a)] + b in d:
                    return (k, d[k]), (k[: -len(a)] + b, d[k[: -len(a)] + b])
        return None
