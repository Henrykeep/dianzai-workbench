#!/usr/bin/env python3
"""mech.py 对手算算例（数值在注释里一步步写出，计算器必须一致）。"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mech  # noqa: E402

TPL = pathlib.Path(__file__).resolve().parent.parent / "templates"


def close(a, b, rel=1e-6):
    assert abs(a - b) <= rel * max(1.0, abs(b)), (a, b)


def test_inertia():
    close(mech.inertia("cylinder", 2.0, r=0.1), 0.01)            # ½·2·0.1² = 0.01
    close(mech.inertia("rod", 1.0, L=0.6), 0.03)                 # 1·0.36/12 = 0.03
    close(mech.inertia("rod", 1.0, L=0.6, d=0.3), 0.12)          # 杆绕端点 = ⅓mL² = 0.12（平行轴 0.03+0.09）
    close(mech.inertia("point", 0.5, d=0.2), 0.02)               # 0.5·0.04
    close(mech.inertia("box", 1.2, a=0.1, b=0.2), 0.005)         # 1.2·(0.01+0.04)/12


def test_chassis_flat_and_slope():
    c = {"kind": "diff_chassis", "mass_kg": 1.0, "wheel": {"radius_mm": 50, "count_driven": 2},
         "motion": {"v_max_mps": 1.0, "a_max_mps2": 2.0}}
    r = mech.run(c)["per_motor"]
    close(r["T_req_nm"], 0.05)            # F = 1·2 = 2 N；每轮 2·0.05/2 = 0.05 N·m
    close(r["n_req_rpm"], 60 / (2 * math.pi) * 20)   # ω = 1/0.05 = 20 rad/s ≈ 190.99 rpm
    close(r["P_w"], 1.0)                  # 0.05·20
    c["motion"] = {"v_max_mps": 1.0, "a_max_mps2": 0.0, "slope_deg": 30}
    close(mech.run(c)["per_motor"]["T_req_nm"], 9.80665 * 0.5 * 0.05 / 2)   # 0.122583


def test_chassis_efficiency_and_wheel_inertia():
    c = {"kind": "diff_chassis", "mass_kg": 0.0, "wheel": {"radius_mm": 50, "mass_kg": 0.08, "count_driven": 2},
         "motion": {"v_max_mps": 1.0, "a_max_mps2": 1.0}, "drive": {"efficiency": 0.5}}
    # J = ½·0.08·0.05² = 1e-4；α = 1/0.05 = 20；T = 2e-3 / 0.5 = 4e-3
    close(mech.run(c)["per_motor"]["T_req_nm"], 4e-3)


def test_beam_hand():
    c = {"kind": "beam", "beam": {"length_mm": 500, "mass_kg": 0.2}, "ball": {"mass_kg": 0.03, "x_max_mm": 200},
         "move": {"angle_deg": 10, "time_s": 0.2}}
    r = mech.run(c)
    close(r["J_kgm2"], 0.2 * 0.25 / 12 + 0.03 * 0.04)            # 0.0041667 + 0.0012 = 0.0053667
    close(r["alpha_rad_s2"], 4 * math.radians(10) / 0.04)        # 17.4533
    close(r["M_grav_nm"], 0.03 * 9.80665 * 0.2)                  # 0.0588399
    close(r["actuator"]["T_req_nm"], 0.0053667 * 17.4533 + 0.0588399, rel=1e-4)   # 0.152506


def test_motor_check():
    m = {"stall_torque_nm": 1.0, "no_load_rpm": 300, "rated_torque_nm": 0.3}
    r = mech.motor_check(0.2, 150, m, sf=1.5)
    close(r["T_avail_nm"], 0.5); close(r["margin"], 2.5); assert r["ok"] and r["rated_ok"]   # 1·(1−150/300)
    assert not mech.motor_check(0.4, 150, m)["ok"]                # 0.5 < 1.5·0.4
    assert not mech.motor_check(0.01, 320, m)["ok"]               # 超空载转速
    r = mech.motor_check(0.1, 10, {**m, "gear_ratio": 30, "rotor_inertia_kgm2": 1e-6}, J_load=0.009)
    close(r["inertia_ratio"], 10.0)                               # 0.009 / (900·1e-6)


def test_gimbal_hand():
    c = {"kind": "gimbal", "axes": {"pitch": {"payload": {"mass_kg": 0.3, "a_mm": 60, "b_mm": 40, "com_offset_mm": 10},
                                              "rate_max_dps": 180, "accel_time_s": 0.1}}}
    r = mech.run(c)["axes"]["pitch"]
    J = 0.3 * (0.0036 + 0.0016) / 12 + 0.3 * 0.0001             # 1.3e-4 + 3e-5 = 1.6e-4
    close(r["J_kgm2"], J); close(r["alpha_rad_s2"], math.pi / 0.1)
    close(r["T_req_nm"], J * math.pi / 0.1 + 0.3 * 9.80665 * 0.01)   # 0.005027 + 0.02942


def test_templates_run():
    for p in sorted(TPL.glob("*.yaml")):
        assert mech.main([str(p)]) in (0, 1), p


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1
    print(f"test_mech: {n} 项通过")
