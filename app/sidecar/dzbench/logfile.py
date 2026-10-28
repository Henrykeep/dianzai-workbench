""".dzlog：原始字节全量记录（不抽稀），回放时走同一条解析路径。

格式：b"DZLOG1\\n" + 一行 JSON 头（端口、波特率、开始时间、schema）+ 若干记录
记录：<d 相对秒> <B 方向 0=收 1=发> <I 长度> <字节>
参考：PlotJuggler/SerialPlot 都是“先完整录原始流，再离线解析”，保证事后能用新 schema 重新解码。
"""
from __future__ import annotations

import json
import pathlib
import struct
import threading
import time

MAGIC = b"DZLOG1\n"
REC = struct.Struct("<dBI")
RX, TX = 0, 1


class LogWriter:
    def __init__(self, path: pathlib.Path, header: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.f = open(path, "wb")
        self.f.write(MAGIC + json.dumps(header, ensure_ascii=False).encode() + b"\n")
        self.t0 = time.monotonic()
        self.lock = threading.Lock()
        self.bytes = 0

    def write(self, direction: int, data: bytes) -> None:
        with self.lock:
            if self.f.closed:
                return
            self.f.write(REC.pack(time.monotonic() - self.t0, direction, len(data)) + data)
            self.bytes += len(data)

    def close(self) -> None:
        with self.lock:
            self.f.close()


def read_log(path) -> tuple[dict, list[tuple[float, int, bytes]]]:
    raw = pathlib.Path(path).read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError(f"{path} 不是 .dzlog 文件（缺少 DZLOG1 头）")
    nl = raw.index(b"\n", len(MAGIC))
    header = json.loads(raw[len(MAGIC):nl])
    recs, off = [], nl + 1
    while off + REC.size <= len(raw):
        t, d, n = REC.unpack_from(raw, off)
        off += REC.size
        if off + n > len(raw):
            break                                    # 程序崩溃时最后一条可能不完整：丢掉
        recs.append((t, d, raw[off:off + n]))
        off += n
    return header, recs
