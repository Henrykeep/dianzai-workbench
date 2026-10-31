#!/usr/bin/env python3
"""#38 阶跃实验 step_result / param_reject / 心跳 bit17 的 host-sim 端到端测试（make test 调用）。

每个支持阶跃的应用（app.yaml link.step）：编译 tests/step/step_run.c + 真实应用代码，按脚本驱动，然后
  1. C↔Python 参数哈希：板上 dzctl_params_crc32(默认参数) == tools/dzstep.py params_hash_yaml(app.yaml)；step_result.params_hash 同值
  2. rel 阶跃（iter 1）与回零阶跃（iter 2，sp=0）：板上指标 vs 用同一批原始遥测在 Python 里算的参考（容差见 TOL）
  3. abs 口径：已在 0 附近再给 sp=0（iter 3）→ metric_mode=abs，指标同样对拍
  4. param_reject：range / type（NaN、Inf、整型给小数）/ step（max_delta）/ state（实验进行中、急停锁存中），参数不变
  5. 心跳 bit17：实验中至少一帧为 1，结果发出后为 0；实验中急停 → aborted=1、abort_cause=1，急停沿心跳及之后 bit17=0
  6. 实验中途上位机又发设定值 → aborted=1、abort_cause=0x80
用法：test_step_result.py [app ...]
"""
from __future__ import annotations

import json
import math
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dzstep  # noqa: E402

# 容差：时间 ±1 个遥测周期（C 用 f32、Python 用 f64，阈值恰好压线时可能差一个样本）；百分比 ±0.05 个百分点；
# 物理量相对 1e-4（f32 累加）；u_sat_ratio ±1/n
TOL_PCT, TOL_REL = 0.05, 1e-4
# 每个应用：前置脚本、阶跃目标、窗口
APPS = {
    "motor_pos":    {"pre": [], "target": 90.0, "dur": 2000},
    "pendulum_rot": {"pre": ["cmd U"], "target": 30.0, "dur": 2000},
    "pan_tilt":     {"pre": [], "target": 40.0, "dur": 2000},
    "line_car":     {"pre": [], "target": 10.0, "dur": 1500},
    "car_2wd":      {"pre": [], "target": 2.0, "dur": 1500, "preempt": "vw 0.1 0"},
}
DATA, PARAM_ACK, HB = 0, 2, 3


