"""dzframe/1 协议的 Python 实现（运行在 Linux/视觉协处理器上：NVIDIA Jetson Nano、树莓派、地瓜派 RDK、MaixCAM2 …，以及 PC 工作台）。

与 firmware/proto/dzframe/dzframe.c 逐字节一致；tests/host 里有 C↔Python 互通测试。
  python3 -m dzlink.protocol encode KIND ID SEQ HEXPAYLOAD   -> 打印帧的十六进制
  python3 -m dzlink.protocol decode HEX                       -> 打印解析出的帧
只依赖 Python 3.6+ 标准库。
"""
import struct, sys
SOF = b"\xA5\x5A"
VER = 1
MAX_PAYLOAD = 64
DATA, PARAM_SET, PARAM_ACK, HEARTBEAT = 0, 1, 2, 3
FMT = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I", "i32": "i", "f32": "f"}


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(kind: int, id_: int, seq: int, payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload 太长")
    body = bytes([VER, kind, id_, seq & 0xFF, len(payload)]) + payload
    return SOF + body + struct.pack("<H", crc16(body))


def pack_fields(fields, values) -> bytes:
    """fields 为 board.yaml channels[].fields，values 为 {name: 值}。"""
    return b"".join(struct.pack("<" + FMT[f["type"]], values[f["name"]]) for f in fields)


def unpack_fields(fields, payload: bytes) -> dict:
    out, off = {}, 0
    for f in fields:
        fmt = "<" + FMT[f["type"]]
        out[f["name"]] = struct.unpack_from(fmt, payload, off)[0]
        off += struct.calcsize(fmt)
    return out


class Parser:
    """与 C 版相同的重同步策略：出错时从缓存里下一个 0xA5 重新开始。"""

    def __init__(self):
        self.buf = bytearray()
        self.good = self.bad = 0

    def _check(self):
        b = self.buf
        n = len(b)
        if (n >= 1 and b[0] != 0xA5) or (n >= 2 and b[1] != 0x5A) or (n >= 3 and b[2] != VER) or (n >= 7 and b[6] > MAX_PAYLOAD):
            return -1
        if n < 7 or n < b[6] + 9:
            return 0
        L = b[6]
        return 1 if struct.unpack_from("<H", b, 7 + L)[0] == crc16(bytes(b[2:7 + L])) else -1

    def feed(self, data: bytes):
        frames = []
        for byte in data:
            if not self.buf and byte != 0xA5:
                continue
            self.buf.append(byte)
            while True:
                r = self._check()
                if r == 0:
                    break
                if r == 1:
                    L = self.buf[6]
                    frames.append((self.buf[3], self.buf[4], self.buf[5], bytes(self.buf[7:7 + L])))
                    self.good += 1
                    self.buf.clear()
                    break
                if len(self.buf) > 1 or self.buf[0] == 0xA5:
                    self.bad += 1
                i = 1
                while i < len(self.buf) and self.buf[i] != 0xA5:
                    i += 1
                del self.buf[:i]
                if not self.buf:
                    break
        return frames


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "encode":
        print(encode(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), bytes.fromhex(sys.argv[5] if len(sys.argv) > 5 else "")).hex())
    elif len(sys.argv) == 3 and sys.argv[1] == "decode":
        for fr in Parser().feed(bytes.fromhex(sys.argv[2])):
            print(f"kind={fr[0]} id={fr[1]} seq={fr[2]} payload={fr[3].hex()}")
    else:
        print(__doc__)
        sys.exit(2)
