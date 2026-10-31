#!/usr/bin/env python3
"""随机被控对象生成器（host-sim 仿真板，通用链路）。

    python tools/randplant.py --seed N [--order 1-3] [--kind pos|vel|temp|any] --out <dir> [--build] [--run]

<dir> 里输出：
  app.yaml   —— 应用声明（link.telemetry / link.params / link.step），固件链路全部由 tools/gen_link.py 生成
  link.yaml  —— 同一份 link: 段的副本（给只读链路的工具）
  spec.txt   —— 题面式的一句话指标（例：“稳态误差不超过 2°C，超调不超过 10%”），给后端练习从原文抽取误差带
  app_main.c —— 按本对象随机出来的控制器结构生成（可调参数的名字、个数、种类都随机）+ link_app.h
  sim_setup.c—— 被控对象（离散状态空间 + Padé 纯滞后 + 饱和 + 死区 + 传感器限幅 + 噪声），只在 host-sim 编译
  plant.json —— 真值：传函、采样周期、参数角色、feasible + 原因类别、reference（粗搜最好指标和参数）、
                按 metrics_card items 结构写的逐条真值。只给评分/门禁用，被测方不许读
  build/     —— --build 时：仿真板 sim:randplant-<seed> 的可执行文件（也在仓库 build/host-sim/randplant-<seed>/）

link.step 只写物理上限（sensor_range 传感器量程、max_step 执行器能承受的单次最大阶跃），不写阶跃幅度和回位容差：
那两样要上位机实测得出。随机系统用 python-control 的 control.rss()，滞后用 control.pade，所有随机数都来自
numpy.random.default_rng(seed)。同一 seed + 同一参数 → 逐字节相同的输出。本工具只生成对象和参考答案；
辨识/整定/判达标是后端的事，不在这里。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pydeps  # noqa: E402

if __name__ == "__main__" and sys.argv[1:2] == ["doctor"]:
    sys.exit(pydeps.doctor_main())
pydeps.require("control", "numpy")

import numpy as np  # noqa: E402

import control  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import plantmodel  # noqa: E402  共享对象模型（plant: 声明也用它）
MADE_UP = ["zorb", "qlu", "nit/s"]                       # 编出来的单位：界面/后端没见过也要照原样处理
UNITS = {"pos": ["deg", "mm"], "vel": ["rpm", "A", "V"], "temp": ["°C", "%RH", "kPa"]}
UNITS["any"] = sorted({u for v in UNITS.values() for u in v}) + MADE_UP
KIND_OF_UNIT = {u: k for k, v in UNITS.items() if k != "any" for u in v} | {u: "vel" for u in MADE_UP}
DTS = [0.0005, 0.001, 0.002, 0.005, 0.01]                # 候选采样/控制周期（s）
# 可调参数的角色 → 候选名字（名字随机，角色只写在 plant.json 里，被测方要自己从声明/实验里弄明白）
NAMES = {"P": ["kp", "Kp", "gain_p", "k_prop", "kc", "k1"], "I": ["ki", "Ki", "k_int", "i_gain", "k2"],
         "D": ["kd", "Kd", "k_der", "d_gain", "k3"], "FF": ["kff", "ff_gain", "k_ff", "feedfwd"],
         "LIM": ["u_max", "out_lim", "u_limit", "sat_cmd", "lim"]}
INFEASIBLE = {"saturation": "执行器饱和：满输出也到不了目标附近，稳态误差下不来",
              "delay_too_large": "纯滞后相对时间常数太大：调节时间要求比滞后本身还紧",
              "unstable_zero": "右半平面零点（非最小相位）：先反向再回来，调节时间要求做不到",
              "no_stable_gain": "可调参数范围内找不到闭环稳定的一组",
              "steady_state_error": "可调参数里没有积分作用，比例增益又受稳定性限制，稳态误差下不来"}


def _r(x: float, n: int = 6) -> float:
    return float(f"{x:.{n}g}")


def _nice_up(x: float) -> float:
    """向上取一个“题面里会写的”整数值（1/2/2.5/5 × 10^k）。"""
    if x <= 0:
        return 0.0
    e = np.floor(np.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * 10 ** e >= x * (1 - 1e-9):
            return _r(m * 10 ** e, 3)
    return _r(10 ** (e + 1), 3)


def _nice_down(x: float) -> float:
    if x <= 0:
        return 0.0
    e = np.floor(np.log10(x))
    for m in (10, 5, 2.5, 2, 1):
        if m * 10 ** e <= x * (1 + 1e-9):
            return _r(m * 10 ** e, 3)
    return _r(10 ** (e - 1), 3)


def _plant(rng, n: int, tau: float, gain: float, integrator: bool):
    np.random.seed(int(rng.integers(0, 2**31 - 1)))         # control.rss 用 numpy 全局状态 → 由 rng 派生的整数播种
    while True:
        sys_c = control.rss(n, 1, 1, strictly_proper=True)
        poles = np.asarray(control.poles(sys_c))
        if np.all(poles.real < -1e-3) and abs(float(control.dcgain(sys_c))) > 1e-6:
            break
    a = float(np.min(-poles.real)) * tau                    # 最慢极点 = 1/tau（形状保持）
    tf = control.ss2tf(sys_c)
    zs, ps = np.asarray(control.zeros(tf)) / a, poles / a
    g = control.tf(np.real(np.poly(zs)) if len(zs) else np.array([1.0]), np.real(np.poly(ps)))
    g = g * (gain / float(control.dcgain(g)))               # 恒正增益；方向由接线/声明解决
    if integrator:
        g = g * control.tf([1.0], [1.0, 0.0]) * (1.0 / max(tau, 0.05))
    return g


def _disc(g, delay: float, dt: float):
    gd = g
    if delay > 0:
        pn, pd = control.pade(delay, 2)
        gd = g * control.tf(pn, pd)
    s = control.c2d(control.ss(gd), dt, method="zoh")
    return tuple(np.asarray(m, dtype=float) for m in (s.A, s.B, s.C, s.D))


def simulate(p: dict, gains: np.ndarray, sp: float, T: float) -> np.ndarray:
    """与 app_main.c / sim_setup.c 逐拍一致的批量仿真（不加噪声）。gains: (M, 5) 按角色 P,I,D,FF,LIM。返回 y (M, K)。"""
    A, B, C, D = (np.asarray(p["ss"][k], dtype=float) for k in ("A", "B", "C", "D"))
    B, C, D = B.ravel(), C.ravel(), float(D)
    dt, sat, dz, half = p["dt_s"], p["sat"], p["deadzone"], 0.5 * p["sensor_range"]
    M, K = len(gains), int(round(T / dt))
    kp, ki, kd, ff, lim = (gains[:, i] for i in range(5))
    x = np.zeros((M, len(B))); yi = np.zeros(M); integ = np.zeros(M); pe = np.zeros(M); df = np.zeros(M)
    alpha = dt / (dt + 5 * dt)
    out = np.empty((M, K))
    for k in range(K):
        e = sp - yi
        integ = np.clip(integ + ki * e * dt, -lim, lim)
        df = df + alpha * ((e - pe) / dt - df) if k else df
        pe = e
        u = np.clip(kp * e + integ + kd * df + ff * sp, -lim, lim)
        ua = np.clip(u, -sat, sat)
        ua = np.where(np.abs(ua) <= dz, 0.0, ua - np.sign(ua) * dz)
        y = x @ C + D * ua
        x = x @ A.T + np.outer(ua, B)
        yi = np.clip(np.nan_to_num(y, nan=1e9), -half, half)
        out[:, k] = yi
    return out


def _metrics(y: np.ndarray, sp: float, dt: float) -> dict:
    K = y.shape[1]
    tail = y[:, int(0.9 * K):]
    ss = np.abs(tail.mean(1) - sp)
    os_ = np.maximum(0.0, (y.max(1) - sp) / abs(sp) * 100.0)
    band = 0.05 * abs(sp)                                    # 调节时间：进入并保持在终值 ±5% 幅度内
    outside = np.abs(y - tail.mean(1, keepdims=True)) > band
    last = np.where(outside.any(1), K - np.argmax(outside[:, ::-1], 1), 0)
    settle = last * dt
    stable = (np.ptp(tail, 1) < 0.2 * abs(sp)) & np.isfinite(y).all(1) & (np.abs(tail.mean(1)) >= 0.5 * abs(sp))   # 稳定且真的走过去了
    return {"ss": ss, "os": os_, "settle": np.where(outside[:, -1], np.inf, settle), "stable": stable}


def _grid(p: dict) -> np.ndarray:
    roles, rg = p["roles"], p["ranges"]
    def axis(role, m, zero=True):
        if role not in roles:
            return np.array([0.0])
        lo, hi = rg[roles[role]]
        v = hi * np.geomspace(1e-3, 1.0, m)
        return np.r_[0.0, v] if zero else v
    P = axis("P", 14, zero=False)
    I = axis("I", 6); Dd = axis("D", 3)
    FF = np.array([0.0]) if "FF" not in roles else np.unique(np.clip([0.0, 1.0 / p["gain"]] if not p["integrator"] else [0.0],
                                                                     *rg[roles["FF"]]))
    L = np.array([1.0]) if "LIM" not in roles else np.array([rg[roles["LIM"]][1]])
    return np.array(np.meshgrid(P, I, Dd, FF, L, indexing="ij")).reshape(5, -1).T


def search(p: dict) -> dict:
    """粗搜（python-control 离散化后的同一模型，不加噪声）：每项能做到的最好值 + 综合最好的一组参数。"""
    sp = 0.25 * p["sensor_range"]
    T = p["horizon_s"]
    G = _grid(p)
    m = _metrics(simulate(p, G, sp, T), sp, p["dt_s"])
    ok = m["stable"] & np.isfinite(m["settle"])
    roles = p["roles"]
    def params(i):
        return {roles[r]: _r(float(G[i, k]), 4) for k, r in enumerate(("P", "I", "D", "FF", "LIM")) if r in roles}
    if not ok.any():
        return {"step_amp": _r(sp), "found": False}
    score = np.where(ok, m["settle"] / T + m["ss"] / abs(sp) + m["os"] / 100.0, np.inf)
    b = int(np.argmin(score))
    return {"step_amp": _r(sp), "found": True, "horizon_s": T,
            "best": {"ss_err": _r(float(m["ss"][b]), 4), "overshoot_pct": _r(float(m["os"][b]), 4),
                     "settle_s": _r(float(m["settle"][b]), 4), "params": params(b)},
            "best_each": {"ss_err": _r(float(m["ss"][ok].min()), 4), "overshoot_pct": _r(float(m["os"][ok].min()), 4),
                          "settle_s": _r(float(m["settle"][ok].min()), 4)},
            "grid_n": int(len(G)), "ss_err_ok": bool(m["ss"][b] <= 0.1 * abs(sp))}


def gen(seed: int, order: str = "1-3", kind: str = "any") -> dict:
    rng = np.random.default_rng(seed)
    lo, hi = (int(v) for v in (order.split("-") + [order])[:2])
    n = int(rng.integers(lo, hi + 1))
    unit = str(rng.choice(UNITS[kind]))
    k_eff = KIND_OF_UNIT[unit] if kind == "any" else kind
    integrator = bool(k_eff == "pos" and rng.random() < 0.5)
    tau = float(np.exp(rng.uniform(np.log(0.02), np.log(2.0))))
    gain = float(np.exp(rng.uniform(np.log(0.2), np.log(50.0))))
    # 故意注入不可达：约 1/5（另有粗搜判出的不可达，合计约 4 成）
    bad = str(rng.choice(list(INFEASIBLE)[:3])) if rng.random() < 0.2 else ""
    if bad == "saturation" and integrator:
        bad = "delay_too_large"
    g = _plant(rng, n, tau, gain, integrator)
    if bad == "unstable_zero":
        z = float(rng.uniform(0.7, 2.0)) / tau
        g = g * control.tf([-1.0 / z, 1.0], [1.0 / z, 1.0])
    delay = round(float(rng.uniform(0.002, 0.3 * tau + 0.002)), 4) if rng.random() < 0.5 else 0.0
    if bad == "delay_too_large":
        delay = round(float(rng.uniform(1.5, 3.0)) * tau, 4)
    sat = _r(float(rng.uniform(0.5, 1.0)))
    dz = _r(float(rng.choice([0.0, rng.uniform(0.0, 0.08)])))
    yspan = gain * sat if not integrator else gain * sat / max(tau, 0.05)
    sensor = _r(max(1e-3, 2.0 * yspan * float(rng.uniform(1.0, 1.6))), 3)       # 传感器量程（物理）
    if bad == "saturation":
        sat = _r(0.25 * sensor * float(rng.uniform(0.3, 0.7)) / gain)           # 满输出只能走到目标的 30~70%
    noise = _r(float(rng.choice([0.0, rng.uniform(0, 0.004)])) * sensor, 3)
    max_step = _r(sensor * float(rng.uniform(0.3, 0.6)), 3)                      # 执行器能承受的单次最大阶跃（物理）
    tl = tau + delay + (1.0 / (float(rng.uniform(0.7, 2.0)) / tau) if bad == "unstable_zero" else 0)
    dt_ok = [d for d in DTS if d <= tl / 20] or DTS[:1]
    dt = float(rng.choice(dt_ok[-3:]))
    tel_ms = int(rng.choice([m for m in (5, 10, 20) if m >= dt * 1000]))
    A, B, C, D = _disc(g, delay, dt)

    # 可调参数：角色和名字都随机（只有 P 必有；可能只有它）
    roles = {"P": str(rng.choice(NAMES["P"]))}
    for r, pr in (("I", 0.5 if integrator else 0.8), ("D", 0.35), ("FF", 0.3), ("LIM", 0.4)):
        if rng.random() < pr:
            roles[r] = str(rng.choice([x for x in NAMES[r] if x not in roles.values()]))
    k0 = 1.0 / (gain if not integrator else gain / max(tau, 0.05))
    ranges = {roles["P"]: (0.0, _r(k0 * float(rng.uniform(5, 50)), 3))}
    if "I" in roles:
        ranges[roles["I"]] = (0.0, _r(k0 / max(tau, 0.02) * float(rng.uniform(5, 50)), 3))
    if "D" in roles:
        ranges[roles["D"]] = (0.0, _r(k0 * tau * float(rng.uniform(0.5, 5)), 3))
    if "FF" in roles:
        ranges[roles["FF"]] = (0.0, _r(k0 * float(rng.uniform(1.5, 4)), 3))
    if "LIM" in roles:
        ranges[roles["LIM"]] = (0.1, 1.0)
    init, max_delta = {}, {}
    for r, nm in roles.items():
        a, b = ranges[nm]
        init[nm] = 1.0 if r == "LIM" else _r(float(rng.uniform(a + 0.05 * (b - a), a + 0.6 * (b - a))), 4)
        max_delta[nm] = _r((b - a) * float(rng.uniform(0.1, 0.4)), 3)
    p = {"seed": seed, "name": f"randplant-{seed}", "kind": k_eff, "unit": unit, "order": n, "integrator": integrator,
         "tf": {"num": [_r(float(c)) for c in np.ravel(control.tfdata(g)[0][0][0])],
                "den": [_r(float(c)) for c in np.ravel(control.tfdata(g)[1][0][0])]},
         "gain": _r(gain), "tau_s": _r(tau), "delay_s": delay, "pade_order": 2 if delay > 0 else 0,
         "sat": sat, "deadzone": dz, "noise_std": noise, "sensor_range": sensor, "max_step": max_step,
         "dt_s": dt, "telem_period_ms": tel_ms, "horizon_s": _r(min(30.0, 10 * tl + 20 * dt), 3),
         "roles": roles, "ranges": {k: list(v) for k, v in ranges.items()}, "init": init, "max_delta": max_delta,
         "ss": {"A": A.tolist(), "B": B.ravel().tolist(), "C": C.ravel().tolist(), "D": float(D.ravel()[0])}}
    ref = search(p)
    p["reference"] = ref
    p.update(_spec(p, rng, bad, ref))
    return p


def _fmt(v: float) -> str:
    return f"{v:g}"


def _spec(p: dict, rng, bad: str, ref: dict) -> dict:
    """题面式指标 + metrics_card 结构的逐条真值。feasible：参考参数同时满足全部条目；
    不可达：某一条比粗搜里该项能做到的最好值还紧一半（原因类别写明）。"""
    u, amp = p["unit"], ref["step_amp"]
    if not ref["found"]:                                     # 粗网格上一组稳定的都没有：按“不可达”出题，原因归到注入的类别
        bad = bad or "no_stable_gain"
        ss_t, os_t, st_t = _nice_down(0.02 * amp), 10.0, None
    else:
        b, e = ref["best"], ref["best_each"]
        ss_t = _nice_up(max(1.5 * b["ss_err"], 0.01 * amp))
        os_t = _nice_up(max(b["overshoot_pct"] + 5, 10.0))
        st_t = _nice_up(max(1.5 * b["settle_s"], 2 * p["dt_s"])) if (bad or rng.random() < 0.5) else None
        if not bad and b["ss_err"] > 0.1 * amp:              # 没有积分、比例受稳定性限制：题面要的精度做不到
            bad, ss_t = "steady_state_error", _nice_down(0.05 * amp)
        if bad == "saturation":
            ss_t = _nice_down(0.5 * e["ss_err"])
        elif bad in ("delay_too_large", "unstable_zero"):
            st_t = _nice_down(max(0.5 * e["settle_s"], p["dt_s"]))
    items = [{"name": "稳态误差", "clause": "要求(1)", "target": {"op": "<=", "value": ss_t, "unit": u},
              "reference": ref["best"]["ss_err"] if ref["found"] else None},
             {"name": "超调量", "clause": "要求(2)", "target": {"op": "<=", "value": os_t, "unit": "%"},
              "reference": ref["best"]["overshoot_pct"] if ref["found"] else None}]
    if st_t is not None:
        items.append({"name": "调节时间", "clause": "要求(3)", "target": {"op": "<=", "value": st_t, "unit": "s"},
                      "reference": ref["best"]["settle_s"] if ref["found"] else None})
    for it in items:
        it["verdict_expected"] = "pass" if not bad else "fail_or_unknown"
    parts = [f"稳态误差不超过 {_fmt(ss_t)}{u}", f"超调不超过 {_fmt(os_t)}%"] + ([f"调节时间不超过 {_fmt(st_t)} s"] if st_t else [])
    text = f"阶跃幅度为 {_fmt(amp)}{u} 时，" + "，".join(parts) + "。"
    if ss_t > 0.2 * amp:
        ss_t = _nice_down(0.2 * amp)
    return {"feasible": not bad, "reason_category": bad or None, "reason": INFEASIBLE.get(bad, ""),
            "spec_text": text, "items": items}


def app_yaml(p: dict) -> str:
    u = p["unit"]; r = p["ranges"]; i = p["init"]; md = p["max_delta"]
    lim = p["roles"].get("LIM")
    params = "\n".join(f"    - {{ name: {nm}, type: float, default: {i[nm]}, min: {r[nm][0]}, max: {r[nm][1]}, max_delta: {md[nm]}, role: {ro} }}"
                       for ro, nm in p["roles"].items())
    return f"""# 由 tools/randplant.py --seed {p['seed']} 生成：随机被控对象（只在 host-sim 上跑）。不要手改，重新生成。