def build(app: str) -> tuple[pathlib.Path, dict]:
    subprocess.run(["make", "-s", "BOARD=host-sim", f"APP={app}"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    d = ROOT / "build/host-sim" / app
    objs = [str(p) for p in (d / "obj").rglob("*.o") if p.name != "main_host.c.o"]
    inc = ["-Ifirmware/common", "-Ifirmware/pal", "-Iports/host-sim", "-Ibuild/host-sim/gen", f"-I{d}/linkgen", "-Iapps/include"]
    inc += [f"-I{p.relative_to(ROOT)}" for p in sorted(ROOT.glob("firmware/*/*")) if p.is_dir()]
    exe = d / "step_run"
    subprocess.run(["cc", "-std=c11", "-O1", *inc, "-c", "tests/step/step_run.c", "-o", f"{d}/step_run.o"], cwd=ROOT, check=True)
    subprocess.run(["cc", f"{d}/step_run.o", *objs, "-fsanitize=address,undefined", "-lm", "-o", str(exe)], cwd=ROOT, check=True)
    return exe, json.loads((d / "linkgen/link_schema.json").read_text())


def run(exe: pathlib.Path, script: list[str]) -> tuple[int, list]:
    p = subprocess.run([str(exe)], input="\n".join(script) + "\n", capture_output=True, text=True, cwd=ROOT, timeout=300)
    if p.returncode:
        raise RuntimeError(f"step_run rc={p.returncode}: {p.stderr[-2000:]}")
    crc, frames = None, []
    for ln in p.stdout.splitlines():
        if ln.startswith("CRC "):
            crc = int(ln.split()[1])
            continue
        ms, kind, fid, *hx = ln.split()
        frames.append((int(ms), int(kind), int(fid), bytes.fromhex(hx[0]) if hx else b""))
    return crc, frames


def telem(schema: dict, frames: list) -> list[dict]:
    fmt = {"f32": "f", "u32": "I", "i32": "i", "u16": "H", "i16": "h", "u8": "B"}
    fl = schema["telemetry"]["fields"]
    st = struct.Struct("<" + "".join(fmt[f["type"]] for f in fl))
    return [dict(zip([f["name"] for f in fl], st.unpack(b[:st.size]))) for _, k, i, b in frames
            if k == DATA and i == schema["telemetry"]["id"] and len(b) >= st.size]


def results(frames):   # (ms, dict)
    return [(ms, dzstep.decode_step_result(b)) for ms, k, i, b in frames if k == DATA and i == dzstep.STEP_ID and len(b) == 56]


def acks(frames):
    return [(ms, dzstep.decode_step_ack(b)) for ms, k, i, b in frames if k == DATA and i == dzstep.STEP_ID and len(b) == 4]


def hbs(frames):       # (ms, status)
    return [(ms, struct.unpack_from("<I", b, 12)[0]) for ms, k, i, b in frames if k == HB and len(b) >= 16]


class Checker:
    def __init__(self, app):
        self.app, self.fail, self.n = app, 0, 0

    def ok(self, cond, msg):
        self.n += 1
        if not cond:
            self.fail += 1
            print(f"✗ [step] {self.app}: {msg}")
        return cond


def compare(c: Checker, tag: str, r: dict, ref: dict, period: int):
    c.ok(r["n"] == ref["n"], f"{tag} n 板 {r['n']} ≠ 参考 {ref['n']}")
    c.ok(r["metric_mode"] == ref["metric_mode"], f"{tag} metric_mode 板 {r['metric_mode']} ≠ 参考 {ref['metric_mode']}")
    c.ok(r["initial"] == dzstep.f32(ref["initial"]), f"{tag} initial {r['initial']} ≠ {ref['initial']}")
    scale = max(1.0, abs(r["setpoint"]), abs(ref["peak_abs_err"]))
    c.ok(abs(r["peak_abs_err"] - ref["peak_abs_err"]) <= TOL_REL * scale, f"{tag} peak_abs_err {r['peak_abs_err']} vs {ref['peak_abs_err']}")
    c.ok(abs(r["band"] - ref["band"]) <= TOL_REL * max(1.0, ref["band"]), f"{tag} band {r['band']} vs {ref['band']}")
    tol_v = TOL_PCT if ref["metric_mode"] == "rel" else TOL_REL * scale
    for k in ("overshoot_pct", "ss_err_pct"):
        c.ok(abs(r[k] - ref[k]) <= tol_v, f"{tag} {k} 板 {r[k]:.4f} vs 参考 {ref[k]:.4f}（容差 {tol_v}）")
    for k in ("rise_ms", "settle_ms"):
        a, b = r[k], ref[k]
        c.ok((a is None and b is None) or (a is not None and b is not None and abs(a - b) <= period),
             f"{tag} {k} 板 {a} vs 参考 {b}（容差 ±{period} ms）")
    if ref["u_sat_ratio"] is None:
        c.ok(r["u_sat_ratio"] is None, f"{tag} 没有 u 时 u_sat_ratio 应为 −1")
    else:
        c.ok(r["u_sat_ratio"] is not None and abs(r["u_sat_ratio"] - ref["u_sat_ratio"]) <= 1.0 / max(1, ref["n"]) + 1e-6,
             f"{tag} u_sat_ratio {r['u_sat_ratio']} vs {ref['u_sat_ratio']}")


def ref_for(schema, tel, r, dur, ch_cfg, params_now):
    y, u = ch_cfg["y"], ch_cfg.get("u")
    um = ch_cfg.get("u_max", 0)
    umax = float(params_now[um]) if isinstance(um, str) else float(um)
    samples = [(t["t_ms"], t[y], t[u] if u else None) for t in tel]
    return dzstep.step_metrics(samples, r["setpoint"], dur, r["t0_ms"], ch_cfg["range"], ch_cfg["abs_tol"], umax)


def app_yaml(app: str) -> pathlib.Path:
    """与 Makefile 的 APP_DIR 查找顺序一致：$DZBENCH_HOME/projects/<app>、apps/<app>、examples/<app>（生成的随机对象走第一个）。"""
    import os
    cands = ([pathlib.Path(os.environ["DZBENCH_HOME"]) / "projects" / app] if os.environ.get("DZBENCH_HOME") else []) + [ROOT / "apps" / app, ROOT / "examples" / app]
    return next((d / "app.yaml" for d in cands if (d / "app.yaml").exists()), ROOT / "apps" / app / "app.yaml")


def test_app(app: str) -> tuple[int, int, str]:
    cfg = APPS[app]
    exe, schema = build(app)
    c = Checker(app)
    yml = app_yaml(app)
    ch = schema["step"][0]
    pnames = [p["name"] for p in schema["params"]]
    defaults = {p["name"]: p["default"] for p in schema["params"]}
    period = schema["telemetry"]["period_ms"]
    T, D = cfg["target"], cfg["dur"]
    pre = [f"300 {x}" for x in cfg["pre"]]

    # ---- 1~3：rel 阶跃、回零、abs ----
    s1 = 1000; s2 = s1 + D + 700; s3 = s2 + D + 700; end = s3 + D + 300
    crc, fr = run(exe, pre + [f"{s1} step 0 1 {T} {D}", f"{s2} step 0 2 0 {D}", f"{s3} step 0 3 0 {D}", f"{end} end"])
    py_crc = dzstep.params_hash_yaml(yml)
    c.ok(crc == py_crc, f"参数哈希 C 0x{crc:08X} ≠ Python 0x{py_crc:08X}")
    tel = telem(schema, fr)
    rs = {r["iter"]: r for _, r in results(fr)}
    c.ok([a["status"] for _, a in acks(fr)] == ["started"] * 3, f"开始应答 {[a for _, a in acks(fr)]}")
    summary = []
    for it, tag in ((1, "rel"), (2, "回零"), (3, "abs")):
        r = rs.get(it)
        if not c.ok(r is not None, f"iter {it} 没有 step_result"):
            continue
        c.ok(r["proto"] == 1 and r["aborted"] == 0 and r["params_hash"] == py_crc, f"iter {it} proto/aborted/hash {r}")
        c.ok(r["n"] >= 20, f"iter {it} 样本太少 n={r['n']}")
        ref = ref_for(schema, tel, r, D, ch, defaults)
        compare(c, f"iter {it}({tag})", r, ref, period)
        if it == 3 and abs(r["initial"]) < ch["abs_tol"]:
            c.ok(r["metric_mode"] == "abs", f"sp=0 且已在 0 附近应为 abs 口径，实际 {r['metric_mode']}（initial={r['initial']}）")
        if it == 2 and abs(r["initial"]) >= max(0.01 * ch["range"], ch["abs_tol"]):   # car_2wd 命令超时后已自行停下 → 幅度小，按 abs
            c.ok(r["metric_mode"] == "rel" and r["setpoint"] == 0.0, f"回零阶跃（幅度 {T}）应为 rel 口径")
        summary.append(f"{tag}: os={r['overshoot_pct']:.2f} rise={r['rise_ms']} settle={r['settle_ms']} ss={r['ss_err_pct']:.3f} n={r['n']}")
    hb = hbs(fr)
    busy_in = [st & dzstep.HB_ITER_BUSY for ms, st in hb if s1 + 100 <= ms < s1 + D - 100]
    c.ok(busy_in and all(busy_in), f"实验中心跳 bit17 应为 1：{busy_in[:5]}")
    r1_ms = next((ms for ms, r in results(fr) if r["iter"] == 1), None)
    after = [st & dzstep.HB_ITER_BUSY for ms, st in hb if r1_ms is not None and r1_ms < ms < s2]
    c.ok(after and not any(after), "结果发出后 bit17 应为 0")

    # ---- 4：param_reject 各原因（空闲时）+ state（实验中、急停中） ----
    md = next(p for p in schema["params"] if p["max_delta"] < p["max"] - p["min"])
    imd = pnames.index(md["name"])
    ip = 0
    p0 = schema["params"][0]
    intp = next((i for i, p in enumerate(schema["params"]) if p["type"] != "f32"), None)
    script = pre + [f"500 param {ip} {p0['max'] + 1}", f"520 param {ip} nan", f"540 param {ip} inf",
                    f"560 param {imd} {min(md['max'], md['default'] + md['max_delta'] * 1.5) if md['default'] + md['max_delta'] * 1.5 <= md['max'] else max(md['min'], md['default'] - md['max_delta'] * 1.5)}"]
    exp = [("range", ip), ("type", ip), ("type", ip), ("step", imd)]
    if intp is not None:
        script.append(f"580 param {intp} {schema['params'][intp]['min'] + 0.5}")
        exp.append(("type", intp))
    script += [f"700 param {imd} {md['default'] + (md['max_delta'] * 0.5 if md['default'] + md['max_delta'] * 0.5 <= md['max'] else -md['max_delta'] * 0.5)}",
               f"1000 step 0 1 {T} {D}", f"1200 param {ip} {p0['default']}", f"{1000 + D // 2} estop",
               f"{1000 + D // 2 + 100} param {ip} {p0['default']}", f"{1000 + D // 2 + 300} R",
               f"{1000 + D + 600} step 0 2 {T} {D}", f"{1000 + D + 900} " + cfg.get("preempt", f"sp {T / 2}"), f"{1000 + 2 * D + 1200} end"]
    exp += [("state", ip), ("state", ip)]
    crc2, fr2 = run(exe, script)
    rej = [dzstep.decode_param_reject(b) for _, k, i, b in fr2 if k == DATA and i == dzstep.REJECT_ID]
    got = [(r["reason"], r["index"]) for r in rej]
    c.ok(got == exp, f"param_reject 期望 {exp} 实际 {got}")
    c.ok(all(r["name"] == pnames[r["index"]][:16] for r in rej), "param_reject 名字不对")
    ack = [(i, b[0]) for _, k, i, b in fr2 if k == PARAM_ACK]
    c.ok([s for _, s in ack].count(dzstep.PARAM_ACK_REJECTED) == len(exp) and ack[len(exp) - 2][1] == 0,
         f"PARAM_ACK status 期望 {len(exp)} 个 5、合法的那次 0：{ack}")
    rs2 = results(fr2)
    ab = next((r for _, r in rs2 if r["iter"] == 1), None)
    c.ok(ab is not None and ab["aborted"] == 1 and ab["abort_cause"] == 1, f"实验中急停应 aborted=1 cause=1：{ab}")
    c.ok(ab is not None and ab["params_hash"] != py_crc, "改过 max_delta 内的合法值后 params_hash 应变化")
    hb2 = hbs(fr2)
    es_ms = 1000 + D // 2
    post = [(ms, st) for ms, st in hb2 if es_ms <= ms < es_ms + 300]
    c.ok(post and post[0][1] & (1 << 10) and post[0][0] - es_ms <= 5, f"急停沿心跳 ≤5 ms 且带 bit10：{post[:2]}")
    c.ok(post and not any(st & dzstep.HB_ITER_BUSY for _, st in post), "急停后心跳 bit17 必须为 0")
    ab_ms = next((ms for ms, r in rs2 if r["iter"] == 1), 10 ** 9)
    c.ok(post and ab_ms <= post[0][0], "aborted 结果应在急停沿心跳之前（同一拍）")
    pre_ = [st for ms, st in hb2 if 1100 <= ms < es_ms]
    c.ok(pre_ and all(st & dzstep.HB_ITER_BUSY for st in pre_), "急停前实验中 bit17 应为 1")
    pr = next((r for _, r in rs2 if r["iter"] == 2), None)
    c.ok(pr is not None and pr["aborted"] == 1 and pr["abort_cause"] == dzstep.ABORT_HOST_STOP, f"中途发设定值应 aborted cause=0x80：{pr}")
    st_acks = [a["status"] for _, a in acks(fr2)]
    c.ok(st_acks == ["started", "started"], f"开始应答 {st_acks}")
    # 急停中开始 → status estop
    _, fr3 = run(exe, pre + ["800 estop", "900 step 0 1 1 1000", "1000 end"])
    c.ok([a["status"] for _, a in acks(fr3)] == ["estop"], f"急停锁存中开始应回 estop：{acks(fr3)}")
    return c.fail, c.n, "; ".join(summary)


def main() -> int:
    apps = sys.argv[1:] or list(APPS)
    fail = 0
    for a in apps:
        f, n, s = test_app(a)
        fail += f
        print(f"  {a}: {n} 项，失败 {f}；{s}")
    if not fail:
        print(f"✓ #38 step_result / param_reject / bit17（{' '.join(apps)}）")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
