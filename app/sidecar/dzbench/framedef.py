"""用户自定义帧结构（没烧工作台固件的板子、第三方模块也能直接画曲线）。

两类：
  hex  —— 二进制帧：帧头（可空）+ 字段表（u8/i8/u16/i16/u32/i32/f16/f32/f64，大/小端，可乘 scale）+ 可选校验 + 帧尾（可空）。
          帧头或帧尾至少一个；校验 sum8 / xor8 / crc16_modbus（低字节在前）/ crc8（多项式 0x07），
          算 [from 帧头起偏移, 校验字节之前) 的字节。错帧丢弃并从下一个字节重新找头（不会整段错位）。
  text —— 文本行：`sep` 分隔的数（FireWater 风格 "名字:1,2,3\\n" 前缀可有可无），按字段表命名；多出的数忽略。
预设：justfloat（VOFA+ JustFloat：N 个 f32 小端 + 帧尾 00 00 80 7F）、firewater（VOFA+ FireWater 文本）。
思路参考 SerialWeb（serialweb-src/index.html 的 HEX 帧结构表）与 VOFA+ 协议说明；代码自写。
接口与 textparse.KvParser 相同：feed(bytes) -> (样本列表, 通道表是否变了)、schema_dict()。
"""
from __future__ import annotations

import re
import struct

from .textparse import EOL, VIRTUAL_HASH, _decode

TYPES = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I", "i32": "i", "f16": "e", "f32": "f", "f64": "d"}
CHECKS = {"none": 0, "sum8": 1, "xor8": 1, "crc8": 1, "crc16_modbus": 2}
MAX_FIELDS = 32
NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
NAME = re.compile(r"^[^\W\d]\w{0,23}$")


class FrameDefError(ValueError):
    pass


def _hex(s) -> bytes:
    s = re.sub(r"[\s,]|0x", "", str(s or ""), flags=re.I)
    try:
        return bytes.fromhex(s)
    except ValueError as e:
        raise FrameDefError(f"十六进制写错了：{s!r}") from e


def crc16_modbus(b: bytes) -> int:
    c = 0xFFFF
    for x in b:
        c ^= x
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


def crc8(b: bytes) -> int:
    c = 0
    for x in b:
        c ^= x
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def _check(kind: str, b: bytes) -> bytes:
    if kind == "sum8":
        return bytes([sum(b) & 0xFF])
    if kind == "xor8":
        x = 0
        for v in b:
            x ^= v
        return bytes([x])
    if kind == "crc8":
        return bytes([crc8(b)])
    if kind == "crc16_modbus":
        return struct.pack("<H", crc16_modbus(b))
    return b""


def preset(name: str, n: int = 4) -> dict:
    if name == "justfloat":
        return {"kind": "hex", "header": "", "footer": "0000807f", "endian": "little",
                "fields": [{"name": f"ch{i}", "type": "f32"} for i in range(n)]}
    if name == "firewater":
        return {"kind": "text", "sep": ",", "fields": [{"name": f"ch{i}"} for i in range(n)]}
    raise FrameDefError(f"没有预设 {name}（有 justfloat / firewater）")


