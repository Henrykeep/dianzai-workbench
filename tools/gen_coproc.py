#!/usr/bin/env python3
"""由协处理板 board.yaml（kind: coprocessor）生成主控侧的通道编解码代码。

  python3 tools/gen_coproc.py boards/jetson-nano-vision/board.yaml -o build/... [--prefix cp_vision]

生成 <prefix>.h / <prefix>.c：
  * 每个通道一个结构体 <prefix>_<ch>_t、通道号宏 <PREFIX>_CH_<CH>
  * <prefix>_<ch>_decode(const dzframe_t *, <prefix>_<ch>_t *)  —— 类型/编号/长度不符返回 false
  * <prefix>_<ch>_encode(const <prefix>_<ch>_t *, uint8_t seq, dzframe_t *)
  * 参数编号宏 <PREFIX>_PARAM_<NAME> 与取值范围表
协处理板一侧（Jetson Nano 的 Python、FPGA 的测试脚本）用 host/python/dzlink 的 pack_fields/unpack_fields
按同一份 board.yaml 打包，两端字段顺序因此永远一致。
"""
import argparse, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import boardlib  # noqa: E402

CT = {"u8": "uint8_t", "i8": "int8_t", "u16": "uint16_t", "i16": "int16_t", "u32": "uint32_t", "i32": "int32_t", "f32": "float"}
SZ = boardlib.TYPE_SIZE


def put(t, expr):
    if t == "f32":
        return f"dzframe_put_f32(f, {expr})"
    w = {1: "u8", 2: "u16", 4: "u32"}[SZ[t]]
    return f"dzframe_put_{w}(f, ({CT['u' + w[1:]]}){expr})"


def get(t, off):
    if t == "f32":
        return f"dzframe_get_f32(f, {off})"
    w = {1: "u8", 2: "u16", 4: "u32"}[SZ[t]]
    return f"({CT[t]})dzframe_get_{w}(f, {off})"


def gen(board, prefix, src):
    P = prefix.upper()
    cp = board["coprocessor"]
    h = [f"/* 自动生成，请勿手改。来源：{src}（{cp['device']}，协议 {cp['link']['protocol']}） */",
         f"#ifndef {P}_H", f"#define {P}_H", "#include <stdbool.h>", "#include <stdint.h>", '#include "dzframe.h"', ""]
    c = [f"/* 自动生成，请勿手改。来源：{src} */", f'#include "{prefix}.h"', ""]
    for ch in cp["channels"]:
        n, N = ch["name"], ch["name"].upper()
        size = sum(SZ[f["type"]] for f in ch["fields"])
        h.append(f"/* 通道 {ch['id']} {n}：{'协处理板 -> 主控' if ch['dir'] == 'to_host' else '主控 -> 协处理板'}，{size} 字节"
                 + (f"，约 {ch['rate_hz']} Hz" if "rate_hz" in ch else "") + " */")
        h.append(f"#define {P}_CH_{N} {ch['id']}u")
        h.append(f"#define {P}_{N}_SIZE {size}u")
        h.append("typedef struct {")
        for f in ch["fields"]:
            note = " ".join(x for x in (f.get("unit", ""), f.get("note", "")) if x)
            h.append(f"    {CT[f['type']]} {f['name']};" + (f"   /* {note} */" if note else ""))
        h.append(f"}} {prefix}_{n}_t;")
        h.append(f"bool {prefix}_{n}_decode(const dzframe_t *f, {prefix}_{n}_t *out);")
        h.append(f"bool {prefix}_{n}_encode(const {prefix}_{n}_t *in, uint8_t seq, dzframe_t *f);")
        h.append("")
        c.append(f"bool {prefix}_{n}_decode(const dzframe_t *f, {prefix}_{n}_t *out)")
        c.append("{")
        c.append(f"    if (!f || !out || f->kind != DZF_DATA || f->id != {P}_CH_{N} || f->len != {P}_{N}_SIZE) return false;")
        off = 0
        for fl in ch["fields"]:
            c.append(f"    out->{fl['name']} = {get(fl['type'], off)};")
            off += SZ[fl["type"]]
        c.append("    return true;")
        c.append("}")
        c.append(f"bool {prefix}_{n}_encode(const {prefix}_{n}_t *in, uint8_t seq, dzframe_t *f)")
        c.append("{")
        c.append(f"    if (!in || !f) return false;")
        c.append(f"    f->kind = DZF_DATA; f->id = {P}_CH_{N}; f->seq = seq; f->len = 0;")
        c.append("    return " + "\n        && ".join(put(fl["type"], f"in->{fl['name']}") for fl in ch["fields"]) + ";")
        c.append("}")
        c.append("")
    params = cp.get("params") or []
    for p in params:
        h.append(f"#define {P}_PARAM_{p['name'].upper()} {p['id']}u   /* {p['type']}" + (f" {p['note']}" if p.get("note") else "") + " */")
    h.append(f"#define {P}_N_PARAMS {len(params)}u")
    h.append(f"typedef struct {{ uint8_t id; const char *name; float min, max, def; }} {prefix}_param_info_t;")
    h.append(f"extern const {prefix}_param_info_t {prefix}_params[{max(len(params), 1)}];")
    c.append(f"const {prefix}_param_info_t {prefix}_params[{max(len(params), 1)}] = {{")
    for p in params:
        c.append(f'    {{ {p["id"]}u, "{p["name"]}", {float(p.get("min", -3.0e38))!r}f, {float(p.get("max", 3.0e38))!r}f, {float(p.get("default", 0))!r}f }},')
    if not params:
        c.append("    { 0u, 0, 0.0f, 0.0f, 0.0f },")
    c.append("};")
    h += ["", "#endif", ""]
    return "\n".join(h), "\n".join(c) + "\n"


def run(board_path: pathlib.Path, out: pathlib.Path, prefix: str) -> int:
    board = boardlib.load_board(board_path)
    rep = boardlib.check_board(board)
    if board.get("kind") != "coprocessor":
        rep.err("不是 kind: coprocessor 的板卡")
    for e in rep.errors:
        print(f"错误  {e}", file=sys.stderr)
    if rep.errors:
        print(f"✗ {board_path} 校验未通过", file=sys.stderr)
        return 1
    h, c = gen(board, prefix, board_path.as_posix())
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{prefix}.h").write_text(h, encoding="utf-8")
    (out / f"{prefix}.c").write_text(c, encoding="utf-8")
    print(f"✓ 已生成 {out}/{prefix}.{{h,c}}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board", type=pathlib.Path)
    ap.add_argument("-o", "--out", type=pathlib.Path, required=True)
    ap.add_argument("--prefix", default="cp")
    a = ap.parse_args()
    sys.exit(run(a.board, a.out, a.prefix))
