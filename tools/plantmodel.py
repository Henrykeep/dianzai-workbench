#!/usr/bin/env python3
"""通用被控对象模型（app.yaml 的 plant: 声明 → host-sim 仿真对象）。全仓只有这一份对象代码：
  - 仿真板：Makefile 对带 plant: 且没有 sim_setup.c 的应用，在 host-sim 上生成 $(OUT)/plantgen/plant_sim.c
  - tools/randplant.py 生成随机对象时也用这里的 discretize()/sim_c()/generic_app()（不重复写）

    python tools/plantmodel.py check <app.yaml|dir>...     校验 plant:（schema/plant.schema.json + 语义）
    python tools/plantmodel.py gen <app.yaml> -o plant_sim.c
    python tools/plantmodel.py scaffold <app.yaml> --out <dir>   没有控制代码的新题：补通用 PID 回路 app_main.c
                                                                  和通用 link:（sp/y/u、kp/ki/kd/u_max、step）

对象：G(s) = gain · Π 1/(τᵢs+1) [· ωn²/(s²+2ζωn s+ωn²)] [· 1/s]，或 tf: {num, den}；ZOH 离散到 sample_s；
纯滞后按整拍延迟执行量；执行器先饱和后死区；输出 = y0 + G·u + N(0, noise_std²)。
仅仿真标称或粗估（estimate: coarse|identified），不作实机判定。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np
import yaml

try:
    import control
except ImportError:  # pragma: no cover
    sys.exit("缺 python-control：pip install -r app/sidecar/requirements.txt")

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "plant.schema.json"
MAX_DELAY_SAMPLES = 8192
STRUCT_KEYS = ("gain", "tau_s", "zeta", "wn_rad_s", "integrator")


def _r(x: float, n: int = 6) -> float:
    return float(f"{x:.{n}g}")


def load(path) -> dict | None:
    p = pathlib.Path(path)
    if p.is_dir():
        p = p / "app.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return doc.get("plant")


def validate(d) -> list[str]:
    """返回错误列表（中文，带字段名）；空 = 合规。"""
    import jsonschema
    if not isinstance(d, dict):
        return ["plant: 必须是映射"]
    v = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    errs = [f"plant.{'.'.join(str(x) for x in e.absolute_path) or '(根)'}: {e.message}" for e in v.iter_errors(d)]
    if errs:
        return errs
    if "tf" in d:
        both = [k for k in STRUCT_KEYS if k in d]
        if both:
            errs.append(f"plant: 给了 tf 就不要再给 {', '.join(both)}")
        den = d["tf"]["den"]
        if den[0] == 0:
            errs.append("plant.tf.den: 首项不能为 0")
        elif len(den) - 1 != d["order"]:
            errs.append(f"plant.order={d['order']} 与 tf.den 阶次 {len(den) - 1} 不符")
        if len(d["tf"]["num"]) > len(den):
            errs.append("plant.tf: 分子阶次高于分母（非因果）")
    else:
        if "gain" not in d:
            errs.append("plant.gain: 没给 tf 时必填")
        if ("zeta" in d) != ("wn_rad_s" in d):
            errs.append("plant: zeta 和 wn_rad_s 要一起给")
        n = len(d.get("tau_s", [])) + (2 if "zeta" in d else 0) + (1 if d.get("integrator") else 0)
        if n != d["order"]:
            errs.append(f"plant.order={d['order']} 与结构不符（tau_s {len(d.get('tau_s', []))} 个"
                        f"{' + 复极点对 2' if 'zeta' in d else ''}{' + 积分 1' if d.get('integrator') else ''} = {n}）")
    lo, hi = sat_limits(d)
    if not lo < hi:
        errs.append(f"plant.saturation: min {lo} 必须小于 max {hi}")
    elif d.get("deadzone", 0) >= max(abs(lo), abs(hi)):
        errs.append("plant.deadzone: 不小于饱和幅值，执行器永远没输出")
    dt = d.get("sample_s", 0.001)
    if round(d.get("delay_s", 0) / dt) > MAX_DELAY_SAMPLES:
        errs.append(f"plant.delay_s/sample_s 超过 {MAX_DELAY_SAMPLES} 拍，加大 sample_s")
    return errs


def sat_limits(d: dict) -> tuple[float, float]:
    s = d.get("saturation", 1.0)
    return (-float(s), float(s)) if isinstance(s, (int, float)) else (float(s["min"]), float(s["max"]))


def continuous(d: dict):
    """无滞后的连续传函。"""
    if "tf" in d:
        return control.tf([float(x) for x in d["tf"]["num"]], [float(x) for x in d["tf"]["den"]])
    g = control.tf([float(d["gain"])], [1.0])
    for t in d.get("tau_s", []):
        g = g * control.tf([1.0], [float(t), 1.0])
    if "zeta" in d:
        wn, z = float(d["wn_rad_s"]), float(d["zeta"])
        g = g * control.tf([wn * wn], [1.0, 2 * z * wn, wn * wn])
    if d.get("integrator"):
        g = g * control.tf([1.0], [1.0, 0.0])
    return g


def discretize(g, dt: float) -> dict:
    s = control.c2d(control.ss(g), dt, method="zoh")
    A, B, C, D = (np.asarray(m, dtype=float) for m in (s.A, s.B, s.C, s.D))
    return {"A": A.tolist(), "B": B.ravel().tolist(), "C": C.ravel().tolist(), "D": float(D.ravel()[0])}


def sim_c(ss: dict, *, dt: float, sat: tuple[float, float], deadzone: float = 0.0, noise_std: float = 0.0,
          delay_n: int = 0, y0: float = 0.0, seed: int = 1, tag: str = "plant") -> str:
    """离散状态空间 → host-sim C：float sim_plant_step(float u)（每个采样周期调一次，返回带噪声的测量值）。"""
    n = len(ss["B"])
    fl = lambda xs: ", ".join(f"{float(x):.9e}f" for x in xs)
    A = ",\n    ".join("{ " + fl(row) + " }" for row in ss["A"])
    lo, hi = sat
    dl = (f"static float s_dl[{delay_n}];\nstatic unsigned s_di;\n" if delay_n else "")
    dstep = (f"    {{ float w = s_dl[s_di]; s_dl[s_di] = u; s_di = (s_di + 1u) % {delay_n}u; u = w; }}\n" if delay_n else "")
    return f"""/* 由 tools/plantmodel.py 生成（{tag}）：离散 ZOH 被控对象，dt = {dt} s，仅 host-sim 编译。不要手改。 */
