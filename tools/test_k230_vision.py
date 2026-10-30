#!/usr/bin/env python3
"""K230 视觉脚本库（缺口第 5 项）自检：打过补丁的脚本里每个 _dz.send(ch, [...]) 的通道号和字段类型顺序
必须与 boards/k230-vision/board.yaml 一致（两端字段顺序靠这个保证）；并用 host/k230/dzsend.py 实际编一帧、
用 host/python/dzlink 解回来。脚本本体依赖 CanMV 的 media 模块，PC 上不执行。"""
import ast, importlib.util, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "host/python"))
import boardlib  # noqa: E402
from dzlink.protocol import encode, pack_fields  # noqa: E402

spec = importlib.util.spec_from_file_location("dzsend", ROOT / "host/k230/dzsend.py")
K = importlib.util.module_from_spec(spec)
spec.loader.exec_module(K)


def main():
    board = boardlib.load_board(ROOT / "boards/k230-vision/board.yaml")
    chans = {c["id"]: c for c in board["coprocessor"]["channels"]}
    errs, seen = [], set()
    files = sorted((ROOT / "third_party/vendored").glob("k230_*/*.py"))
    assert files, "没有 K230 脚本"
    for f in files:
        src = f.read_text(encoding="utf-8")
        ast.parse(src)
        for m in re.finditer(r"_dz\.send\((\d+), \[(.*?)\]\)\s*\n", src, re.S):
            ch = int(m.group(1))
            types = re.findall(r'\("(u8|i8|u16|i16|u32|i32|f32)",', m.group(2))
            want = [x["type"] for x in chans.get(ch, {}).get("fields", [])]
            if types != want:
                errs.append(f"{f.name}: 通道 {ch} 字段类型 {types} ≠ board.yaml {want}")
            seen.add(ch)
            if "DZ_FRAME = True" not in src:
                errs.append(f"{f.name}: 有 _dz.send 但没有 DZ_FRAME 开关")
    if seen != set(chans):
        errs.append(f"board.yaml 通道 {sorted(set(chans) - seen)} 没有任何脚本在发")
    for ch, c in chans.items():                                   # dzsend 编出来的帧 == dzlink 参考实现
        vals = {x["name"]: (1 if x["type"].startswith("u") else -5) for x in c["fields"]}
        out = []
        K.DzSend(out.append).send(ch, [(x["type"], vals[x["name"]]) for x in c["fields"]])
        if out[0] != encode(0, ch, 0, pack_fields(c["fields"], vals)):
            errs.append(f"通道 {ch}: dzsend 与 dzlink 编码不一致")
    for e in errs:
        print("✗", e)
    if errs:
        sys.exit(1)
    print(f"k230 视觉脚本 ok：{len(files)} 个脚本，通道 {sorted(seen)}")


if __name__ == "__main__":
    main()
