"""离线规则助手：没填 API Key / 比赛现场没网时，“问 Agent”仍然可用。

它长得像一个 LLM（chat(messages, tools) → assistant message），但只按关键词识别意图、按固定剧本调工具、
用模板组织回答，所以和真 LLM 走同一个 AgentLoop：同一套工具白名单、风险分级、护栏、人工确认。
能力有限（只认常见几类问题），回答里会说明自己是离线规则；遇到认不出的问题就给出能问什么。
"""
from __future__ import annotations

import json
import re

NAME = "离线规则助手"

INTENTS = (   # 顺序即优先级
    ("estop", r"急停"),
    ("edit", r"(\.ya?ml|默认值|源码|代码).*(改|换|设)|(改|换|设).*(\.ya?ml|默认值)"),
    ("hw", r"上车|实机|实板|真车|上板"),
    ("asym", r"不对称|上下不一样|正负不一样|四段"),
    ("result", r"结果|那轮|下一步|上一轮|这轮"),
    ("why", r"为什么|为啥|怎么回事|原因"),
    ("tune", r"超调|调好|调参|调一下|怎么调|太慢|跟不上|振荡|震荡|抖|稳态|响应|过冲|pid|PID|kp|ki|kd"),
)


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
                    r = json.loads(m["content"])
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
                return [("read_file", {"path": f}) for f in files[:12]] or None
            if step == 2 and (e := self._edit(user, done)):
                return [("propose_edit", e)]
            return None
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
        if it == "tune":
            if step == 0:
                return [("tune_context", {}), ("step_analysis", {})]
            if step == 1 and (p := self._pick(done)):
                return [("propose_param_change", p)]
            return None
        return [("read_telemetry", {"seconds": 2}), ("list_params", {})] if step == 0 else None

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
        files = [f for r in done.get("list_files", []) if r.get("ok") for f in r["result"]][:12]
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
                          "要么当前板子跑的工程里没有这个参数（例如 2026H 的球环比例增益叫 pos_k）。"
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

    @staticmethod
    def _lr(rows):
        d = dict(rows)
        for a, b in (("_a", "_b"), ("_l", "_r"), ("left", "right")):
            for k in d:
                if k.endswith(a) and k[: -len(a)] + b in d:
                    return (k, d[k]), (k[: -len(a)] + b, d[k[: -len(a)] + b])
        return None
