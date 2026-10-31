#!/usr/bin/env python3
"""dzstep.py —— #38 阶跃实验 / 参数哈希 / param_reject 的上位机侧参考实现（dzctl 0.13.0，与 firmware/proto/dzctl/dzstep.c 同口径）。

侧车可以直接 import（只依赖标准库；params_hash_yaml 需要 PyYAML）或整份复制。帧格式见 firmware/proto/dzctl/README.md「0.13.0」。

  params_hash(values)                      list[float]（参数表顺序）→ CRC32（zlib.crc32 over <f32 LE ...>）
  params_hash_yaml(app_yaml, overrides)    从 app.yaml link.params（或 project.yaml 顶层 params）的默认值 + 覆盖值算
  encode_step_start(ch, iter, target, dur_ms) -> bytes   DATA 0x7B 负载（len 12）；停止 = 空负载
  decode_step_ack(payload) / decode_step_result(payload) / decode_param_reject(payload)
  step_metrics(samples, sp, dur_ms, t0, rng, abs_tol, u_max)   由原始遥测样本 [(t_ms, y, u|None)] 算同一组指标（测试参考）

用法：dzstep.py hash <app.yaml> [name=value ...]    |    dzstep.py --selftest
"""
from __future__ import annotations

import math
import pathlib
import struct
import sys
import zlib

STEP_ID, REJECT_ID = 0x7B, 0x7A
PROTO = 1
NONE_U32 = 0xFFFFFFFF
ACK_STATUS = {0: "started", 1: "bad_arg", 2: "estop", 3: "busy", 4: "unsupported", 5: "offline"}
REJECT_REASON = {1: "range", 2: "type", 3: "state", 4: "step"}
ABORT_HOST_STOP = 0x80
PARAM_ACK_REJECTED = 5
HB_ITER_BUSY = 1 << 17

RESULT_FMT = "<BBBBHHIIfffIIffffBBH"   # 56 字节
assert struct.calcsize(RESULT_FMT) == 56


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def params_hash(values) -> int:
    return zlib.crc32(b"".join(struct.pack("<f", float(v)) for v in values)) & 0xFFFFFFFF


def params_hash_yaml(app_yaml, overrides: dict | None = None) -> int:
    import yaml
    y = yaml.safe_load(pathlib.Path(app_yaml).read_text(encoding="utf-8")) or {}
    link = y.get("link") or {}
    params = link["params"] if "params" in link else (y.get("params") or [])
    ov = overrides or {}
    vals = []
    for p in params:
        v = float(ov.get(p["name"], p.get("default", 0)))
        if p.get("type", "float") == "bool":
            v = 1.0 if v >= 0.5 else 0.0
        elif p.get("type", "float") != "float":
            v = float(math.floor(v + 0.5) if v >= 0 else math.ceil(v - 0.5))
        vals.append(v)
    return params_hash(vals)


def encode_step_start(ch: int, it: int, target: float, dur_ms: int) -> bytes:
    return struct.pack("<BBHfI", ch, 0, it, target, dur_ms)


def decode_step_ack(b: bytes) -> dict:
    st, ch, it = struct.unpack("<BBH", b[:4])
    return {"status": ACK_STATUS.get(st, st), "ch": ch, "iter": it}


def decode_step_result(b: bytes) -> dict:
    if len(b) != 56:
        raise ValueError(f"step_result 长度 {len(b)} ≠ 56")
    (proto, mode, aborted, cause, it, n, h, t0, sp, y0, os_, rise, settle, ss, usat, peak, band, ch, _r1, _r2) = \
        struct.unpack(RESULT_FMT, b)
    return {"proto": proto, "metric_mode": "abs" if mode else "rel", "aborted": aborted, "abort_cause": cause,
            "iter": it, "n": n, "params_hash": h, "t0_ms": t0, "setpoint": sp, "initial": y0,
            "overshoot_pct": os_, "rise_ms": None if rise == NONE_U32 else rise,
            "settle_ms": None if settle == NONE_U32 else settle, "ss_err_pct": ss,
            "u_sat_ratio": None if usat < 0 else usat, "peak_abs_err": peak, "band": band, "ch": ch}


