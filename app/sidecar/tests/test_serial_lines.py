"""串口线控 + 自动重连增强（缺口 14）：DTR/RTS 实时开关、脉冲序列、调制解调器线、卡死检测触发重连。"""
import threading
import time

import pytest

from dzbench import ports
from dzbench.session import LinkError, Session
from dzbench.transport import Transport


class FakeSer:
    def __init__(self):
        self.log, self._dtr, self._rts, self.cts, self.dsr, self.ri, self.cd = [], True, True, True, False, False, True

    dtr = property(lambda s: s._dtr, lambda s, v: (setattr(s, "_dtr", v), s.log.append(("dtr", v, time.monotonic()))))
    rts = property(lambda s: s._rts, lambda s, v: (setattr(s, "_rts", v), s.log.append(("rts", v, time.monotonic()))))


class Port(Transport):
    opened: list = []

    def __init__(self, name, baud):
        self.name, self.ser, self.q = name, FakeSer(), [b"x=1\n"]
        Port.opened.append(self)

    def read(self):
        time.sleep(0.01)
        return self.q.pop(0) if self.q else b""          # 只来一行，之后“卡死”：不报错、不来数据

    def write(self, data):
        pass


@pytest.fixture(autouse=True)
def _clean_lines():
    ports.LINES.clear(); Port.opened = []
    yield
    ports.LINES.clear()


def wait(f, t=3.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        if f():
            return True
        time.sleep(0.02)
    return False


def test_lines_live_and_pulses():
    s = Session(); s._open = Port
    s.connect("COM9", 115200, log=False)
    ser = Port.opened[-1].ser
    r = s.serial_lines_set(dtr=False)
    assert r["dtr"] is False and r["rts"] is True and r["cts"] is True and ser.dtr is False
    assert ports.LINES == {"dtr": False, "rts": None}                # 重连 / 下次打开沿用
    ser.log.clear()
    r = s.serial_pulse("esp_boot")
    steps = [(k, v) for k, v, _ in ser.log]
    assert steps == [("dtr", False), ("rts", True), ("dtr", True), ("rts", False), ("dtr", False), ("rts", False)]
    assert ser.log[2][2] - ser.log[1][2] >= 0.09                     # EN 拉低保持 ≥ 100 ms
    assert r["pulse"] == "esp_boot" and ports.LINES == {"dtr": False, "rts": False}
    with pytest.raises(LinkError):
        s.serial_pulse("nope")
    s.disconnect()


def test_lines_need_real_serial(tmp_path):
    s = Session()
    with pytest.raises(LinkError) as e:
        s.serial_modem()
    assert e.value.code == "not_serial"


def test_stall_triggers_reconnect(monkeypatch):
    ev = []
    s = Session(emit=ev.append); s._open = Port
    monkeypatch.setattr(Session, "RECONNECT_BACKOFF", (0.01,))
    monkeypatch.setattr(Session, "HOST_HB_PERIOD_S", 0.05)
    s.stall_s = 0.3
    s.connect("COM9", 115200, log=False)
    assert wait(lambda: any(e.get("type") == "reconnected" for e in ev))
    lost = [e for e in ev if e.get("code") == "link_lost"]
    assert lost and "没收到任何字节" in lost[0]["message"]
    assert any(e.get("type") == "reconnecting" and e["attempt"] == 1 for e in ev)
    assert s.reconnects >= 1 and s.status()["reconnect_attempt"] == 0 and len(Port.opened) >= 2
    s.stall_s = 0
    s.disconnect()


def test_no_stall_without_data(monkeypatch):
    class Silent(Port):
        def __init__(self, n, b):
            super().__init__(n, b); self.q = []
    s = Session(); s._open = Silent
    monkeypatch.setattr(Session, "HOST_HB_PERIOD_S", 0.05)
    s.stall_s = 0.1
    s.connect("COM9", 115200, log=False)
    time.sleep(0.4)
    assert s.reconnects == 0 and len(Port.opened) == 1              # 从没来过数据（波特率不对 / 设备不说话）不算卡死
    s.disconnect()
