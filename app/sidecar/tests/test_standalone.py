"""脱机运行验收（host-sim，DZ_SIM_NVM 文件当 flash，换进程 = 断电重上电）：
存参数一次写入 → 上电 CRC/结构哈希校验后加载 → 自检结果随心跳上报 → 不连上位机照常跑；flash 损坏 → 安全默认值。"""
import struct
import time

import pytest

from dzbench.session import Session

pytestmark = pytest.mark.needs_sim


def _up(hb=True):
    s = Session()
    s.host_hb = hb
    s.connect("sim:car_2wd")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 8 and not (s.status()["alive"] and s.schema and len(s.params) == len(s.schema.params)
                                             and s.status().get("boot")):
        time.sleep(0.05)
    return s


def test_power_cycle_persist_selftest_and_no_link(home, tmp_path, monkeypatch):
    nvm = tmp_path / "nvm.bin"
    monkeypatch.setenv("DZ_SIM_NVM", str(nvm))
    s = _up()
    try:                                                    # 第一次上电：没存过 → 默认值，自检通过
        st = s.status()
        assert st["boot"] == {"params": "default_unsaved", "selftest_ok": True}, st
        assert st["estop_cause"] is None
        s.set_param("kp", 0.37)
        r = s.save_params()
        assert r["ok"] is True and r["result"] == 0 and "flash" in r["message_zh"], r
        s.send_data(1, struct.pack("<ff", 0.3, 0.0))       # 车在动 → 拒写（擦扇区会卡 CPU）
        time.sleep(0.4)
        r = s.save_params()
        assert r["ok"] is False and r["result"] == 1, r
    finally:
        s.disconnect()                                      # 杀进程 = 断电

    s = _up(hb=False)                                       # 再上电，上位机不发心跳（=没连电脑）
    try:
        st = s.status()
        assert st["boot"] == {"params": "flash", "selftest_ok": True}, st
        assert abs(s.read_all_params()["kp"] - 0.37) < 1e-4
        n0 = len(s.window(10.0))
        time.sleep(2.5)                                     # 看门狗没布防：不会因为“没上位机”急停
        st = s.status()
        assert st["estop_cause"] is None and "急停" not in (st["hb_flags"] or []), st
        assert len(s.window(10.0)) > n0 + 20, "脱机时控制循环与遥测照常"
    finally:
        s.disconnect()

    b = bytearray(nvm.read_bytes())                         # flash 损坏：把记录区全翻转
    for i in range(len(b)):
        if b[i] != 0xFF:
            b[i] ^= 0x5A
    nvm.write_bytes(bytes(b))
    s = _up()
    try:
        st = s.status()
        assert st["boot"]["params"] in ("default_unsaved", "default_corrupt") and st["boot"]["selftest_ok"], st
        assert abs(s.read_all_params()["kp"] - 0.08) < 1e-4, "坏 flash → 安全默认值"
        assert st["estop_cause"] is None
    finally:
        s.disconnect()


def _wait(pred, t=4.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _moving(s):
    w = s.window(0.3)
    return bool(w) and abs(w[-1][1].get("spd_a", 0.0)) > 0.5


def test_run_modes_standalone_power_cycle_and_tethered_hb_loss(home, tmp_path, monkeypatch):
    """联机 / 脱机两种运行模式：模式存 flash、只由人切；脱机断电重上电不连上位机自启并持续跑；联机心跳丢失照样停车锁存。"""
    nvm = tmp_path / "nvm.bin"
    monkeypatch.setenv("DZ_SIM_NVM", str(nvm))
    s = _up()
    try:
        assert s.status()["run_mode"]["mode"] == "tethered"            # 出厂 = 联机
        r = s.set_run_mode("standalone")                               # 没过确认卡：不发
        assert r["needs_confirm"] and r["ok"] is False
        from dzbench.session import DATA, ID_CMD
        s._send(DATA, ID_CMD, bytes([ord("M"), 1]))                         # 缺确认字节：板子拒切
        time.sleep(0.6)
        assert s.status()["run_mode"]["mode"] == "tethered"
        s.set_param("sa_autostart", 1)
        assert s.save_params()["ok"] is True
        r = s.set_run_mode("standalone", confirmed=True)
        assert r["ok"] is True and r["result"] == 0, r
        assert _wait(lambda: s.status()["run_mode"]["mode"] == "standalone")
    finally:
        s.disconnect()

    s = _up(hb=False)                                                  # 断电重上电，没连电脑
    try:
        assert _wait(lambda: (s.status()["run_mode"] or {}).get("started")), s.status()
        assert _wait(lambda: _moving(s)), "脱机自检通过后自启：轮子在转"
        time.sleep(2.5)                                                # 远超心跳超时，不急停
        st = s.status()
        assert st["estop_cause"] is None and _moving(s), st
        assert st["run_mode"] == {"mode": "standalone", "started": True, "label_zh": "脱机（运行中）"}
        s.cmd("K", 1)                                                  # 板上按键短按 = 停
        assert _wait(lambda: not s.status()["run_mode"]["started"])
        s.cmd("K", 35)                                                 # 长按 3.5 s = 人切回联机
        assert _wait(lambda: s.status()["run_mode"]["mode"] == "tethered", 6.0)
    finally:
        s.disconnect()

    s = _up()                                                          # 再上电：模式仍是联机（不会自己变）
    try:
        assert s.status()["run_mode"]["mode"] == "tethered"
        s.send_data(1, struct.pack("<ff", 0.3, 0.0))
        time.sleep(0.3)
        s.host_hb = False                                              # 联机：上位机掉线
        assert _wait(lambda: (s.status()["estop_cause"] or {}).get("cause") == "hb_timeout", 4.0), s.status()
        es = s.status()["estop_cause"]
        assert es["run_mode"] == "tethered"
        assert _wait(lambda: not _moving(s), 3.0)
        assert s.status()["run_mode"]["mode"] == "tethered"
    finally:
        s.disconnect()