def decode_param_reject(b: bytes) -> dict:
    i, r, req, cur = struct.unpack("<BBff", b[:10])
    return {"index": i, "reason": REJECT_REASON.get(r, r), "requested": req, "current": cur,
            "name": b[10:].decode("ascii", "replace")}


def step_metrics(samples, sp: float, dur_ms: int, t0: int, rng: float, abs_tol: float, u_max: float) -> dict:
    """samples: [(t_ms, y, u or None)]，取 t0 ≤ t ≤ t0+dur 的样本；口径同 dzstep.h。"""
    s = [(t, y, u) for t, y, u in samples if 0 <= t - t0 <= dur_ms]
    out = {"n": len(s)}
    if not s:
        return out
    y0 = s[0][1]
    amp = abs(sp - y0)
    absm = amp < max(0.01 * rng, abs_tol)
    band = abs_tol if absm else 0.02 * amp
    errs = [abs(sp - y) for _, y, _ in s]
    ssw = [e for (t, _, _), e in zip(s, errs) if 5 * (t - t0) >= 4 * dur_ms]
    settle, pending = 0, False
    for (t, _, _), e in zip(s, errs):
        if e > band:
            pending = True
        elif pending:
            pending, settle = False, t - t0
    us = [u for _, _, u in s if u is not None]
    out.update(metric_mode="abs" if absm else "rel", initial=y0, band=band, peak_abs_err=max(errs),
               settle_ms=None if pending else settle,
               u_sat_ratio=(sum(1 for u in us if u_max > 0 and abs(u) >= 0.99 * u_max) / len(us)) if us else None)
    if absm:
        out.update(overshoot_pct=max(errs), rise_ms=None, ss_err_pct=sum(ssw) / len(ssw) if ssw else -1.0)
    else:
        r = [(t, (y - y0) / (sp - y0)) for t, y, _ in s]
        r10 = next((t for t, x in r if x >= 0.1), None)
        r90 = next((t for t, x in r if x >= 0.9), None)
        out.update(overshoot_pct=max(0.0, max(x for _, x in r) - 1.0) * 100.0,
                   rise_ms=None if r10 is None or r90 is None else r90 - r10,
                   ss_err_pct=sum(ssw) / len(ssw) / amp * 100.0 if ssw else -1.0)
    return out


def selftest() -> int:
    ok = params_hash([]) == 0 and zlib.crc32(b"123456789") == 0xCBF43926
    ok &= decode_step_ack(bytes([0, 0, 3, 0]))["iter"] == 3
    b = struct.pack(RESULT_FMT, 1, 0, 0, 0, 2, 101, 7, 100, 10.0, 0.0, 7.8, NONE_U32, 300, 1.0, -1.0, 10.0, 0.2, 0, 0, 0)
    d = decode_step_result(b)
    ok &= d["rise_ms"] is None and d["u_sat_ratio"] is None and d["n"] == 101
    m = step_metrics([(100 + 10 * k, (22 * k / 100 if k < 50 else 10.0), 1.0 if k < 30 else 0.2) for k in range(101)],
                     10.0, 1000, 100, 100.0, 0.5, 1.0)
    ok &= abs(m["overshoot_pct"] - 7.8) < 0.05 and abs(m["u_sat_ratio"] - 30 / 101) < 1e-9
    print(f"{'✓' if ok else '✗'} dzstep 自检")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--selftest"]:
        sys.exit(selftest())
    if sys.argv[1:2] == ["hash"] and len(sys.argv) >= 3:
        ov = dict(a.split("=", 1) for a in sys.argv[3:])
        print(f"0x{params_hash_yaml(sys.argv[2], {k: float(v) for k, v in ov.items()}):08X}")
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
