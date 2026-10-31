#!/usr/bin/env python3
"""keil_inject.py —— 把工作台模块注入 Keil MDK 工程（.uvprojx），可重复运行（幂等）。

做三件事（每个 <Target> 都做）：
  1. 删除所有组名以 "dz/" 开头的旧组，再按当前模块列表重新添加（dz/<模块名>，一个模块一个组）；
  2. C/C++（TargetArmAds/Cads）的 IncludePath 追加缺少的模块目录（已有的不重复、不改顺序）；
  3. Define 追加缺少的宏。
路径一律写成相对 .uvprojx 所在目录的相对路径（Keil 的约定）。不改其它任何内容，原文件先备份为 .uvprojx.bak。

用法：
  keil_inject.py X.uvprojx --root <工作台根> --module firmware/algo/pid --module firmware/proto/dzframe \\
      [--extra-src build/<板>/gen/board_gen.c] [--extra-inc build/<板>/gen] [--define DZ_CM_TIM_TIMEBASE] [--dry-run]
  keil_inject.py --selftest
【已实测】在用户两个真实工程（USART.uvprojx、Bldc.uvprojx）的副本上注入并重复注入（结果不变）。
【未验证】注入后的工程在 Keil µVision 里打开/编译（本机无 Keil）。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import boardlib  # noqa: E402
GROUP_PREFIX = "dz/"
FILE_TYPE = {".c": 1, ".s": 2, ".h": 5}


def rel(p: pathlib.Path, base: pathlib.Path) -> str:
    """工程文件里写的路径：能相对就相对（Keil 习惯反斜杠）；Windows 上跨盘符（D: 工程、C: 仓库）没有相对路径，退回绝对路径（正斜杠，Keil 也认）。"""
    try:
        return os.path.relpath(p.resolve(), base.resolve()).replace("/", "\\")
    except ValueError:
        return p.resolve().as_posix()


def group_xml(name: str, files: list[str], indent: str) -> str:
    out = [f"{indent}<Group>", f"{indent}  <GroupName>{name}</GroupName>", f"{indent}  <Files>"]
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        out += [f"{indent}    <File>", f"{indent}      <FileName>{os.path.basename(f.replace(chr(92), '/'))}</FileName>",
                f"{indent}      <FileType>{FILE_TYPE.get(ext, 5)}</FileType>", f"{indent}      <FilePath>{f}</FilePath>",
                f"{indent}    </File>"]
    out += [f"{indent}  </Files>", f"{indent}</Group>"]
    return "\n".join(out)


def merge_list(cur: str, add: list[str], sep: str) -> str:
    items = [x for x in cur.split(sep) if x.strip()] if cur.strip() else []
    norm = {x.strip().replace("/", "\\").rstrip("\\").lower() for x in items}
    for a in add:
        if a.replace("/", "\\").rstrip("\\").lower() not in norm:
            items.append(a)
            norm.add(a.lower())
    return sep.join(items)


def inject(text: str, groups: dict[str, list[str]], incs: list[str], defines: list[str]) -> str:
    # 1. 删除旧 dz/ 组
    text = re.sub(r"\n[ \t]*<Group>\s*<GroupName>" + re.escape(GROUP_PREFIX) + r"[^<]*</GroupName>.*?</Group>", "",
                  text, flags=re.S)

    # 2/3. 每个 Target 的 TargetArmAds/Cads/VariousControls
    def fix_cads(m: re.Match) -> str:
        blk = m.group(0)
        blk = re.sub(r"<IncludePath>(.*?)</IncludePath>",
                     lambda k: f"<IncludePath>{merge_list(k.group(1), incs, ';')}</IncludePath>", blk, count=1, flags=re.S)
        blk = re.sub(r"<Define>(.*?)</Define>",
                     lambda k: f"<Define>{merge_list(k.group(1), defines, ',')}</Define>", blk, count=1, flags=re.S)
        return blk
    text, n = re.subn(r"<TargetArmAds>.*?<Cads>.*?</Cads>", fix_cads, text, flags=re.S)
    if n == 0:
        raise SystemExit("✗ 没找到 <TargetArmAds><Cads>：这不是 ARM 目标的 .uvprojx？")

    # 加新组：插在每个 </Groups> 前
    def add_groups(m: re.Match) -> str:
        indent = m.group(1) + "  "
        g = "\n".join(group_xml(k, v, indent) for k, v in groups.items())
        return f"\n{g}\n{m.group(1)}</Groups>"
    text, n = re.subn(r"\n([ \t]*)</Groups>", add_groups, text)
    if n == 0:
        raise SystemExit("✗ 没找到 <Groups>")
    return text


def inject_scatter(text: str, sct: str) -> str:
    """掉电保存区：Linker 页改用仓库生成的分散加载文件（tools/gen_ide_nvm.py），关掉“Use Memory Layout from Target Dialog”。"""
    def fix(m: re.Match) -> str:
        blk = re.sub(r"<umfTarg>\d</umfTarg>", "<umfTarg>0</umfTarg>", m.group(0), count=1)
        if "<ScatterFile>" in blk:
            return re.sub(r"<ScatterFile>.*?</ScatterFile>", lambda _: f"<ScatterFile>{sct}</ScatterFile>", blk, count=1, flags=re.S)
        return blk.replace("</LDads>", f"<ScatterFile>{sct}</ScatterFile></LDads>")
    return re.sub(r"<LDads>.*?</LDads>", fix, text, flags=re.S)


def nvm_for_board(root: pathlib.Path, board: str) -> tuple[list[str], str | None]:
    """board.yaml mcu.nvm_kb > 0 → (DZ_NVM_KB/DZ_FLASH_KB 宏, 仓库里的 dz_nvm.sct)；没开 → ([], None)。"""
    import yaml
    mcu = yaml.safe_load((boardlib.board_dir(board, root) / "board.yaml").read_text(encoding="utf-8")).get("mcu", {})
    n = int(mcu.get("nvm_kb", 0) or 0)
    sct = boardlib.board_dir(board, root) / "keil" / "dz_nvm.sct"
    if not n:
        return [], None
    if not sct.exists():
        raise SystemExit(f"✗ {sct} 不存在：先跑 tools/gen_ide_nvm.py")
    return [f"DZ_NVM_KB={n}u", f"DZ_FLASH_KB={int(mcu['flash_kb'])}u"], str(sct)


def plan(uv: pathlib.Path, root: pathlib.Path, modules: list[str], extra_src: list[str], extra_inc: list[str]):
    base = uv.parent
    groups, incs = {}, []
    for m in modules:
        d = root / m
        if not d.is_dir():
            raise SystemExit(f"✗ 模块目录不存在：{d}")
        srcs = sorted(p for p in d.glob("*.c"))
        groups[GROUP_PREFIX + d.name] = [rel(p, base) for p in srcs]
        incs.append(rel(d, base))
    for inc in ["firmware/common", "firmware/pal"]:
        incs.insert(0, rel(root / inc, base))
    if extra_src:
        groups[GROUP_PREFIX + "board"] = [rel(root / s, base) for s in extra_src]
    incs += [rel(root / i, base) for i in extra_inc]
    return groups, incs


def from_build(root: pathlib.Path, board: str, app: str) -> tuple[list[str], list[str], list[str], list[str]]:
    """--board/--app：不用手列模块。先 make gen，再按 make vars 的源文件做头文件依赖闭包，只挑真正用到的模块。
    返回 (modules, extra_src, extra_inc, defines)。"""
    import re
    import shutil
    import subprocess
    mk = ["make", "-s", "-C", str(root), f"BOARD={board}", f"APP={app}"]
    r = subprocess.run(mk + ["gen"], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"✗ make gen 失败：\n{r.stdout[-600:]}{r.stderr[-600:]}")
    v = dict(l.split("=", 1) for l in subprocess.run(mk + ["vars"], capture_output=True, text=True, check=True).stdout.splitlines() if "=" in l)
    srcs, incs = v["SRCS"].split(), v["INC"].split()
    defs = [d[2:] for d in v.get("DEFS", "").split() if d.startswith("-DDZ_")]   # 芯片宏（STM32F103xB 等）Keil 工程里本来就有
    mod_of = lambda f: str(pathlib.Path(f).parent) if re.match(r"(firmware|ports)/", f) else None
    lib = {}
    for f in srcs:
        if (m := mod_of(f)):
            lib.setdefault(m, []).append(f)
    seed = [f for f in srcs if not mod_of(f)] + lib.get(next((m for m in lib if m.startswith("ports/")), ""), [])
    cc = shutil.which("arm-none-eabi-gcc") or shutil.which("cc") or "gcc"
    need, todo, seen = set(m for m in lib if m.startswith("ports/")), list(seed), set()
    while todo:
        batch = [f for f in todo if f not in seen]; seen.update(batch); todo = []
        if not batch:
            break
        out = subprocess.run([cc, "-MM", "-MG", *[f"-I{i}" for i in incs], *v.get("DEFS", "").split(), *batch],
                             cwd=root, capture_output=True, text=True).stdout
        for h in re.findall(r"(\S+\.h)\b", out.replace("\\\n", " ")):
            m = str(pathlib.Path(h).parent)
            if m in lib and m not in need:
                need.add(m); todo += lib[m]
    extra_src = [f for f in srcs if not mod_of(f)]
    extra_inc = [i for i in incs if not re.match(r"(firmware|ports)/", i) or i in ("apps/include",)]
    return sorted(need), extra_src, extra_inc, defs


def selftest() -> int:
    sample = """<?xml version="1.0"?>