name: {p['name']}
version: 1.0.0
description: 随机对象 seed={p['seed']}（单位 {u}）
requires:
  uart: [LINK]
  timer: [CTRL]
link:
  telemetry:
    id: 2
    period_ms: {p['telem_period_ms']}
    fields:
      - {{ name: t_ms, type: uint32, unit: ms }}
      - {{ name: sp, type: float, unit: "{u}", ref_for: y, hold: latched }}
      - {{ name: y, type: float, unit: "{u}" }}
      - {{ name: u, type: float }}
      - {{ name: run, type: uint8, enum: [STOPPED, RUNNING, ESTOP], pin: 状态 }}
  step:
    - {{ sp: 0, y: y, u: u, u_max: {lim or 1.0}, sensor_range: {p['sensor_range']}, max_step: {p['max_step']} }}
  params:
{params}
"""


def sim_c(p: dict) -> str:
    """对象 C 代码：与 plant: 声明共用 tools/plantmodel.py（滞后已用 Padé 折进状态空间；传感器量程限幅）。"""
    return plantmodel.sim_c(p["ss"], dt=p["dt_s"], sat=(-float(p["sat"]), float(p["sat"])), deadzone=float(p["deadzone"]),
                            noise_std=float(p["noise_std"]), seed=int(p["seed"]), y_range=(-0.5 * float(p["sensor_range"]), 0.5 * float(p["sensor_range"])),
                            tag=f"tools/randplant.py --seed {p['seed']}")


def app_main(p: dict) -> str:
    ro = p["roles"]
    g = lambda r, dflt: f"g_link_params.{ro[r]}" if r in ro else dflt
    us = int(round(p["dt_s"] * 1e6))
    return f"""/* 由 tools/randplant.py --seed {p['seed']} 生成：本对象的控制器（可调参数 {', '.join(ro.values())}）。
 * 链路（0x7B 阶跃、PARAM_SET 校验/param_reject、急停、心跳 bit17、设定值保持）全部来自 link_app.h，零手写。 */