def validate(d: dict) -> dict:
    """检查并补全默认值；错了抛 FrameDefError（中文说明哪里错）。"""
    if not isinstance(d, dict):
        raise FrameDefError("帧结构要是一个对象")
    if d.get("preset"):
        base = preset(d["preset"], int(d.get("n", 4)))
        d = base | {k: v for k, v in d.items() if k not in ("preset", "n")}
    kind = d.get("kind", "hex")
    fields = d.get("fields") or []
    if not fields or len(fields) > MAX_FIELDS:
        raise FrameDefError(f"字段要 1..{MAX_FIELDS} 个")
    names = set()
    out_f = []
    for i, f in enumerate(fields):
        nm = str(f.get("name") or f"ch{i}")
        if not NAME.match(nm) or nm in names:
            raise FrameDefError(f"第 {i + 1} 个字段名 {nm!r} 不合法或重复（字母/中文开头，≤24 字）")
        names.add(nm)
        g = {"name": nm, "scale": float(f.get("scale", 1.0))}
        if kind == "hex":
            t = f.get("type", "f32")
            if t not in TYPES:
                raise FrameDefError(f"字段 {nm} 类型 {t!r} 不认识（{'/'.join(TYPES)}）")
            g["type"] = t
        out_f.append(g)
    if kind == "text":
        sep = d.get("sep", ",")
        if not sep or len(sep) > 4:
            raise FrameDefError("分隔符要 1..4 个字符")
        return {"kind": "text", "sep": sep, "fields": out_f}
    if kind != "hex":
        raise FrameDefError(f"kind 只能 hex / text，不是 {kind!r}")
    head, foot = _hex(d.get("header")), _hex(d.get("footer"))
    if not head and not foot:
        raise FrameDefError("二进制帧要帧头或帧尾至少一个（不然没法对齐）")
    endian = d.get("endian", "little")
    if endian not in ("little", "big"):
        raise FrameDefError("endian 只能 little / big")
    ck = d.get("checksum", "none") or "none"
    if ck not in CHECKS:
        raise FrameDefError(f"校验 {ck!r} 不认识（{'/'.join(CHECKS)}）")
    frm = int(d.get("check_from", 0))
    body = struct.calcsize(("<" if endian == "little" else ">") + "".join(TYPES[f["type"]] for f in out_f))
    if not 0 <= frm <= len(head) + body:
        raise FrameDefError("check_from 超出帧范围")
    return {"kind": "hex", "header": head.hex(), "footer": foot.hex(), "endian": endian, "checksum": ck,
            "check_from": frm, "fields": out_f}


class FrameDefParser:
    def __init__(self, d: dict):
        self.d = validate(d)
        self.names = [f["name"] for f in self.d["fields"]]
        self._announced = False
        self.buf = b""
        self.bad = 0                       # 校验错 / 帧尾不对 的帧数（给 UI 显示）
        if self.d["kind"] == "hex":
            self.head, self.foot = bytes.fromhex(self.d["header"]), bytes.fromhex(self.d["footer"])
            self.fmt = ("<" if self.d["endian"] == "little" else ">") + "".join(TYPES[f["type"]] for f in self.d["fields"])
            self.body = struct.calcsize(self.fmt)
            self.cklen = CHECKS[self.d["checksum"]]
            self.flen = len(self.head) + self.body + self.cklen + len(self.foot)

    def _row(self, vals) -> dict:
        return {f["name"]: float(v) * f["scale"] for f, v in zip(self.d["fields"], vals)}

    def feed(self, data: bytes) -> tuple[list[dict], bool]:
        self.buf += data
        rows = self._text() if self.d["kind"] == "text" else self._hexrows()
        grew = not self._announced
        self._announced = True
        return rows, grew

    def _text(self) -> list[dict]:
        if len(self.buf) > 4096 and b"\n" not in self.buf:
            self.buf = self.buf[-512:]
        *lines, self.buf = EOL.split(self.buf)
        out = []
        for ln in lines:
            s = _decode(ln)
            if ":" in s:
                s = s.split(":", 1)[1]                    # FireWater 前缀 "名字:"
            nums = [x for x in (p.strip() for p in s.split(self.d["sep"])) if x]
            if len(nums) < len(self.names) or not all(NUM.fullmatch(x) for x in nums[:len(self.names)]):
                continue
            out.append(self._row(float(x) for x in nums[:len(self.names)]))
        return out

    def _hexrows(self) -> list[dict]:
        out, b, i = [], self.buf, 0
        while True:
            if self.head:
                j = b.find(self.head, i)
                if j < 0:
                    i = max(i, len(b) - len(self.head) + 1)
                    break
                i = j
            if len(b) - i < self.flen:
                break
            fr = b[i:i + self.flen]
            p = len(self.head)
            ok = fr.endswith(self.foot)
            if ok and self.cklen:
                ok = _check(self.d["checksum"], fr[self.d["check_from"]:p + self.body]) == fr[p + self.body:p + self.body + self.cklen]
            if ok:
                vals = struct.unpack(self.fmt, fr[p:p + self.body])
                if all(v == v and abs(v) != float("inf") for v in vals):
                    out.append(self._row(vals))
                i += self.flen
            else:
                self.bad += 1
                i += 1                                        # 从下一个字节重新找头
        self.buf = b[i:][-max(4096, 4 * self.flen):]
        return out

    def schema_dict(self, period_ms: int | None = None) -> dict:
        return {"version": 1, "hash": VIRTUAL_HASH, "virtual": True,
                "telemetry": {"id": -1, "period_ms": period_ms, "fields": [{"name": n, "type": "f32"} for n in self.names]},
                "params": []}