#include <math.h>
#include <stdint.h>

float sim_plant_step(float u);
void host_sim_app_setup(void);

#define SP_N {n}
static const float A[SP_N][SP_N] = {{
    {A}
}};
static const float B[SP_N] = {{ {fl(ss['B'])} }};
static const float C[SP_N] = {{ {fl(ss['C'])} }};
static const float D = {ss['D']:.9e}f;
static float x[SP_N];
{dl}static uint32_t s_rng = {(int(seed) * 2654435761) % 2**32 or 1}u;

static float urand(void) {{ s_rng ^= s_rng << 13; s_rng ^= s_rng >> 17; s_rng ^= s_rng << 5; return (float)(s_rng >> 8) * (1.0f / 16777216.0f); }}
static float gauss(void) {{ float a = urand() + 1e-7f, b = urand(); return sqrtf(-2.0f * logf(a)) * cosf(6.2831853f * b); }}

/* 一步对象：饱和 → 死区 → 纯滞后（整拍）→ 线性；返回 y0 + 输出 + 噪声 */
float sim_plant_step(float u)
{{
    float xn[SP_N], y;
    if (u != u) u = 0.0f;
    if (u > {hi:.9e}f) u = {hi:.9e}f;
    if (u < {lo:.9e}f) u = {lo:.9e}f;
    u = fabsf(u) <= {float(deadzone):.9e}f ? 0.0f : (u > 0 ? u - {float(deadzone):.9e}f : u + {float(deadzone):.9e}f);
{dstep}    y = D * u;
    for (int i = 0; i < SP_N; i++) y += C[i] * x[i];
    for (int i = 0; i < SP_N; i++) {{ xn[i] = B[i] * u; for (int j = 0; j < SP_N; j++) xn[i] += A[i][j] * x[j]; }}
    for (int i = 0; i < SP_N; i++) x[i] = xn[i];
    return {float(y0):.9e}f + y + {float(noise_std):.9e}f * gauss();
}}

