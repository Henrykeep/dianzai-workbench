"""项目进度：侧车 RPC `progress.get` 与推送事件 `progress.changed`（界面进度条与 Agent 共用同一份数据）。

步骤 id 与界面左侧导航一致：req→project→sim→bringup→tune→score→seal（读题→工程→仿真→上板联调→调参→评分→封箱），与统筹者《开发全流程旅程图》
（/workspace/charter/旅程图.md）及 bench 阶段表 tools/bench/journey.yaml 的 stage 一一对应（见 STEPS 的 journey 字段），
本模块不另立阶段定义。

只读：所有状态都从已有来源推出——link.state、会话状态（心跳标志、急停锁存、参数表、遥测）、依赖自检（doctor）、
参数掉电保存记录（黑匣子 BB 6/7）、调参护栏记录；不发任何帧、不改任何文件。

返回结构（约定）：
  {steps:[{id,title,state:todo|doing|done|blocked,reason?,detail?}], current, next:{title,action,hint},
   blockers:[{code,message,fix_action,blocks}], mode}
next.action 与每个 blocker 的 fix_action 都是入口规则表 docs/dev/entrypoints.yaml 里的动作 id（测试逐个核对）。
"""
from __future__ import annotations

STATES = ("todo", "doing", "done", "blocked")

# (id, 标题, 旅程图 / journey.yaml 的 stage)。id 与界面左侧导航一致（前端约定，固定 7 项）。
STEPS = (
    ("req", "读题", "拆指标"),
    ("project", "工程", "搭工程配引脚"),
    ("sim", "仿真", "驱动点亮"),
    ("bringup", "上板联调", "子系统联调"),
    ("tune", "调参", "调参"),
    ("score", "评分", "对照评分自测"),
    ("seal", "封箱", "封箱"),
)
TITLE = {i: t for i, t, _ in STEPS}

# 动作 id 一律取自入口规则表 docs/dev/entrypoints.yaml 的 actions[].id（界面按钮与 Agent 共用；本模块不执行）
ACTIONS = {
    "connect": "连接板子",
    "doctor": "运行自检，按提示安装缺失依赖",
    "tune_relay": "无初值一键起步调参",
    "estop_clear": "确认安全后解除急停",
    "blackbox": "读取黑匣子，查明自检未通过的原因",
    "params_flash": "将参数写入 Flash",
    "project_flow": "读题到生成工程引导",
    "build": "编译固件",
    "cal_polarity": "极性自检",
    "score": "评分项逐项验收",
    "precontest": "赛前全绿检查与封箱清单",
}

BLOCKER_CODES = ("no_board", "missing_deps", "gains_zero", "estop", "selftest_fail", "params_not_saved")
FIX = {"no_board": "connect", "missing_deps": "doctor", "gains_zero": "tune_relay",
       "estop": "estop_clear", "selftest_fail": "blackbox", "params_not_saved": "params_flash"}
STEP_ACTION = {"req": "project_flow", "project": "project_flow", "sim": "build", "bringup": "cal_polarity",
               "tune": "tune_relay", "score": "score", "seal": "precontest"}
# 每类阻塞挡住哪些步骤（"mode:standalone" = 切换到脱机模式）
BLOCKS = {"no_board": ["sim", "bringup", "tune", "score", "seal"],
          "missing_deps": ["project", "sim"],
          "gains_zero": ["tune"],
          "estop": ["bringup", "tune", "score"],
          "selftest_fail": ["bringup", "tune", "score", "seal"],
          "params_not_saved": ["score", "seal", "mode:standalone"]}

LINK_REASON = {"port_not_found": "未找到上次使用的串口", "port_ambiguous": "检测到多块同型号板子",
               "transport_closed": "连接中断，正在重连", "resuming": "侧车重启后正在恢复连接",
               "no_frames": "已打开串口但未收到合法帧"}


def _blocker(code: str, message: str) -> dict:
    return {"code": code, "message": message, "fix_action": FIX[code], "blocks": list(BLOCKS[code])}


