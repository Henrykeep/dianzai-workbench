"""把 tuning / gateway / llm / loop 组装到一个会话上，供 server 调用（也方便测试时注入假 LLM）。"""
from __future__ import annotations

import itertools
import os
import re
import pathlib
import math
import struct
import time

from .. import config as cfg_mod
from .. import elfsym, hardfault, keil
from ..agent_api import AgentTools
from ..flash import FlashError, Flasher, schema_hash_of
from ..session import LinkError, Session
from ..transport import ROOT
from . import llm as llm_mod
from . import risk, yamlpar
from .guard import GuardError, TuneGuard, key_samples
from .gateway import Gateway, GatewayError
from .journal import BoardMemory, Journal, board_key
from .loop import AgentLoop
from .offline import OfflineAssistant
from .experiment import StagedSearch, asymmetry, four_segment_metrics, four_segment_plan, steady_state
from .tuning import StepMetrics, step_metrics, tuning_hints


def guess_pairs(fields: list[str]) -> list[tuple[str, str]]:
    """猜 (反馈, 设定) 通道对：sp_a↔spd_a、ball_sp_px↔cam_x_px 之类靠后缀/同名去掉 sp。"""
    out = []
    for sp in fields:
        if not re.search(r"(^|_)(sp|set|target|ref)(_|$)", sp):
            continue
        key = re.sub(r"(^|_)(sp|set|target|ref)(_|$)", r"\1", sp).strip("_")
        cands = [f for f in fields if f != sp and (f.endswith("_" + key) or f.startswith(key + "_") or key and key in f)]
        if cands:
            out.append((sorted(cands, key=len)[0], sp))
    return out


def guess_gain(params: list[str], kind: str) -> str | None:
    for p in params:
        if p == kind or p.endswith("_" + kind):
            return p
    return None


