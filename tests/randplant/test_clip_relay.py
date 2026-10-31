#!/usr/bin/env python3
"""#103 量程钳位 + 随机对象的 0x7C 继电接管（make test）。
  A. plant: 声明的不稳定对象（不写 range）：plantmodel 生成的仿真 C 在默认量程内钳住、不发散，钳住时置 DZCTL_HB_SENSOR_SAT；
     写了 plant.range 就钳在 range。
  B. randplant 随机对象（RANDPLANT_SEEDS，含一个改成不稳定极点的 seed）：
     - 不稳定：继电给常值输入一直推 → 遥测 y 始终在 ±sensor_range/2 内，心跳 bit18 置位；
     - 稳定：上电静止时（bias≈工作点）0x7C 开始应答 0，继电期间 u 在 bias±amp 两档切换、y 随之振荡，停止后回到原控制器；急停中开始应答 2。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import plantmodel  # noqa: E402
import randplant  # noqa: E402

HOME = ROOT / "build" / "randplant-clip"
os.environ["DZBENCH_HOME"] = str(HOME)
import test_step_result as tsr  # noqa: E402

HB_SENSOR_SAT = 1 << 18
RELAY_ID = 0x7C
fail = 0


def ok(cond, msg):
    global fail
    print(("✓ " if cond else "✗ ") + msg)
    fail += not cond


def part_a():
    harness = r"""
#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
static uint32_t g_flags;
void dzctl_set_flags(uint32_t m, bool on) { if (on) g_flags |= m; else g_flags &= ~m; }
float sim_plant_step(float u);
int main(void) { float y = 0, ymax = -1e30f, ymin = 1e30f; unsigned sat_n = 0;
  for (int i = 0; i < 20000; i++) { y = sim_plant_step(i < 15000 ? 1.0f : -1.0f); if (y > ymax) ymax = y; if (y < ymin) ymin = y; sat_n += (g_flags >> 18) & 1u; }
  printf("%g %g %g %u %u\n", y, ymin, ymax, sat_n, (unsigned)((g_flags >> 18) & 1u)); return 0; }
