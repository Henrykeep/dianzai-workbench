"""继电反馈自整定（调参页“一键起步”）——适配层，算法本体是 Arduino PID AutoTune（BSD）的移植：
third_party/vendored/pid_autotune/pid_atune.py（见 SOURCE.md）。

用途：没有初值时，先让执行器在工作点附近 ±step 来回切，测出临界增益 Ku、临界周期 Pu，按 Ziegler–Nichols 系给第一组 PID，
再交给 TuneGuard / search.optimize 细调。比开环阶跃辨识（identify.py）更适合积分型/不稳定前的对象（转速、温度、平衡车内环）。
- 本文件只做：在 FOPDT 仿真对象上跑完整继电实验（relay_sim），以及把任意 step(u)->y 的对象接进来（relay_run）。
- 实机：继电实验会让对象持续振荡，必须由调用方限幅、看门狗，并走提议确认；这里不碰硬件。
  只对稳定对象（电机速度环、温控）；钢珠、平衡车须在已闭合的外环下做，调用方先过 agent.experiment.require_open_loop。
- 实板/仿真板：固件 pid 1.2.0 的继电覆盖（dzctl DATA 0x7C，板端限幅、超时自动恢复）出 u，侧车只记录 y 并用 relay_analyze 离线算 Ku/Pu；
  入口 = 调参 → 更多实验 →“无初值一键起步”（op tune_relay → AgentService.run_relay_tune）。
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
    """规则见 RULES。zn = 原版 PID 规则（超调 30–40%，见 USAGE_MATRIX #1）；tl = Tyreus–Luyben（更保守，默认）；zn_pi = 原版 PI。"""
    if rule == "zn":
        kp, ti, td = 0.6 * ku, pu / 2, pu / 8
    elif rule == "zn_no_os":                           # ZN“无超调”表：0.2Ku, Ti=Pu/2, Td=Pu/3（对非积分型对象）
        kp, ti, td = 0.2 * ku, pu / 2, pu / 3
    elif rule == "pd_int":                             # 积分型对象（位置环）：不要 I（对象自带积分，I 只会带来超调），D 加重
        kp, ti, td = 0.45 * ku, 0.0, pu / 4
    elif rule == "zn_pi":
        kp, ti, td = 0.4 * ku, pu / 1.2, 0.0          # ki = 0.48·Ku/Pu
    else:
        kp, ti, td = ku / 2.2, 2.2 * pu, pu / 6.3
    return {"kp": kp, "ki": kp / ti if ti else 0.0, "kd": kp * td, "rule": rule}


RULES = {"tl": "Tyreus–Luyben（保守，非积分型对象默认）", "zn": "Ziegler–Nichols 原版 PID（超调大）",
         "zn_no_os": "ZN 无超调表 0.2Ku", "zn_pi": "ZN 原版 PI",
         "pd_int": "积分型对象 PD：0.45Ku、Td=Pu/4、无积分（位置环推荐）"}


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


def relay_analyze(t: list[float], y: list[float], *, amp: float, noise_band: float, pid: bool = True) -> dict:
    """板子已在做继电（u = bias ± amp）时，对记录下的 (t, y) 用同一个 PIDATune 找峰、判收敛、算 Ku/Pu（输出项不用）。"""
    if len(t) < 10:
        return {"ok": False, "why": "样本太少"}
    dts = sorted(b - a for a, b in zip(t, t[1:]) if b > a)
    dt = dts[len(dts) // 2] if dts else 0.01
    span = t[-1] - t[0]
    m = sum(y) / len(y)                                  # 找峰的回看窗口要短于半周期：先按过均值次数粗估周期
    cross = [a for a, b0, b1 in zip(t[1:], y, y[1:]) if (b0 - m) * (b1 - m) < 0]
    p_est = 2 * (cross[-1] - cross[0]) / (len(cross) - 1) if len(cross) > 2 else span / 4
    at = PIDATune(output_step=amp, noise_band=noise_band, control_type=1 if pid else 0, sample_time=dt,
                  lookback_s=max(3 * dt, p_est / 8))
    for a, b in zip(t, y):
        done, _ = at.runtime(a, b, 0.0)
        if done:
            return {"ok": True, "ku": at.ku, "pu": at.pu, "cycles": at.peak_count, "t": a - t[0]}
    return {"ok": False, "why": f"{span:.1f} s 内峰值没稳定（{getattr(at, 'peak_count', 0)} 个周期）：加大 amp 或延长 timeout_s"}
