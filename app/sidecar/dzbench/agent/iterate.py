"""#38 自动迭代（本地服务侧）。协议见 docs/dev/iterate.md，帧格式见 firmware/proto/dzctl/README.md「0.13.0」。

一次人工确认（批量卡）→ 从板上当前参数出发（iter 0 基线 + params_hash）→ 每轮 改参 → 板上阶跃（DATA 0x7B）→
step_result 判定 → 直到达标或停止条件（预算 180 s / 轮数上限 实机 8 · 仿真 20 / 急停 / 人停 / 连续无效 / 无改进 / 不稳定 / 被挡住）。
帧编解码直接用 tools/dzstep.py（与固件 dzstep.c 同口径），不另写一份。

引擎只依赖一个 io 适配器（Session 侧实现见 SessionIO；测试里用 mock step_result）：
  io.order() -> [参数名（参数表顺序）]       io.read_params() -> {name: value}（板上当前值）
  io.write(name, v) -> {"status": "ok"} | {"status": "rejected", "reason": range|type|state|step}
  io.step(it, ch, target, dur_ms) -> step_result dict（dzstep.decode_step_result 的结构）；开始被拒抛 IterError
  io.locked() -> bool（急停锁存）           io.busy() -> bool（心跳 bit17 DZCTL_HB_ITER_BUSY）
"""
from __future__ import annotations

import threading
import struct
import time

from ..stepproto import dzstep        # tools/dzstep.py：0.13.0 帧格式的参考实现

BUDGET_S = 180.0
MAX_ROUNDS = {"hw": 8, "sim": 20}
GOOD_REL = {"overshoot_pct": 10.0, "ss_err_pct": 2.0}
MIN_SAMPLES = 20
MAX_DUR_MS = 30000            # 板上阶跃时长上限（与 session.step_start 校验一致）
CONSEC_PASS, CONSEC_INVALID, CONSEC_NO_IMPROVE = 2, 3, 3
UNSTABLE_OVERSHOOT = 40.0
HW_RATIO = (0.7, 1.5)          # 实机 HW 档：新值在当前值 ×0.7~×1.5
HW_SPAN_FRAC, HW_ZERO_FRAC = 0.10, 0.02
ACK_ZH = {"bad_arg": "开始帧参数不对（通道/时长 200–30000 ms）", "estop": "板子急停中", "busy": "板上已有阶跃实验在跑",
          "unsupported": "这个应用没配阶跃通道（app.yaml link.step）", "offline": "板子在脱机模式"}


class IterError(Exception):
    def __init__(self, code: str, message_zh: str):
        super().__init__(message_zh)
        self.code, self.message_zh = code, message_zh


INVALID_ZH = {"empty_metrics": "指标为空", "step_failed": "阶跃没做成", "no_rise": "没测出上升时间",
              "settle_zero": "调节时间为 0（窗口没对上）", "zero_step": "阶跃幅度为 0（目标就是当前位置）",
              "aborted": "阶跃被打断", "too_few_samples": "样本太少", "hash_mismatch": "参数哈希对不上", "no_result": "板子没回结果"}


def step_invalid(m: dict | None) -> str | None:
    """唯一的“这一轮能不能用”判定（#68/#75/#92/#94）：台账、结果卡、提议、自动迭代都调这一个。返回原因码或 None。
    同时认上位机口径（rise_s / settling_s）和板上 step_result 口径（rise_ms / settle_ms）；
    带 step_amp + step_tol 时，幅度小于回位容差 = 没做阶跃（zero_step）。"""
    if not m or not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in m.values()):
        return "empty_metrics"
    if m.get("ok") is False:
        return "step_failed"
    amp, tol = m.get("step_amp"), m.get("step_tol")
    if isinstance(amp, (int, float)) and isinstance(tol, (int, float)) and abs(amp) < tol:
        return "zero_step"
    for k in ("rise_s", "rise_ms"):
        if k in m and m[k] is None:
            return "no_rise"
    for k in ("settling_s", "settle_ms"):
        if k in m and m[k] is not None and float(m[k]) == 0.0:
            return "settle_zero"
    return None