class AgentService:
    def __init__(self, session: Session, tools: AgentTools, emit, root=None, llm=None, runner=None):
        # 工程仓库：DZBENCH_REPO > 配置 repo > 本仓库（开发模式）。安装版必须在 ⚙ 里指定（未在 Windows 实测）
        root = root or os.environ.get("DZBENCH_REPO") or llm_mod.load_config().get("repo") or ROOT
        self.s, self.tools, self.emit = session, tools, emit
        self.journal = Journal()
        self.tune_orig: dict | None = None     # Agent 第一次改参数前的整套参数（ArduPilot 自整定 ORIGINAL 增益的思路）
        self.gw = Gateway(root, self._gw_emit, **({"runner": runner} if runner else {}))
        tools.on_apply = self._param_applied
        self._llm = llm
        rules = self.gw.root / "AGENTS.md"
        self.cfg = cfg_mod.load(self.gw.root)
        self.flasher = Flasher(session, self.cfg)
        self.guard: TuneGuard | None = None
        self.staged = StagedSearch()
        self.actions: dict[int, dict] = {}
        self._aid = itertools.count(1)
        self.syms: dict | None = None
        self.last_verdict: dict | None = None
        self.plan: dict | None = None
        self.loop = AgentLoop(None, {
            "read_telemetry": tools.read_telemetry,
            "list_params": tools.list_params,
            "step_analysis": self.step_analysis,
            "propose_param_change": self.agent_propose_param,
            "tune_context": self.tune_context,
            "observe": lambda reason="": {"status": "observing", "reason": reason},
            "run_step_test": self.run_step_test,
            "run_sweep_test": self.run_sweep_test,
            "bode_predict": self.bode_predict,
            "rollback_best": self.rollback_best,
            "flash": lambda dry_run=True: self.flasher.flash(dry_run),
            "flash_rollback": lambda dry_run=True: self.flasher.rollback(dry_run),
            "build": self.build,
            "build_log": self.build_log,
            "decode_hardfault": self.decode_hardfault,
            "read_symbol": self.read_symbol,
            "list_files": lambda glob="**/*": self.gw.list_files(glob),
            "read_file": lambda path: self.gw.read_file(path),
            "propose_edit": lambda path, search, replace, reason: self.gw.propose_edit(path, search, replace, reason, "agent"),
            "update_plan": self.update_plan,
            "board_memory": lambda: self.memory().summary(),
        }, emit, project_rules=rules.read_text(encoding="utf-8") if rules.exists() else "",
            gate=self.gate)

    # -------------------------------------------------------------- 计划 / 记忆 / 撤销
    def update_plan(self, steps: list, current: int | None = None) -> dict:
        """把多步计划显示给用户（Codex update_plan / DeepSeek Harness todo_write：整表替换，每步带状态，
        最多一步进行中）。只显示，不执行任何东西。steps 可以是字符串（兼容旧写法，用 current 推状态）或 {step, status}。"""
        rows, seen = [], set()
        for i, x in enumerate((steps or [])[:8]):
            if isinstance(x, dict):
                text, st = str(x.get("step", "")).strip()[:120], str(x.get("status", "pending"))
            else:
                text = str(x).strip()[:120]
                c = int(current or 0)
                st = "completed" if i < c else "in_progress" if i == c else "pending"
            if not text:
                raise GatewayError("bad_plan", "计划里有空步骤")
            if text in seen:
                raise GatewayError("bad_plan", f"计划里步骤重复：{text}")
            if st not in ("pending", "in_progress", "completed"):
                raise GatewayError("bad_plan", f"状态只能是 pending / in_progress / completed，收到 {st}")
            seen.add(text)
            rows.append({"step": text, "status": st})
        if sum(r["status"] == "in_progress" for r in rows) > 1:
            raise GatewayError("bad_plan", "同一时间只能有一步 in_progress")
        cur = next((i for i, r in enumerate(rows) if r["status"] == "in_progress"),
                   next((i for i, r in enumerate(rows) if r["status"] == "pending"), len(rows)))
        self.plan = {"steps": [r["step"] for r in rows], "items": rows, "current": cur}
        self.emit({"type": "agent_plan", **self.plan})
        return {"shown": len(rows), "done": sum(r["status"] == "completed" for r in rows)}

    def memory(self) -> BoardMemory:
        return BoardMemory(board_key(self.s.schema_hash, self.s.board_uid))

    def _gw_emit(self, e: dict) -> None:
        if e.get("type") == "change" and e.get("status") == "committed" and e.get("source") == "agent" and e.get("commit"):
            if not any(j.get("commit") == e["commit"] for j in self.journal.list()):
                self.journal.add("commit", commit=e["commit"], title=e.get("title", ""))
                self.memory().add("commit", commit=e["commit"], title=e.get("title", ""))
        self.emit(e)

    def _mark_tuning(self, name: str, old) -> None:
        if self.tune_orig is None:
            self.tune_orig = {"values": {**self.s.params, **({name: old} if old is not None else {})}, "changed": []}
        if name not in self.tune_orig["changed"]:
            self.tune_orig["changed"].append(name)
        self.emit({"type": "agent_tune_pending", **self.tune_status()})

    def tune_status(self) -> dict:
        o = self.tune_orig
        if not o:
            return {"pending": False, "items": []}
        return {"pending": True, "items": [{"name": k, "orig": o["values"].get(k), "now": self.s.params.get(k)} for k in o["changed"]]}

    def tune_finish(self, keep: bool) -> dict:
        """人点“保留 / 恢复原值”。Agent 调出来的参数不经人确认就一直算“试用中”（ArduPilot 自整定结束后不保存就恢复原增益）。
        保留 = 存一份快照（掉电后可一键恢复）；恢复 = 把改过的参数逐个写回并回读比对。"""
        o = self.tune_orig
        if not o:
            raise LinkError("no_tuning", "Agent 这次没有改过参数")
        if keep:
            snap = self.s.snapshot_save(time.strftime("agent_%m%d_%H%M%S"), "Agent 调参结果（用户确认保留）")
            out = {"kept": o["changed"], "snapshot": snap}
        else:
            out = {"restored": [self.s.set_param(k, o["values"][k], verify=True) for k in o["changed"] if o["values"].get(k) is not None]}
            self.loop.note("用户没有保留你这轮调出的参数，已恢复到调参前的值：" + "，".join(f"{k}={o['values'].get(k)}" for k in o["changed"]))
        self.memory().add("tune_end", keep=keep, params=o["changed"])
        self.tune_orig = None
        self.emit({"type": "agent_tune_pending", **self.tune_status()})
        return out

    def _param_applied(self, p: dict, r: dict) -> None:
        if p.get("source") != "agent":
            return
        self._mark_tuning(p["name"], p.get("current"))
        self.journal.add("param", name=p["name"], old=p.get("current"), new=r.get("applied", p["value"]), reason=p.get("reason", ""))
        self.memory().add("param", name=p["name"], old=p.get("current"), new=r.get("applied", p["value"]))
        self.emit({"type": "agent_journal", "items": self.journal_list()})

    def journal_list(self) -> list[dict]:
        return [{k: v for k, v in e.items() if k != "t"} | {"ago_s": round(time.time() - e["t"])} for e in self.journal.list()]

    def set_mode(self, mode: str) -> dict:
        r = self.loop.set_mode(mode)
        self.emit({"type": "agent_workmode", **r})
        return r

    def undo_last(self) -> dict:
        """一键撤销 Agent 最近一次已落地的改动：参数改回旧值 / git revert 那次提交。由人点按钮触发，不给 Agent 用。"""
        e = self.journal.pop()
        if not e:
            raise LinkError("nothing_to_undo", "这次会话里 Agent 还没改过东西", "")
        try:
            if e["kind"] == "param":
                if e.get("old") is None:
                    raise LinkError("undo_unknown_old", f"不知道 {e['name']} 改之前是多少，不能自动撤销", "用快照恢复或手动改回")
                r = self.s.set_param(e["name"], e["old"])
                out = {"undone": "param", "name": e["name"], "value": r.get("applied", e["old"]), "was": e["new"]}
            else:
                r = self.gw.rollback(e["commit"])
                out = {"undone": "commit", **r, "title": e.get("title", "")}
        except GatewayError as ex:
            self.journal.push_back(e)
            raise LinkError(ex.code, ex.message, ex.fix) from ex
        except LinkError:
            self.journal.push_back(e)
            raise
        self.memory().add("undo", **{k: v for k, v in out.items() if k != "undone"}, what=out["undone"])
        self.loop.note(f"用户撤销了你的改动：{'参数 ' + out['name'] + ' 改回 ' + str(out['value']) if out['undone'] == 'param' else '提交 ' + out['reverted'] + '（' + out.get('title', '') + '）已 revert'}。"
                       "不要再原样重做这次改动；如果仍认为需要，先说明理由。")
        self.emit({"type": "agent_journal", "items": self.journal_list()})
        return out

    # -------------------------------------------------------------- 风险分级
    @property
    def sim(self) -> bool:
        return (self.s.port or "").startswith("sim:") or bool(getattr(self.s, "replay", None))

    def gate(self, tool: str, args: dict, run):
        """loop 每次调工具都经过这里：auto 直接跑；log 跑完记审计；human 变成待点击的动作卡；forbid 拒绝。"""
        t = risk.tier(tool, self.sim)
        if t == risk.FORBID:
            risk.audit(tool, args, t, "denied")
            raise GatewayError("forbidden", f"{tool} 是禁止操作，Agent 永远不能执行")
        if t == risk.HUMAN:
            aid = next(self._aid)
            preview = None
            if tool in ("flash", "flash_rollback"):
                try:
                    preview = (self.flasher.flash if tool == "flash" else self.flasher.rollback)(dry_run=True)
                except FlashError as e:
                    preview = {"error": e.message}
            self.actions[aid] = {"id": aid, "tool": tool, "args": args, "run": run}
            self.emit({"type": "agent_action", "id": aid, "tool": tool, "args": args, "preview": preview, "sim": self.sim})
            risk.audit(tool, args, t, "pending_human")
            return {"status": "pending_human_click", "action_id": aid, "note": "需要用户在界面上点“执行”"}
        r = run()
        if t == risk.LOG:
            risk.audit(tool, args, t, "ok")
        return r

    def action_decide(self, aid: int, accept: bool) -> dict:
        a = self.actions.pop(aid, None)
        if not a:
            raise LinkError("no_action", f"动作 {aid} 不存在或已处理")
        risk.audit(a["tool"], a["args"], risk.HUMAN, "accepted" if accept else "rejected")
        if not accept:
            return {"id": aid, "status": "rejected"}
        args = dict(a["args"])
        if a["tool"] in ("flash", "flash_rollback"):
            args["dry_run"] = False                      # 人点了“确认烧录”才真烧
        try:
            return {"id": aid, "status": "done", "result": self.loop.handlers[a["tool"]](**args)}
        except (FlashError, GuardError, LinkError) as e:
            raise LinkError(getattr(e, "code", "action"), e.message, getattr(e, "fix", "")) from e

    # -------------------------------------------------------------- 调参护栏
    def _guard(self) -> TuneGuard:
        if self.guard is None or self.guard.sim != self.sim:
            b = {p["name"]: (p["min"], p["max"]) for p in (self.s.schema.params if self.s.schema else [])}
            t = self.cfg["tune"]
            self.guard = TuneGuard(b, self.sim, limits={"vbat_min": t["vbat_min"], "temp_max": t["temp_max"]},
                                   max_rounds=t["max_rounds_sim"] if self.sim else min(int(t["max_rounds_hw"]), 10),
                                   weights=t.get("weights", "balanced"))
            self.staged = StagedSearch(order=tuple(self._gains()) or ("kp", "ki", "kd"))
        return self.guard

    def reset_guard(self) -> dict:
        self.guard = None
        return {"status": "reset"}

    def agent_propose_param(self, name: str, value: float, reason: str) -> dict:
        g = self._guard()
        try:
            v, notes = g.check(name, self.s.params.get(name), value)
        except GuardError as e:
            raise GatewayError(e.code, e.message) from e
        r = self.tools.propose_param_change(name, v, reason + ("（护栏：" + "；".join(notes) + "）" if notes else ""), "agent")
        return r | {"value": v, "guard": notes}

    def _gain_names(self) -> dict:
        """{kp/ki/kd: 板上参数名}：step_test.gains 写明的优先（如 2026H 球环 kp=pos_k），否则按名字猜。"""
        names = [p["name"] for p in (self.s.schema.params if self.s.schema else [])]
        cfg = (self.step_cfg() or {}).get("gains") or {}
        return {x: n for x in ("kp", "ki", "kd") if (n := cfg.get(x) if cfg.get(x) in names else (None if cfg else guess_gain(names, x)))}

    def _gains(self) -> dict:
        ks = list(self._gain_names().values())
        return {k: self.s.params.get(k, 0.0) for k in ks}

    def tune_context(self) -> dict:
        """给 LLM 的紧凑上下文：指标 + 约 20 个关键样本 + 带标签的历史表 + 护栏规则（思路参考 llm-pid-tuner，MIT）。"""
        g = self._guard()
        st = self.step_cfg() or {}
        w = self.s.window(float(st.get("hold_s", 3)) + 1)
        out = {"rules": g.prompt_rules(), "history": g.history_table(), "gains": self._gains(), "stopped": g.stopped,
               "reply_format": '{"action":"PROPOSE|OBSERVE|DONE","param":"kp","value":0.1,"reason":"..."}'}
        mem = self.memory().summary(6)
        if mem["entries"]:
            out["board_memory"] = mem
        if self.last_verdict:
            out["last_verdict"] = {k: self.last_verdict.get(k) for k in ("round", "action", "reason", "steady", "asymmetry", "advice") if k in self.last_verdict}
        if w and st.get("y") and st.get("sp"):
            t = [a for a, _ in w]
            y, sp = [float(v.get(st["y"], 0)) for _, v in w], [float(v.get(st["sp"], 0)) for _, v in w]
            out["samples_t_y_sp"] = key_samples(t, y, sp)
            out["metrics"] = step_metrics(t, y, sp).as_dict()
        return out

    def step_cfg(self) -> dict | None:
        """按对象选阶跃实验配置：dzbench.json 的 step_test（单个或列表）+ step_tests（按工程名的字典），
        取第一个 y/sp 两个通道都在当前遥测里的；还没识别出 schema 时取第一个。"""
        st = self.cfg.get("step_test")
        cands = (st if isinstance(st, list) else [st] if st else []) + list((self.cfg.get("step_tests") or {}).values())
        fields = {f["name"] for f in self.s.schema.fields} if self.s.schema else set()
        for c in cands:
            if isinstance(c, dict) and (not fields or (c.get("y") in fields and c.get("sp") in fields)):
                return c
        return None

    START_CMDS = ("T", "P", "G", "S")     # 'R' 不在里面：它同时是“解除急停”，Agent/自动实验永远不发

    def step_start(self, st: dict) -> None:
        """实验前的准备命令（如 2026H：'T'1 选测试 → 'G' 开始）。运行中再发会被板子状态机忽略。
        上一轮已到 DONE（限时到了）时需要复位，但复位帧也是解除急停，所以只有在“没急停锁存 + 遥测 state 正是 DONE”
        时才发 'R'；急停状态下直接拒绝做实验。"""
        if not st.get("start"):
            return
        if self.s.tx_locked:
            raise LinkError("estop", "急停已锁存：不做实验", "人工检查后按“解除急停 R”")
        w = self.s.window(0.3)
        sf, done = st.get("state_field", "state"), st.get("done_state")
        if done is not None and w and w[-1][1].get(sf) == done:
            self.s.cmd("R")
            time.sleep(0.1)
        for c in st["start"]:
            if c[0] not in self.START_CMDS:
                raise LinkError("bad_start", f"step_test.start 里不允许命令 {c[0]!r}", f"只能用 {'/'.join(self.START_CMDS)}")
            self.s.cmd(c[0], c[1] if len(c) > 1 else None)
            time.sleep(0.05)

    def run_step_test(self) -> dict:
        """按 dzbench.json 的 step_test 通过链路做一次标准阶跃实验，交给护栏判定。实机是 human 级。"""
        st = self.step_cfg()
        if not st:
            raise LinkError("no_step_test", "没配置（或没有匹配当前遥测的）阶跃实验", '在 dzbench.json 写 step_test，如 {"kind":"data","id":1,"fmt":"<ff","low":[0,0],"high":[0.4,0],"hold_s":1.5,"y":"spd_a","sp":"sp_a"}')
        self.step_start(st)
        lo, hi, hold = st["low"], st["high"], float(st.get("hold_s", 1.5))
        pre = float(st.get("pre_s", 0.6))
        segs = None
        if int(st.get("segments", 1)) == 4:          # 四段正负阶跃：SP → SP−Δ → SP → SP+Δ → SP（SP = high）
            d = st.get("delta") or [x * 0.25 for x in hi]
            plan = four_segment_plan(1.0, 1.0, hold)
            vecs = [[h + (v - 1.0) * dd for h, dd in zip(hi, d)] for _, v in plan]
            w0 = self.s.window(0.05)
            tb = w0[-1][0] if w0 else 0.0               # 板子时钟（t_ms）对齐：发第一段时最新样本的时间
            t0 = time.monotonic()
            for k, vals in enumerate(vecs):
                while time.monotonic() < t0 + (k + 1) * hold:
                    self.s.send_data(int(st["id"]), struct.pack(st["fmt"], *vals))
                    time.sleep(0.1)
            w = [x for x in self.s.window(5 * hold + 1.0) if x[0] >= tb]
            t = [a for a, _ in w]
            ys, sps = [float(v[st["y"]]) for _, v in w], [float(v[st["sp"]]) for _, v in w]
            segs = four_segment_metrics([x - tb for x in t], ys, sps, plan)
            ok = [StepMetrics(**{k: v for k, v in sg.items() if k not in ("seg", "dir")}) for sg in segs if sg.get("ok")]
            g = self._guard()
            m = max(ok, key=g.score) if ok else StepMetrics(False, "四段实验没有有效段")   # 护栏按最差一段判
        else:
            t_end = time.monotonic() + pre + hold
            while time.monotonic() < t_end:
                vals = lo if time.monotonic() < t_end - hold else hi
                self.s.send_data(int(st["id"]), struct.pack(st["fmt"], *vals))
                time.sleep(0.1)
            w = self.s.window(hold + pre * 0.5)
            t = [a for a, _ in w]
            ys = [float(v[st["y"]]) for _, v in w]
            m = step_metrics(t, ys, [float(v[st["sp"]]) for _, v in w])
            g = self._guard()
        ss = steady_state(t, ys, window_s=min(0.3, hold / 3))
        verdict = g.record(m, self._gains(), w[-1][1] if w else {})
        verdict["steady"] = ss
        if not ss["steady"] and ss["reason"] in ("still_drifting", "warming_up"):
            verdict["advice"] = "OBSERVE：实验结束时还没稳（%s），先加长 step_test.hold_s 再判断，不要据此改参数" % ss["text"]
        if segs is not None:
            verdict["segments"], verdict["asymmetry"] = segs, asymmetry(segs)
        if verdict["action"] == "rollback" and verdict.get("auto"):
            verdict["rolled_back"] = self.rollback_best(_auto=True)
        self.last_verdict = verdict
        self.memory().add("verdict", round=verdict.get("round"), action=verdict.get("action"), gains=self._gains(),
                          overshoot_pct=round(m.overshoot_pct, 1), settling_s=m.settling_s)
        self.emit({"type": "tune_round", "verdict": verdict, "metrics": m.as_dict()})
        return {"verdict": verdict, "metrics": m.as_dict()}

    SWEEP_MAX_S = 90.0
    SWEEP_SEND_S = 0.02                              # 主机发设定值的周期：频率上限按它的 1/10 算

    def run_sweep_test(self, f0: float | None = None, f1: float | None = None, n: int | None = None,
                       amp: float | None = None) -> dict:
        """闭环扫频：设定值 = high + amp·(high−low)·sin(2πft)，增益/相位用遥测里板子实际收到的 sp 和 y 算
        （主机发送抖动不影响结果，只影响幅值）。频点间不回到 low。"""
        from . import bode
        st = self.step_cfg()
        if not st:
            raise LinkError("no_step_test", "扫频复用 step_test 的配置（通道、工作点），但现在没有", "先在 dzbench.json 写 step_test")
        sw = st.get("sweep") or {}
        f0, f1 = float(f0 or sw.get("f0", 0.5)), float(f1 or sw.get("f1", 5.0))
        n, amp = int(n or sw.get("n", 6)), float(amp or sw.get("amp", 0.2))
        settle, cyc = float(sw.get("settle_cycles", 2)), float(sw.get("cycles", 4))
        per = ((self.s.schema.d["telemetry"].get("period_ms") if self.s.schema else None) or 10) / 1000.0
        fmax = min(1 / (10 * self.SWEEP_SEND_S), 1 / (8 * per))
        if not (0 < f0 < f1 <= fmax) or n < 2:
            raise LinkError("bad_sweep", f"频率范围要满足 0 < f0 < f1 ≤ {fmax:.3g} Hz（发送周期 {self.SWEEP_SEND_S * 1000:.0f} ms、遥测 {per * 1000:.0f} ms 决定）")
        freqs = bode.log_freqs(f0, f1, n)
        total = sum((settle + cyc) / f for f in freqs)
        if total > self.SWEEP_MAX_S:
            raise LinkError("sweep_too_long", f"要 {total:.0f} s，超过 {self.SWEEP_MAX_S:.0f} s", "提高 f0 或减少频点 n")
        lo, hi = st["low"], st["high"]
        idx = [i for i, (a, b) in enumerate(zip(lo, hi)) if a != b]
        self.step_start(st)
        pts, errs = [], []
        for f in freqs:
            dur = (settle + cyc) / f
            w0 = self.s.window(0.05)
            tb = w0[-1][0] if w0 else 0.0
            t0 = time.monotonic()
            while (el := time.monotonic() - t0) < dur:
                k = amp * math.sin(2 * math.pi * f * el)
                vals = [h + (k * (h - l) if i in idx else 0.0) for i, (l, h) in enumerate(zip(lo, hi))]
                self.s.send_data(int(st["id"]), struct.pack(st["fmt"], *vals))
                time.sleep(self.SWEEP_SEND_S)
            w = [x for x in self.s.window(dur + 1.0) if x[0] > tb]
            try:
                pts.append(bode.measure([a for a, _ in w], [float(v[st["sp"]]) for _, v in w],
                                        [float(v[st["y"]]) for _, v in w], f, settle))
            except (ValueError, KeyError) as e:
                errs.append({"f": f, "error": str(e)})
        self.s.send_data(int(st["id"]), struct.pack(st["fmt"], *hi))
        if len(pts) < 2:
            raise LinkError("sweep_failed", f"有效频点不足：{errs}")
        summ = bode.closed_loop_summary(pts)
        res = {"points": [{k: round(v, 4) if isinstance(v, float) else v for k, v in p.items()} for p in pts],
               "summary": summ, "errors": errs, "gains": self._gains()}
        self.memory().add("sweep", gains=self._gains(), bandwidth_hz=summ["bandwidth_hz"], peak_db=round(summ["peak_db"], 2))
        self.emit({"type": "sweep_result", **res})
        return res

    def bode_predict(self, K: float, tau: float, kp: float, L: float = 0.0, ki: float = 0.0, kd: float = 0.0, tf: float = 0.0) -> dict:
        from . import bode
        if tau <= 0 or L < 0:
            raise LinkError("bad_model", "tau 要 > 0，L 要 ≥ 0（秒）")
        r = bode.predict(K, tau, L, kp, ki, kd, tf)
        keep = ("crossover_hz", "phase_margin_deg", "gain_margin_db", "phase180_hz", "bandwidth_hz", "peak_db", "peak_hz")
        out = {k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in keep}
        out["note"] = "模型预测（FOPDT + PID），不是实测；用 run_sweep_test 实测对比"
        return out

    def rollback_best(self, _auto: bool = False) -> dict:
        g = self._guard()
        b = g.best()
        if not b:
            raise LinkError("no_best", "还没有稳定的一轮可回滚")
        changed = {k: self.s.params.get(k) for k, v in b.gains.items() if self.s.params.get(k) != v}
        applied = {k: self.s.set_param(k, v, verify=True) for k, v in b.gains.items() if k in changed}
        for k, old in changed.items():
            self._mark_tuning(k, old)
        g.proposed_this_round = None
        return {"round": b.n, "gains": b.gains, "applied": list(applied), "auto": _auto}

    def rule_round(self) -> dict:
        """无 LLM 模式：默认分阶段 P→I→D（tune.rule_mode=staged），否则用规则提示；同样经过护栏与人工确认。"""
        g = self._guard()
        if self.cfg["tune"].get("rule_mode", "staged") == "staged" and g.rounds:
            p = self.staged.propose(StepMetrics(**g.rounds[-1].metrics), self._gains(), g)
            if not p:
                return {"action": "OBSERVE", "reason": "分阶段搜索 P→I→D 已走完，没有可用的单项建议"}
            ph = "PID"[min(self.staged.stage, 2)]
            return self.agent_propose_param(p[0], p[1], f"分阶段搜索（{ph} 阶段）：{p[0]} → {p[1]:.4g}")
        a = self.step_analysis()
        for h in a["hints"]:
            for k, v in (h.get("changes") or {}).items():
                d = 1 if v > (self.s.params.get(k) or 0) else -1
                if (k, d) not in g.blocked:
                    return self.agent_propose_param(k, v, "规则：" + h["text"])
        return {"action": "OBSERVE", "reason": "规则没有可用的单项建议"}

    # -------------------------------------------------------------- 编译 / 故障 / 变量
    def _note_build(self, res: dict, log_mtime: float | None = None) -> dict:
        """编译结果交给烧录器（烧录前置条件 build_ok 只认这里登记的镜像）。
        读的是旧日志（镜像比日志新/旧超过 120 s）就不登记：日志和镜像对不上。"""
        b = self.cfg["build"]
        img = b.get("image") or b.get("elf")
        if not img:
            res["flash_ready"] = "没配置 build.image / build.elf，编译结果不会用于烧录"
            return res
        p = self.gw.root / img
        if log_mtime is not None and (not p.exists() or abs(p.stat().st_mtime - log_mtime) > 120):
            res["flash_ready"] = "日志和镜像时间对不上（旧日志？），没登记为可烧录；重新编译一次"
            return res
        sch = schema_hash_of(self.gw.root / b["link_schema"]) if b.get("link_schema") else None
        self.flasher.note_build(bool(res.get("ok")), str(p), sch)
        res["flash_ready"] = bool(res.get("ok")) and p.exists()
        return res

    def build(self) -> dict:
        b = self.cfg["build"]
        if not (b.get("keil_uv4") and b.get("keil_project")):
            raise LinkError("no_build", "没配置 Keil 编译", "dzbench.json 写 build.keil_uv4（UV4.exe 路径）和 build.keil_project（.uvprojx）")
        res = keil.build(b["keil_uv4"], str(self.gw.root / b["keil_project"]), b.get("keil_target"))
        return self._note_build(res)

    def build_log(self, path: str | None = None) -> dict:
        b = self.cfg["build"]
        p = pathlib.Path(path) if path else None
        if p is None and b.get("keil_project"):
            p = (self.gw.root / b["keil_project"]).with_suffix(".dzbench_build.log")
        if not p or not p.exists():
            raise LinkError("no_log", "没有 Keil 编译日志", "先在 Keil 编一次，或配置 build.keil_uv4 + keil_project")
        return self._note_build(keil.parse_log(p.read_text(encoding="utf-8", errors="replace")), p.stat().st_mtime)

    def _symbols(self) -> dict:
        if self.syms is None:
            elf = self.cfg["build"].get("elf")
            if not elf:
                raise LinkError("no_elf", "没配置 ELF", "dzbench.json 写 build.elf（如 build/car_2wd.elf 或 Objects/xx.axf）")
            self.syms = elfsym.load_symbols(self.gw.root / elf)
        return self.syms

    def decode_hardfault(self, frame: list[int], exc_return: int | None = None, regs: dict | None = None) -> dict:
        core = self.cfg.get("core") or hardfault.guess_core(self.cfg["flash"].get("target"))
        try:
            syms = self._symbols()
        except (LinkError, elfsym.ElfError):
            syms = None
        return hardfault.decode(frame, exc_return, core, regs, syms)

    # ---- ELF 变量观察（不用改固件：SWD 直接按地址读内存，样本走虚拟通道画线）
    def elf_symbols(self, query: str = "", limit: int = 50) -> list[dict]:
        q = query.lower()
        out = [s for s in self._symbols().values() if s.kind == "object" and s.size in (1, 2, 4) and q in s.name.lower()]
        out.sort(key=lambda s: (not s.name.lower().startswith(q), s.name))
        return [{"name": s.name, "addr": f"0x{s.addr:08x}", "size": s.size,
                 "type": {1: "u8", 2: "i16", 4: "f32"}[s.size]} for s in out[:limit]]

    def watch_start(self, spec: list[dict], period_ms: int = 20, probe=None) -> dict:
        self.watch_stop()
        self._probe = probe or self.flasher.factory()
        self.watch = elfsym.SymbolWatch(self.s, self._probe, self._symbols())
        try:
            return self.watch.start(spec, period_ms)
        except Exception:
            self.watch_stop()
            raise

    def watch_stop(self) -> dict:
        w, pr = getattr(self, "watch", None), getattr(self, "_probe", None)
        if w:
            w.stop()
        if pr and hasattr(pr, "close"):
            pr.close()
        self.watch = self._probe = None
        return {"stopped": bool(w)}

    def read_symbol(self, name: str) -> dict:
        s = self._symbols().get(name)
        if not s:
            raise LinkError("no_symbol", f"ELF 里没有 {name}")
        return {"name": s.name, "addr": f"0x{s.addr:08x}", "size": s.size, "kind": s.kind}

    # -------------------------------------------------------------- 离线调参
    def step_analysis(self, y: str | None = None, sp: str | None = None, seconds: float = 5.0,
                      kp: str | None = None, ki: str | None = None, kd: str | None = None) -> dict:
        w = self.s.window(seconds)
        if not w:
            raise LinkError("no_data", "还没有遥测数据", "先连接板子（或仿真板）并给一个阶跃")
        fields = list(w[0][1])
        if not (y and sp) and (st := self.step_cfg()) and st.get("y") in fields and st.get("sp") in fields:
            y, sp = st["y"], st["sp"]          # 工程配置里写明了哪路是反馈/设定，优先于按名字猜
        if not (y and sp):
            pairs = guess_pairs(fields)
            if not pairs:
                raise LinkError("no_pair", "认不出哪路是设定值、哪路是反馈", "在下拉框里手动选反馈和设定通道")
            y, sp = pairs[0]
        for f in (y, sp):
            if f not in fields:
                raise LinkError("bad_field", f"没有通道 {f}")
        gn = self._gain_names()
        kp, ki, kd = kp or gn.get("kp"), ki or gn.get("ki"), kd or gn.get("kd")
        m = step_metrics([t for t, _ in w], [float(v[y]) for _, v in w], [float(v[sp]) for _, v in w])
        gains = {k: self.s.params[k] for k in (kp, ki, kd) if k and k in self.s.params}
        hints = tuning_hints(m, gains, kp or "kp", ki, kd)
        return {"y": y, "sp": sp, "pairs": guess_pairs(fields), "gains": {"kp": kp, "ki": ki, "kd": kd},
                "metrics": m.as_dict(), "hints": [h.as_dict() for h in hints]}

    def propose_hint(self, changes: dict, reason: str) -> list[dict]:
        return [self.tools.propose_param_change(k, v, reason, "规则") for k, v in changes.items()]

    # -------------------------------------------------------------- 写回 yaml
    def configure(self, update: dict) -> dict:
        if update.get("repo"):
            import pathlib
            r = pathlib.Path(update["repo"]).expanduser()
            if not (r / ".git").exists():
                raise LinkError("bad_repo", f"{r} 不是 git 仓库", "选你的电赛工程根目录（里面有 Makefile 和 .git）")
            self.gw = Gateway(r, self.emit, **({"runner": self.gw.runner} if hasattr(self.gw, "runner") else {}))
        return llm_mod.save_config(update) | {"repo": str(self.gw.root)}

    def yaml_target(self) -> str:
        names = {p["name"] for p in self.s.schema.params} if self.s.schema else set()
        if not names:
            raise LinkError("no_schema", "还没识别出参数表")
        for f in yamlpar.param_files(self.gw.root):
            txt = f.read_text(encoding="utf-8")
            if all(re.search(rf"\bname:\s*{re.escape(n)}\b", txt) for n in names):
                return f.relative_to(self.gw.root).as_posix()
        raise LinkError("no_yaml", "仓库里找不到包含这组参数的 app.yaml / project.yaml", "确认工作台仓库与板上固件是同一个工程")

    def yaml_writeback(self, path: str | None = None, values: dict | None = None) -> dict:
        path = path or self.yaml_target()
        values = values if values is not None else dict(self.s.params)
        return self.gw.propose_yaml_params(path, values, "把当前板上调好的参数写回为默认值", "user")

    # -------------------------------------------------------------- LLM
    def llm(self):
        """注入的 LLM > 配置的大模型 > 离线规则助手（没填 Key 且不是 Ollama）。"""
        if self._llm:
            return self._llm
        c = llm_mod.load_config()
        if not c.get("api_key") and c.get("provider") != "ollama":
            return OfflineAssistant()
        return llm_mod.OpenAICompat(c)

    def ask(self, text: str) -> str:
        """回答前发 agent_mode（界面标出这次是哪个“脑子”在答）。连不上模型服务时自动退回离线规则助手。"""
        self.loop.llm = self.llm()
        mode = "offline" if isinstance(self.loop.llm, OfflineAssistant) else "llm"
        self.loop.guards = isinstance(self.loop.llm, llm_mod.OpenAICompat)
        self.emit({"type": "agent_mode", "mode": mode, "name": getattr(self.loop.llm, "name", "") or llm_mod.load_config().get("model", "")})
        try:
            return self.loop.ask(text)
        except llm_mod.LLMError as e:
            if mode == "offline" or not e.message.startswith("连不上"):
                raise LinkError("llm", e.message, e.fix) from e
            self.loop.llm = OfflineAssistant()
            self.emit({"type": "agent_mode", "mode": "offline", "name": OfflineAssistant.name, "fallback": e.message})
            return f"（连不上模型服务，改由{OfflineAssistant.name}回答）\n" + self.loop.ask(text)


__all__ = ["AgentService", "GatewayError", "guess_pairs"]
