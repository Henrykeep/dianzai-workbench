"""python3 -m dzlink.test_dzlink —— 回环自测，不需要硬件。"""
import os, random, sys
from . import Link, LoopbackTransport, Parser, encode, crc16, DATA

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def main():
    assert crc16(b"123456789") == 0x29B1
    lb = LoopbackTransport()
    link = Link.from_board(os.path.join(ROOT, "boards", "jetson-nano-vision", "board.yaml"), lb)
    link.send("ball", x_px=-12, y_px=480, found=1)
    lb.buf[0:0] = b"\x00\xA5garbage"                       # 前面插垃圾
    bad = bytearray(encode(DATA, 1, 0, b"\x01\x02\x03\x04\x05")); bad[-1] ^= 0xFF
    lb.buf += bad                                          # 坏帧
    link.heartbeat()
    got = link.poll()
    assert got[0] == ("ball", {"x_px": -12, "y_px": 480, "found": 1}), got
    assert got[1][0] == "heartbeat", got
    p = Parser(); random.seed(1)
    p.feed(bytes(random.randrange(256) for _ in range(20000)))
    p.feed(bytes(80))
    assert len(p.feed(encode(DATA, 1, 0, b"abc"))) == 1
    print("dzlink 自测通过")


if __name__ == "__main__":
    sys.exit(main())
