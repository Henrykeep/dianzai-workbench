"""心跳 status 字（dzctl 0.5.0）：复位原因 + 标志的解析与时间线事件。"""
from dzbench.session import hb_status_dict, hb_status_event, run_mode_dict


def test_old_firmware_none():
    assert hb_status_dict(None) == {"reset": None, "hb_flags": None, "boot": None}
    assert run_mode_dict(None) is None


def test_run_mode_bits():
    assert run_mode_dict(1)["mode"] == "tethered" and run_mode_dict(1)["started"] is False
    d = run_mode_dict(1 | (1 << 14))
    assert d["mode"] == "standalone" and d["started"] is False and "按键" in d["label_zh"]
    assert run_mode_dict(1 | (1 << 14) | (1 << 15))["started"] is True
    assert run_mode_dict(1 | (1 << 15))["started"] is False          # 联机下 bit15 无意义


def test_decode():
    d = hb_status_dict(4 | (1 << 8) | (1 << 10))
    assert d["reset"] == "看门狗" and d["hb_flags"] == ["安全态", "急停"]


def test_events():
    assert hb_status_event(1) is None                       # 正常上电不报
    assert hb_status_event(1 | (1 << 10)) is None           # 普通急停已有自己的事件
    k, t, src = hb_status_event(4 | (1 << 8))
    assert src == "firmware:watchdog_reset"
    assert k == "watchdog" and "看门狗" in t and "R" in t
    k, t, src = hb_status_event(1 | (1 << 9))
    assert src.startswith("firmware:")
    assert k == "watchdog" and "堵转" in t


def test_bb_record_text():
    from dzbench.session import bb_record
    assert "看门狗" in bb_record(0, 1, 4, 0, 0)["text"]
    assert "第 1 路堵转" in bb_record(5, 2, 1, 0.9, 0.01)["text"]
    assert "应用事件 0x100" in bb_record(5, 0x100, 0, 0, 0)["text"]
