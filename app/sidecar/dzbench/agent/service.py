"""把 tuning / gateway / llm / loop 组装到一个会话上，供 server 调用（也方便测试时注入假 LLM）。"""
from __future__ import annotations

import itertools
import os
import re
import pathlib
import struct
import time

from .. import config as cfg_mod
from .. import elfsym, hardfault, keil
from ..agent_api import AgentTools
from ..flash import FlashError, Flasher
from ..session import LinkError, Session
from ..transport import ROOT
from . import llm as llm_mod
from . import risk, yamlpar
from .guard import GuardError, TuneGuard, key_samples
from .gateway import Gateway, GatewayError
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
        self.gw = Gateway(root, emit, **({"runner": runner} if runner else {}))
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
        self.loop = AgentLoop(None, {
            "read_telemetry": tools.read_telemetry,
            "list_params": tools.list_params,
            "step_analysis": self.step_analysis,
            "propose_param_change": self.agent_propose_param,
            "tune_context": self.tune_context,
            "observe": lambda reason="": {"status": "observing", "reason": reason},
            "run_step_test": self.run_step_test,
            "rollback_best": self.rollback_best,
            "flash": lambda dry_run=True: self.flasher.flash(dry_run),
            "build_log": self.build_log,
            "decode_hardfault": self.decode_hardfault,
            "read_symbol": self.read_symbol,
            "list_files": lambda glob="**/*": self.gw.list_files(glob),
            "read_file": lambda path: self.gw.read_file(path),
            "propose_edit": lambda path, search, replace, reason: self.gw.propose_edit(path, search, replace, reason, "agent"),
        }, emit, project_rules=rules.read_text(encoding="utf-8") if rules.exists() else "",
            gate=self.gate)

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
            if tool == "flash":
                try:
                    preview = self.flasher.flash(dry_run=True)
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
        if a["tool"] in ("flash",):
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
        self.emit({"type": "tune_round", "verdict": verdict, "metrics": m.as_dict()})
        return {"verdict": verdict, "metrics": m.as_dict()}

    def rollback_best(self, _auto: bool = False) -> dict:
        g = self._guard()
        b = g.best()
        if not b:
            raise LinkError("no_best", "还没有稳定的一轮可回滚")
        applied = {k: self.s.set_param(k, v) for k, v in b.gains.items() if self.s.params.get(k) != v}
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
    def build_log(self, path: str | None = None) -> dict:
        b = self.cfg["build"]
        p = pathlib.Path(path) if path else None
        if p is None and b.get("keil_project"):
            p = (self.gw.root / b["keil_project"]).with_suffix(".dzbench_build.log")
        if not p or not p.exists():
            raise LinkError("no_log", "没有 Keil 编译日志", "先在 Keil 编一次，或配置 build.keil_uv4 + keil_project")
        return keil.parse_log(p.read_text(encoding="utf-8", errors="replace"))

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