def blockers(f: dict) -> list[dict]:
    """facts → 阻塞项列表（顺序即处理优先级）。"""
    out = []
    if f.get("deps_missing"):
        names = "、".join(f["deps_missing"][:4])
        out.append(_blocker("missing_deps", f"开发环境缺少必需依赖：{names}。"))
    board = (f.get("link") or {}).get("board")
    if board != "connected":
        why = LINK_REASON.get((f.get("link") or {}).get("reason") or "", "")
        out.append(_blocker("no_board", "未连接板子" + (f"：{why}。" if why else "。")))
        return out                       # 板子不在线时，板上状态（急停、自检、参数）均不可信，不再判
    if f.get("estop"):
        out.append(_blocker("estop", "急停已锁存" + (f"：{f['estop_reason']}" if f.get("estop_reason") else "。")))
    if f.get("selftest_fail"):
        out.append(_blocker("selftest_fail", f"板上自检未通过：{f['selftest_fail']}。"))
    gains = f.get("gains") or {}
    if gains and all(v is not None and float(v) == 0.0 for v in gains.values()):
        out.append(_blocker("gains_zero", "控制增益（" + "、".join(gains) + "）全部为零，闭环不会产生输出。"))
    if f.get("params_saved") is False:
        out.append(_blocker("params_not_saved", "板上参数已修改但尚未写入 Flash，断电后将恢复为旧值。"))
    return out


def derive(f: dict) -> dict:
    """facts（见 collect）→ 进度快照。纯函数，便于测试。"""
    bl = blockers(f)
    by_step: dict[str, list[dict]] = {}
    for b in bl:
        for s in b["blocks"]:
            by_step.setdefault(s, []).append(b)
    connected = (f.get("link") or {}).get("board") == "connected"
    real = connected and not f.get("sim_board")
    done = {
        "req": bool(f.get("req_items")),
        "project": bool(f.get("project_ready")) or bool(f.get("schema_ok")),
        "sim": bool(f.get("sim_ok")) or (connected and bool(f.get("schema_ok")) and bool(f.get("has_samples"))),
        "bringup": real and bool(f.get("has_samples")) and bool(f.get("params_read")),
        "tune": bool(f.get("tune_best")),
        "score": bool(f.get("score_evidence")),
        "seal": bool(f.get("sealed")),
    }
    detail = {
        "req": f"{f.get('req_items')} 个评分项" if done["req"] else "尚未从题目整理评分项",
        "project": "检测到工作台固件" if f.get("schema_ok") else ("工程已配置" if f.get("project_ready") else "尚未配置工程"),
        "sim": "仿真板已收到遥测" + (f"（固件 {f['fw_rev']}）" if f.get("fw_rev") else "") if done["sim"] else "",
        "bringup": f"实物板已读回 {f.get('params_read', 0)} 个参数" if done["bringup"] else "",
        "tune": "已有稳定的最佳一轮" if done["tune"] else "",
        "score": f"{f.get('score_evidence')} 项已有证据" if done["score"] else "",
        "seal": "",
    }
    steps, current = [], None
    for sid, title, _j in STEPS:
        st = {"id": sid, "title": title}
        bs = by_step.get(sid, [])
        if bs:
            st.update(state="blocked", reason=bs[0]["code"], detail=bs[0]["message"])
        elif done[sid]:
            st["state"] = "done"
        else:
            st["state"] = "todo"
        if st["state"] != "done" and current is None:
            current = sid
            if st["state"] == "todo":
                st["state"] = "doing"
        if "detail" not in st and detail[sid]:
            st["detail"] = detail[sid]
        steps.append(st)
    if bl:
        b = bl[0]
        nxt = {"title": ACTIONS[b["fix_action"]], "action": b["fix_action"], "hint": b["message"]}
    elif current:
        a = STEP_ACTION[current]
        nxt = {"title": ACTIONS[a], "action": a, "hint": f"当前步骤：{TITLE[current]}。"}
    else:
        nxt = {"title": "全部完成", "action": "", "hint": "各步骤均已完成，可导出封箱清单存档。"}
    return {"steps": steps, "current": current, "next": nxt,
            "blockers": [{k: b[k] for k in ("code", "message", "fix_action", "blocks")} for b in bl],
            "mode": f.get("mode")}


