"""RTT 传输：按 pyOCD 主干 API（假 pyocd）连上、找控制块、resume、读写；没控制块给清楚的错。"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.syspath_prepend(os.path.join(HERE, "fakepyocd"))
    for m in [m for m in sys.modules if m == "pyocd" or m.startswith("pyocd.")]:
        monkeypatch.delitem(sys.modules, m)
    import pyocd
    monkeypatch.setattr(pyocd, "BOARD", object(), raising=False)
    monkeypatch.setattr(pyocd, "LOG", [], raising=False)
    monkeypatch.setattr(pyocd, "RTT_UP", bytearray(), raising=False)
    monkeypatch.setattr(pyocd, "RTT_DOWN", bytearray(), raising=False)
    monkeypatch.setattr(pyocd, "RTT_PRESENT", True, raising=False)
    return pyocd


def test_rtt_read_write_and_resume(fake):
    from dzbench.transport import RttTransport, open_transport
    t = open_transport("rtt:mspm0g3507", 0)
    assert isinstance(t, RttTransport) and t.name == "rtt:mspm0g3507"
    assert ("resume",) in fake.LOG and any(e[0] == "pack" for e in fake.LOG)   # MSPM0 带器件包；连上后放开内核
    fake.RTT_UP.extend(b"\xa5\x5a hello")
    assert t.read() == b"\xa5\x5a hello" and t.read() == b""
    t.write(b"x" * 40)                                  # 下行缓冲一次只收 16 B：要循环写完
    assert bytes(fake.RTT_DOWN) == b"x" * 40
    t.close()
    assert fake.LOG[-1] == ("close",)


def test_rtt_no_control_block(fake):
    from dzbench.transport import RttTransport
    fake.RTT_PRESENT = False
    with pytest.raises(RuntimeError, match="RTT 控制块"):
        RttTransport("stm32f407vg")
    assert fake.LOG[-1] == ("close",)                   # 失败也要关掉会话


def test_rtt_probe_serial(fake):
    from dzbench.transport import RttTransport
    RttTransport("stm32f407vg@0669FF")
    assert ("connect", "stm32f407vg") in fake.LOG


def test_rtt_listed_only_with_pyocd_and_target(fake, home):
    import json
    from dzbench import ports
    assert ports.rtt_ports() == []                                  # 没配 flash.target
    (home / "machine.json").write_text(json.dumps({"flash": {"target": "mspm0g3507", "probe": "ABC"}}), encoding="utf-8")
    assert ports.rtt_ports()[0]["port"] == "rtt:mspm0g3507@ABC"
