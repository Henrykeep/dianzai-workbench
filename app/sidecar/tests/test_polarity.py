"""极性自检：用一阶对象 + P 控制器造“手推”和“点动”数据，四种接错方式都要判出来并指对位置。"""
import random

from dzbench.agent import polarity as P


def jog(act_dir=1, sensor_dir=1, dead=0.0, n=400, dt=0.005, seed=1):
    """开环点动 +0.5/0/−0.5/0，各 0.5 s。对象 x' = act_dir·(u 去死区)，读数 y = sensor_dir·x + 噪声。"""
    rnd = random.Random(seed)
    t, u, y, x = [], [], [], 0.0
    for k in range(n):
        uk = [0.5, 0.0, -0.5, 0.0][(k * 4) // n]
        ue = 0.0 if abs(uk) <= dead else uk
        x += dt * act_dir * ue
        t.append(k * dt); u.append(uk); y.append(sensor_dir * x + rnd.gauss(0, 0.001))
    return t, u, y


def push(sensor_dir=1, err_dir=-1, kp=2.0, n=200, seed=2):
    """观察模式：人把真实位置从 0 推到 1（sp=0），控制器算 u 但不送执行器。"""
    rnd = random.Random(seed)
    y, e, u = [], [], []
    for k in range(n):
        x = k / (n - 1)
        yk = sensor_dir * x + rnd.gauss(0, 0.005)
        ek = (0.0 - yk) if err_dir == -1 else (yk - 0.0)   # −1：e = sp − y；+1：e = y − sp
        y.append(yk); e.append(ek); u.append(kp * ek)
    return y, e, u


def run(act_dir=1, sensor_dir=1, err_dir=-1, kp=2.0):
    y, e, u = push(sensor_dir, err_dir, kp)
    s1 = P.sensor_axis(y, +1)["sign"]
    s2 = P.error_sign(y, e)["sign"]
    s3 = P.controller_sign(e, u)["sign"]
    t, uj, yj = jog(act_dir, sensor_dir)
    s4 = P.actuator_sign(t, uj, yj, 0.2)["sign"]
    return (s1, s2, s3, s4), P.verdict(s1, s2, s3, s4)


def test_correct_loop_is_negative_feedback():
    s, v = run()
    assert s == (1, -1, 1, 1) and v["ok"] is True


def test_actuator_reversed():
    s, v = run(act_dir=-1)
    assert s[3] == -1 and v["ok"] is False and "执行器方向" in v["msg"] and "传感器" not in v["msg"]


def test_error_written_backwards():
    s, v = run(err_dir=+1)
    assert s[1] == 1 and v["ok"] is False and "y − sp" in v["msg"]


def test_negative_gain_flagged():
    s, v = run(kp=-2.0)
    assert s[2] == -1 and v["ok"] is False and "负增益" in v["msg"]


def test_sensor_reversed_points_to_sensor():
    # 传感器反：手推读数减（s1=−1）；点动时读数随 u 也反（s4=−1）→ 正反馈；根因只指传感器，不冤枉执行器
    s, v = run(sensor_dir=-1)
    assert s[0] == -1 and s[3] == -1 and v["ok"] is False and "传感器轴" in v["msg"] and "执行器方向" not in v["msg"]


def test_two_wrongs_warn():
    s, v = run(sensor_dir=-1, act_dir=-1)       # 两处反、乘起来对
    assert v["ok"] is True and "两负得正" in v["msg"]


def test_deadzone_and_weak_data_are_inconclusive():
    t, u, y = jog(dead=0.6)                     # 点动幅度 0.5 在死区里：不动
    r = P.actuator_sign(t, u, y, 0.2)
    assert r["sign"] == 0
    assert P.verdict(1, -1, 1, 0)["ok"] is None
    assert P.sensor_axis([0.0] * 50)["sign"] == 0
    assert P.error_sign([1, -1, 1, -1, 1, -1], [1, 1, -1, -1, 1, 1])["sign"] == 0     # 不相关
    assert P.error_sign([1, 2], [2, 1])["sign"] == 0                                  # 太少


def test_check_window_on_recorded_channels():
    y, e, u = push()
    t = [k * 0.01 for k in range(len(y))]
    r = P.check_window({"y": (t, y), "e": (t, e), "u": (t, u)}, "push", y="y", e="e", u="u")
    assert (r["sensor"]["sign"], r["err"]["sign"], r["ctrl"]["sign"]) == (1, -1, 1)
    tj, uj, yj = jog(act_dir=-1)
    tu = [x + 0.001 for x in tj]                      # 指令通道时间戳略错开：零阶保持对齐
    r = P.check_window({"y": (tj, yj), "u": (tu, uj)}, "jog", y="y", u="u", u_min=0.2)
    assert r["act"]["sign"] == -1