def standalone_blocker(snapshot: dict) -> dict | None:
    """切换到脱机模式前的检查：有挡 mode:standalone 的阻塞就返回它（切换命令须拒绝并提示 fix_action）。"""
    return next((b for b in snapshot.get("blockers", []) if "mode:standalone" in b.get("blocks", [])), None)


# ------------------------------------------------------------------ 从会话收集事实
def _params_saved(s) -> bool | None:
    """None = 无从判断（未连接或无参数表）。参数等于固件默认值 → 无需保存；
    黑匣子记录到“参数已存进 Flash / 上电读了 Flash”且之后没有再写参数 → 已保存；否则未保存。"""
    if not s.schema or not s.params:
        return None
    diff = any(s.params.get(p["name"]) is not None and abs(float(s.params[p["name"]]) - float(p["default"]))
               > 1e-6 * max(1.0, abs(float(p["default"]))) for p in s.schema.params)
    if not diff:
        return True
    return getattr(s, "flash_saved_writes", -1) == getattr(s, "param_writes", 0)


def collect(s, svc=None, deps: list[dict] | None = None) -> dict:
    """从会话（Session）、Agent 服务（可选）和依赖自检结果收集事实。只读。"""
    st = s.status()
    link = s.link.last or {"board": "connected" if st.get("alive") else "disconnected", "reason": None}
    flags = st.get("hb_flags") or []
    estop = bool(st.get("tx_locked")) or "急停" in flags
    reason = None
    if estop:
        ev = [e for e in s.timeline.history() if e.get("kind") in ("estop", "watchdog")]
        reason = ev[-1]["text"] if ev else ("板子上报急停标志" if "急停" in flags else None)
    self_fail = None
    if "安全态" in flags and not estop:
        self_fail = f"板子处于安全态（复位原因：{st.get('reset') or '未知'}）"
    elif st.get("reset") in ("看门狗", "内核锁死"):
        self_fail = f"异常复位（{st['reset']}）"
    gains = {}
    tune_best = False
    if svc is not None and s.schema:
        try:
            gains = svc._gains()
            tune_best = bool(svc.guard and svc.guard.best())
        except Exception:  # noqa: BLE001 —— 进度只读，取不到按未知处理
            gains = {}
    return {
        "link": {"board": link.get("board"), "reason": link.get("reason")},
        "mode": link.get("mode"),
        "schema_ok": bool(st.get("schema_ok")),
        "fw_rev": st.get("fw_rev"),
        "has_samples": bool(s.samples),
        "sim_board": str(st.get("port") or "").startswith("sim:"),
        "params_read": len(s.params),
        "deps_missing": [d["name"] for d in (deps or []) if d.get("level") == "fail"],
        "estop": estop, "estop_reason": reason,
        "selftest_fail": self_fail,
        "gains": gains,
        "params_saved": _params_saved(s),
        "tune_best": tune_best,
        "project_ready": bool(getattr(svc, "cfg", {}).get("flash", {}).get("target")) if svc is not None else False,
    }


class Progress:
    """缓存依赖自检；snapshot() 每次重算，changed() 只在内容变化时返回事件。"""

    def __init__(self, session, svc=None, doctor=None):
        self.s, self.svc, self._doctor = session, svc, doctor
        self.deps: list[dict] | None = None
        self._last: dict | None = None

    def refresh_deps(self) -> None:
        if self._doctor:
            try:
                self.deps = self._doctor()
            except Exception:  # noqa: BLE001
                self.deps = []

    def snapshot(self) -> dict:
        return derive(collect(self.s, self.svc, self.deps))

    def changed(self) -> dict | None:
        snap = self.snapshot()
        if snap == self._last:
            return None
        self._last = snap
        return {"type": "progress.changed", **snap}