"""
    cases = [({"order": 1, "gain": -2.0, "tau_s": [-0.5], "saturation": 1.0, "unit": "kPa", "y0": 100.0,
               "estimate": "coarse", "sample_s": 0.001}, None),
             ({"order": 1, "gain": -2.0, "tau_s": [-0.5], "saturation": 1.0, "unit": "kPa", "y0": 100.0,
               "range": {"min": 0.0, "max": 150.0}, "estimate": "coarse", "sample_s": 0.001}, (0.0, 150.0))]
    with tempfile.TemporaryDirectory() as d:
        for i, (pl, want) in enumerate(cases):
            ok(not plantmodel.validate(pl), f"plant 声明合法 {plantmodel.validate(pl)}")
            lo, hi = plantmodel.y_range(pl)
            if want:
                ok((lo, hi) == want, f"plant.range 优先：{(lo, hi)}")
            else:
                ok(lo < 100.0 < hi and hi - lo < 1e4, f"默认量程按对象量级：{(lo, hi)}")
            src = pathlib.Path(d) / f"p{i}.c"
            src.write_text(plantmodel.gen_c(pl) + harness, encoding="utf-8")
            exe = pathlib.Path(d) / f"p{i}"
            subprocess.run(["cc", "-std=c11", "-O1", "-Ifirmware/proto/dzctl", "-Ifirmware/common", "-Ifirmware/proto/dzframe",
                            *[f"-I{q.relative_to(ROOT)}" for q in sorted(ROOT.glob("firmware/*/*")) if q.is_dir()],
                            str(src), "-lm", "-o", str(exe)], cwd=ROOT, check=True)
            y, ymin, ymax, sat_n, flag_end = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split()
            y, ymin, ymax = float(y), float(ymin), float(ymax)
            ok(lo - 1e-3 <= ymin and ymax <= hi + 1e-3, f"不稳定对象 y∈[{ymin:.3g}, {ymax:.3g}] ⊂ 量程 [{lo:.3g}, {hi:.3g}]")
            ok(int(sat_n) > 1000, f"钳住期间置 bit18（{sat_n} 拍）")
            # 反向推 5 s：不积分饱和 → 状态停在边界，反向输入能把它拉回来（不会卡死在边界上）
            ok(int(flag_end) == 1 or ymin < hi - 1e-3, "反向输入后离开过边界或仍在另一侧边界")


def unstable(p: dict, rng_k: float) -> dict:
    q = dict(p)
    tau = 0.05 + 0.1 * rng_k
    k = 3.0 * 0.5 * p["sensor_range"] / max(p["sat"], 1e-6)   # 满幅输入的“稳态”远超量程 → 必然钳住
    q["ss"] = plantmodel.discretize(plantmodel.continuous({"gain": -k, "tau_s": [-tau]}), p["dt_s"])
    q["name"] = p["name"] + "-unstable"
    return q


def relay_acks(fr):
    return [b[0] for _, k, i, b in fr if k == tsr.DATA and i == RELAY_ID and len(b) == 1]


def part_b():
    seeds = [int(s) for s in os.environ.get("RANDPLANT_SEEDS", "3 7 10").split()]
    shutil.rmtree(HOME, ignore_errors=True)
    plants = [randplant.gen(s) for s in seeds] + [unstable(randplant.gen(seeds[0] + 100), 0.37)]
    for p in plants:
        out = HOME / "projects" / p["name"]
        randplant.write(p, out)
        exe, schema = tsr.build(p["name"])
        half = 0.5 * p["sensor_range"]
        amp = round(0.3 * p["sat"], 4)
        tag = f"{p['name']}（{p['unit']}，sat={p['sat']}，量程 ±{half}）"
        if p["name"].endswith("-unstable"):
            # 滞环比量程还大 → 继电保持在一侧 = 常值输入，不稳定对象一路往外推
            _, fr = tsr.run(exe, [f"500 relay 0 {amp} {10 * p['sensor_range']} 3", "4000 end"])
            tel = tsr.telem(schema, fr)
            ys = [t["y"] for t in tel]
            ok(relay_acks(fr) == [0], f"{tag} 继电开始应答 0：{relay_acks(fr)}")
            ok(max(abs(v) for v in ys) <= half * 1.0001 + 4 * p["noise_std"], f"{tag} y 始终在量程内（max |y| = {max(abs(v) for v in ys):.4g}）")
            ok(any(st & HB_SENSOR_SAT for _, st in tsr.hbs(fr)), f"{tag} 到边界后心跳 bit18 SENSOR_SAT 置位")
            continue
        _, fr = tsr.run(exe, [f"60 relay 0 {amp} 0 6", "8500 estop", f"8700 relay 0 {amp} 0 1", "9000 end"])
        tel = tsr.telem(schema, fr)
        ok(relay_acks(fr) == [0, 2], f"{tag} 0x7C 应答 [0 开始, 2 急停中拒绝]：{relay_acks(fr)}")
        win = [t for t in tel if 150 <= t["t_ms"] <= 5900]
        us = sorted({round(t["u"], 4) for t in win})
        ok(len(us) == 2 and abs(us[1] - us[0] - 2 * min(amp, p["sat"])) < 1e-3, f"{tag} 继电期间 u 只取 bias±amp 两档：{us[:6]}")
        ys = [t["y"] for t in win]
        ok(max(ys) - min(ys) > 4 * p["noise_std"], f"{tag} 继电期间 y 振荡（峰峰 {max(ys) - min(ys):.4g}）")
        after = [t for t in tel if 6300 <= t["t_ms"] <= 8400]
        ok(len({round(t["u"], 4) for t in after}) > 2 or not after, f"{tag} 继电超时后回到原控制器（u 不再两档）")
        ok(all(abs(t["y"]) <= half * 1.0001 + 4 * p["noise_std"] for t in tel), f"{tag} y 在量程内")


if __name__ == "__main__":
    part_a()
    part_b()
    print(f"{'✗' if fail else '✓'} clip/relay：失败 {fail}")
    sys.exit(1 if fail else 0)