def params_hash(order: list[str], values: dict) -> int:
    return dzstep.params_hash([values[n] for n in order])


def judge(r: dict, abs_tol: float | None, good: dict | None = None) -> dict:
    """每项是否达标。rel：超调 ≤10%、|稳态误差| ≤2%、进了 2% 带；abs（物理单位）：稳态误差 ≤ abs_tol、进带，
    超调按 max|e| 不另设门限（口径本身就是绝对误差，记录但不判）。"""
    g = {**GOOD_REL, **(good or {})}
    settled = r.get("settle_ms") is not None
    if r.get("metric_mode") == "abs":
        tol = abs_tol if abs_tol else r.get("band") or 0.0
        p = {"ss_err": abs(r["ss_err_pct"]) <= tol, "overshoot": None, "settle": settled, "rise": None}
    else:
        p = {"ss_err": abs(r["ss_err_pct"]) <= g["ss_err_pct"], "overshoot": r["overshoot_pct"] <= g["overshoot_pct"],
             "settle": settled, "rise": r.get("rise_ms") is not None}
    p["all"] = all(v for k, v in p.items() if v is not None and k != "rise")
    return p


def gaps(r: dict, abs_tol: float | None, good: dict | None = None) -> dict:
    """离达标还差多少（只列没达标的项；单位：rel 为 %，abs 为物理单位）。"""
    g = {**GOOD_REL, **(good or {})}
    out = {}
    if r.get("metric_mode") == "abs":
        tol = abs_tol if abs_tol else r.get("band") or 0.0
        if abs(r["ss_err_pct"]) > tol:
            out["ss_err"] = {"value": r["ss_err_pct"], "limit": tol, "gap": round(abs(r["ss_err_pct"]) - tol, 6), "unit": "abs"}
    else:
        if r["overshoot_pct"] > g["overshoot_pct"]:
            out["overshoot"] = {"value": r["overshoot_pct"], "limit": g["overshoot_pct"], "gap": round(r["overshoot_pct"] - g["overshoot_pct"], 4), "unit": "%"}
        if abs(r["ss_err_pct"]) > g["ss_err_pct"]:
            out["ss_err"] = {"value": r["ss_err_pct"], "limit": g["ss_err_pct"], "gap": round(abs(r["ss_err_pct"]) - g["ss_err_pct"], 4), "unit": "%"}
    if r.get("settle_ms") is None:
        out["settle"] = {"value": None, "limit": "进带", "gap": None, "unit": "ms"}
    return out


def score(r: dict, abs_tol: float | None, good: dict | None = None) -> float:
    """越小越好：各项超出门限的比例之和；没进带 +1。"""
    g = {**GOOD_REL, **(good or {})}
    if r.get("metric_mode") == "abs":
        tol = abs_tol or r.get("band") or 1.0
        s = abs(r["ss_err_pct"]) / tol + 0.1 * r["overshoot_pct"] / tol
    else:
        s = r["overshoot_pct"] / g["overshoot_pct"] + abs(r["ss_err_pct"]) / g["ss_err_pct"]
    return s + (0.0 if r.get("settle_ms") is not None else 1.0)


def limits_for(p: dict, cur: float, sim: bool) -> tuple[float, float]:
    """本轮允许的 [lo, hi]：参数范围 ∩ |Δ| ≤ max_delta ∩（实机）×0.7~×1.5、单步 ≤ 量程 10%、0 起步 ≤ 量程 2%。"""
    lo, hi = float(p["min"]), float(p["max"])
    md = float(p.get("max_delta") or (hi - lo))
    a, b = max(lo, cur - md), min(hi, cur + md)
    if not sim:
        span = hi - lo
        if cur == 0:
            a, b = max(a, -HW_ZERO_FRAC * span), min(b, HW_ZERO_FRAC * span)
        else:
            r1, r2 = sorted((cur * HW_RATIO[0], cur * HW_RATIO[1]))
            a, b = max(a, r1, cur - HW_SPAN_FRAC * span), min(b, r2, cur + HW_SPAN_FRAC * span)
    return a, b


STEP_FRAC = 0.25        # 坐标搜索初始相对步长
MIN_STEP_FRAC = 0.05
ZERO_STEP_FRAC = 0.02   # 当前值为 0 时按量程的 2% 起步


