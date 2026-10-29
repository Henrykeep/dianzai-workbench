"""通用仿真被控对象（apps/motor_pos、pendulum_rot、pan_tilt、line_car）：同一套侧车/Agent 工具不改代码就能跑。
每个对象：发现 → 连上 → schema/参数 → 自动选对阶跃配置 → 阶跃实验出指标；外加对象特有的仿真事件（视觉丢帧、摆倒等）。"""
import time

import pytest

from dzbench import ports
from dzbench.agent.service import AgentService
from dzbench.agent_api import AgentTools
from dzbench.session import Session

pytestmark = pytest.mark.needs_sim

PLANTS = {  # 对象 → (阶跃配置里的 y, 期望的 pin 字段)
    "motor_pos": ("pos_deg", None),
    "pendulum_rot": ("arm_deg", "mode"),
    "pan_tilt": ("tgt_x_px", "vis_state"),
    "line_car": ("line_mm", "mode"),
}


def wait(cond, t=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_plants_discovered():
    assert set(PLANTS) <= set(ports.sim_apps())


@pytest.mark.parametrize("app", sorted(PLANTS))
def test_plant_step_generic(home, app):
    y, pin = PLANTS[app]
    s = Session()
    s.connect(f"sim:{app}")
    try:
        assert wait(lambda: s.schema and len(s.window(0.5)) > 5, 30)
        if pin:
            assert any(f["name"] == pin and f.get("pin") for f in s.schema.fields)
        svc = AgentService(s, AgentTools(s, lambda e: None), lambda e: None)
        cfg = svc.step_cfg()
        assert cfg and cfg["y"] == y, cfg          # 不能被别的对象（同名 sp_a/spd_a）的配置抢走
        r = svc.run_step_test()
        m = r["metrics"]
        assert m["ok"], m
        assert m["rise_s"] is not None and m["rise_s"] < 2.0
    finally:
        s.disconnect()


def test_pendulum_rest_is_quantisation_only(home):
    """默认增益静止时只剩编码器 ±1~2 个计数的抖动（摆杆 2400 CPR = 0.15°/计数）；k_al 0.8 时曾有 ±0.9° 极限环。"""
    s = Session()
    s.connect("sim:pendulum_rot")
    try:
        assert wait(lambda: s.schema and len(s.window(0.5)) > 5, 30)
        time.sleep(8)
        p = [v["pend_deg"] for _, v in s.window(3)]
        assert max(p) - min(p) <= 0.5, (min(p), max(p))
    finally:
        s.disconnect()


def test_line_car_lost_search_recover_blackbox(home):
    """line_car 1.1.0：被撞偏丢线 → line_obs 判丢（SEARCH=3）→ 朝丢线一侧找回（RUNNING=1）；丢线记黑匣子 BB_EV_LINE_LOST(5)。"""
    s = Session()
    s.connect("sim:line_car")
    try:
        assert wait(lambda: s.schema and len(s.window(0.5)) > 5, 30)
        time.sleep(1.0)
        assert s.window(0.3)[-1][1]["mode"] == 1
        s.cmd("O", 70)                                   # 往左挪 70 mm：超出 8 路灰度量程（±42 mm）
        assert wait(lambda: any(v["mode"] == 3 for _, v in s.window(0.5)), 3), "没进入找线"
        assert wait(lambda: s.window(0.3) and all(v["mode"] == 1 for _, v in s.window(0.3)), 8), "没找回线"
        recs = s.blackbox()
        lost = [r for r in recs if r["code"] == 5]
        assert lost and lost[0]["arg"] == 2, recs        # arg = LINE_OBS_LOST
    finally:
        s.disconnect()
