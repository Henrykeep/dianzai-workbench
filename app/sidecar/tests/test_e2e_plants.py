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
