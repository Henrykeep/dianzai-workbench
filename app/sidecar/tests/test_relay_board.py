"""固件继电覆盖（pid 1.2.0 + dzctl 0.7.0 DATA 0x7C）在仿真板 sim:motor_pos 上：限幅、超时自动恢复、急停结束、一键起步出提议卡。"""
import struct
import time

import pytest

from dzbench.agent.service import AgentService
from dzbench.agent_api import AgentTools
from dzbench.session import Session

pytestmark = pytest.mark.needs_sim



def _unlocked(s, t=3.0):
    """发 R 后等固件心跳 bit10 清零、侧车解锁。"""
    t_end = time.monotonic() + t
    while s.tx_locked and time.monotonic() < t_end:
        time.sleep(0.01)
    assert not s.tx_locked

def _wait(cond, t=30.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _hold(s, sec, sp=90.0):
    t_end = time.monotonic() + sec
    while time.monotonic() < t_end:
        s.send_data(1, struct.pack("<f", sp)); time.sleep(0.1)


@pytest.fixture
def board(home):
    s = Session()
    s.connect("sim:motor_pos")
    assert _wait(lambda: s.schema and len(s.window(0.5)) > 5)
    yield s
    s.disconnect()


def test_relay_override_limits_timeout_estop(board):
    s = board
    _hold(s, 0.8)
    assert s.relay(0, 0.3, 0.5, 0.6)["ok"]
    assert s.relay(0, 0.3, 0.5, 0.6)["status"] == 1          # 同时只能一个回路在继电
    _hold(s, 0.4)
    us = [abs(v["u"]) for _, v in s.window(0.3)]
    assert max(us) <= 0.3 + 0.03 + 1e-3                         # ±amp（+ 应用的死区补偿），板端限幅
    _hold(s, 0.6)                                              # 0.6 s 超时 → 板子自己恢复 PID
    assert s.relay(0, 0.3, 0.5, 5.0)["ok"]                     # 能再次开始 = 上一次确已结束
    s.estop(); time.sleep(0.2)
    assert all(v["u"] == 0 for _, v in s.window(0.1))
    s.cmd("R"); _unlocked(s)
    assert s.relay(0, 0.3, 0.5, 0.5)["ok"]                     # 急停结束了继电
    assert s.relay(9, 0.3, 0.5, 0.5)["status"] == 1            # 没有这个回路


def test_relay_one_click_start_proposes(board):
    svc = AgentService(board, AgentTools(board, lambda e: None), lambda e: None)
    r = svc.run_relay_tune()
    assert r["ok"], r
    assert 0.1 < r["ku"] < 0.3 and 0.05 < r["pu"] < 0.2, r       # 实测 Ku≈0.166 Pu≈0.09 s（USAGE_MATRIX #1）
    assert len(r["proposals"]) == 3                              # kp/ki/kd 各一张提议卡，采纳才写入


@pytest.mark.parametrize("target", ["sim:car_2wd", "sim:2026H_ball"])
def test_relay_answers_on_own_link_boards(home, target):
    """car_2wd、2026H io_link 自带收帧，也走 apps/include/link_relay.h：按钮不会是“板子没回应”。"""
    s = Session()
    s.connect(target)
    try:
        assert _wait(lambda: s.schema and len(s.window(0.5)) > 3)
        assert s.relay(0, 0.2, 0.1, 1.0)["ok"]
        assert s.relay(0, 0.2, 0.1, 1.0)["status"] == 1          # 已在继电
        s.estop(); time.sleep(0.3)
        s.cmd("R"); _unlocked(s)
        assert s.relay(0, 0.2, 0.1, 1.0)["ok"]                    # 急停结束了上一次继电
        assert s.relay(9, 0.2, 0.1, 1.0)["status"] == 1
        assert s.relay_stop()
    finally:
        s.disconnect()
