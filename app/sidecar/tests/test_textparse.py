"""KvParser：任意字节切分、CRLF/CR 行尾、GBK/UTF-8 中文名。"""
from dzbench.textparse import KvParser


def _feed_chunks(data: bytes, cuts):
    p, out, i = KvParser(), [], 0
    for c in list(cuts) + [len(data)]:
        out += p.feed(data[i:c])[0]
        i = c
    return out, p


def test_every_byte_split_gives_same_result():
    data = b"x=1,y=-2.5\r\nx=3 y=4e1\nspd:0.5;err=-.25\r\n"
    whole, _ = _feed_chunks(data, [])
    assert whole == [{"x": 1, "y": -2.5}, {"x": 3, "y": 40.0}, {"spd": 0.5, "err": -0.25}]
    for k in range(1, len(data)):
        assert _feed_chunks(data, [k])[0] == whole, k
    assert _feed_chunks(data, range(1, len(data)))[0] == whole    # 一字节一字节


def test_crlf_split_between_cr_and_lf():
    out, p = _feed_chunks(b"a=1\r\na=2\r\n", [4])                 # 切在 \r 和 \n 中间
    assert out == [{"a": 1}, {"a": 2}] and p.buf == b""


def test_cr_only_line_endings():
    out, _ = _feed_chunks(b"a=1\ra=2\r", [])
    assert out == [{"a": 1}, {"a": 2}]


def test_gbk_chinese_names():
    data = "速度=1.5,角度=-3\n".encode("gbk")
    whole, p = _feed_chunks(data, [])
    assert whole == [{"速度": 1.5, "角度": -3}] and p.names == ["速度", "角度"]
    for k in range(1, len(data)):                                  # 切在双字节字符中间也一样
        assert _feed_chunks(data, [k])[0] == whole, k


def test_gbk_no_fake_ascii_names():
    # “丄”的 GBK 是 81 41，第二字节就是 ASCII 'A'：按 utf-8 replace 解码会冒出假通道 “A”
    data = "丄=7\n".encode("gbk")
    assert data[1:2] == b"A"
    out, p = _feed_chunks(data, [])
    assert out == [{"丄": 7}] and "A" not in p.names


def test_utf8_chinese_and_label_prefix():
    out, _ = _feed_chunks("[log] 温度: 36.6 x=1\n".encode(), [])
    assert out == [{"温度": 36.6, "x": 1}]


def test_name_not_split_from_word():
    out, _ = _feed_chunks(b"a1b=2 3c=4\n", [])
    assert out == [{"a1b": 2}]                                     # “3c” 不是名字，也不拆出 “c”


def test_serial_lines_set_before_open(monkeypatch):
    """DTR/RTS 在 open() 前设好；None 表示不动（走普通构造）。"""
    import serial
    from dzbench import ports
    log = []

    class FakeSerial:
        def __init__(self, port=None, baud=0, **kw):
            log.append(("init", port))
            self.port = port
        def __setattr__(self, k, v):
            if k in ("dtr", "rts"):
                log.append((k, v))
            object.__setattr__(self, k, v)
        def open(self):
            log.append(("open", self.port))
    monkeypatch.setattr(serial, "Serial", FakeSerial)
    monkeypatch.setattr(ports, "LINES", {"dtr": False, "rts": None})
    ports.open_serial("COM9", 115200)
    assert log == [("init", None), ("dtr", False), ("open", "COM9")]
    log.clear()
    monkeypatch.setattr(ports, "LINES", {"dtr": None, "rts": None})
    ports.open_serial("COM9", 115200)
    assert log == [("init", "COM9")]
