#!/usr/bin/env python3
"""把 /workspace/refs/drivers/catalog.yaml 里的第三方驱动原样（逐字节）拷进 firmware/drivers/<vendor>/<part>/。
只拷驱动源码、接口头、例程、许可和 README；不改任何一行（ADS1256/ST7735/ILI9488 的 HAL→pal 替换由
tools/pal_patch_hal.py 另做，并把 diff 存在 PAL-CHANGES.patch）。每个来源写 SOURCE.md（仓库、提交、许可）。
用法：python3 tools/vendor_drivers.py [--refs /workspace/refs/drivers]（只在维护者机器上跑；产物进 git）"""
import argparse, pathlib, shutil, subprocess, sys, yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
DST = ROOT / "firmware/drivers"
LD_KEEP = ("src", "interface", "example", "LICENSE", "README.md")

def head(repo: pathlib.Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"

def copy(src: pathlib.Path, dst: pathlib.Path):
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)

def source_md(d: pathlib.Path, repo: str, commit: str, lic: str, note: str = ""):
    (d / "SOURCE.md").write_text(f"Source: {repo}@{commit}\nLicense: {lic}\nVendored verbatim by tools/vendor_drivers.py.{(' ' + note) if note else ''}\n", encoding="utf-8")

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--refs", default="/workspace/refs/drivers")
    a = ap.parse_args(); refs = pathlib.Path(a.refs)
    cat = yaml.safe_load((refs / "catalog.yaml").read_text(encoding="utf-8"))
    done = []
    # libdriver：目录名即 part（小写）
    ld_dirs = sorted(p for p in (refs / "libdriver").iterdir() if (p / "src").is_dir())
    ld_dirs += [refs / n for n in ("max7219", "tm1637") if (refs / n / "src").is_dir()]
    for p in ld_dirs:
        out = DST / "libdriver" / p.name
        for k in LD_KEEP:
            if (p / k).exists(): copy(p / k, out / k)
        source_md(out, f"https://github.com/libdriver/{p.name}", head(p), "MIT")
        done.append(("libdriver", p.name))
    # ADI no-OS：公共 include/api/util + 目录表里的每个驱动目录
    nos = refs / "adi-no-os"; nout = DST / "adi-no-os"; c = head(nos)
    for k in ("LICENSE_BSD", "COPYING", "include", "drivers/api", "util"):
        copy(nos / k, nout / k)
    for e in cat["entries"]:
        if e.get("backbone") == "adi-no-os" and (nos / e["path"]).is_dir():
            copy(nos / e["path"], nout / e["path"]); done.append(("adi-no-os", e["path"]))
    for f in ("display.c", "display.h"):   # ssd_1306 依赖的 no-OS 通用显示层
        if (nos / "drivers/display" / f).exists(): copy(nos / "drivers/display" / f, nout / "drivers/display" / f)
    source_md(nout, "https://github.com/analogdevicesinc/no-OS", c, "BSD-3-Clause (ADI), LICENSE_BSD")
    # 其他：ADS1256(eta-systems/ADS1255)、ST7735(afiskon)、ILI9XXX(maudeve-it)
    others = [("ads1256", refs / "ads1256", ("src", "inc", "LICENSE", "README.md"), "https://github.com/eta-systems/ADS1255", "Apache-2.0"),
              ("st7735", refs / "st7735", ("st7735", "LICENSE", "README.md"), "https://github.com/afiskon/stm32-st7735", "MIT"),
              ("ili9488", refs / "ili9xxx", ("1-HOWTO", "LICENSE", "README.md"), "https://github.com/maudeve-it/ILI9XXX-XPT2046-STM32", "MIT")]
    for name, r, keep, url, lic in others:
        if not r.is_dir(): print(f"缺少 {r}", file=sys.stderr); continue
        out = DST / "other" / name
        for k in keep:
            if (r / k).exists(): copy(r / k, out / k)
        source_md(out, url, head(r), lic); done.append(("other", name))
    print(f"vendored {len(done)} drivers")
    return 0

if __name__ == "__main__":
    sys.exit(main())
