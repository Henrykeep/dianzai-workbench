#!/usr/bin/env python3
"""gen_m0_keil.py —— 为 MSPM0 板 + 应用生成 Keil µVision 工程 boards/<板>/keil/<板>_<应用>.uvprojx。

模板：tools/templates/mspm0-keil/（取自 nuedc-2026-h-ball-balance 的 beam_control Keil 工程，MIT；改自 TI SDK empty 例程）。
做法：替换工程名 / SDK 路径（→ 仓库 third_party/mspm0-sdk 的相对路径）/ 源文件（板的 .syscfg 与 syscfg/ti_msp_dl_config.[ch]），
再调 keil_inject.py --board --app 按这次构建注入工作台模块、包含路径、DZ_ 宏（与 make 同一份清单）。
【未测】未在 µVision 里打开或编译过（本机没有 armclang）。
用法：gen_m0_keil.py --board <板> --app <应用>
"""
import argparse, pathlib, re, shutil, subprocess, sys, os

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import boardlib  # noqa: E402
TPL = REPO / "tools/templates/mspm0-keil"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True); ap.add_argument("--app", required=True)
    x = ap.parse_args()
    bd = boardlib.board_dir(x.board, REPO)
    sc = sorted((bd / "ccs").glob("*.syscfg"))
    if not sc or not (bd / "syscfg/ti_msp_dl_config.c").exists():
        sys.exit(f"✗ {bd} 不是 MSPM0 SysConfig 板（缺 ccs/*.syscfg 或 syscfg/ti_msp_dl_config.c）")
    kd = bd / "keil"; kd.mkdir(exist_ok=True)
    for f in ("startup_mspm0g350x_uvision.s", "mspm0g3507.sct"):
        shutil.copy(TPL / f, kd / f)
    name = f"{x.board}_{x.app}"
    sdk = os.path.relpath(REPO / "third_party/mspm0-sdk", kd).replace(os.sep, "/")
    t = (TPL / "empty_LP_MSPM0G3507_nortos_keil.uvprojx").read_text(encoding="utf-8")
    t = t.replace("<TargetName>empty_LP_MSPM0G3507_nortos_keil</TargetName>", f"<TargetName>{name}</TargetName>")
    t = re.sub(r"<OutputName>[^<]*</OutputName>", f"<OutputName>{name}</OutputName>", t)
    t = re.sub(r"\.\./\.\./mspm0_sdk_[\d_]+", sdk, t)
    rel = lambda p: os.path.relpath(p, kd).replace(os.sep, "/")
    t = t.replace("<FileName>empty.syscfg</FileName>", f"<FileName>{sc[0].name}</FileName>").replace("<FilePath>../empty.syscfg</FilePath>", f"<FilePath>{rel(sc[0])}</FilePath>")
    for f in ("ti_msp_dl_config.h", "ti_msp_dl_config.c"):
        t = t.replace(f"<FilePath>../{f}</FilePath>", f"<FilePath>{rel(bd / 'syscfg' / f)}</FilePath>")
    t = re.sub(r"\s*<File>\s*<FileName>empty\.c</FileName>.*?</File>", "", t, flags=re.S)      # 例程 main 换成工作台的（keil_inject 注入）
    t = t.replace(f"<IncludePath>{sdk}/source/third_party", "<IncludePath>../syscfg," + f"{sdk}/source/third_party", 1)
    uv = kd / f"{name}.uvprojx"; uv.write_text(t, encoding="utf-8")
    p = subprocess.run([sys.executable, str(REPO / "tools/keil_inject.py"), str(uv), "--root", str(REPO), "--board", x.board, "--app", x.app],
                       capture_output=True, text=True)
    print(p.stdout + p.stderr, end="")
    if p.returncode:
        return p.returncode
    (kd / (uv.name + ".bak")).unlink(missing_ok=True)       # 刚生成的，不需要 keil_inject 的备份
    print(f"✓ {uv.relative_to(REPO)}（模板 beam_control/keil，MIT；【未测】未在 µVision 编译）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
