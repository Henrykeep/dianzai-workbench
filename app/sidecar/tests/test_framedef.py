"""framedef：用户自定义 HEX/文本帧（VOFA JustFloat/FireWater 预设、校验、错帧重同步、任意字节切分），接进 Session。"""
import struct

import pytest

from dzbench.framedef import FrameDefError, FrameDefParser, crc16_modbus, validate
from dzbench.session import LinkError, Session


def feed_all(p, data, cuts=()):
    out, i = [], 0
    for c in list(cuts) + [len(data)]:
        out += p.feed(data[i:c])[0]
        i = c
    return out


def jf(*v):
    return struct.pack(f"<{len(v)}f", *v) + bytes.fromhex("0000807f")


def test_justfloat_preset_every_split():
    data = jf(1.0, -2.5) + jf(3.0, 4.0)
    whole = feed_all(FrameDefParser({"preset": "justfloat", "n": 2}), data)
    assert whole == [{"ch0": 1.0, "ch1": -2.5}, {"ch0": 3.0, "ch1": 4.0}]
    for k in range(1, len(data)):
        assert feed_all(FrameDefParser({"preset": "justfloat", "n": 2}), data, [k]) == whole, k


def test_justfloat_resyncs_after_garbage():
    p = FrameDefParser({"preset": "justfloat", "n": 1})
    assert feed_all(p, b"\x01\x02\x03" + jf(7.0) + jf(8.0)) == [{"ch0": 7.0}, {"ch0": 8.0}]


def test_hex_header_fields_big_endian_scale_sum8():
    d = {"kind": "hex", "header": "AA 55", "endian": "big", "checksum": "sum8", "check_from": 2,
         "fields": [{"name": "速度", "type": "i16", "scale": 0.01}, {"name": "n", "type": "u8"}]}
    body = struct.pack(">hB", -150, 9)
    good = b"\xaa\x55" + body + bytes([sum(body) & 0xFF])
    bad = b"\xaa\x55" + body + b"\x00"
    p = FrameDefParser(d)
    rows = feed_all(p, bad + b"\xaa" + good, range(1, 20))
    assert rows == [{"速度": pytest.approx(-1.5), "n": 9.0}] and p.bad >= 1


def test_crc16_modbus_and_footer():
    assert crc16_modbus(b"123456789") == 0x4B37
    d = {"header": "A5", "footer": "5A", "checksum": "crc16_modbus", "fields": [{"name": "x", "type": "f32"}]}
    body = b"\xa5" + struct.pack("<f", 2.0)
    fr = body + struct.pack("<H", crc16_modbus(body)) + b"\x5a"
    assert feed_all(FrameDefParser(d), fr * 2) == [{"x": 2.0}] * 2
    assert feed_all(FrameDefParser(d), fr[:-1] + b"\x00") == []


def test_firewater_text():
    p = FrameDefParser({"preset": "firewater", "n": 3})
    assert feed_all(p, b"ch:1,2.5,-3\r\n4,5,6\nbad,1,2\n1,2\n") == [
        {"ch0": 1.0, "ch1": 2.5, "ch2": -3.0}, {"ch0": 4.0, "ch1": 5.0, "ch2": 6.0}]


def test_validate_errors_are_chinese_and_specific():
    for d, word in [({"fields": [{"name": "x"}]}, "帧头或帧尾"), ({"header": "zz", "fields": [{"name": "x"}]}, "十六进制"),
                    ({"header": "AA", "fields": [{"name": "x", "type": "f128"}]}, "类型"),
                    ({"header": "AA", "fields": [{"name": "x"}, {"name": "x"}]}, "重复"),
                    ({"header": "AA", "fields": []}, "字段"), ({"preset": "nope"}, "预设")]:
        with pytest.raises(FrameDefError, match=word):
            validate(d)


def test_session_uses_framedef_for_non_dz_device():
    s = Session()
    got, ev = [], []
    s.on_sample = got.append
    s.emit = ev.append
    s.set_framedef({"preset": "justfloat", "n": 2})
    s._on_bytes(jf(1.0, 2.0) + jf(3.0, 4.0))
    assert got == [{"ch0": 1.0, "ch1": 2.0}, {"ch0": 3.0, "ch1": 4.0}]
    assert any(e.get("type") == "schema" for e in ev)
    with pytest.raises(LinkError):
        s.set_framedef({"header": ""})
    s.set_framedef(None)
    got.clear()
    s._on_bytes(b"a=1\n")
    assert got == [{"a": 1.0}]