class Iterator:
    def __init__(self, io, plan: dict, sim: bool, emit=lambda e: None, now=time.monotonic,
                 budget_s: float = BUDGET_S, max_rounds: int | None = None):
        self.io, self.plan, self.sim, self.emit, self.now = io, plan, sim, emit, now
        self.budget_s = budget_s
        self.max_rounds = max_rounds or MAX_ROUNDS["sim" if sim else "hw"]
        self.abs_tol = plan.get("abs_tol")
        self.good = plan.get("good")
        self.stop_ev = threading.Event()
        self.rounds: list[dict] = []
        self.best: dict | None = None

    # ------------------------------------------------------------ 批量确认卡
    @staticmethod
    def card(plan: dict, start: dict, order: list[str], sim: bool, budget_s: float = BUDGET_S, max_rounds: int | None = None) -> dict:
        mr = max_rounds or MAX_ROUNDS["sim" if sim else "hw"]
        return {"title": "自动迭代调参（一次确认）",
                "params": [{"name": p["name"], "min": p["min"], "max": p["max"],
                            "max_delta": p.get("max_delta") if p.get("max_delta") is not None else float(p["max"]) - float(p["min"]),
                            "start": start.get(p["name"])} for p in plan["params"]],
                "start_hash": f"{params_hash(order, start):08x}",
                "budget": {"time_s": budget_s, "rounds": mr, "where": "仿真" if sim else "实机"},
                "step": {"ch": plan.get("ch", 0), "target": plan["target"], "dur_ms": plan["dur_ms"]},
                "stop": ["连续 2 轮达标", f"{budget_s:.0f} s 或 {mr} 轮先到", "急停 / 点“停止迭代”立即停",
                         "连续 3 轮无效", "连续 3 轮无改进", "振荡发散（超调 > 40%）", "所有方向被板子拒绝或限幅挡住"],
                "note": "从板上当前参数出发（iter 0 = 基线）；每轮只改 1 个参数，单步不超过 max_delta；超出卡上范围会停下重新确认"}

    # ------------------------------------------------------------ 一轮
    def _round(self, it: int, values: dict, changed: dict) -> dict:
        order = self.io.order()
        r = self.io.step(it, self.plan.get("ch", 0), self.plan["target"], self.plan["dur_ms"])
        local = params_hash(order, values)
        rec = {"iter": it, "params": dict(values), "changed": changed,
               "params_hash": f"{r['params_hash']:08x}",          # 以板上 step_result 的 CRC32 为准
               "local_hash": f"{local:08x}", "source": "firmware",
               **{k: r.get(k) for k in ("ss_err_pct", "overshoot_pct", "settle_ms", "rise_ms", "metric_mode", "u_sat_ratio", "n", "band")},
               "unit": "abs" if r.get("metric_mode") == "abs" else "%"}
        rec["sensor_sat"] = bool(r.get("sensor_sat"))     # #102：到量程的数据不可信，不算稳定
        rec["target"] = self.plan["target"]               # 相对口径 ss_err % → 物理单位要用 |sp − y0|
        if r.get("start_y") is not None:
            rec["start_y"] = r["start_y"]
        if r.get("start_offset") is not None:             # 没回到起点：用实测起点当基线，这一轮标出来
            rec["start_offset"], rec["start_y"] = r["start_offset"], r.get("start_y")   # abs 口径：超调 / 稳态误差是物理单位，不是百分比
        for k in ("step_amp", "step_tol"):
            if r.get(k) is not None:
                rec[k] = r[k]
        why = None
        if r.get("aborted"):
            why = "aborted"
            rec["abort_cause"] = "host_stop" if r.get("abort_cause") == dzstep.ABORT_HOST_STOP else r.get("abort_cause")
        elif (r.get("n") or 0) < MIN_SAMPLES:
            why = "too_few_samples"
        elif r["params_hash"] != local:
            why = "hash_mismatch"
        else:                                             # 其余一律走统一判定（与台账 / 结果卡 / 提议同一个函数）
            m = {k: r.get(k) for k in ("overshoot_pct", "ss_err_pct", "settle_ms") if k in r} | \
                {k: rec[k] for k in ("step_amp", "step_tol") if k in rec}
            if r.get("metric_mode") != "abs":
                m["rise_ms"] = r.get("rise_ms")
            why = step_invalid(m)
        rec["valid"], rec["why_invalid"] = why is None, why
        if why is not None:                               # #68 验收：无效轮指标置 null（固件发的 0% / 0 ms 看着像完美）
            for k in ("overshoot_pct", "settle_ms", "ss_err_pct", "rise_ms"):
                rec[k] = None
            rec["verdict"] = "unknown"
        if why is None:
            rec["pass"] = judge(r, self.abs_tol, self.good)
            rec["score"] = round(score(r, self.abs_tol, self.good), 4)
        return rec

    def _write(self, name: str, v: float) -> dict:
        if self.io.locked():
            raise IterError("estop", "急停中，不写参数")
        if self.io.busy():
            raise IterError("busy", "板上阶跃实验进行中（bit17），不写参数")
        return self.io.write(name, v)

    @staticmethod
    def stable(r: dict) -> bool:
        """#102：有效且没发散（相对口径超调 ≤ UNSTABLE_OVERSHOOT）才算稳定一轮。"""
        return bool(r) and bool(r.get("valid")) and not r.get("sensor_sat") and not (r.get("metric_mode") == "rel" and (r.get("overshoot_pct") or 0) > UNSTABLE_OVERSHOOT)

    def _stopped(self, reason: str, msg: str) -> dict:
        last_sat = bool(self.rounds and self.rounds[-1].get("sensor_sat"))
        best = self.best if self.best is not None and self.stable(self.best) and not last_sat else None
        if (best is None and any(r["valid"] for r in self.rounds) and not any(self.stable(r) for r in self.rounds)) or last_sat:
            msg = "发散，未找到稳定参数"                              # #102：没有稳定的一轮就不给“最好参数”
        out = {"type": "iterate.stopped", "reason": reason, "sensor_sat": last_sat, "message_zh": msg, "rounds": len([r for r in self.rounds if r["valid"]]),
               "best": None if not best else {"iter": best["iter"], "params": best["params"], "params_hash": best["params_hash"],
                                              "metrics": {k: best.get(k) for k in ("overshoot_pct", "ss_err_pct", "settle_ms", "rise_ms", "metric_mode")},
                                              "pass": best["pass"], "gaps": gaps(best, self.abs_tol, self.good)},
               "next_zh": self._next_hint(reason)}
        if reason == "invalid":                                       # 卡上写清楚哪一种无效，不只说“没有可用的一轮”
            whys = [r.get("why_invalid") for r in self.rounds if not r["valid"]][-CONSEC_INVALID:]
            out["why_invalid"] = whys[-1] if whys else None
            out["reason_zh"] = "连续无效：" + "、".join(dict.fromkeys(INVALID_ZH.get(w, str(w)) for w in whys))
        r0 = next((r for r in self.rounds if r["valid"]), None)       # 卡上和最好一轮并排对比的初值轮
        if r0:
            out["round0"] = {"iter": r0["iter"], "pass": r0.get("pass"),
                             "metrics": {k: r0.get(k) for k in ("overshoot_pct", "ss_err_pct", "settle_ms", "rise_ms", "metric_mode")}}
        self.emit(out)
        return out

    def _next_hint(self, reason: str) -> str:
        return {"pass": "已连续达标：点“保存参数”写入 flash",
                "budget_time": "预算用完：先采用最好一轮的参数，看差距最大的一项再定方向，确认后可再开一次迭代",
                "budget_rounds": "轮数用完：先采用最好一轮，再按差距最大的一项继续",
                "estop": "急停：确认安全后解除急停，再决定是否重新开始迭代",
                "stopped": "已按你的指令停止，参数停在当前值",
                "invalid": "连续 3 轮无效：检查通道/遥测（样本太少、被打断或参数哈希对不上）",
                "no_improve": "连续 3 轮没改进：换参数或换策略（例如先调 ki/kd）",
                "unstable": "发散：已回到最好一轮" if self.sim else "发散：请确认回到最好一轮的参数",
                "blocked": "各方向都被板子拒绝或限幅挡住：放宽 max_delta / 范围后重新确认"}.get(reason, "")

    # ------------------------------------------------------------ 主循环
    def run(self) -> dict:
        t0 = self.now()
        order = self.io.order()
        cur = self.io.read_params()                       # 从板上当前参数出发（不沿用上次运行 / 别的工程）
        self.emit({"type": "iterate.started", "plan": self.plan, "start": cur, "start_hash": f"{params_hash(order, cur):08x}",
                   "limits": {"time_s": self.budget_s, "rounds": self.max_rounds}})
        it = 0
        cand_params = [p for p in self.plan["params"]]
        pi, direction, tried = 0, -1.0, set()             # 坐标搜索：当前参数下标、方向（先降增益）、已试过的(参数,方向)
        frac = {p["name"]: STEP_FRAC for p in self.plan["params"]}   # #69：每个参数的相对步长；变差换方向时减半（不再每轮砍一半到 0）
        streak_pass = streak_invalid = streak_noimp = 0
        changed: dict = {}
        while True:
            if self.stop_ev.is_set():
                return self._stopped("stopped", "人点了停止迭代")
            if self.io.locked():
                return self._stopped("estop", "急停")
            if self.now() - t0 >= self.budget_s:
                return self._stopped("budget_time", f"预算 {self.budget_s:.0f} s 用完")
            if it > self.max_rounds:
                return self._stopped("budget_rounds", f"轮数上限 {self.max_rounds} 用完")
            try:
                rec = self._round(it, cur, changed)
            except IterError as e:
                if e.code == "estop" or self.io.locked():
                    return self._stopped("estop", e.message_zh)
                rec = {"iter": it, "params": dict(cur), "valid": False, "why_invalid": e.code, "source": "firmware"}
            self.rounds.append(rec)
            self.emit({"type": "iterate.round", **rec})
            if self.io.locked():
                return self._stopped("estop", "急停")
            if not rec["valid"]:
                if rec["why_invalid"] in ("settle_zero", "no_rise") and self.plan["dur_ms"] < MAX_DUR_MS:
                    # 窗口太短（对象慢）：时长翻倍重做同一轮，不算无效（时长由实测得出，不按题目写死）
                    self.plan = dict(self.plan, dur_ms=min(MAX_DUR_MS, int(self.plan["dur_ms"]) * 2))
                    self.emit({"type": "iterate.dur_extended", "dur_ms": self.plan["dur_ms"], "why": rec["why_invalid"]})
                    continue
                streak_invalid += 1
                if rec["why_invalid"] == "aborted" and rec.get("abort_cause") == "host_stop" and self.stop_ev.is_set():
                    return self._stopped("stopped", "人点了停止迭代")
                if streak_invalid >= CONSEC_INVALID:
                    return self._stopped("invalid", "连续 3 轮无效")
                continue                                   # 无效轮不占号：同一 iter 重跑
            streak_invalid = 0
            improved = self.stable(rec) and (self.best is None or rec["score"] < self.best["score"])   # #102：发散轮不当最好
            if improved:
                self.best, streak_noimp = rec, 0
            else:
                streak_noimp += 1
            streak_pass = streak_pass + 1 if rec["pass"]["all"] else 0
            if streak_pass >= CONSEC_PASS:
                return self._stopped("pass", "连续 2 轮达标")
            if rec.get("metric_mode") == "rel" and rec["overshoot_pct"] > UNSTABLE_OVERSHOOT:
                if self.sim and self.best is not rec and self.stable(self.best):
                    for n, v in self.best["params"].items():
                        if v != cur.get(n):
                            self._write(n, v)
                return self._stopped("unstable", f"超调 {rec['overshoot_pct']:.1f}% > 40%")
            if streak_noimp >= CONSEC_NO_IMPROVE:
                return self._stopped("no_improve", "连续 3 轮没有改进")
            if it > self.max_rounds:
                return self._stopped("budget_rounds", f"轮数上限 {self.max_rounds} 用完")
            if not improved and changed:                   # 变差：回到最好一轮的值，换方向，步长减半
                nm = cand_params[pi]["name"]
                tried.add((nm, direction))
                direction = -direction
                frac[nm] = max(MIN_STEP_FRAC, frac[nm] * 0.5)
            base = self.best["params"]
            while True:                                    # 选下一步（每轮只改 1 个参数）；被板子拒绝就换方向再选，不空跑阶跃
                nxt = None
                for _ in range(2 * len(cand_params) + 2):
                    p = cand_params[pi]
                    if (p["name"], direction) in tried:
                        direction = -direction
                        if (p["name"], direction) in tried:
                            pi, direction = (pi + 1) % len(cand_params), -1.0
                        continue
                    c0 = float(base[p["name"]])
                    a, b = limits_for(p, c0, self.sim)
                    v = b if direction > 0 else a
                    if ((rec.get("u_sat_ratio") or 0) > 0.5 and direction > 0) or abs(v - c0) < 1e-9:
                        tried.add((p["name"], direction))      # 饱和不往更激进走；到边了
                        continue
                    d = abs(c0) * frac[p["name"]] if c0 else (float(p["max"]) - float(p["min"])) * ZERO_STEP_FRAC
                    nxt = (p, min(b, max(a, c0 + direction * d)))   # #69：相对步长（默认 ±25%），夹在本轮允许范围内
                    break
                if nxt is None:
                    return self._stopped("blocked", "所有方向都被拒绝或限幅挡住")
                p, v = nxt
                try:
                    for n, bv in base.items():                 # 其余参数先回到最好一轮的值
                        if cur.get(n) != bv and n != p["name"]:
                            self._write(n, bv)
                            cur[n] = bv
                    w = self._write(p["name"], v)
                except IterError as e:
                    return self._stopped("estop" if e.code == "estop" else "blocked", e.message_zh)
                if w.get("status") == "rejected":          # param_reject：换方向，不重试同一个值
                    self.emit({"type": "iterate.param_reject", "name": p["name"], "value": v, "reason": w.get("reason")})
                    tried.add((p["name"], direction))
                    continue
                break
            cur = dict(base) | {p["name"]: w.get("applied", v)}
            changed = {p["name"]: {"from": base[p["name"]], "to": cur[p["name"]]}}
            it += 1

    def stop(self) -> None:
        self.stop_ev.set()


