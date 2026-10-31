"""预设/定时/触发发送（急停后全部停用）与 key=value 文本遥测（离线，假串口）。"""
import time

import pytest

from dzbench.sender import Sender, encode_preset
from dzbench.session import LinkError, Session
from dzbench.textparse import KvParser
from test_batch1 import Flaky, wait


@pytest.fixture
def sess(home):
    Flaky.alive, Flaky.fail_next = [], 0
    ev = []
    s = Session(emit=ev.append)
    s._open = Flaky
    s.connect("COM9", 115200, log=False)
    tx = []
    Flaky.alive[-1].write = tx.append
    yield s, ev, tx
    s.disconnect()


def test_kv_parser():
    k = KvParser()
    rows, grew = k.feed(b"x=1.5, y:-2 z 3\r\nnoise\nx=2;y=1e3\nhalf=")
    assert grew and k.names == ["x", "y"] and rows == [{"x": 1.5, "y": -2.0}, {"x": 2.0, "y": 1000.0}]
    rows, grew = k.feed(b"7\n")
    assert grew and rows == [{"half": 7.0}]


def test_text_device_gets_virtual_schema_and_samples(sess):
    s, ev, _ = sess
    Flaky.alive[-1].q += [b"cx=120,cy=", b"88,lock=1\n", b"cx=121,cy=87,lock=1\n"]
    assert wait(lambda: len(s.window(10)) == 2)
    sch = [e for e in ev if e.get("type") == "schema"][-1]["schema"]
    assert sch["virtual"] and [f["name"] for f in sch["fields"]] == ["cx", "cy", "lock"]
    assert s.window(10)[1][1] == {"cx": 121.0, "cy": 87.0, "lock": 1.0}


def test_presets_timer_trigger_and_estop_lock(sess, home):
    s, ev, tx = sess
    sd = Sender(s, ev.append)
    sd.save_preset({"name": "at", "kind": "text", "payload": "AT", "eol": "\r\n"})
    sd.save_preset({"name": "go", "kind": "hex", "payload": "A5 5A 01"})
    assert {p["name"] for p in __import__("json").loads((home / "presets.json").read_text(encoding="utf-8"))} == {"at", "go"}   # 存盘了
    assert sd.send("at") and tx[-1] == b"AT\r\n"
    sd.start_timer("go", 20, count=3)
    assert wait(lambda: tx.count(b"\xa5\x5a\x01") == 3)
    # 触发：lock 从 0 变 1 时发一次，保持 1 不重复
    sd.add_trigger("at", "lock", ">=", 1, cooldown_ms=0)
    n = tx.count(b"AT\r\n")
    Flaky.alive[-1].q += [b"lock=0\n", b"lock=1\n", b"lock=1\n", b"lock=0\n", b"lock=1\n"]
    assert wait(lambda: tx.count(b"AT\r\n") == n + 2)
    time.sleep(0.1)
    assert tx.count(b"AT\r\n") == n + 2
    # 急停：定时/触发全停，之后任何侧车主动发送都被拒
    sd.start_timer("go", 20)
    s.estop()
    assert not sd.timers and not sd.triggers and s.status()["tx_locked"]
    k = len(tx); time.sleep(0.1)
    assert all(b != b"\xa5\x5a\x01" for b in tx[k:])
    for f in (lambda: sd.send("at"), lambda: s.send_data(1, b""), lambda: s.send_raw(b"x"), lambda: sd.start_timer("go", 50)):
        with pytest.raises(LinkError) as e:
            f()
        assert e.value.code == "tx_locked"
    s.cmd("R")
    t_end = time.monotonic() + 3
    while s.tx_locked and time.monotonic() < t_end:
        time.sleep(0.01)
    assert not s.tx_locked and sd.send("at")


def test_preset_validation():
    with pytest.raises(LinkError):
        encode_preset({"kind": "hex", "payload": "ZZ"})
    with pytest.raises(LinkError):
        encode_preset({"kind": "cmd", "payload": "R"})                # 解除急停不能做成预设
    assert encode_preset({"kind": "data", "id": 1, "payload": "0102"}) == ("data", b"\x01\x02", 1)
