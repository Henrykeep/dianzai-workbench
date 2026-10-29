"""极性自检（标定向导的第 0 步：先验证方向，再调参数）。

思路来源：MICU-auto-embedded（实验室/开源小组工程）templates/auto-embedded/refs/control-loop-sign-debug.md
——“Kp/限幅是放大器，修不了方向错”“观察模式：人手给已知输入、只采样不控制”。代码自写。

闭环里有三处符号：传感器轴（人往 + 推，读数涨不涨）、误差极性（e = sp − y 还是 y − sp）、
执行器方向（正指令让被控量往哪走），再加控制器本身 u = K·e（K>0）。负反馈要求
    s_act · s_ctrl · s_err < 0     （y 随 u 的符号 × u 随 e 的符号 × e 随 y 的符号）
三步各录一段（工作台录像窗口即可），本模块只做判读，不发任何指令：
  1. 手推（观察模式，执行器不出力）：人把被控量往约定的 + 方向推 → sensor_axis 看 y 涨没涨；同一段里 error_sign 看 e 随 y 的方向；
     若控制器在算（输出不送执行器），controller_sign 看 u 随 e 的方向；
  2. 点动（开环小幅 +u / 0 / −u / 0，或用户手动给 PWM）：actuator_sign 看 y 的变化方向是否跟 u 同号，正反两段要一致；
  3. verdict 合成三处符号给结论和改法（改哪一处的 dir，别去调增益）。
"""
from __future__ import annotations

import statistics


def _slope(x: list[float], y: list[float]) -> float:
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    return 0.0 if sxx == 0 else sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx


def _corr(x: list[float], y: list[float]) -> float:
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x); syy = sum((b - my) ** 2 for b in y)
    return 0.0 if sxx == 0 or syy == 0 else sxy / (sxx * syy) ** 0.5


def _sign_by_fit(x: list[float], y: list[float], min_r: float) -> dict:
    if len(x) < 5:
        return {"sign": 0, "why": "数据太少（<5 点）"}
    r = _corr(x, y)
    if abs(r) < min_r:
        return {"sign": 0, "r": round(r, 3), "why": f"相关性太弱（|r|={abs(r):.2f} < {min_r}）：动作幅度太小或噪声大，加大动作再录"}
    return {"sign": 1 if r > 0 else -1, "r": round(r, 3), "slope": _slope(x, y)}