#include "board_gen.h"
#include "app.h"
#include "link_app.h"
#include "pid.h"
#include "dz_compiler.h"

#define CTRL_PERIOD_US {us}u
#define DT ({us}e-6f)

DZ_WEAK float sim_plant_step(float u);
DZ_WEAK float sim_plant_step(float u) {{ (void)u; return 0.0f; }}   /* 真板没有对象：只在 host-sim 由 sim_setup.c 提供 */

static link_app_t L;
static volatile float s_y, s_u;
static float s_i, s_pe, s_df;
static bool s_first = true;

static float clampf(float v, float m) {{ return v > m ? m : (v < -m ? -m : v); }}

/* 0x7C 继电输出接管：借 pid 库的继电器（同一套 bias±amp/滞环/超时/急停结束语义）。s_relay 只当“回路 0”的
 * 继电槽，不做 PID：平时每拍把它的输出对齐到本控制器的 u（继电开始时 bias = 当前工作点），继电期间输出由它给。 */
static pid_ctrl_t s_relay;
static bool s_was_relay;

static void ctrl_isr(void *ctx)
{{
    (void)ctx;
    float u = 0.0f, lim = {g('LIM', '1.0f')}, sp = L.sp[0];
    if (L.estop) {{ s_i = 0.0f; s_df = 0.0f; s_first = true; s_was_relay = false; }}
    else if (pid_relay_active() == 0 || s_was_relay) {{
        u = clampf(pid_update(&s_relay, sp, s_y), lim);
        s_was_relay = pid_relay_active() == 0;
        if (!s_was_relay) {{ s_i = clampf(u, lim); s_first = true; }}   /* 继电结束：积分项接住 bias，无扰切回 */
    }}
    else {{
        float e = sp - s_y;
        s_i = clampf(s_i + {g('I', '0.0f')} * e * DT, lim);
        if (!s_first) s_df += (1.0f / 6.0f) * ((e - s_pe) / DT - s_df);
        s_first = false; s_pe = e;
        u = clampf({g('P', '0.0f')} * e + s_i + {g('D', '0.0f')} * s_df + {g('FF', '0.0f')} * sp, lim);
    }}
    if (pid_relay_active() != 0) pid_reset_to(&s_relay, u);
    s_u = u;
    s_y = sim_plant_step(u);
}}

