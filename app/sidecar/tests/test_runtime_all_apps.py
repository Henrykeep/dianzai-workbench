"""dzctl 0.12.0 通用运行时（apps/include/dz_runtime.h）：每个应用默认都报自检 / 运行模式 / 存参，都认 'H' 重跑自检。
host-sim 上逐个应用跑：上电自检上报 → 'H' 回 mask → 'W' 存参 → 'M' 切脱机 → 断电重上电（不发心跳）：参数来自 flash、仍是脱机、不急停。"""
import time

import pytest

from dzbench.session import DATA, ID_CMD, Session

pytestmark = pytest.mark.needs_sim

APPS = ["motor_pos", "line_car", "pan_tilt", "pendulum_rot", "2026X_follow", "car_2wd", "2026H_ball"]


def _wait(pred, t=6.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _up(app, hb=True):
    s = Session()
    s.host_hb = hb
    s.connect("sim:" + app)
    ok = _wait(lambda: s.status()["alive"] and s.schema and s.status().get("boot") and s.status().get("selftest"), 20.0)
    assert ok, (app, s.status())
    return s


@pytest.mark.parametrize("app", APPS)
def test_generic_runtime(app, home, tmp_path, monkeypatch):
    monkeypatch.setenv("DZ_SIM_NVM", str(tmp_path / "nvm.bin"))
    s = _up(app)
    try:
        st = s.status()
        assert st["boot"] == {"params": "default_unsaved", "selftest_ok": True}, st
        assert st["selftest"]["pass"] is True, st
        assert st["run_mode"]["mode"] == "tethered", st
        r = s.run_selftest()
        assert r["ok"] is True and r["mask"] == 0, r
        r = s.save_params()
        assert r["ok"] is True and r["result"] == 0, r
        s._send(DATA, ID_CMD, bytes([ord("M"), 1, 0x00]))           # 确认字节不对：拒切（回 4）
        time.sleep(0.3)
        assert s.status()["run_mode"]["mode"] == "tethered"
        r = s.set_run_mode("standalone", confirmed=True)
        assert r["ok"] is True and r["result"] == 0, r
        assert _wait(lambda: s.status()["run_mode"]["mode"] == "standalone")
    finally:
        s.disconnect()

    s = _up(app, hb=False)                                            # 断电重上电，不连上位机
    try:
        st = s.status()
        assert st["boot"] == {"params": "flash", "selftest_ok": True}, st
        assert st["run_mode"]["mode"] == "standalone", st
        time.sleep(2.0)                                               # 远超心跳超时：脱机不急停
        st = s.status()
        assert st["estop_cause"] is None, st
        assert s.run_selftest()["ok"] is True
        r = s.set_run_mode("tethered", confirmed=True)
        assert r["ok"] is True, r
    finally:
        s.disconnect()