def sensor_axis(y: list[float], pushed_dir: int = +1, min_delta: float = 0.0) -> dict:
    """手推段：人往约定的 pushed_dir 方向推。读数净变化同号 → +1（轴向对），反号 → −1（传感器轴反了）。"""
    if len(y) < 2:
        return {"sign": 0, "why": "数据太少"}
    d = statistics.fmean(y[-max(1, len(y) // 10):]) - statistics.fmean(y[:max(1, len(y) // 10)])
    if abs(d) <= min_delta:
        return {"sign": 0, "delta": d, "why": f"读数几乎没变（{d:.4g}）：没推动，或传感器没接上"}
    s = 1 if d * pushed_dir > 0 else -1
    return {"sign": s, "delta": d, "why": "" if s > 0 else "人往 + 推，读数在减：传感器轴向与约定相反"}


def error_sign(y: list[float], e: list[float], min_r: float = 0.8) -> dict:
    """e 随 y 的方向：−1 = e = sp − y（标准写法），+1 = e = y − sp。"""
    return _sign_by_fit(y, e, min_r)


def controller_sign(e: list[float], u: list[float], min_r: float = 0.6) -> dict:
    """u 随 e 的方向：+1 = u = K·e（K>0）。"""
    return _sign_by_fit(e, u, min_r)


def actuator_sign(t: list[float], u: list[float], y: list[float], u_min: float) -> dict:
    """点动段：|u| ≥ u_min 的每一段取 y 的平均变化率，与 u 同号 → +1。正反两段方向矛盾 → 0（死区/间隙/打滑/限位）。"""
    segs, cur = [], None
    for i in range(len(u)):
        s = 1 if u[i] >= u_min else -1 if u[i] <= -u_min else 0
        if cur and s == cur[0]:
            cur[2] = i
        else:
            if cur and cur[0]:
                segs.append(tuple(cur))
            cur = [s, i, i]
    if cur and cur[0]:
        segs.append(tuple(cur))
    res = []
    for s, a, b in segs:
        if b - a < 3 or t[b] == t[a]:
            continue
        ts, ys = t[a:b + 1], y[a:b + 1]
        rate = _slope(ts, ys)
        b0 = statistics.fmean(ys) - rate * statistics.fmean(ts)
        resid = statistics.pstdev([yy - (b0 + rate * tt) for tt, yy in zip(ts, ys)])
        moved = abs(rate * (ts[-1] - ts[0])) > 3.0 * resid          # 变化量要明显大于噪声，否则算“没动”
        res.append({"u_sign": s, "rate": rate, "agree": (1 if rate * s > 0 else -1) if moved else 0})
    if not res:
        return {"sign": 0, "segments": [], "why": f"没有 |u| ≥ {u_min} 的点动段"}
    ag = {r["agree"] for r in res}
    if ag == {0}:
        return {"sign": 0, "segments": res, "why": "点动时被控量没动（变化不超过噪声）：在死区里（加大点动幅度）、没上电或机械卡住"}
    if ag == {1}:
        return {"sign": 1, "segments": res}
    if ag == {-1}:
        return {"sign": -1, "segments": res, "why": "正指令让被控量往 − 走：执行器（电机线/舵机安装/dir）反了"}
    return {"sign": 0, "segments": res,
            "why": "正反点动结论不一致（或有一段没动）：可能是死区（加大点动幅度）、机械间隙/打滑、或一边碰到限位"}


def verdict(s_sensor: int, s_err: int, s_ctrl: int, s_act: int) -> dict:
    """合成。s_act 是点动时“读数”随 u 的方向（= 执行器真实方向 × 传感器轴），所以执行器本身的方向 = s_act · s_sensor。"""
    if 0 in (s_err, s_ctrl, s_act):
        missing = [n for n, v in (("误差极性", s_err), ("控制器", s_ctrl), ("执行器点动", s_act)) if v == 0]
        return {"ok": None, "msg": "还判不了：" + "、".join(missing) + " 那一步没得出结论，按提示重录"}
    act_true = s_act * (s_sensor or 1)
    if s_act * s_ctrl * s_err < 0:
        warn = ""
        if s_sensor < 0 and act_true < 0:
            warn = "（但传感器轴和执行器方向都与约定相反，两负得正；建议两处都改回约定，免得以后只改一处就变正反馈）"
        elif s_sensor == 0:
            warn = "（手推那步没得出传感器轴向：约定的 + 方向未核对）"
        return {"ok": True, "msg": "负反馈，方向正确：可以开始调增益" + warn}
    who = []
    if s_sensor < 0:
        who.append("传感器轴（读数取反或改安装方向）")
    if s_err > 0:
        who.append("误差写成了 y − sp（改成 sp − y）")
    if s_ctrl < 0:
        who.append("控制器增益为负（别用负增益修方向）")
    if act_true < 0:
        who.append("执行器方向（dir = −1 / 换电机线 / 舵机反装）")
    return {"ok": False, "msg": "正反馈：方向错，先别调增益。按约定逐处核对，第一处不对的就是根因："
            + "；".join(who or ["单看每处都对、乘起来是正：检查约定本身"])}


def check_window(win: dict, step: str, *, y: str, e: str | None = None, u: str | None = None,
                 pushed_dir: int = 1, u_min: float = 0.0) -> dict:
    """侧车 op polarity_check 用：win = {通道名: (t, v)}（Session.window_field 的结果）。只读遥测、不发指令。
    step="push"：手推段 → sensor/err/ctrl 三个符号（e、u 没给就跳过）；step="jog"：点动段 → act。"""
    ty, yy = win[y]
    if step == "push":
        out = {"sensor": sensor_axis(yy, pushed_dir)}
        if e:
            out["err"] = error_sign(yy, _align(ty, win[e]))
        if e and u:
            out["ctrl"] = controller_sign(_align(ty, win[e]), _align(ty, win[u]))
        return out
    if step == "jog":
        if not u:
            raise ValueError("点动段要给执行器指令通道 u")
        return {"act": actuator_sign(ty, _align(ty, win[u]), yy, u_min)}
    raise ValueError(f"step 只能是 push / jog，收到 {step}")


def _align(t_ref: list[float], tv: tuple[list[float], list[float]]) -> list[float]:
    """同一帧遥测里的通道时间戳相同；不同则取不晚于 t 的最近一个（零阶保持）。"""
    t, v = tv
    if list(t) == list(t_ref):
        return list(v)
    out, j = [], 0
    for x in t_ref:
        while j + 1 < len(t) and t[j + 1] <= x:
            j += 1
        out.append(v[j] if v else 0.0)
    return out
