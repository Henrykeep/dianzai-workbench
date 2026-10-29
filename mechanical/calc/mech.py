#!/usr/bin/env python3
"""机械估算：转动惯量 / 所需扭矩 / 电机选型核对（纯 Python，无依赖）。

  python3 mechanical/calc/mech.py mechanical/templates/diff_chassis.yaml      # 打印结果表
  python3 mechanical/calc/mech.py <题目>.yaml --sim out.yaml                   # 另存 sim: 块（host-sim 对象参数）

通用部分（与机构无关）：
  inertia(shape, ...)        常见形状对质心轴的转动惯量 + 平行轴定理
  axis_torque(J, α, 重力矩, 摩擦)   T = Jα + M_g + T_f
  bang_bang_alpha(θ, t)      走 θ 用时 t（先加速后减速）所需 α = 4θ/t²
  motor_check(需求, 电机)     线性机械特性 T(n) = T_stall·(1 − n/n0)，按安全系数核对，给裕量和惯量比
机构模板（mechanical/templates/*.yaml，kind 选一个）只负责把几何/质量换成 J、α、重力矩，再调用通用部分：
  diff_chassis（差速底盘）、gimbal（二轴云台）、beam（球杆 / 平板的一根轴，ball_plate 两轴同算）。
单位：输入 yaml 用 kg、mm、deg、s（工程习惯），内部全换 SI。所有结果是**估算**，以称重/实测为准。
"""
from __future__ import annotations

import argparse
import math
import pathlib
import sys

G = 9.80665


# ── 通用 ────────────────────────────────────────────────────────
def inertia(shape: str, m: float, **k) -> float:
    """对质心轴（加 d= 则用平行轴定理移到距质心 d 的轴）。长度单位 m。"""
    if shape == "point":
        j = 0.0
    elif shape == "cylinder":            # 实心圆柱/圆盘绕自身轴
        j = 0.5 * m * k["r"] ** 2
    elif shape == "ring":                # 薄壁圆环绕自身轴
        j = m * k["r"] ** 2
    elif shape == "rod":                 # 细杆绕中点垂直轴
        j = m * k["L"] ** 2 / 12
    elif shape == "plate":               # 矩形板绕过质心、平行于边 b 的轴（a 为垂直于轴的边长）；厚度 t 可选
        j = m * (k["a"] ** 2 + k.get("t", 0.0) ** 2) / 12
    elif shape == "box":                 # 长方体绕过质心、垂直于 a×b 面的轴
        j = m * (k["a"] ** 2 + k["b"] ** 2) / 12
    elif shape == "sphere":              # 实心球
        j = 0.4 * m * k["r"] ** 2
    else:
        raise ValueError(f"未知形状 {shape}")
    return j + m * k.get("d", 0.0) ** 2


def axis_torque(J: float, alpha: float, grav_moment: float = 0.0, friction: float = 0.0) -> float:
    return J * alpha + grav_moment + friction


def bang_bang_alpha(theta_rad: float, t_s: float) -> float:
    return 4 * theta_rad / t_s ** 2


def motor_check(T_req: float, n_req_rpm: float, motor: dict, sf: float = 1.5, J_load: float | None = None) -> dict:
    """motor: stall_torque_nm / no_load_rpm 为**输出轴**（含减速箱）数据；gear_ratio + rotor_inertia_kgm2 可选，用来算惯量比。"""
    Ts, n0 = motor["stall_torque_nm"], motor["no_load_rpm"]
    T_av = Ts * (1 - n_req_rpm / n0) if n_req_rpm < n0 else 0.0
    out = {"T_req_nm": T_req, "n_req_rpm": n_req_rpm, "T_avail_nm": T_av,
           "margin": (T_av / T_req) if T_req > 0 else math.inf, "ok": T_av >= sf * T_req and n_req_rpm < n0,
           "rated_ok": None}
    if "rated_torque_nm" in motor:        # 连续工作看额定扭矩（堵转只能短时）
        out["rated_ok"] = motor["rated_torque_nm"] >= T_req
    if J_load is not None and motor.get("rotor_inertia_kgm2"):
        N = motor.get("gear_ratio", 1)
        out["inertia_ratio"] = J_load / (N ** 2 * motor["rotor_inertia_kgm2"])   # 折算到电机轴；经验 ≤10 好调
    return out


# ── 机构 ────────────────────────────────────────────────────────
def diff_chassis(c: dict) -> dict:
    m, w, mo = c["mass_kg"], c["wheel"], c["motion"]
    r = w["radius_mm"] / 1000
    n = w.get("count_driven", 2)
    a, th = mo["a_max_mps2"], math.radians(mo.get("slope_deg", 0))
    F = m * (a + G * math.sin(th) + mo.get("crr", 0.0) * G * math.cos(th))
    alpha = a / r
    Jw = inertia("cylinder", w.get("mass_kg", 0.0), r=r)
    eta = c.get("drive", {}).get("efficiency", 1.0)
    T = axis_torque(Jw, alpha, F * r / n) / eta
    omega = mo["v_max_mps"] / r
    rpm = omega * 60 / (2 * math.pi)
    res = {"per_motor": {"T_req_nm": T, "n_req_rpm": rpm, "P_w": T * omega}, "sim": {"mass_kg": m, "wheel_radius_m": r, "wheel_inertia_kgm2": Jw}}
    if "motor" in c:
        res["motor"] = motor_check(T, rpm, c["motor"], c.get("safety_factor", 1.5))
    return res