__attribute__((weak)) void host_sim_app_setup(void) {{ }}
"""


def gen_c(d: dict, tag: str = "plant:") -> str:
    dt = float(d.get("sample_s", 0.001))
    return sim_c(discretize(continuous(d), dt), dt=dt, sat=sat_limits(d), deadzone=float(d.get("deadzone", 0.0)),
                 noise_std=float(d.get("noise_std", 0.0)), delay_n=int(round(float(d.get("delay_s", 0.0)) / dt)),
                 y0=float(d.get("y0", 0.0)), seed=int(d.get("seed", 1)), tag=f"{tag} estimate={d['estimate']}")


# ------------------------------------------------------------------ 通用回路（新题没有控制代码时的脚手架）
def generic_app(ctrl_period_us: int = 1000) -> str:
    return """/* 由 tools/plantmodel.py 生成：通用 PID 回路。链路（0x7B 阶跃、PARAM_SET 校验/param_reject、急停、心跳）全部来自 link_app.h；
 * 对象在 host-sim 上由 plant: 声明生成（sim_plant_step），真板上换成实际的采样/驱动。 */
#include "board_gen.h"
#include "app.h"
#include "pid.h"
#include "link_app.h"
#include "dz_compiler.h"

#define CTRL_PERIOD_US %du

DZ_WEAK float sim_plant_step(float u);
DZ_WEAK float sim_plant_step(float u) { (void)u; return 0.0f; }   /* 真板没有仿真对象 */

static pid_ctrl_t s_pid;
static link_app_t L;
static volatile bool s_dirty = true;
static volatile float s_y, s_u;

static void apply_params(void) { s_dirty = true; }

static void ctrl_isr(void *ctx)
{
    (void)ctx;
    if (s_dirty) {
        (void)pid_set_gains(&s_pid, g_link_params.kp, g_link_params.ki, g_link_params.kd);
        s_pid.cfg.out_min = -g_link_params.u_max; s_pid.cfg.out_max = g_link_params.u_max;
        s_pid.cfg.i_min = -g_link_params.u_max; s_pid.cfg.i_max = g_link_params.u_max;
        s_dirty = false;
    }
    float u = 0.0f;
    if (L.estop) pid_reset(&s_pid);
    else u = pid_update(&s_pid, L.sp[0], s_y);
    s_u = u;
    s_y = sim_plant_step(u);
}

dz_err_t app_init(void)
{
    dz_err_t e;
    pid_cfg_t pc = pid_cfg_default(CTRL_PERIOD_US * 1e-6f);
    pc.kp = g_link_params.kp; pc.ki = g_link_params.ki; pc.kd = g_link_params.kd;
    pc.out_min = -1.0f; pc.out_max = 1.0f; pc.i_min = -1.0f; pc.i_max = 1.0f;
    if ((e = pid_init(&s_pid, &pc)) != DZ_OK) return e;
    link_app_init(&L, apply_params, 0);
    return pal_timer_start(RES_TIMER_CTRL, CTRL_PERIOD_US, ctrl_isr, 0);
}

void app_loop(void)
{
    uint32_t now = pal_millis();
    if (!link_app_poll(&L, now)) return;
    link_telem_t t = { 0 };
    uint32_t st = pal_irq_save();
    t.t_ms = now; t.sp = L.sp[0]; t.y = s_y; t.u = s_u;
    pal_irq_restore(st);
    t.run = L.estop ? 2u : 1u;
    link_app_send_telem(&L, &t);
}
""" % ctrl_period_us


def link_yaml(unit: str, ranges: dict, init: dict, step: dict | None = None, u_max_hi: float = 1.0) -> str:
    """通用 link: 段（sp/y/u 遥测、kp/ki/kd/u_max 参数、一个阶跃通道）。step 只写给了的键（物理上限等）。"""
    md = lambda k: _r((ranges[k][1] - ranges[k][0]) * 0.25, 3)
    st = ", ".join(f"{k}: {v}" for k, v in (step or {}).items())
    return f"""link:
  telemetry:
    id: 2
    period_ms: 10
    fields:
      - {{ name: t_ms, type: uint32, unit: ms }}
      - {{ name: sp, type: float, unit: {json.dumps(unit, ensure_ascii=False)}, ref_for: y, hold: latched }}
      - {{ name: y, type: float, unit: {json.dumps(unit, ensure_ascii=False)} }}
      - {{ name: u, type: float }}
      - {{ name: run, type: uint8, enum: [STOPPED, RUNNING, ESTOP], pin: 状态 }}
  step:
    - {{ sp: 0, y: y, u: u, u_max: u_max{', ' + st if st else ''} }}
  params:
