"""K230（CanMV，MicroPython）上的 dzframe/1 发送端 —— 单文件，拷到 /sdcard 即可 import。

CanMV 不是 Linux、没有 pyserial，所以单独写：只用 struct（MicroPython 内置）和 machine.UART。
    from dzsend import DzSend
    tx = DzSend.open_uart(uart_id=2, baud=115200)            # 引脚复用按 CanMV 文档用 FPIOA 配【未验证】
    tx.send(1, [("u8", 1), ("i16", 320), ("u32", 1234)])     # 通道 id + (类型, 值) 列表，顺序 = board.yaml fields
与 host/python/dzlink/protocol.py 逐字节一致（host/python/dzlink/test_dzsend_k230.py 在 PC 上核对）。
【未验证】未在 K230 实机运行；machine.UART 构造参数以 CanMV K230 文档为准。
"""
import struct

_FMT = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I", "i32": "i", "f32": "f"}
_RANGE = {"u8": (0, 0xFF), "i8": (-128, 127), "u16": (0, 0xFFFF), "i16": (-32768, 32767),
          "u32": (0, 0xFFFFFFFF), "i32": (-2147483648, 2147483647)}


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(kind, id_, seq, payload):
    if len(payload) > 64:
        raise ValueError("payload > 64")
    body = bytes([1, kind, id_, seq & 0xFF, len(payload)]) + payload
    return b"\xA5\x5A" + body + struct.pack("<H", crc16(body))


def pack(items):
    out = b""
    for t, v in items:
        if t == "f32":
            v = float(v)
        else:
            lo, hi = _RANGE[t]
            v = max(lo, min(hi, int(round(v))))
        out += struct.pack("<" + _FMT[t], v)
    return out


class DzSend:
    def __init__(self, write):
        self.write = write
        self.seq = 0

    @classmethod
    def open_uart(cls, uart_id=2, baud=115200):
        from machine import UART
        u = UART(uart_id, baudrate=baud)
        return cls(u.write)

    def send(self, ch_id, items):
        self.write(encode(0, ch_id, self.seq, pack(items)))
        self.seq = (self.seq + 1) & 0xFF

    def heartbeat(self):
        self.write(encode(3, 0, self.seq, b""))
        self.seq = (self.seq + 1) & 0xFF