def beam(c: dict) -> dict:
    """一根转轴 + 球。plate: true 时把 length 当平板边长（球杆和平板的一根轴同一公式）。"""
    b, ball = c["beam"], c.get("ball", {"mass_kg": 0.0})
    L = b["length_mm"] / 1000
    d = b.get("com_offset_mm", 0.0) / 1000          # 梁质心到转轴的距离（偏心产生重力矩）
    J_beam = inertia("plate" if b.get("plate") else "rod", b["mass_kg"], a=L, L=L, d=d)
    x = ball.get("x_max_mm", L * 500) / 1000         # 默认球在端部
    J_ball = inertia("point", ball["mass_kg"], d=x)
    mv = c["move"]
    alpha = bang_bang_alpha(math.radians(mv["angle_deg"]), mv["time_s"])
    M_g = ball["mass_kg"] * G * x + b["mass_kg"] * G * d   # 水平附近最坏（cos≈1）
    T = axis_torque(J_beam + J_ball, alpha, M_g, c.get("friction_nm", 0.0))
    lever = c.get("lever_ratio", 1.0)                 # 舵机经连杆：梁扭矩 / 舵机扭矩
    peak_w = alpha * mv["time_s"] / 2
    res = {"J_kgm2": J_beam + J_ball, "alpha_rad_s2": alpha, "M_grav_nm": M_g,
           "actuator": {"T_req_nm": T / lever, "n_req_rpm": peak_w * lever * 60 / (2 * math.pi)},
           "sim": {"J_kgm2": J_beam + J_ball, "ball_mass_kg": ball["mass_kg"], "beam_length_m": L}}
    if "motor" in c:
        res["motor"] = motor_check(T / lever, res["actuator"]["n_req_rpm"], c["motor"], c.get("safety_factor", 1.5),
                                   (J_beam + J_ball) / lever ** 2)
    return res


def gimbal(c: dict) -> dict:
    out = {"axes": {}, "sim": {}}
    for ax, a in c["axes"].items():
        p = a["payload"]
        if "inertia_kgm2" in p:
            J = p["inertia_kgm2"]
        else:
            J = inertia("box", p["mass_kg"], a=p["a_mm"] / 1000, b=p["b_mm"] / 1000, d=p.get("com_offset_mm", 0) / 1000)
        J += a.get("extra_inertia_kgm2", 0.0)
        w = math.radians(a["rate_max_dps"])
        alpha = w / a["accel_time_s"]
        M_g = p["mass_kg"] * G * p.get("com_offset_mm", 0) / 1000 if a.get("gravity", True) else 0.0
        T = axis_torque(J, alpha, M_g, a.get("friction_nm", 0.0))
        rpm = w * 60 / (2 * math.pi)
        r = {"J_kgm2": J, "alpha_rad_s2": alpha, "M_grav_nm": M_g, "T_req_nm": T, "n_req_rpm": rpm}
        if "motor" in a:
            r["motor"] = motor_check(T, rpm, a["motor"], c.get("safety_factor", 1.5), J)
        out["axes"][ax] = r
        out["sim"][ax] = {"J_kgm2": J}
    return out


KINDS = {"diff_chassis": diff_chassis, "beam": beam, "ball_plate": beam, "gimbal": gimbal}


def run(c: dict) -> dict:
    if c["kind"] not in KINDS:
        raise ValueError(f"kind 只能是 {sorted(KINDS)}")
    return KINDS[c["kind"]](c)


def _fmt(d, ind=0):
    L = []
    for k, v in d.items():
        if isinstance(v, dict):
            L.append(" " * ind + f"{k}:"); L += _fmt(v, ind + 2)
        else:
            L.append(" " * ind + f"{k}: {v:.4g}" if isinstance(v, float) else " " * ind + f"{k}: {v}")
    return L


def main(argv=None) -> int:
    import yaml
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("yaml"); ap.add_argument("--sim", help="把 sim: 块写到这个 yaml")
    a = ap.parse_args(argv)
    c = yaml.safe_load(pathlib.Path(a.yaml).read_text(encoding="utf-8"))
    r = run(c)
    print(f"# {a.yaml}  kind={c['kind']}  struct_version={c.get('struct_version', '?')}")
    print("\n".join(_fmt(r)))
    bad = [k for k, v in _walk(r) if k == "ok" and v is False]
    if a.sim:
        pathlib.Path(a.sim).write_text(yaml.safe_dump({"struct_version": c.get("struct_version"), "sim": r["sim"]}, allow_unicode=True), encoding="utf-8")
    if bad:
        print("✗ 有电机不满足（扭矩×安全系数 或 转速）")
    return 1 if bad else 0


def _walk(d):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _walk(v)
        else:
            yield k, v


if __name__ == "__main__":
    sys.exit(main())