""" + "".join(f"    - {{ name: {k}, type: float, default: {init[k]}, min: {ranges[k][0]}, max: {ranges[k][1]}, max_delta: {md(k)} }}\n"
              for k in ("kp", "ki", "kd")) + f"    - {{ name: u_max, type: float, default: {u_max_hi}, min: 0.1, max: {u_max_hi} }}\n"


def param_ranges(d: dict) -> tuple[dict, dict]:
    """按对象量级给 kp/ki/kd 的范围和起始值（不同题目量纲不同，范围随对象走；不是整定）。"""
    g = continuous(d)
    p = np.asarray(control.poles(g))
    nz = np.abs(p[np.abs(p) > 1e-9])
    tau = float(1.0 / nz.min()) if nz.size else 1.0
    k, integ = static_gain(g)
    k0 = 1.0 / max(abs(k) / max(tau, 0.05), 1e-9) if integ else 1.0 / max(abs(k), 1e-9)
    rng = {"kp": (0.0, _r(20 * k0, 3)), "ki": (0.0, _r(20 * k0 / max(tau, 0.02), 3)), "kd": (0.0, _r(2 * k0 * tau, 3))}
    init = {"kp": _r(k0, 4), "ki": 0.0, "kd": 0.0}
    return rng, init


def static_gain(g) -> tuple[float, bool]:
    """(增益, 是否含积分)：带 1/s 时返回速度增益（去掉分母的零常数项再求 DC 增益，避免 0·∞）。"""
    num = np.ravel(control.tfdata(g)[0][0][0]).astype(float)
    den = np.ravel(control.tfdata(g)[1][0][0]).astype(float)
    integ = abs(den[-1]) <= 1e-12 * max(1.0, float(np.max(np.abs(den))))
    if integ:
        den = den[:-1]
    return float(np.polyval(num, 0.0) / np.polyval(den, 0.0)), bool(integ)


def step_limits(d: dict) -> dict:
    """阶跃通道的物理量级（gen_link 目前要求 range/abs_tol）：range = 执行器满幅下对象能走到的幅度
    （积分对象取 1 s 行程），abs_tol = 1% range 与 3σ 噪声取大。仅由声明推出，阶跃幅度/容差由后端实测再定。"""
    k, _ = static_gain(continuous(d))
    span = abs(k) * max(abs(x) for x in sat_limits(d))
    span = _r(max(span, 1e-3), 3)
    return {"range": span, "abs_tol": _r(max(0.01 * span, 3 * float(d.get("noise_std", 0.0)), 1e-4), 3)}


def scaffold(app_yaml: pathlib.Path, out: pathlib.Path) -> None:
    doc_txt = app_yaml.read_text(encoding="utf-8")
    doc = yaml.safe_load(doc_txt) or {}
    d = doc.get("plant")
    errs = validate(d)
    if errs:
        raise SystemExit("\n".join(errs))
    out.mkdir(parents=True, exist_ok=True)
    txt = doc_txt.rstrip() + "\n"
    if "requires" not in doc:
        txt += "requires:\n  uart: [LINK]\n  timer: [CTRL]\n"
    if "link" not in doc:
        r, i = param_ranges(d)
        txt += link_yaml(d["unit"], r, i, step=step_limits(d), u_max_hi=_r(max(abs(x) for x in sat_limits(d)), 4))
    (out / "app.yaml").write_text(txt, encoding="utf-8")
    if not any(out.glob("*.c")):
        (out / "app_main.c").write_text(generic_app(int(round(float(d.get("sample_s", 0.001)) * 1e6))), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("paths", nargs="+", type=pathlib.Path)
    g = sub.add_parser("gen"); g.add_argument("app", type=pathlib.Path); g.add_argument("-o", required=True, type=pathlib.Path)
    s = sub.add_parser("scaffold"); s.add_argument("app", type=pathlib.Path); s.add_argument("--out", required=True, type=pathlib.Path)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        bad = 0
        for p in a.paths:
            d = load(p)
            errs = ["没有 plant: 段"] if d is None else validate(d)
            for e in errs:
                print(f"✗ {p}: {e}")
            bad += bool(errs)
        return 1 if bad else 0
    if a.cmd == "gen":
        d = load(a.app)
        errs = ["没有 plant: 段"] if d is None else validate(d)
        if errs:
            print("\n".join(f"✗ {a.app}: {e}" for e in errs), file=sys.stderr)
            return 1
        a.o.parent.mkdir(parents=True, exist_ok=True)
        a.o.write_text(gen_c(d), encoding="utf-8")
        return 0
    scaffold(a.app if a.app.is_file() else a.app / "app.yaml", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
