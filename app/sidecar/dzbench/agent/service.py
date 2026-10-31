"""把 tuning / gateway / llm / loop 组装到一个会话上，供 server 调用（也方便测试时注入假 LLM）。"""
from __future__ import annotations

import itertools
import os
import re
import pathlib
import math
import struct
import time
import threading

from .. import config as cfg_mod
from .. import elfsym, hardfault, keil
from ..agent_api import AgentTools
from . import cards, steptools
from .. import pageops
from .. import paths
from ..flash import FlashError, Flasher, schema_hash_of
from ..session import LinkError, Session
from ..transport import ROOT
from . import llm as llm_mod
from . import pretune as pretune_mod, risk, yamlpar
from .guard import GuardError, TuneGuard, key_samples
from .gateway import Gateway, GatewayError
from .journal import BoardMemory, Journal, board_key
from .loop import AgentLoop
from ..tuning.identify import steady_state
from . import codemap, knowledge
from .experiment import StagedSearch, asymmetry, four_segment_metrics, four_segment_plan
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
        self.pretune: pretune_mod.PreTune | None = None   # 调参前问答（人确认过的偏好；只收紧护栏）
        self.staged = StagedSearch()
        self.actions: dict[int, dict] = {}
        self.quick: dict[str, dict] = {}        # quick_start 的题型/仿真对象（确认后接着调参、评分）
        self.chains: dict[str, dict] = {}       # project_chain 的预览结果（project_apply 卡确认时用这一份，不重新跑）
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
            "repo_map": lambda focus="": codemap.render(self.gw.root, focus),
            "remember": lambda note, reason: knowledge.propose_memory(self.gw, note, reason),
            "list_files": lambda glob="**/*": self.gw.list_files(glob),
            "read_file": lambda path: self.gw.read_file(path),
            "propose_edit": lambda path, search, replace, reason: self.gw.propose_edit(path, search, replace, reason, "agent"),
            "update_plan": self.update_plan,
            "board_memory": lambda: self.memory().summary(),
            "progress_get": self.progress_get,
            "project_list": self.project_list,
            "project_open": self.project_open,
            "project_state": lambda code=None: steptools.project_state(self.gw.root, code),
            "flow_preview": lambda step, code, **m: steptools.flow_preview(self.gw.root, step, code, **m),
            "flow_accept": lambda step, code, **m: steptools.flow_accept(self.gw.root, step, code, **m),
            "score_items": lambda path=None: steptools.score_items(self, path),
            "project_chain": self.project_chain,
            "score_run": self.score_run, "score_save": self.score_save, "score_writeback": self.score_writeback,
            "tune_autopilot": self.tune_autopilot,
            "iterate_start": self._iterate_start_agent, "iterate_cancel": self.iterate_cancel,
            "polarity_check": lambda **m: pageops.polarity_check(self.s, m),
            "fft": lambda **m: pageops.fft(self.s, m), "wave_measure": lambda **m: pageops.wave_measure(self.s, m),
            "project_apply": self.project_apply,
            "quick_start": lambda text: self.quick_start(text),
        }, emit, preload=self._preload, project_rules=rules.read_text(encoding="utf-8") if rules.exists() else "",
            gate=self.gate, knowledge=self._knowledge, memory=lambda: knowledge.memory_text(self.gw.root))
        self._kn_seen: set[str] = set()

    def project_list(self) -> dict:
        from .. import project
        return {"projects": project.list_projects(self.gw.root), "current": project.current()}

    def project_open(self, code: str) -> dict:
        """与 op project.open 同一校验；错误按 原因 + 怎么解决 返回给模型。进度推送由侧车轮询 progress.changed 负责。"""
        from .. import project
        try:
            return {"project": project.open_project(self.gw.root, code)}
        except project.ProjectError as e:
            return {"error": e.code, "message": e.msg, "fix": e.fix, "fix_action": e.fix_action}

    def progress_get(self) -> dict:
        """与 op progress.get 同一份推导（dzbench/progress.py）；依赖自检沿用侧车缓存，没有就不报 missing_deps。"""
        src = getattr(self, "progress_src", None)            # 侧车里挂的是 server.Progress（同一份依赖自检缓存）
        if src is not None:
            return src.snapshot()
        from .. import progress
        return progress.derive(progress.collect(self.s, self, None))

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

    def _knowledge(self, text: str) -> list[dict]:
        """每次提问现读 docs/agent-knowledge（文件少、很快），新对话时 reset 已附过的记录。"""
        if len(self.loop.messages) <= 1:
            self._kn_seen = set()
        return knowledge.match(text, knowledge.load(self.gw.root), self._kn_seen)

    def memory(self) -> BoardMemory:
        return BoardMemory(board_key(self.s.schema_hash, self.s.board_uid), self._project_path())

    @staticmethod
    def _project_path() -> str | None:
        from .. import project
        cur = project.current()
        return cur["path"] if cur else None

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
        port = self.s.port or ""
        return (port.startswith("sim:") and not port.endswith("+hw")) or bool(getattr(self.s, "replay", None))

    def gate(self, tool: str, args: dict, run):
        """loop 每次调工具都经过这里：auto 直接跑；log 跑完记审计；human 变成待点击的动作卡；forbid 拒绝。"""
        t = risk.tier(tool, self.sim)
        if t == risk.FORBID:
            risk.audit(tool, args, t, "denied")
            raise GatewayError("forbidden", f"{tool} 是禁止操作，Agent 永远不能执行")
        if t == risk.HUMAN:
            dup = next((a for a in self.actions.values() if a["tool"] == tool and a["args"] == args), None)
            if dup:                                          # 同一操作的卡还挂着（如 quick_start 已出 project_apply 卡，模型又调一次）→ 不重复出卡
                return {"status": "pending_human_click", "action_id": dup["id"], "note": "这张确认卡已经在界面上了，等用户点，不要再调"}
            aid = next(self._aid)
            preview = cards.build(self, tool, args)          # 卡片内容：人话 + 旧→新，见 agent/cards.py
            self.actions[aid] = {"id": aid, "tool": tool, "args": args, "run": run, "t": time.monotonic()}
            self.emit({"type": "agent_action", "id": aid, "tool": tool, "args": args, "preview": preview, "sim": self.sim,
                       "as_hw": (self.s.port or "").endswith("+hw"),
                       "ttl_s": self.ARM_TTL_S if tool in self.EXPERIMENTS else None})
            risk.audit(tool, args, t, "pending_human")
            return {"status": "pending_human_click", "action_id": aid, "note": "需要用户在界面上点“执行”"}
        r = run()
        if t == risk.LOG:
            risk.audit(tool, args, t, "ok")
        return r

    def project_chain(self, code: str, **m) -> dict:
        r = steptools.project_chain(self.gw.root, code, **m)
        self.chains[code] = r
        return {k: v for k, v in r.items() if k != "batch"} | {"to_write": [s for s, _ in r["batch"]]}

    def _preload(self) -> str:
        """第一轮附上：仓库地图（顶层目录 + 一句话用途）、板卡、项目、仿真对象。几百字，换掉 3~6 次只读调用。"""
        from .. import ports as ports_mod
        root = pathlib.Path(self.gw.root)
        st = steptools.project_state(root, None)
        cm = {"apps": "应用固件（每个子目录一个应用）", "examples": "内置例题（只读；用户工程在 $DZBENCH_HOME/projects/）", "boards": "板卡定义 board.yaml",
              "firmware": "通用固件库（algo/drivers/proto，冻结层）", "tools": "命令行工具（req/scheme/alloc/gen/keil_inject）", "subsys": "子系统库"}
        lines = [f"- {k}/：{v}" for k, v in cm.items() if (root / k).is_dir()]
        try:
            sims = ", ".join(ports_mod.sim_apps())
        except Exception:  # noqa: BLE001
            sims = ""
        return ("仓库地图：\n" + "\n".join(lines) + f"\n板卡：{', '.join(st.get('boards') or []) or '无'}"
                + f"\n项目：{', '.join(st.get('projects') or []) or '无'}" + (f"\n仿真对象：{sims}" if sims else "")
                + f"\n当前连接：{self.s.port or '未连接'}")

    def quick_start(self, text: str) -> dict:
        """一句话起项目：解析 → ①–⑤ 整链预览（只写暂存区）→ 一张确认卡（方案 + 引脚表）。
        用户点确认 → 写入项目 → 连仿真板 → 一键起步调参 → 评分。返回 action_id 给界面。"""
        sp = steptools.quick_spec(text)
        sp["code"] = steptools.fresh_code(self.gw.root, sp["code"])     # 新建一律落新目录，不复用旧项目/示例（#39）
        d = steptools._flow(self.gw.root).home / sp["code"]; d.mkdir(parents=True, exist_ok=True)
        (d / "problem.txt").write_text(sp["problem"], encoding="utf-8")
        ch = self.project_chain(sp["code"], src=str(d / "problem.txt"), mcu=sp["mcu"])
        if ch.get("stopped_at"):
            return {"spec": sp, "chain": ch, "action_id": None}
        self.quick[sp["code"]] = sp
        card = self.gate("project_apply", {"code": sp["code"]}, lambda: None)
        return {"spec": sp, "chain": ch, "action_id": card.get("action_id"),
                "note": "确认卡已出（含方案与引脚表）；用户点确认后自动写项目、上仿真、调参、评分。不要再调 project_apply。"}

    def _quick_after(self, code: str, written: dict) -> dict:
        """确认后接着跑：仿真板 → 一键起步调参 → 评分（仿真里都是 log 级，不再出卡）。"""
        sp = self.quick.pop(code)
        if not self.s.port:
            self.s.connect(sp["sim"], 115200, log=False)
            t0 = time.monotonic()
            while (self.s.schema_hash is None or not self.s.params) and time.monotonic() - t0 < 10:
                time.sleep(0.05)
        if not self.sim:
            return {"written": written, "stopped": "不在仿真板上：实机调参每轮要人确认，没有自动连跑"}
        tune = self.tune_autopilot(4)
        items = (steptools._yaml(paths.project_dir(self.gw.root, code) / "requirements.yaml").get("items") or [])
        score = self.score_run(str(items[0]["id"]), n=1, band=sp["band"]) if items else {"error": "没有评分项"}
        return {"written": written, "sim": self.s.port, "tune": tune, "score": score}

    def project_apply(self, code: str) -> dict:
        r = self.chains.pop(code, None)
        if not r or not r["batch"]:
            raise GatewayError("no_chain", f"{code} 还没有可写入的预览", "先 project_chain")
        out = steptools.project_apply(self.gw.root, code, r["batch"])
        if code in self.quick and not out.get("failed"):
            return self._quick_after(code, out)
        return out

    # -------------------------------------------------------------- 评分：跑 N 次 → 存证据 → 回写
    def score_run(self, item: str, n: int = 3, path: str | None = None, band: float | None = None, hold_s: float = 0.3) -> dict:
        """按 step_test 跑 N 次，每次用评分页同一验收定义（accept.py）判；最差一次算数。结果留在内存给 score_save。"""
        from .. import scoring
        from ..accept import accept_eval
        it = next((x for x in scoring.items(self, {"path": path} if path else {})["items"] if x["id"] == str(item)), None)
        if not it:
            raise GatewayError("no_item", f"没有评分项 {item}", "先 score_items 看编号")
        specs = {a.get("name"): a for a in (self.s.schema.d.get("accept") or [])} if self.s.schema else {}
        name = it.get("accept") or next((x.get("accept") for x in it["metrics"] if x.get("accept")), None)
        # 人/模型按题目原文给的 band 优先；否则只认评分项点名的规格（不拿别的示例规格凑数）
        spec = ({"name": f"item{item}", "band": float(band), "hold_s": float(hold_s)} if band is not None else None) or specs.get(name)
        if not spec:
            raise GatewayError("no_accept", f"评分项 {item} 没对上 schema 的 accept 规格", "在 yaml 的 accept: 段写 band/hold_s 并在评分项写 accept: 名字；或按题目原文给 band（允许误差）")
        st = self.step_cfg() or {}
        yk, sk = spec.get("y") or st.get("y"), spec.get("sp") or st.get("sp")
        runs = []
        for k in range(1, max(1, min(int(n), 10)) + 1):
            v = self.run_step_test()
            w = self.s.window(float(st.get("hold_s", 1.5)) * (5 if int(st.get("segments", 1)) == 4 else 1) + float(st.get("pre_s", 0.6)))
            t = [a for a, _ in w]; y = [float(b[yk]) for _, b in w]; sp = [float(b[sk]) for _, b in w]
            if int(st.get("segments", 1)) != 4:        # 单阶跃：只判阶跃之后那段（之前的 low 段是上一轮的尾巴）
                j = max((i for i in range(1, len(sp)) if sp[i] != sp[i - 1]), default=0)
                t, y, sp = t[j:], y[j:], sp[j:]
            r = accept_eval(t, y, sp, spec) or {"pass": False, "why": "窗口太短"}
            csv = "t,%s,%s\n" % (yk, sk) + "".join(f"{a:.4f},{b:.6g},{c:.6g}\n" for a, b, c in zip(t, y, sp))
            runs.append({"n": k, "csv": csv, "result": r, "verdict": v["verdict"].get("action")})
        ok = sum(1 for r in runs if r["result"].get("pass"))
        res = "pass" if ok == len(runs) else ("fail" if ok == 0 else "partial")
        self.score_runs = getattr(self, "score_runs", {}) | {str(item): {"runs": runs, "result": res, "spec": spec.get("name", name), "code": self._code_of(path)}}
        return {"item": str(item), "spec": spec, "runs": [{"n": r["n"], "pass": r["result"].get("pass"), **{k: r["result"].get(k) for k in ("t_arrive_s", "err_max", "why") if k in r["result"]}} for r in runs],
                "passed": f"{ok}/{len(runs)}", "result": res}

    def _code_of(self, path=None) -> str:
        from .. import scoring
        return scoring.items(self, {"path": path} if path else {})["code"]

    def score_save(self, item: str) -> dict:
        from .. import scoring
        r = getattr(self, "score_runs", {}).get(str(item))
        if not r:
            raise GatewayError("no_runs", f"评分项 {item} 还没跑", "先 score_run")
        out = scoring.save(self, {"code": r["code"], "item": str(item), "layer": "sim" if self.sim else "bench",
                                  "runs": [{k: x[k] for k in ("n", "csv", "result")} for x in r["runs"]],
                                  "summary": {"result": r["result"], "spec": r["spec"]}})
        r["dir"] = out.get("dir")                       # 回写默认指向刚存的证据
        return out

    def score_writeback(self, item: str, dir: str | None = None, note: str = "") -> dict:
        """先拿 diff（卡片里展示），确认后用同一 sha 写，文件期间被改过就拒绝。"""
        from .. import scoring
        r = getattr(self, "score_runs", {}).get(str(item)) or {}
        dir = dir or r.get("dir")
        if not dir:
            raise GatewayError("no_evidence", f"评分项 {item} 还没存证据", "先 score_save")
        m = {"item": str(item), "dir": dir, "layer": "sim" if self.sim else "bench", "result": r.get("result", "fail"), "note": note}
        d = scoring.writeback(self, m)
        return scoring.writeback(self, m | {"confirm": True, "sha": d.get("sha")}) if d.get("sha") else d

    # -------------------------------------------------------------- 仿真自动调参
    # -------------------------------------------------------------- #38 自动迭代（板上阶跃 step_result）
    def iterate_plan(self, params: list | None = None, target: float | None = None, dur_ms: int = 2000, ch: int = 0) -> dict:
        """按 link_schema.json 拼迭代方案：参数的 [min, max] / max_delta、阶跃通道（link.step）。"""
        sch = self.s.schema
        if not sch:
            raise GatewayError("no_schema", "还没识别出参数表", "先连上板子等心跳")
        steps = sch.step
        if not steps or not 0 <= int(ch) < len(steps):
            raise GatewayError("no_step_channel", "这个应用没配阶跃通道（app.yaml link.step）", "固件升到 dzctl 0.13.0 并在 app.yaml 加 link.step")
        names = list(params or self._gains().keys())
        bad = [n for n in names if n not in sch.param_index]
        if bad or not names:
            raise GatewayError("bad_param", f"没有这些参数：{bad or '（空）'}", "用 list_params 看参数名")
        st = steps[int(ch)]
        if target is None:
            raise GatewayError("need_target", "要给阶跃目标值 target（物理单位）", f"例如量程 {st['range']:g} 的 1/4")
        return {"ch": int(ch), "target": float(target), "dur_ms": int(dur_ms), "abs_tol": float(st["abs_tol"]),
                "params": [dict(sch.params[sch.param_index[n]]) for n in names]}

    def iterate_card(self, args: dict) -> dict:
        from .iterate import Iterator, SessionIO
        plan = self.iterate_plan(**args)
        io = SessionIO(self.s)
        return Iterator.card(plan, io.read_params(), io.order(), self.sim)

    ITER_ROUNDS: int | None = None                               # 测试用：缩短轮数上限（None = Iterator 默认 实机 8 / 仿真 20）

    def iterate_start(self, **args) -> dict:
        """一张批量确认卡（参数范围 / max_delta / 起始值 + hash / 预算）→ 人点一次 → 后台自动迭代到达标或停止条件。"""
        self.iterate_plan(**args)                                # 先校验，错了不出卡

        def run():
            from .iterate import Iterator, SessionIO
            th = getattr(self, "iter_thread", None)
            if th and th.is_alive():
                raise GatewayError("iterate_running", "已经在自动迭代", "先点“停止迭代”")
            it = Iterator(SessionIO(self.s), self.iterate_plan(**args), self.sim, emit=self._iter_emit,
                          **({"max_rounds": self.ITER_ROUNDS} if self.ITER_ROUNDS else {}))
            self.iterator, self.iter_result = it, None
            self.iter_thread = threading.Thread(target=self._iter_run, args=(it,), daemon=True, name="iterate")
            self.iter_thread.start()
            return {"status": "started", "budget": {"time_s": it.budget_s, "rounds": it.max_rounds}}
        return self.gate("iterate_start", args, run)

    def _iterate_start_agent(self, **args) -> dict:
        """#53 Agent 走的 iterate_start：仿真里直接跑完（等后台线程到停止条件），把结果和“采用最好参数”卡一起回给模型；
        实机先出批量确认卡（pending），点了以后同样在结束时出最好参数卡。"""
        r = self.iterate_start(**args)
        th = getattr(self, "iter_thread", None)
        if r.get("status") != "started" or th is None:
            return r
        th.join(float(r["budget"]["time_s"]) + 30)
        res = dict(self.iter_result or {"reason": "running", "message_zh": "迭代还没结束"})
        res["instruction"] = ("迭代已结束，界面上已出“采用最好参数”确认卡（best_card）。最终回复：总结最好一轮的指标、各项差距和下一步，"
                              "告诉用户点卡上的确认即可写入；不要以提问结束。") if res.get("best_card") else ""
        return res

    def iterate_apply_best(self, params: dict, iter: int | None = None, params_hash: str | None = None) -> dict:  # noqa: A002
        """“采用最好参数”卡被人确认：把最好一轮的参数写回板子（逐个 set_param，校验/限幅/急停锁都在 Session）。"""
        applied = {}
        cur = self.s.params
        for n, v in params.items():
            if cur.get(n) is None or abs(float(cur[n]) - float(v)) > 1e-9:
                applied[n] = self.s.set_param(n, float(v), verify=True)["applied"]
        return {"status": "applied", "iter": iter, "params_hash": params_hash, "applied": applied,
                "next_zh": "已写入最好一轮参数；需要掉电保持就点“保存参数”"}

    CARD_ONLY = {"iterate_apply_best": iterate_apply_best}       # 只由服务端出卡、模型调不到的动作（不进工具表）

    def _best_card(self, res: dict) -> int | None:
        """迭代停止（任何原因）且有最好一轮 → 出“采用最好参数”卡（always human）。"""
        best = res.get("best")
        if not best:
            return None
        r = self.gate("iterate_apply_best", {"params": best["params"], "iter": best["iter"], "params_hash": best["params_hash"]},
                      lambda: None)
        return r.get("action_id")

    def _iter_emit(self, e: dict) -> None:
        if e.get("type") == "iterate.round" and e.get("valid"):
            self.memory().add("iterate", iter=e["iter"], params=e["params"], score=e.get("score"), passed=(e.get("pass") or {}).get("all"))
        self.emit(e)

    def _iter_run(self, it) -> None:
        try:
            res = it.run()
        except Exception as e:  # noqa: BLE001  后台线程不能把异常漏掉
            res = {"type": "iterate.stopped", "reason": "error", "message_zh": f"{type(e).__name__}: {e}"}
            self.emit(res)
        try:
            res["best_card"] = self._best_card(res)
        except Exception as e:  # noqa: BLE001
            res["best_card"], res["best_card_error"] = None, str(e)
        self.iter_result = res

    def iterate_cancel(self) -> dict:
        it = getattr(self, "iterator", None)
        if it is None:
            return {"ok": False, "message_zh": "没有正在进行的自动迭代"}
        it.stop()
        try:
            self.s.step_stop()
        except Exception:  # noqa: BLE001
            pass
        th = getattr(self, "iter_thread", None)
        if th:
            th.join(5)
        return {"ok": True, "result": self.iter_result}

    def tune_autopilot(self, rounds: int = 6) -> dict:
        """仅仿真：提议→采纳→阶跃→护栏判，直到护栏说 done/stop 或轮数用完；最后回到最好的一轮。实机每次写都要人点，不走这里。"""
        if not self.sim:
            raise GatewayError("hw_needs_human", "实机调参每次写参数都要你确认，不能自动连跑", "用逐轮模式：run_step_test → 提议 → 你点采纳")
        log = []
        v = self.run_step_test()["verdict"]
        log.append({"round": v.get("round"), "action": v.get("action"), "gains": self._gains(), "score": v.get("score")})
        for _ in range(max(1, min(int(rounds), 20))):
            if v.get("action") in ("done", "stop", "rollback"):
                break
            p = self.rule_round()
            if p.get("id") is None:
                log.append({"stop": p.get("reason")})
                break
            self.verify_groups = {k: g for k, g in getattr(self, "verify_groups", {}).items() if k != p["id"]}
            name = self.tools.pending[p["id"]]["name"]
            self.tools.decide(p["id"], True)
            v = self.run_step_test()["verdict"]
            log.append({"round": v.get("round"), "change": {name: p.get("value")}, "action": v.get("action"), "score": v.get("score")})
        g = self._guard()
        b = g.best()
        best = {"round": b.n, "gains": b.gains, "metrics": b.metrics, "score": round(b.score, 4)} if b else None
        if v.get("action") != "done" and g.rounds:
            self.rollback_best(_auto=True)
        return {"rounds": log, "final": v.get("action"), "best_round": best, "gains_now": self._gains(),
                "passed": v.get("action") == "done"}

    def _flow_next(self, code: str) -> dict | None:
        """项目步写入后，顺手把下一步预览跑好并出确认卡（省一次“再问 Agent / 点运行”）。
        下一步缺人给的输入（题目、CubeMX 工程）或预览失败 → 只报告，不出卡。"""
        st = steptools.project_state(self.gw.root, code)
        nxt = st.get("next_step")
        if not nxt or nxt in steptools.NEEDS:
            return {"next_step": nxt, "needs": st.get("next_needs")} if nxt else None
        try:
            pv = steptools.flow_preview(self.gw.root, nxt, code)
        except GatewayError as e:
            return {"next_step": nxt, "error": e.message, "fix": e.fix}
        if pv.get("rc"):
            return {"next_step": nxt, "preview": pv}
        card = self.gate("flow_accept", {"step": nxt, "code": code}, lambda: None)
        return {"next_step": nxt, "preview": pv, "action_id": card.get("action_id")}

    def action_decide(self, aid: int, accept: bool) -> dict:
        a = self.actions.pop(aid, None)
        if not a:
            raise LinkError("no_action", f"动作 {aid} 不存在或已处理")
        risk.audit(a["tool"], a["args"], risk.HUMAN, "accepted" if accept else "rejected")
        if not accept:
            return {"id": aid, "status": "rejected"}
        args = dict(a["args"])
        if a["tool"] in self.EXPERIMENTS:               # 一次点击只放行一次实验；卡片放久了板子状态可能已变 → 过期重来
            if time.monotonic() - a.get("t", 0) > self.ARM_TTL_S:
                raise LinkError("arm_expired", f"这张确认卡已超过 {self.ARM_TTL_S:.0f} s，板子状态可能变了，没有执行", "让 Agent 重新发起一次")
            pa = self.prearm()
            if pa["failed"]:
                raise LinkError("prearm", "实验前检查没通过：" + "；".join(pa["failed"]), "处理后让 Agent 重新发起")
        if a["tool"] in ("flash", "flash_rollback"):
            args["dry_run"] = False                      # 人点了“确认烧录”才真烧
        try:
            out = {"id": aid, "status": "done", "result": (self.loop.handlers.get(a["tool"]) or self.CARD_ONLY[a["tool"]].__get__(self))(**args)}
            if a["tool"] == "flow_accept":
                out["next"] = self._flow_next(args["code"])
            return out
        except (FlashError, GuardError, LinkError) as e:
            raise LinkError(getattr(e, "code", "action"), e.message, getattr(e, "fix", "")) from e

    # -------------------------------------------------------------- 调参护栏
    def _guard(self) -> TuneGuard:
        proj = self._project_path()
        if self.guard is None or self.guard.sim != self.sim or getattr(self, "_guard_proj", None) != proj:
            self._guard_proj = proj            # 换项目 = 新的调参历史（不带上个项目的 best / 初值，#39）
            b = {p["name"]: (p["min"], p["max"]) for p in (self.s.schema.params if self.s.schema else [])}
            t = self.cfg["tune"]
            self.guard = TuneGuard(b, self.sim, limits={"vbat_min": t["vbat_min"], "temp_max": t["temp_max"]},
                                   max_rounds=t["max_rounds_sim"] if self.sim else min(int(t["max_rounds_hw"]), 10),
                                   weights=t.get("weights", "balanced"),
                                   max_step_ratio=(float(t["max_step_ratio"]) if t.get("max_step_ratio") else None))
            if self.pretune:
                self.pretune.apply(self.guard)
            self.staged = StagedSearch(order=tuple(self._gains()) or ("kp", "ki", "kd"))
        return self.guard

    # -------------------------------------------------------------- 调试探针设置（flash.tool / probe_kind / probe）
    def probe_config_get(self, list_probes: bool = True) -> dict:
        from .. import probes
        f = self.cfg["flash"]
        proj = cfg_mod._read(self.gw.root / "dzbench.json").get("flash", {}) if self.gw.root else {}
        out = {"tool": f.get("tool") or "pyocd", "probe_kind": f.get("probe_kind") or "", "probe": f.get("probe") or "",
               "target": f.get("target"), "tools": list(probes.TOOLS), "kinds": list(probes.PROBE_KINDS),
               "status": probes.tool_status(f),
               "project_overrides": [k for k in cfg_mod.MACHINE_FLASH_KEYS if k in proj]}   # 工程文件写了的键，本机设置会被它盖住
        if list_probes:
            out["list"] = probes.list_probes_for(out["tool"], f)
        return out

    def probe_config_set(self, values: dict) -> dict:
        from .. import probes
        v = {k: values.get(k) for k in cfg_mod.MACHINE_FLASH_KEYS if k in values}
        if v.get("tool") and v["tool"] not in probes.TOOLS:
            raise LinkError("bad_tool", f"不认识烧录工具 {v['tool']}")
        if v.get("probe_kind") and v["probe_kind"] not in probes.PROBE_KINDS:
            raise LinkError("bad_probe_kind", f"不认识探针类型 {v['probe_kind']}")
        cfg_mod.save_machine_flash(v)
        new = cfg_mod.load(self.gw.root)["flash"]             # 重新分层合并（工程文件 / 环境变量仍优先）
        self.cfg["flash"].clear(); self.cfg["flash"].update(new)   # Flasher 持有同一个 dict，原地改
        self.watch_stop()                                     # 旧后端的变量读取连接作废
        return self.probe_config_get(list_probes=False)

    # -------------------------------------------------------------- 调参前问答（缺口 9）
    def pretune_get(self) -> dict:
        return {"questions": pretune_mod.QUESTIONS, "current": pretune_mod.to_dict(self.pretune)}

    def pretune_set(self, answers: dict | None) -> dict:
        """界面对话框里人点“确认” = 已人工确认。answers 为 None / 空 = 清掉偏好。护栏重建（新偏好从下一轮起生效）。"""
        if not answers:
            self.pretune = None; self.guard = None
            self.loop.note("用户清掉了调参前问答的偏好，回到默认调参策略。")
            return {"current": None, "applied": []}
        self.pretune = pretune_mod.from_answers(answers)
        self.guard = None
        applied = self.pretune.apply(TuneGuard({}, self.sim, weights="balanced"))   # 预览改了什么；真护栏在 _guard 里重建时套用
        self.loop.note(self.pretune.prompt_text())
        return {"current": pretune_mod.to_dict(self.pretune), "applied": applied}

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
        if self.sim and r.get("id") is not None:     # 仿真：采纳即自动验证阶跃（省一次点击）；实机仍由 run_step_test 出确认卡
            self.verify_groups = getattr(self, "verify_groups", {}) | {r["id"]: {r["id"]}}
            r = r | {"verify_step": "采纳后自动做一次验证阶跃"}
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
        """按对象选阶跃实验配置：dzbench.json 的 step_test（单个或列表，优先）+ step_tests（按工程名的字典）。
        只考虑 y/sp 两个通道都在当前遥测里的；多个都符合时（例如好几个对象都有 sp_a/spd_a）不靠顺序猜：
        step_test > 名字等于当前仿真应用的 step_tests 项 > gains 里的参数在板上都存在的 > 先出现的。
        还没识别出 schema 时取第一个。"""
        st = self.cfg.get("step_test")
        cands = [(200, c) for c in (st if isinstance(st, list) else [st] if st else [])]
        app = (getattr(self.s, "port", "") or "").split(":", 1)[-1].split("+")[0] if str(getattr(self.s, "port", "")).startswith("sim:") else ""
        cands += [(100 if k == app else 0, c) for k, c in (self.cfg.get("step_tests") or {}).items()]
        fields = {f["name"] for f in self.s.schema.fields} if self.s.schema else set()
        params = {p["name"] for p in self.s.schema.params} if self.s.schema else set()
        best, best_sc = None, -1
        for pri, c in cands:
            if not isinstance(c, dict):
                continue
            if not fields:
                return c
            if c.get("y") not in fields or c.get("sp") not in fields:
                continue
            g = list((c.get("gains") or {}).values())
            sc = pri + (10 if g and all(x in params for x in g) else 0)
            if sc > best_sc:
                best, best_sc = c, sc
        return best

    START_CMDS = ("T", "P", "G", "S")     # 'R' 不在里面：它同时是“解除急停”，Agent/自动实验永远不发

    EXPERIMENTS = ("run_step_test", "run_sweep_test", "run_relay_tune", "open_loop_test", "score_run")
    ARM_TTL_S = 120.0
    LINK_STALE_S = 1.0

    def prearm(self) -> dict:
        """ArduPilot 式解锁前检查（实机实验前；确认卡预览里显示，点击时再查一次）：
        急停锁存、链路新鲜、实验通道在遥测里、电池/温度门限、板上增益回读 = 侧车记录（防止板子被复位/别的工具改过）。"""
        failed, checked = [], []
        if self.s.tx_locked:
            failed.append("急停已锁存")
        age = time.monotonic() - (self.s.last_rx or 0)
        checked.append("link")
        if age > self.LINK_STALE_S:
            failed.append(f"已经 {age:.1f} s 没收到板子数据")
        st = self.step_cfg()
        w = self.s.window(0.5)
        last = w[-1][1] if w else {}
        if st:
            miss = [st[k] for k in ("y", "sp") if st.get(k) and st[k] not in last]
            checked.append("channels")
            if miss:
                failed.append(f"遥测里没有实验通道 {', '.join(miss)}")
        else:
            failed.append("没配置 step_test")
        env = self._guard()._env_stop(last)
        checked.append("env")
        if env:
            failed.append(env)
        if self.s.schema:
            checked.append("readback")
            for k, v in self._gains().items():
                try:
                    rb = self.s.read_param(k)
                except Exception as e:  # noqa: BLE001
                    failed.append(f"读不回 {k}：{e}")
                    continue
                if v is not None and abs(rb - v) > 1e-6 * max(1.0, abs(v)):
                    failed.append(f"{k} 板上是 {rb:g}，本地服务记录是 {v:g}（板子复位过或被改过）")
        return {"ok": not failed, "failed": failed, "checked": checked}

    def step_start(self, st: dict) -> None:
        """实验前的准备命令（如 2026H：'T'1 选测试 → 'G' 开始）。运行中再发会被板子状态机忽略。
        上一轮已到 DONE（限时到了）时需要复位，但复位帧也是解除急停，所以只有在“没急停锁存 + 遥测 state 正是 DONE”
        时才发 'R'；急停状态下直接拒绝做实验。"""
        if not st.get("start"):
            return
        if self.s.tx_locked or self.s.estop_cause or (self.s.hb_status or 0) & (1 << 10):   # 板子已报急停（心跳还没让本地锁上）也拒绝
            raise LinkError("estop", "急停已锁存：不做实验", "人工检查后按“解除急停”")
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
        spw = [float(v[st["sp"]]) for _, v in w]
        k = max((i for i in range(1, len(spw)) if spw[i] != spw[i - 1]), default=None)   # 最后一次设定值跳变 = 阶跃时刻
        ss = steady_state(t, ys, t_step=t[k] if k else None, window_s=min(0.3, hold / 3),
                          span_ref=abs(spw[k] - spw[k - 1]) if k else None,
                          base_s=hold / 2 if segs is not None else None)   # 四段：基线 = 上一段后半（同 four_segment_metrics）
        verdict = g.record(m, self._gains(), w[-1][1] if w else {})
        verdict["steady"] = ss
        if not ss["steady"] and ss["reason"] in ("still_drifting", "warming_up"):
            verdict["advice"] = "OBSERVE：实验结束时还没稳（%s），先加长 step_test.hold_s 再判断，不要据此改参数" % ss["text"]
        if segs is not None:
            verdict["segments"], verdict["asymmetry"] = segs, asymmetry(segs)
        self._save_best_snapshot(g, verdict)
        if verdict["action"] == "rollback" and verdict.get("auto"):
            verdict["rolled_back"] = self.rollback_best(_auto=True)
        self.last_verdict = verdict
        self.memory().add("verdict", round=verdict.get("round"), action=verdict.get("action"), gains=self._gains(),
                          overshoot_pct=round(m.overshoot_pct, 1), settling_s=m.settling_s)
        self.emit({"type": "tune_round", "verdict": verdict, "metrics": m.as_dict()})
        return {"verdict": verdict, "metrics": m.as_dict()}

    RELAY_MAX_S = 30.0

    def run_relay_tune(self) -> dict:
        """无初值一键起步：设定值停在 step_test.high，固件把 PID 输出换成继电器 ±amp（dzctl 0.7.0，板端限幅 + 超时自动恢复），
        记录 y → relay_analyze 得 Ku/Pu → Tyreus–Luyben 增益 → 提议卡（你采纳才写入）。配置 step_test.relay = {loop, amp, hyst, timeout_s}。"""
        from ..tuning.relay import gains as relay_gains, relay_analyze
        st = self.step_cfg()
        if not st:
            raise LinkError("no_step_test", "没配置（或没有匹配当前遥测的）阶跃实验", "继电起步复用 step_test 的通道和工作点")
        rc = st.get("relay") or {}
        amp = float(rc.get("amp", 0.3)); hyst = float(rc.get("hyst", 0.0)); loop = int(rc.get("loop", 0))
        dur = min(float(rc.get("timeout_s", 12.0)), self.RELAY_MAX_S)
        self.step_start(st)
        sp = st["high"]
        t0 = time.monotonic() + 0.8
        while time.monotonic() < t0:                    # 先把设定值送到位，让对象停在工作点附近
            self.s.send_data(int(st["id"]), struct.pack(st["fmt"], *sp)); time.sleep(0.1)
        w0 = self.s.window(0.05); tb = w0[-1][0] if w0 else 0.0
        r = self.s.relay(loop, amp, hyst, dur)
        if not r["ok"]:
            return {"ok": False, "why": r["why"]}
        try:
            t_end = time.monotonic() + dur
            while time.monotonic() < t_end:
                if self.s.tx_locked:
                    break
                self.s.send_data(int(st["id"]), struct.pack(st["fmt"], *sp)); time.sleep(0.1)
        finally:
            self.s.relay_stop()                         # 板子超时也会自己恢复；这里是双保险
        w = [x for x in self.s.window(dur + 1.0) if x[0] > tb]
        t = [a for a, _ in w]; ys = [float(v[st["y"]]) for _, v in w]
        span = (max(ys) - min(ys)) if ys else 0.0
        res = relay_analyze(t, ys, amp=amp, noise_band=max(hyst, 0.02 * span))
        if not res["ok"]:
            return res
        g = relay_gains(res["ku"], res["pu"], str(rc.get("rule", "tl")))
        names = st.get("gains") or {}
        changes = {names[k]: round(g[k], 6) for k in ("kp", "ki", "kd") if names.get(k)}
        props = self.propose_hint(changes, f"继电起步：Ku={res['ku']:.4g} Pu={res['pu']:.3g}s，{g['rule'].upper()} 规则", source="继电起步") if changes else []
        from ..tuning.relay import RULES
        alts = {r: {k: round(v, 6) for k, v in relay_gains(res["ku"], res["pu"], r).items() if k != "rule"} for r in RULES}
        out = {"ok": True, "ku": res["ku"], "pu": res["pu"], "cycles": res["cycles"], "gains": g, "proposals": props,
               "rules": {r: {"desc": RULES[r], **alts[r]} for r in RULES}}   # 同一组 Ku/Pu 换规则：前端可选另一套再提议
        self.emit({"type": "relay_result", **{k: v for k, v in out.items() if k != "proposals"}})
        return out

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

    BEST_SNAPSHOT = "自动-最好一轮"

    def _save_best_snapshot(self, g: TuneGuard, verdict: dict) -> None:
        """最好一轮变了就落盘成快照（侧车重启 / 护栏重置后仍能在快照页一键恢复）。失败只记 verdict，不影响实验。"""
        b = g.best()
        if not b or not self.s.schema or getattr(self, "_best_saved", None) == (id(g), b.n):
            return
        try:
            from .. import snapshots
            snapshots.save(self.s.schema.hash, self.BEST_SNAPSHOT, {**self.s.params, **b.gains},
                           f"第 {b.n} 轮，得分 {b.score:.4g}（护栏自动记录）")
            self._best_saved = (id(g), b.n)
            verdict["best_snapshot"] = self.BEST_SNAPSHOT
        except OSError as e:
            verdict["best_snapshot_error"] = str(e)

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

    def sim_search(self, y: str, u: str, seconds: float = 5.0, strategy: str = "pso", wide: bool = False, top_k: int = 3) -> dict:
        """缺口第 2 项接到界面：最近 seconds 秒的开环阶跃（u 跳变）→ 辨识 FOPDT → 仿真 PSO/分阶段 → top-k。
        候选只返回，不写板子；实机验证走 propose（提议卡 → 你确认 → 限幅写入），每次一个候选。"""
        from ..tuning.search import search_from_step
        w = [x for x in self.s.window(seconds) if y in x[1] and u in x[1]]
        if len(w) < 10:
            raise LinkError("no_data", f"最近 {seconds:g} s 没有同时含 {y} 和 {u} 的数据", "开环下给控制量一个台阶并录 2–5 s，再点仿真搜索")
        gn = self._gain_names()
        seed = {k: float(self.s.params.get(n, 0.0)) for k, n in gn.items()}
        try:
            r = search_from_step([x[0] for x in w], [float(x[1][y]) for x in w], [float(x[1][u]) for x in w],
                                 seed=seed, strategy=strategy, wide=bool(wide), top_k=int(top_k))
        except (ValueError, GuardError) as e:
            raise LinkError("search_failed", str(e), "确认是开环台阶数据、反馈和控制量通道选对")
        except Exception as e:  # noqa: BLE001  identify 的 IdentError 等带中文原因
            raise LinkError("search_failed", str(e), "确认是开环台阶数据、反馈和控制量通道选对")
        return r | {"names": gn}

    def propose_hint(self, changes: dict, reason: str, verify_step: bool = False, source: str | None = None) -> list[dict]:
        """verify_step=True（仿真搜索“上板验证”勾了自动阶跃）：这组提议卡全部被你采纳后，自动做一次阶跃实验，
        TuneGuard 判定（继续/达标/回滚）走 tune_round 事件显示。有一张被拒 → 这组作废、不做实验。"""
        src = source or ("仿真搜索" if verify_step else "规则")
        out = [self.tools.propose_param_change(k, v, reason or "阶跃分析规则建议", src) for k, v in changes.items()]
        if verify_step and out:
            if not hasattr(self, "verify_groups"):
                self.verify_groups = {}
            ids = {r["id"] for r in out}
            for i in ids:
                self.verify_groups[i] = ids
        return out

    def verify_after_decide(self, pid: int, result: dict) -> bool:
        """提议卡决定后调用；返回 True = 这组都已采纳，该做验证阶跃了（由调用方在后台跑 run_step_test）。"""
        groups = getattr(self, "verify_groups", {})
        ids = groups.pop(pid, None)
        if ids is None:
            return False
        if result.get("status") not in ("applied", "ok", "clamped"):   # set_param 的 status 会盖掉 "applied"（以前整组验证从不触发）
            for i in ids:
                groups.pop(i, None)
            return False
        return not any(i in groups for i in ids)

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
        """注入的 LLM（测试里的脚本化模型）> 配置的大模型；没配 Key（且不是 Ollama）→ None。"""
        if self._llm:
            return self._llm
        return llm_mod.build(emit=self.emit)

    def ask(self, text: str) -> str:
        """回答前发 agent_mode。没配模型 / 连不上 → 发 agent_unreachable（界面给“重试 / 设置”），
        不再有规则助手兜底：调参、示波、急停、阶跃测试、评分页都不依赖 Agent，照常能用。"""
        llm = self.llm()
        if llm is None:
            return self._unreachable("还没接大模型", "点“大模型设置”选服务商、填 Key；本地 Ollama 不需要 Key", text)
        self.loop.llm = llm
        self.loop.guards = isinstance(llm, (llm_mod.OpenAICompat, llm_mod.Failover))
        local = getattr(llm, "active", None) is getattr(llm, "local", 0) or getattr(llm, "cfg", {}).get("provider") == "ollama"
        self.emit({"type": "agent_mode", "mode": "local" if local else "llm", "name": getattr(llm, "name", "")})
        n0 = len(self.loop.messages)
        r0 = getattr(self, "iter_result", None)
        try:
            return self._end_with_card(self.loop.ask(text), r0)
        except llm_mod.LLMError as e:
            del self.loop.messages[n0:]                  # 本轮作废，下一句从干净的对话接着来
            self._agent_error(e)
            return self._unreachable(e.message, e.fix, text)
        except Exception as e:                           # noqa: BLE001 —— 任何意外都不能让界面干等
            del self.loop.messages[n0:]
            err = self._agent_error(e)
            return f"（Agent 这一轮出错了：{err['message']}）"

    def _end_with_card(self, reply: str, r0) -> str:
        """#53：本轮跑完了自动迭代 → 这一轮以“采用最好参数”卡收尾，不以提问结束（模型偶尔还是会问“要不要…？”）。"""
        res = getattr(self, "iter_result", None)
        if not res or res is r0 or not res.get("best_card"):
            return reply
        t = (reply or "").rstrip()
        if t.endswith(("？", "?")):
            cut = max(t.rfind(c, 0, len(t) - 1) for c in "。！!\n")
            t = t[:cut + 1].rstrip() if cut >= 0 else ""
        b = res.get("best") or {}
        tail = f"最好一轮是第 {b.get('iter')} 轮（参数 hash {b.get('params_hash')}），已出“采用最好参数”卡，点确认即写入。"
        return (t + "\n" + tail).strip() if tail not in t else t

    # agent_error.fix_action 只能是 docs/dev/entrypoints.yaml 里的入口 id（或 None）；测试会核对
    FIX_SETTINGS, FIX_RESEND = "llm_cfg", "agent_chat"

    def _agent_error(self, e: BaseException) -> dict:
        """fix_action = docs/dev/entrypoints.yaml 里的入口 id（llm_cfg 大模型设置 / agent_chat 重发）或 None。
        把本轮异常变成 agent_error 事件：原因 + 怎么解决；密钥打码；调用栈只进 detail 和日志。"""
        import sys
        import traceback
        key = (getattr(getattr(self.loop, "llm", None), "cfg", None) or {}).get("api_key") or ""
        tb = llm_mod._redact("".join(traceback.format_exception(type(e), e, e.__traceback__)), key)
        print(f"[dzbench] agent_error\n{tb}", file=sys.stderr)
        if isinstance(e, llm_mod.LLMError):
            st = getattr(e, "code", None)
            if isinstance(st, int):
                code = f"llm_{st}"
            else:
                code = "llm_timeout" if "超时" in e.message else ("llm_network" if e.down else "llm_error")
            action = self.FIX_SETTINGS if getattr(e, "model_hint", False) or st in (401, 402, 403, 404) or e.down or "Key" in e.message or "地址" in e.message else self.FIX_RESEND
            retryable = bool(getattr(e, "retry", False) or e.down)
            msg = f"{e.message}。{e.fix}" if e.fix else e.message
            detail = ""
        elif isinstance(e, (KeyError, TypeError)) and any(k in str(e) for k in ("input_schema", "description", "'name'", "parameters")):
            code, action, retryable, detail = "tool_schema", None, False, tb
            msg = f"有个 Agent 工具的定义格式不对（缺字段 {e}），这一轮没法调用模型。工作台需要修这个工具定义；先重发一次或换个说法，其它功能不受影响"
        elif isinstance(e, TimeoutError):
            code, action, retryable, detail = "timeout", self.FIX_RESEND, True, tb
            msg = "Agent 这一轮超时了。点“重试”再发一次；一直超时就检查网络或换个更快的模型"
        else:
            code, action, retryable, detail = "internal", self.FIX_RESEND, True, tb
            msg = f"Agent 内部出错（{type(e).__name__}）。点“重试”再发一次；反复出现请把“详情”发给开发者"
        ev = {"type": "agent_error", "code": code, "message": llm_mod._redact(msg, key), "detail": detail,
              "fix_action": action, "retryable": retryable}
        self.emit(ev)
        return ev

    def _unreachable(self, message: str, fix: str, text: str) -> str:
        self.emit({"type": "agent_unreachable", "message": message, "fix": fix, "text": text})
        return f"（Agent 暂时用不了：{message}。{fix}。调参、示波、急停、阶跃测试和评分页不受影响。）"


__all__ = ["AgentService", "GatewayError", "guess_pairs"]
