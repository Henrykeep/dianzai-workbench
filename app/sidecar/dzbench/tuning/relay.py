"""继电反馈自整定（调参页“一键起步”）——适配层，算法本体是 Arduino PID AutoTune（BSD）的移植：
third_party/vendored/pid_autotune/pid_atune.py（见 SOURCE.md）。

用途：没有初值时，先让执行器在工作点附近 ±step 来回切，测出临界增益 Ku、临界周期 Pu，按 Ziegler–Nichols 系给第一组 PID，
再交给 TuneGuard / search.optimize 细调。比开环阶跃辨识（identify.py）更适合积分型/不稳定前的对象（转速、温度、平衡车内环）。
- 本文件只做：在 FOPDT 仿真对象上跑完整继电实验（relay_sim），以及把任意 step(u)->y 的对象接进来（relay_run）。
- 实机：继电实验会让对象持续振荡，必须由调用方限幅、看门狗，并走提议确认；这里不碰硬件。
  只对稳定对象（电机速度环、温控）；钢珠、平衡车须在已闭合的外环下做，调用方先过 agent.experiment.require_open_loop。
- 现状 [仿真]：还没接入口。真跑需要固件“输出覆盖”（控制器输出换成继电器），见 docs/25 P1。
- 取代了原先自写的 agent/relay.py：同一 FOPDT、同噪声下对比（refs/USAGE_MATRIX.md #1），无噪声时 Ku/Pu 一致，
  噪声 0.01–0.03 时自写版 9 例里 5 例判“峰没稳定”失败，移植版全部收敛且在线自停；自写版的 Tyreus–Luyben 规则保留在 gains()。
"""
from __future__ import annotations

import pathlib
import sys

_P = pathlib.Path(__file__).resolve().parents[4] / "third_party" / "vendored" / "pid_autotune"
if _P.is_dir() and str(_P) not in sys.path:
    sys.path.insert(0, str(_P))

from pid_atune import PIDATune  # noqa: E402


def gains(ku: float, pu: float, rule: str = "tl") -> dict:
    """zn = 原版 PID 规则（超调 30–40%，见 USAGE_MATRIX #1）；tl = Tyreus–Luyben（更保守，默认）；zn_pi = 原版 PI。"""
    if rule == "zn":
        kp, ti, td = 0.6 * ku, pu / 2, pu / 8
    elif rule == "zn_pi":
        kp, ti, td = 0.4 * ku, pu / 1.2, 0.0          # ki = 0.48·Ku/Pu
    else:
        kp, ti, td = ku / 2.2, 2.2 * pu, pu / 6.3
    return {"kp": kp, "ki": kp / ti, "kd": kp * td, "rule": rule}


def relay_run(plant_step, *, dt: float, u0: float = 0.0, step: float, noise_band: float, pid: bool = True,
              lookback_s: float | None = None, t_max: float = 120.0) -> dict:
    """plant_step(u) -> y，每调用一次前进 dt 秒。返回 {ok, ku, pu, gains, t, cycles, trace:[(t,y,u)]}。"""
    at = PIDATune(output_step=step, noise_band=noise_band, control_type=1 if pid else 0,
                  sample_time=dt, lookback_s=lookback_s or 20 * dt)
    t, u, trace = 0.0, u0, []
    y = plant_step(u)
    while t < t_max:
        done, u = at.runtime(t, y, u0 if not trace else u)
        trace.append((round(t, 6), y, u))
        if done:
            return {"ok": True, "ku": at.ku, "pu": at.pu, "gains": at.gains(), "t": t,
                    "cycles": at.peak_count, "trace": trace}
        y = plant_step(u)
        t += dt
    return {"ok": False, "why": f"{t_max:g} s 内没收敛：加大 step 或 noise_band，或者对象根本不振荡", "trace": trace}


def relay_sim(K: float, T: float, L: float, *, dt: float = 0.005, step: float = 0.5, noise_band: float = 0.01,
              pid: bool = True) -> dict:
    """FOPDT 对象 K·e^{-Ls}/(Ts+1) 上的继电实验（仿真用，也是测试基准）。"""
    nd = max(1, int(round(L / dt)))
    buf, st = [0.0] * nd, {"y": 0.0}

    def plant(u):
        buf.append(u)
        ud = buf.pop(0)
        st["y"] += dt / T * (K * ud - st["y"])
        return st["y"]
    return relay_run(plant, dt=dt, step=step, noise_band=noise_band, pid=pid, lookback_s=max(20 * dt, (T + L) / 4))
