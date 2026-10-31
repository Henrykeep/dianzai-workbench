"""原始监视器、自动重连、CSV 导出（离线，无硬件）。"""
import csv
import struct
import threading
import time

from dzbench._dzlink import DATA, HEARTBEAT, encode
from dzbench.export import dzlog_to_csv
from dzbench.logfile import RX, LogWriter
from dzbench.schema import Schema
from dzbench.session import Session
from dzbench.transport import Transport

SCHEMA = {"version": 1, "hash": 0x1234ABCD, "telemetry": {"id": 2, "fields": [
    {"name": "t_ms", "type": "u32"}, {"name": "spd", "type": "f32", "unit": "rps"},
    {"name": "state", "type": "u8", "enum": ["空闲", "运行"]}]}, "params": []}


class Flaky(Transport):
    """可控的假串口：.die() 模拟拔线；opens 记录被打开的次数。"""
    alive: list = []

    def __init__(self, port, baud):
        if Flaky.fail_next > 0:
            Flaky.fail_next -= 1
            raise OSError("拔着呢")
        self.name, self.q, self.dead = port, [], threading.Event()
        Flaky.alive.append(self)

    def read(self):
        if self.dead.is_set():
            raise OSError("设备已移除")
        time.sleep(0.01)
        return self.q.pop(0) if self.q else b""

    def write(self, data):
        if self.dead.is_set():
            raise OSError("设备已移除")


def wait(f, t=3.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        if f():
            return True
        time.sleep(0.02)
    return False


def test_auto_reconnect_backoff_and_user_disconnect(monkeypatch):
    Flaky.alive, Flaky.fail_next = [], 2
    ev = []
    s = Session(emit=ev.append)
    s._open = Flaky
    monkeypatch.setattr(Session, "RECONNECT_BACKOFF", (0.01, 0.02))
    Flaky.fail_next = 0
    s.connect("COM7", 115200, log=False)
    Flaky.fail_next = 2                                    # 拔线后前两次重开失败
    Flaky.alive[-1].dead.set()
    assert wait(lambda: any(e.get("type") == "reconnected" for e in ev))
    assert s.status()["connected"] and not s.reconnecting and s.reconnects == 1 and len(Flaky.alive) == 2
    lost = [e for e in ev if e.get("code") == "link_lost"]
    assert lost and "自动重连" in lost[0]["fix"]
    # 重连中按急停：如实报告没送到
    Flaky.fail_next = 10 ** 6
    Flaky.alive[-1].dead.set()
    assert wait(lambda: s.reconnecting)
    assert s.estop()["ok"] is False and "重连" in s.status()["hint"]
    s.disconnect()                                         # 主动断开 → 不再重连
    Flaky.fail_next = 0
    time.sleep(0.1)
    assert not s.status()["connected"] and len(Flaky.alive) == 2


def test_no_reconnect_when_disabled():
    Flaky.alive, Flaky.fail_next = [], 0
    ev = []
    s = Session(emit=ev.append)
    s._open, s.auto_reconnect = Flaky, False
    s.connect("COM7", 115200, log=False)
    Flaky.alive[-1].dead.set()
    assert wait(lambda: any(e.get("code") == "link_lost" for e in ev))
    time.sleep(0.1)
    assert len(Flaky.alive) == 1 and "重连" in [e for e in ev if e.get("code") == "link_lost"][0]["fix"]
    s.disconnect()


def test_raw_monitor_collects_rx_tx_only_when_on():
    Flaky.alive, Flaky.fail_next = [], 0
    s = Session()
    s._open = Flaky
    s.connect("COM7", 115200, log=False)
    Flaky.alive[-1].q.append(b"hello\r\n")
    time.sleep(0.1)
    assert s.take_raw() == []
    s.raw_on = True
    Flaky.alive[-1].q.append(b"AT+OK\r\n")
    s.cmd("R")
    assert wait(lambda: len(s._raw) >= 2)
    c = s.take_raw()
    assert any(d == 0 and b == b"AT+OK\r\n" for _, d, b in c) and any(d == 1 for _, d, _b in c)
    s.RAW_MAX_BYTES = 10
    s._push_raw(time.monotonic(), 0, b"x" * 30)
    assert s.raw_dropped >= 30 and s._raw_bytes <= 10
    s.disconnect()


def test_dzlog_to_csv_bom_and_enum(tmp_path):
    sch = Schema(SCHEMA)
    w = LogWriter(tmp_path / "a.dzlog", {"port": "COM7", "schema_hash": None})
    w.write(RX, encode(HEARTBEAT, 0, 0, struct.pack("<I", 0x1234ABCD)))
    for i in range(5):
        fr = encode(DATA, 2, i, struct.pack("<IfB", i * 20, 0.5 * i, i % 2))
        w.write(RX, fr[:3]); w.write(RX, fr[3:])              # 帧被拆成两块也要能解
    w.write(RX, b"\x00garbage")
    w.close()
    r = dzlog_to_csv(tmp_path / "a.dzlog", schema=sch)
    raw = (tmp_path / "a.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and r["rows"] == 5
    rows = list(csv.reader((tmp_path / "a.csv").read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0] == ["t_s", "spd[rps]", "state", "state_txt"]
    assert rows[3] == ["0.0400", "1.0", "0", "空闲"] and rows[2][3] == "运行"
    r = dzlog_to_csv(tmp_path / "a.dzlog", schema=sch, fmt="plotjuggler")
    pj = (tmp_path / "a.pj.csv").read_bytes()
    assert not pj.startswith(b"\xef\xbb\xbf") and r["fmt"] == "plotjuggler"
    rows = list(csv.reader(pj.decode().splitlines()))
    assert rows[0] == ["time", "spd[rps]", "state"] and rows[3] == ["0.0400", "1.0", "0"]
