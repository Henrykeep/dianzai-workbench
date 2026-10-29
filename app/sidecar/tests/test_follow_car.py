"""examples/2026X_follow 双车安全回归（host-sim）：后车跑真固件，前车是 sim_setup.c 里的虚拟车（发真实 peerlink 帧）。
“没撞车”用仿真侧的真间距（gap0 + 前车里程 − 后车真里程）判，不信固件自己的间距估计。
场景：稳态跟车 → 前车急刹 → 链路断 → 前车中止 → 本车急停（双向中止）。思路来自 DS-land-and-air 的
mission_safety_regression_sim.c（逐场景断言状态而不是看曲线），代码自写，见 docs/参考来源.md。"""
import re
import time

import pytest

from dzbench.session import Session

pytestmark = pytest.mark.needs_sim

GAP_REF, GAP_MIN = 0.40, 0.20


def wait(cond, t=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if cond():
            return True
        time.sleep(0.03)
    return False


def last(s):
    w = s.window(0.3)
    return w[-1][1] if w else {}


def truth(s, path):
    """真间距最小值（自上次读起），m；顺带前车速度。"""
    path.unlink(missing_ok=True)
    s.cmd("Q")
    assert wait(lambda: path.exists() and path.read_text().strip(), 2)
    m = re.search(r"gap_min_true_mm=(-?\d+) lead_v=([\d.\-]+)", path.read_text())
    return int(m.group(1)) / 1000.0, float(m.group(2))


@pytest.fixture
def car(home, tmp_path, monkeypatch):
    tp = tmp_path / "truth.txt"
    monkeypatch.setenv("DZ_SIM_TRUTH", str(tp))
    s = Session()
    s.connect("sim:2026X_follow")
    assert wait(lambda: s.schema and len(s.window(0.5)) > 5, 40)
    yield s, tp
    s.disconnect()


def test_two_car_safety_regression(car):
    s, tp = car
    # 1 稳态跟车：间距收敛到 gap_ref ±5 cm，链路新鲜
    assert wait(lambda: last(s).get("mode") == 1 and abs(last(s)["gap_m"] - GAP_REF) < 0.05 and last(s)["v_self"] > 0.2, 8)
    time.sleep(2.0)
    assert all(abs(v["gap_m"] - GAP_REF) < 0.05 and v["fstate"] == 0 for _, v in s.window(1.0))
    g, _ = truth(s, tp)
    assert g > GAP_MIN, g

    # 2 前车 2 m/s² 急刹到停 → 后车停住，真间距始终 > gap_min
    s.cmd("B")
    assert wait(lambda: last(s)["v_lead"] == 0.0 and abs(last(s)["v_self"]) < 0.02, 3), last(s)
    time.sleep(0.5)
    g, _ = truth(s, tp)
    assert g > GAP_MIN, f"前车急刹时真间距 {g:.3f} m 小于 gap_min"
    s.cmd("G")
    assert wait(lambda: last(s)["fstate"] == 0 and last(s)["v_self"] > 0.2, 4)

    # 3 链路断：stale_ms(200)+一拍内判 LINK_LOST，按 f_decel(1.5) 1 s 内停住；恢复后继续跟
    s.cmd("X")
    t0 = time.monotonic()
    assert wait(lambda: last(s)["fstate"] == 2, 1.0), "链路断没判出来"
    assert time.monotonic() - t0 < 0.6
    assert wait(lambda: abs(last(s)["v_self"]) < 0.02, 1.5), "链路断后没停车"
    s.cmd("Y")
    assert wait(lambda: last(s)["fstate"] == 0 and last(s)["v_self"] > 0.2, 4), "链路恢复后没继续跟"

    # 4 前车发 ABORT：立刻中止并锁存，只有人工 'C' 才解除
    s.cmd("A")
    assert wait(lambda: last(s)["mode"] == 4, 0.5), "收到 ABORT 没中止"
    assert wait(lambda: abs(last(s)["v_self"]) < 0.02, 1.0)
    time.sleep(0.5)
    assert all(v["mode"] == 4 for _, v in s.window(0.4)), "中止没锁存"
    s.cmd("C")
    assert wait(lambda: last(s)["mode"] == 1 and last(s)["v_self"] > 0.2, 4)

    # 5 本车急停：本车停 + 对方收到 3 帧 ABORT 也停（双向中止）
    s.estop()
    assert wait(lambda: last(s)["mode"] == 2 and abs(last(s)["v_self"]) < 0.02, 1.0)
    assert wait(lambda: truth(s, tp)[1] == 0.0, 3), "前车没收到本车的 ABORT"

    codes = [r["code"] for r in s.blackbox()]
    assert 0x101 in codes and 0x102 in codes, codes    # 中止（收/发）、链路断都进了黑匣子
