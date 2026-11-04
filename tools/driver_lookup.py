#!/usr/bin/env python3
"""查驱动：按器件名或类别查已拷进仓库的第三方驱动（路径、接口、许可、三个目标的编译状态）。
数据：firmware/drivers/catalog.yaml（资料/仓库搜索者的器件目录）+ firmware/drivers/compile_status.json
（tools/build_drivers.py 实测）+ glue/libdriver/glue_report.json，合成 firmware/drivers/driver_index.json（--build）。
用法：
  python3 tools/driver_lookup.py <器件名或类别> [--json]     # 不区分大小写，子串匹配 part / category
  python3 tools/driver_lookup.py --list [--json]
  python3 tools/driver_lookup.py --build                     # 重新生成 driver_index.json
  python3 tools/driver_lookup.py --check                     # driver_index.json 与生成结果一致
退出码：0 找到；1 没找到匹配的器件；2 参数错；3 缺依赖（索引文件 / PyYAML）。"""
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
D = ROOT / "firmware/drivers"
INDEX = D / "driver_index.json"
TARGETS = ("host", "stm32", "mspm0")


class ArgErr(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgErr(message)


def rel(p: pathlib.Path) -> str:
    return p.relative_to(ROOT).as_posix()


def locate(e: dict):
    """catalog 条目 → (仓库内路径, 编译单元名列表, 胶水文件)；没拷进来返回 (None, [], None)。"""
    b, p, part = e.get("backbone"), str(e.get("path") or ""), e["part"]
    if b == "libdriver":
        n = p.split("/")[1] if p.startswith("libdriver/") else p.split("/")[0]
        d = D / "libdriver" / n
        if d.is_dir():
            return d, [n], [rel(D / f"glue/libdriver/{n}_pal.c"), rel(D / "glue/ld_pal.c")]
    if b == "adi-no-os":
        d = D / "adi-no-os" / p
        if d.is_dir():
            sub = p[len("drivers/"):]
            return d, ["no-os/" + sub], [rel(D / "glue/no-os/no_os_pal.c")]
    other = {"ADS1256": ("other/ads1256", "ads1256"), "ST7735": ("other/st7735", "st7735"),
             "ILI9488 等大屏": ("other/ili9488", "ili9488"), "AD9850": ("ad983x", "ad983x(firework)")}
    if part in other:
        d = D / other[part][0]
        if d.is_dir():
            g = [rel(D / "ad983x/ad983x_port.c")] if part == "AD9850" else [rel(D / "glue/pal_hal_compat.h")]
            return d, [other[part][1]], g
    return None, [], None


def build_index() -> dict:
    try:
        import yaml
    except ImportError:
        raise FileNotFoundError("PyYAML（pip install pyyaml）")
    cat = yaml.safe_load((D / "catalog.yaml").read_text(encoding="utf-8"))
    st = json.loads((D / "compile_status.json").read_text(encoding="utf-8"))["drivers"]
    glue = {r["part"]: r for r in json.loads((D / "glue/libdriver/glue_report.json").read_text(encoding="utf-8"))}
    out = []
    for e in cat["entries"]:
        d, us, g = locate(e)
        units = {u: st[u] for u in us if u in st}
        # 目录型（如 potentiometer）有多个编译单元：同前缀的都算
        if d is not None and e.get("backbone") == "adi-no-os":
            pre = us[0] + "/"
            units.update({k: v for k, v in st.items() if k.startswith(pre)})
        comp = {t: ("pass" if units and all(v[t] == "pass" for v in units.values()) else ("fail" if units else "not_built")) for t in TARGETS}
        errs = sorted({v[t + "_error"] for v in units.values() for t in TARGETS if v.get(t + "_error")})
        n = us[0] if us else None
        out.append({
            "part": e["part"], "category": e.get("category"), "vendor": e.get("backbone"),
            "path": rel(d) if d is not None else None, "vendored": d is not None,
            "interface": {"hooks": e.get("hooks") or [], "glue": g or [],
                          "gpio_roles": glue.get(n, {}).get("gpio_roles", []), "unmapped": glue.get(n, {}).get("unmapped", [])},
            "license": e.get("license"), "upstream": e.get("repo"), "commit": e.get("commit"),
            "compile": comp, "compile_errors": errs, "note": e.get("status"),
        })
    return {"version": 1, "source": "firmware/drivers/catalog.yaml", "count": len(out),
            "vendored": sum(1 for x in out if x["vendored"]), "entries": out}


def dump(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def human(x: dict) -> str:
    c = " ".join(f"{t}:{x['compile'][t]}" for t in TARGETS)
    return f"{x['part']:<22} {x['category'] or '':<12} {x['path'] or '（未拷入）'}  [{x['license']}]  {c}"


def main(argv=None) -> int:
    ap = Parser(prog="driver_lookup.py", description="查驱动")
    ap.add_argument("query", nargs="?"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true"); ap.add_argument("--build", action="store_true"); ap.add_argument("--check", action="store_true")
    try:
        a = ap.parse_args(argv)
        if sum(bool(v) for v in (a.query, a.list, a.build, a.check)) != 1:
            raise ArgErr("要给一个器件名/类别，或 --list / --build / --check 之一")
    except ArgErr as e:
        msg = {"ok": False, "exit": 2, "reason": "bad_args", "message": str(e)}
        print(dump(msg) if "--json" in (argv or sys.argv[1:]) else f"参数错：{e}", end="" if "--json" in (argv or sys.argv[1:]) else "\n", file=sys.stdout if "--json" in (argv or sys.argv[1:]) else sys.stderr)
        return 2
    try:
        if a.build or a.check:
            doc = dump(build_index())
            if a.build:
                INDEX.write_text(doc, encoding="utf-8"); print(f"✓ {rel(INDEX)}"); return 0
            if not INDEX.exists() or INDEX.read_text(encoding="utf-8") != doc:
                print("driver_index.json 过期：python3 tools/driver_lookup.py --build", file=sys.stderr); return 1
            return 0
        if not INDEX.exists():
            raise FileNotFoundError(rel(INDEX))
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        if a.json: print(dump({"ok": False, "exit": 3, "reason": "missing_dependency", "missing": str(e)}), end="")
        else: print(f"缺少依赖：{e}", file=sys.stderr)
        return 3
    if a.list:
        hits = idx["entries"]
    else:
        q = a.query.lower()
        hits = [x for x in idx["entries"] if q in x["part"].lower() or q in str(x["category"]).lower()]
    if a.json:
        print(dump({"ok": bool(hits), "exit": 0 if hits else 1, "query": a.query, "count": len(hits), "results": hits}), end="")
    else:
        for x in hits: print(human(x))
        if not hits: print(f"没找到「{a.query}」", file=sys.stderr)
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