dz_err_t app_init(void)
{{
    pid_cfg_t rc = pid_cfg_default(DT);
    rc.dt_s = DT; rc.out_min = -{float(p['sat']):.6g}f; rc.out_max = {float(p['sat']):.6g}f; rc.i_min = rc.out_min; rc.i_max = rc.out_max;
    dz_err_t e = pid_init(&s_relay, &rc);   /* 继电槽 = 回路 0 */
    if (e != DZ_OK) return e;
    link_app_init(&L, 0, 0);
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}}

void app_loop(void)
{{
    uint32_t now = pal_millis();
    if (!link_app_poll(&L, now)) return;
    link_telem_t t = {{ 0 }};
    uint32_t st = pal_irq_save();
    t.t_ms = now; t.sp = L.sp[0]; t.y = s_y; t.u = s_u;
    pal_irq_restore(st);
    t.run = L.estop ? 2u : 1u;
    link_app_send_telem(&L, &t);
}}
"""


def write(p: dict, out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    y = app_yaml(p)
    (out / "app.yaml").write_text(y, encoding="utf-8")
    (out / "link.yaml").write_text(y[y.index("link:"):], encoding="utf-8")
    (out / "spec.txt").write_text(p["spec_text"] + "\n", encoding="utf-8")
    (out / "app_main.c").write_text(app_main(p), encoding="utf-8")
    (out / "sim_setup.c").write_text(sim_c(p), encoding="utf-8")
    (out / "plant.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


def build(p: dict, out: pathlib.Path) -> pathlib.Path:
    """在仓库 build/host-sim/<name>/ 编出仿真板（侧车按 sim:<name> 找它），再拷一份到 <out>/build/。"""
    name = p["name"]
    subprocess.run(["make", "-s", "-C", str(ROOT), "BOARD=host-sim", f"APP={name}", f"APP_DIR={out.resolve()}"], check=True,
                   stdout=subprocess.DEVNULL)
    exe = ".exe" if sys.platform == "win32" else ""
    elf = ROOT / "build" / "host-sim" / name / f"{name}.elf{exe}"
    (out / "build").mkdir(exist_ok=True)
    shutil.copy2(elf, out / "build" / elf.name)
    return elf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--order", default="1-3")
    ap.add_argument("--kind", default="any", choices=list(UNITS))
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--build", action="store_true", help="编出仿真板 sim:randplant-<seed>")
    ap.add_argument("--run", action="store_true", help="编完直接启动仿真板（前台，Ctrl+C 结束）")
    a = ap.parse_args(argv)
    p = gen(a.seed, a.order, a.kind)
    write(p, a.out)
    print(f"{p['name']}: order={p['order']} unit={p['unit']} dt={p['dt_s']} params={list(p['roles'].values())} "
          f"feasible={p['feasible']}{'（' + p['reason_category'] + '）' if p['reason_category'] else ''} → {a.out}\n  spec: {p['spec_text']}")
    if a.build or a.run:
        elf = build(p, a.out)
        print(f"仿真板 sim:{p['name']} → {elf}")
        if a.run:
            return subprocess.call([str(elf)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
