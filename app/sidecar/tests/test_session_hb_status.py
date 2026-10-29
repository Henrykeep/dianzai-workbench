"""心跳 status 字（dzctl 0.5.0）：复位原因 + 标志的解析与时间线事件。"""
from dzbench.session import hb_status_dict, hb_status_event


def test_old_firmware_none():
    assert hb_status_dict(None) == {"reset": None, "hb_flags": None}


def test_decode():
    d = hb_status_dict(4 | (1 << 8) | (1 << 10))
    assert d["reset"] == "看门狗" and d["hb_flags"] == ["安全态", "急停"]


def test_events():
    assert hb_status_event(1) is None                       # 正常上电不报
    assert hb_status_event(1 | (1 << 10)) is None           # 普通急停已有自己的事件
    k, t = hb_status_event(4 | (1 << 8))
    assert k == "watchdog" and "看门狗" in t and "R" in t
    k, t = hb_status_event(1 | (1 << 9))
    assert k == "watchdog" and "堵转" in t