<Project><Targets><Target><TargetName>T</TargetName><TargetOption><TargetArmAds><Cads><VariousControls>
<Define>USE_HAL_DRIVER</Define><IncludePath>../Core/Inc</IncludePath></VariousControls></Cads>
<Aads><VariousControls><Define></Define><IncludePath></IncludePath></VariousControls></Aads></TargetArmAds></TargetOption>
    <Groups>
      <Group>
        <GroupName>App</GroupName>
      </Group>
    </Groups></Target></Targets></Project>
"""
    g = {"dz/pid": ["..\\fw\\pid.c"]}
    a = inject(sample, g, ["..\\fw"], ["DZ_X"])
    b = inject(a, g, ["..\\fw"], ["DZ_X"])
    ok = a == b and a.count("<GroupName>dz/pid</GroupName>") == 1 and "<Define>USE_HAL_DRIVER,DZ_X</Define>" in a \
        and "<IncludePath>../Core/Inc;..\\fw</IncludePath>" in a and "<GroupName>App</GroupName>" in a \
        and "<Aads><VariousControls><Define></Define>" in a
    c = inject(a, {"dz/lpf": ["x.c"]}, [], [])
    ok = ok and "dz/pid" not in c and "dz/lpf" in c
    ld = "<LDads><umfTarg>1</umfTarg><ScatterFile></ScatterFile></LDads>"
    d = inject_scatter(inject_scatter(ld, "..\\keil\\dz_nvm.sct"), "..\\keil\\dz_nvm.sct")
    ok = ok and d == "<LDads><umfTarg>0</umfTarg><ScatterFile>..\\keil\\dz_nvm.sct</ScatterFile></LDads>"
    print("✓ keil_inject 自测通过" if ok else "✗ keil_inject 自测失败")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("uvprojx", nargs="?", type=pathlib.Path)
    ap.add_argument("--root", type=pathlib.Path, default=ROOT)
    ap.add_argument("--module", action="append", default=[])
    ap.add_argument("--extra-src", action="append", default=[])
    ap.add_argument("--extra-inc", action="append", default=[])
    ap.add_argument("--define", action="append", default=[])
    ap.add_argument("--board", help="和 --app 一起用：按这次构建自动挑模块、源文件、包含路径、DZ_ 宏（不用手列 --module）")
    ap.add_argument("--app")
    ap.add_argument("--scatter", help="Linker 页用这个 .sct（--board 且 nvm_kb>0 时自动填 boards/<板>/keil/dz_nvm.sct）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.uvprojx:
        ap.error("需要 .uvprojx 路径")
    if a.board or a.app:
        if not (a.board and a.app):
            ap.error("--board 和 --app 要一起给")
        m, xs, xi, d = from_build(a.root, a.board, a.app)
        a.module += [x for x in m if x not in a.module]; a.extra_src += xs; a.extra_inc += xi
        a.define += [x for x in d if x not in a.define]
        nd, sct = nvm_for_board(a.root, a.board)
        a.define += [x for x in nd if x not in a.define]
        if sct:
            a.scatter = rel(pathlib.Path(sct), a.uvprojx.parent)
        print(f"按 {a.board}/{a.app} 的构建挑出 {len(m)} 个模块：{', '.join(pathlib.Path(x).name for x in m)}")
    text = a.uvprojx.read_text(encoding="utf-8")
    groups, incs = plan(a.uvprojx, a.root, a.module, a.extra_src, a.extra_inc)
    new = inject(text, groups, incs, a.define)
    if a.scatter:
        new = inject_scatter(new, a.scatter)
    if a.dry_run:
        print(f"将添加组：{list(groups)}\n包含路径：{incs}\n宏：{a.define}\n分散加载：{a.scatter or '不改'}")
        return 0
    if new != text:
        shutil.copy2(a.uvprojx, str(a.uvprojx) + ".bak")
        a.uvprojx.write_text(new, encoding="utf-8")
        print(f"✓ 已更新 {a.uvprojx}（备份 .bak）：{len(groups)} 个 dz/ 组")
    else:
        print(f"✓ {a.uvprojx} 已是最新，未改动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