class SessionIO:
    """Iterator 的实机 / 仿真适配：全部走 Session（校验、急停锁、bit17 都在 Session 里）。"""

    def __init__(self, s):
        self.s = s

    def order(self) -> list[str]:
        return [p["name"] for p in (self.s.schema.params if self.s.schema else [])]

    def read_params(self) -> dict:
        return self.s.read_all_params()

    def locked(self) -> bool:
        return bool(self.s.tx_locked)

    def busy(self) -> bool:
        return self.s.iter_busy()

    def write(self, name: str, v: float) -> dict:
        from ..session import LinkError
        try:
            r = self.s.set_param(name, v)
        except LinkError as e:
            if e.code == "invalid_param" and (e.extra or {}).get("reject") == "step":
                return {"status": "rejected", "reason": "step"}
            if e.code == "invalid_param":
                return {"status": "rejected", "reason": "range"}
            if e.code in ("param_locked", "tx_locked"):
                raise IterError("estop" if self.s.tx_locked else "busy", e.message) from e
            raise
        return {"status": "rejected" if r["status"] == "rejected" else "ok", "reason": r.get("reason"), "applied": r["applied"]}

    RETURN_DT = 0.05
    RETURN_TIMEOUT_S = 8.0          # 回起点最多等这么久；超时用实测起点当基线并标 start_offset

    def _y(self, ch: int) -> tuple[str | None, int | None, float | None]:
        cfg = next((c for c in (self.s.schema.step if self.s.schema else []) if int(c.get("sp", -1)) == int(ch)), None) \
            or ((self.s.schema.step or [None])[0] if self.s.schema else None)
        if not cfg or not cfg.get("y"):
            return None, None, None
        tol = cfg.get("abs_tol")
        if tol is None and cfg.get("range") is not None:
            tol = 0.02 * float(cfg["range"])
        return cfg["y"], int(cfg.get("sp", ch)), (float(tol) if tol is not None else None)

    def _y_now(self, y: str) -> float | None:
        w = self.s.window(0.15)
        vs = [float(v[y]) for _, v in w if v.get(y) is not None] if w else []
        return sum(vs) / len(vs) if vs else None

    START_FRAC = 0.25     # 目标就在当前位置时：起点放到目标下方 量程 × 25%（app.yaml link.step.range；通用，不看题号）

    def _send_sp(self, slot: int | None, v: float) -> None:
        names = self.s.setpoint_names()
        vals = [float(self.s._sp_live.get(n, 0.0)) for n in names]
        if slot is not None and slot < len(vals):
            vals[slot] = v
            self.s.send_data(1, struct.pack(f"<{len(vals)}f", *vals))

    def _cfg(self, ch: int) -> dict:
        return next((c for c in (self.s.schema.step if self.s.schema else []) if int(c.get("sp", -1)) == int(ch)), None) \
            or ((self.s.schema.step or [{}])[0] if self.s.schema else {})

    def return_to_start(self, ch: int, it: int, target: float | None = None) -> dict:
        """上位机负责回起点（r9）：第 0 轮记下起点 y0；之后每轮先把设定值放回 y0，等 |y − y0| < tol（app.yaml link.step.abs_tol，
        没给按 2% range）持续 0.3 s，最多 8 s。超时不硬等：以实测位置为基线，这一轮标 start_offset。"""
        y, slot, tol = self._y(ch)
        if y is None or tol is None:
            return {}
        if getattr(self, "y0", None) is None:          # 整次迭代只定一次起点（无效轮重跑同一 iter 也回这个起点，#94）
            now = self._y_now(y)
            rng = self._cfg(ch).get("range")
            if target is not None and now is not None and abs(float(target) - now) < 2 * tol and rng:
                span = self.START_FRAC * float(rng)       # 目标就是当前位置 → 先退到起点再跳，不做 0 幅度阶跃
                self.y0 = float(target) - span if float(target) - span >= -float(rng) else float(target) + span
            else:
                self.y0 = now
                return {"start_y": now, **self._amp(target, tol)}
        self._send_sp(slot, self.y0)
        # 按拍数计时（每拍 RETURN_DT），不读墙钟（Windows 15.6 ms 时钟粒度会让“持续 0.3 s”判不出来）
        dt = self.RETURN_DT
        n_hold, n_max, ok_n, k = round(0.3 / dt), round(self.RETURN_TIMEOUT_S / dt), 0, 0
        cur = self._y_now(y)
        while k < n_max:
            cur = self._y_now(y)
            ok_n = ok_n + 1 if cur is not None and abs(cur - self.y0) < tol else 0
            if ok_n >= n_hold:
                return {"start_y": round(cur, 4), "return_s": round(k * dt, 2), **self._amp(target, tol, cur)}
            time.sleep(dt)
            k += 1
        return {"start_y": None if cur is None else round(cur, 4), "start_offset": None if cur is None else round(cur - self.y0, 4),
                "return_s": round(k * dt, 2), **self._amp(target, tol, cur)}

    def _amp(self, target, tol, y=None) -> dict:
        y = self.y0 if y is None else y
        if target is None or y is None or tol is None:
            return {}
        return {"step_amp": round(abs(float(target) - float(y)), 6), "step_tol": float(tol)}

    def step(self, it: int, ch: int, target: float, dur_ms: int) -> dict:
        from ..session import LinkError
        back = self.return_to_start(ch, it, target)
        t0 = time.monotonic()
        try:
            self.s.step_start(ch, it, target, dur_ms)
        except LinkError as e:
            raise IterError("estop" if e.code in ("step_estop", "tx_locked") else e.code, e.message) from e
        r = self.s.step_wait(it, dur_ms / 1000.0 + 2.0)
        if r is None:
            raise IterError("no_result", "板子没发 step_result")
        sat = getattr(self.s, "sensor_sat_at", None)
        return dict(r) | back | {"sensor_sat": sat is not None and sat >= t0}   # #102 bit18：这一轮里被控量到过量程边界
