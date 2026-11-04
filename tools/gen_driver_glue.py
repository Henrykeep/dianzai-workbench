#!/usr/bin/env python3
"""从每个 libdriver 驱动的 interface/driver_<part>_interface.h 生成 pal 胶水
firmware/drivers/glue/libdriver/<part>_pal.{c,h}：按函数名后缀把回调转到 glue/ld_pal.c 的 ld_* 帮手。
原驱动文件一行不改。认不出的回调生成“返回 1”的桩，并记进 glue/libdriver/glue_report.json（unmapped）。
用法：python3 tools/gen_driver_glue.py [--check]（--check：生成结果与仓库里不一致就退出 1）"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LD = ROOT / "firmware/drivers/libdriver"
OUT = ROOT / "firmware/drivers/glue/libdriver"
PROTO = re.compile(r"^\s*((?:uint8_t|uint16_t|void)\s+([a-z0-9_]+)_interface_([a-z0-9_]+)\s*\(([^;{]*?)\))\s*;", re.M | re.S)
HDR = "/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */\n"


def params(sig: str) -> list[tuple[str, str]]:
    sig = " ".join(sig.split())
    if sig in ("void", ""):
        return []
    out = []
    for p in sig.split(","):
        p = p.strip(); m = re.match(r"(.*?)([A-Za-z_][A-Za-z0-9_]*)$", p)
        out.append((m.group(1).strip(), m.group(2)))
    return out


def time_fields(part: str, typ: str) -> str | None:
    t = typ.replace("*", "").strip()
    for h in (LD / part / "src").glob("*.h"):
        m = re.search(r"typedef struct \w+\s*\{([^{}]*)\}\s*" + re.escape(t) + r"\s*;", h.read_text(encoding="utf-8", errors="replace"), re.S)
        if m:
            names = re.findall(r"\b(\w+)\s*;", re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S))
            return ",".join(names)
    return None


def body(part: str, fn: str, ps: list[tuple[str, str]], ret: str, roles: list[str]) -> tuple[str, bool]:
    """返回（函数体，是否已映射）。"""
    n = [p[1] for p in ps]
    B = f"g_{part}_bind"
    def gpio_role(name):
        r = name.upper()
        if r not in roles: roles.append(r)
        return f"{B}.gpio[LD_{part.upper()}_GPIO_{r}]"
    if fn == "debug_print":
        return f"    __builtin_va_list ap;\n    __builtin_va_start(ap, {n[0]});\n    ld_debug_vprint({n[0]}, ap);\n    __builtin_va_end(ap);\n", True
    if fn in ("delay_ms", "delay_us"):
        return f"    ld_{fn}({n[0]});\n", True
    if fn == "disable_irq": return "    ld_irq_disable();\n", True
    if fn == "enable_irq": return "    ld_irq_enable();\n", True
    if re.fullmatch(r"(.+_)?(init|deinit)", fn) or fn in ("init", "deinit"):
        g = re.fullmatch(r"(.+)_gpio_(init|deinit)", fn)
        if g: gpio_role(g.group(1))
        return "    return 0;\n", True
    if "callback" in fn:
        return "".join(f"    (void){x};\n" for x in n), True
    if fn == "timestamp_read":
        f = time_fields(part, ps[0][0]) or ""
        if f == "s,us": return f"    if (!{n[0]}) return 1;\n    ld_time_now(&{n[0]}->s, &{n[0]}->us, 0, 0);\n    return 0;\n", True
        if f == "microsecond,millisecond": return f"    if (!{n[0]}) return 1;\n    ld_time_now(0, 0, &{n[0]}->microsecond, &{n[0]}->millisecond);\n    return 0;\n", True
        return None, False
    if fn in ("iic_read", "iic_write") and len(n) == 4:
        return f"    return ld_{fn}({B}.i2c, {n[0]}, {n[1]}, {n[2]}, {n[3]});\n", True
    if fn in ("iic_read_cmd", "iic_write_cmd") and len(n) == 3:
        return f"    return ld_{fn}({B}.i2c, {n[0]}, {n[1]}, {n[2]});\n", True
    if fn in ("iic_read_address16", "iic_write_address16", "iic_scl_read_address16") and len(n) == 4:
        k = "read16" if "read" in fn else "write16"
        return f"    return ld_iic_{k}({B}.i2c, {n[0]}, {n[1]}, {n[2]}, {n[3]});\n", True
    if fn == "spi_read" and len(n) == 3:
        return f"    uint8_t h = (uint8_t){n[0]};\n    return ld_spi_frame({B}.spi, &h, 1, 0, 0, {n[1]}, {n[2]});\n", True
    if fn == "spi_write" and len(n) == 3:
        return f"    uint8_t h = (uint8_t){n[0]};\n    return ld_spi_frame({B}.spi, &h, 1, {n[1]}, {n[2]}, 0, 0);\n", True
    if fn == "spi_read_address16" and len(n) == 3:
        return f"    uint8_t h[2] = {{ (uint8_t)({n[0]} >> 8), (uint8_t)({n[0]} & 0xFF) }};\n    return ld_spi_frame({B}.spi, h, 2, 0, 0, {n[1]}, {n[2]});\n", True
    if fn == "spi_write_cmd" and len(n) == 2:
        return f"    return ld_spi_frame({B}.spi, 0, 0, {n[0]}, {n[1]}, 0, 0);\n", True
    if fn == "spi_read_cmd" and len(n) == 2:
        return f"    return ld_spi_frame({B}.spi, 0, 0, 0, 0, {n[0]}, {n[1]});\n", True
    if fn == "spi_transmit" and len(n) == 3:
        return f"    return ld_spi_transmit({B}.spi, {n[0]}, {n[1]}, {n[2]});\n", True
    if fn == "spi_write_read" and len(n) == 4:
        return (f"    if ({n[1]} > 64u || {n[3]} > 64u) return 1;\n"
                f"    return ld_spi_frame({B}.spi, 0, 0, {n[0]}, (uint16_t){n[1]}, {n[2]}, (uint16_t){n[3]});\n"), True
    if fn == "spi_qspi_write_read" and len(n) == 14:
        (ins, il, adr, al, alen, alt, altl, altlen, dummy, ib, ilen, ob, olen, dl) = n
        return (f"    uint8_t h[12]; uint16_t k = 0; uint8_t i;\n"
                f"    if (({il} > 1u) || ({alen} && {al} > 1u) || ({altlen} && {altl} > 1u) || {dl} > 1u || {alen} > 4u || {altlen} > 4u || ({dummy} % 8u)) return 1;\n"
                f"    if ({il}) h[k++] = {ins};\n"
                f"    for (i = 0; i < {alen}; i++) h[k++] = (uint8_t)({adr} >> (8u * ({alen} - 1u - i)));\n"
                f"    for (i = 0; i < {altlen}; i++) h[k++] = (uint8_t)({alt} >> (8u * ({altlen} - 1u - i)));\n"
                f"    for (i = 0; i < {dummy} / 8u && k < sizeof h; i++) h[k++] = 0xFF;\n"
                f"    if ({ilen} > 64u || {olen} > 64u) return 1;\n"
                f"    return ld_spi_frame({B}.spi, h, k, {ib}, (uint16_t){ilen}, {ob}, (uint16_t){olen});\n"), True
    if fn == "uart_write" and len(n) == 2:
        return f"    return ld_uart_write({B}.uart, {n[0]}, {n[1]});\n", True
    if fn == "uart_read" and len(n) == 2:
        return f"    return ld_uart_read({B}.uart, {n[0]}, {n[1]});\n", True
    if fn == "adc_read" and len(n) == 2:
        return f"    uint16_t i, v;\n    if (!{n[0]}) return 1;\n    for (i = 0; i < {n[1]}; i++) {{ if (ld_adc_read({B}.adc, &v)) return 1; {n[0]}[i] = v; }}\n    return 0;\n", True
    if fn == "uart_flush":
        return f"    return ld_uart_flush({B}.uart);\n", True
    m = re.fullmatch(r"(?:(.+)_gpio_|(.+)_)?(write|read)", fn)
    if m and len(n) == 1:
        role = m.group(1) or m.group(2) or "data"
        return f"    return ld_gpio_{m.group(3)}({gpio_role(role)}, {n[0]});\n", True
    return None, False


def gen(part: str):
    hs = list((LD / part / "interface").glob("driver_*_interface.h"))
    if not hs:
        return None
    text = hs[0].read_text(encoding="utf-8", errors="replace")
    roles: list[str] = []; funcs = []; unmapped = []
    for m in PROTO.finditer(text):
        decl, pre, fn, sig = m.group(1), m.group(2), m.group(3), m.group(4)
        ret = decl.split()[0]
        ps = params(re.sub(r"\s*,\s*\.\.\.", "", sig))
        b, ok = body(part, fn, ps, ret, roles)
        if not ok:
            unmapped.append(fn)
            b = "".join(f"    (void){x[1]};\n" for x in ps) + ("    return 1;   /* 未映射：见 glue_report.json */\n" if ret != "void" else "")
        weak = "__attribute__((weak)) " if "callback" in fn else ""
        funcs.append(f"{weak}{' '.join(decl.split())}\n{{\n{b}}}\n")
    if len(roles) > 8: raise SystemExit(f"{part}: gpio 角色超过 8 个")
    P = part.upper()
    h = HDR + f"#ifndef {P}_PAL_H\n#define {P}_PAL_H\n#include \"ld_pal.h\"\n\n"
    h += "".join(f"#define LD_{P}_GPIO_{r} {i}u\n" for i, r in enumerate(roles))
    h += f"\n/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_{P}_GPIO_*]）；在调用 {part}_init 之前调用一次。 */\nvoid {part}_pal_bind(const ld_pal_bind_t *b);\n\n#endif\n"
    c = HDR + f"#include <stdint.h>\n#include \"{hs[0].name}\"\n#include \"{part}_pal.h\"\n\n"
    c += f"static ld_pal_bind_t g_{part}_bind = LD_PAL_BIND_NONE;\n\nvoid {part}_pal_bind(const ld_pal_bind_t *b) {{ if (b) g_{part}_bind = *b; }}\n\n"
    c += "\n".join(funcs)
    return h, c, {"part": part, "gpio_roles": [r.lower() for r in roles], "functions": len(funcs), "unmapped": unmapped}


def main() -> int:
    check = "--check" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    rep, bad = [], []
    for d in sorted(p for p in LD.iterdir() if p.is_dir()):
        g = gen(d.name)
        if not g: continue
        h, c, r = g; rep.append(r)
        for name, txt in ((f"{d.name}_pal.h", h), (f"{d.name}_pal.c", c)):
            f = OUT / name
            if check:
                if not f.exists() or f.read_text(encoding="utf-8") != txt: bad.append(name)
            else:
                f.write_text(txt, encoding="utf-8")
    rj = json.dumps(rep, ensure_ascii=False, indent=1) + "\n"
    if check:
        if (OUT / "glue_report.json").read_text(encoding="utf-8") != rj: bad.append("glue_report.json")
        if bad: print("胶水与生成结果不一致，请运行 python3 tools/gen_driver_glue.py：", *bad); return 1
        return 0
    (OUT / "glue_report.json").write_text(rj, encoding="utf-8")
    um = [r for r in rep if r["unmapped"]]
    print(f"glue: {len(rep)} drivers, {sum(r['functions'] for r in rep)} callbacks, {len(um)} with unmapped:", {r['part']: r['unmapped'] for r in um})
    return 0


if __name__ == "__main__":
    sys.exit(main())
