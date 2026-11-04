#!/usr/bin/env python3
"""编译全部原样拷进来的第三方驱动 + 芯台胶水，三个目标：host（gcc）、stm32（arm-none-eabi，Cortex-M4）、
mspm0（arm-none-eabi，Cortex-M0+）。只编到 .o（驱动是库，不单独链接），记录每个驱动在每个目标上是否通过。
结果写 firmware/drivers/compile_status.json（--write）；不加 --write 时与该文件比对，不一致退出 1。
退出码：0 全部与记录一致；1 不一致；3 缺编译器（arm-none-eabi-gcc / gcc）。
用法：python3 tools/build_drivers.py [--write] [--only <name>] [-j N]"""
import argparse, concurrent.futures as cf, json, os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
D = ROOT / "firmware/drivers"
STATUS = D / "compile_status.json"
COMMON_INC = [ROOT / "firmware/pal", ROOT / "firmware/common", D / "glue", D / "glue/libdriver", D / "glue/no-os"]
TARGETS = {
    "host": ["gcc", "-std=gnu11"],
    "stm32": ["arm-none-eabi-gcc", "-std=gnu11", "-mcpu=cortex-m4", "-mthumb", "-mfloat-abi=hard", "-mfpu=fpv4-sp-d16", "--specs=nano.specs"],
    "mspm0": ["arm-none-eabi-gcc", "-std=gnu11", "-mcpu=cortex-m0plus", "-mthumb", "--specs=nano.specs"],
}
FLAGS = ["-Os", "-c", "-w", "-ffunction-sections"]


def units():
    """(name, vendor, sources, include dirs)"""
    out = []
    for p in sorted((D / "libdriver").iterdir()):
        if not (p / "src").is_dir(): continue
        srcs = sorted((p / "src").glob("*.c")) + [D / f"glue/libdriver/{p.name}_pal.c", D / "glue/ld_pal.c"]
        out.append((p.name, "libdriver", srcs, [p / "src", p / "interface"]))
    nos = D / "adi-no-os"
    api = [nos / "drivers/api" / f for f in ("no_os_spi.c", "no_os_i2c.c", "no_os_gpio.c", "no_os_uart.c", "no_os_irq.c")]
    util = sorted((nos / "util").glob("*.c"))
    for p in sorted(x for x in (nos / "drivers").rglob("*") if x.is_dir() and any(x.glob("*.c")) and "api" not in x.parts):
        rel = p.relative_to(nos / "drivers").as_posix()
        if rel == "display": continue
        extra = [nos / "drivers/display"] if rel.startswith("display/") else []
        # iio_*.c 是可选的 IIO 上位机接口层（要整个 no-OS iio 框架），原样保留但不进编译
        srcs = sorted(x for x in p.glob("*.c") if not x.name.startswith("iio_")) + [s for e in extra for s in sorted(e.glob("*.c"))] + api + util + [D / "glue/no-os/no_os_pal.c"]
        common = [p.parent / "common"] if (p.parent / "common").is_dir() else []
        out.append(("no-os/" + rel, "adi-no-os", srcs, [p, nos / "include", *extra, *common]))
    oth = D / "other"
    for name, sub, inc in (("ads1256", ["src"], ["inc"]), ("st7735", ["st7735/st7735"], ["st7735/st7735"]), ("ili9488", ["1-HOWTO"], ["1-HOWTO"])):
        if not (oth / name).is_dir(): continue
        srcs = [s for x in sub for s in sorted((oth / name / x).glob("*.c")) if not s.name.endswith("_test.c") and "touch" not in s.name]
        out.append((name, "other", srcs, [oth / name / x for x in inc]))
    ad = D / "ad983x"
    if ad.is_dir():
        out.append(("ad983x(firework)", "firework", sorted(ad.glob("*.c")), [ad]))
    return out


def build(unit, tgt, tmp):
    name, _, srcs, incs = unit
    cc = TARGETS[tgt]
    args = [f"-I{i}" for i in [*incs, *COMMON_INC]]
    for s in srcs:
        o = pathlib.Path(tmp) / f"{tgt}_{abs(hash((name, str(s))))}.o"
        r = subprocess.run([*cc, *FLAGS, *args, str(s), "-o", str(o)], capture_output=True, text=True)
        if r.returncode:
            first = next((l for l in r.stderr.splitlines() if "error" in l), r.stderr.strip()[:200])
            return False, f"{pathlib.Path(s).relative_to(ROOT).as_posix()}: {first.split('error:', 1)[-1].strip()}"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true"); ap.add_argument("--only"); ap.add_argument("-j", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    for c in {t[0] for t in TARGETS.values()}:
        if not shutil.which(c):
            print(f"缺少编译器 {c}", file=sys.stderr); return 3
    us = [u for u in units() if not a.only or u[0] == a.only]
    res = {}
    with tempfile.TemporaryDirectory() as tmp, cf.ThreadPoolExecutor(a.j) as ex:
        fut = {(u[0], t): ex.submit(build, u, t, tmp) for u in us for t in TARGETS}
        for u in us:
            res[u[0]] = {"vendor": u[1]}
            for t in TARGETS:
                ok, why = fut[(u[0], t)].result()
                res[u[0]][t] = "pass" if ok else "fail"
                if why: res[u[0]][t + "_error"] = why
    summary = {t: sum(1 for r in res.values() if r[t] == "pass") for t in TARGETS}
    doc = {"total": len(res), "pass": summary, "drivers": res}
    txt = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    print(f"{len(res)} drivers; pass: " + ", ".join(f"{t} {n}" for t, n in summary.items()))
    if a.only: return 0
    if a.write:
        STATUS.write_text(txt, encoding="utf-8"); return 0
    old = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    if old != doc:
        diff = [k for k in res if old.get("drivers", {}).get(k) != res[k]]
        print("与 firmware/drivers/compile_status.json 不一致：", diff[:20], file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
