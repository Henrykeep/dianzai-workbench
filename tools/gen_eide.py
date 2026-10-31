#!/usr/bin/env python3
"""gen_eide.py —— 为 板 + 应用生成 VS Code EIDE（Embedded IDE）工程 boards/<板>/eide/<应用>/.eide/eide.json。

源文件 / 包含路径 / 宏 / CPU / 链接脚本 / 库 全部取自 `make -B -n BOARD=… APP=…` 的真实编译命令，和 make、Keil 注入同一份清单，不另维护。
工具链 GCC（arm-none-eabi-gcc），下载器 OpenOCD（STM32 用 stlink.cfg，MSPM0 用 xds110.cfg，按需在 EIDE 里改）。
【未测】未在 VS Code EIDE 插件里打开或编译过（字段按 EIDE 3.x 工程格式）；以 make 编译为准。
用法：gen_eide.py --board <板> --app <应用>
"""
import argparse, json, os, pathlib, re, shlex, subprocess, sys, uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import boardlib  # noqa: E402
CPU = {"cortex-m0plus": "Cortex-M0+", "cortex-m3": "Cortex-M3", "cortex-m4": "Cortex-M4", "cortex-m7": "Cortex-M7"}


def parse(board, app):
    p = subprocess.run(["make", "-B", "-n", f"BOARD={board}", f"APP={app}"], cwd=REPO, capture_output=True, text=True)
    if p.returncode:
        sys.exit("✗ make -n 失败：\n" + (p.stdout + p.stderr)[-1500:])
    src, inc, defs, flags, ld, libs, cflags = [], [], [], {}, None, [], None
    for ln in p.stdout.splitlines():
        if "arm-none-eabi-gcc" not in ln:
            continue
        t = shlex.split(ln)
        if "-c" in t:
            s = t[t.index("-c") + 1]
            if s not in src:
                src.append(s)
            for i, a in enumerate(t):
                if a.startswith("-I") and a[2:] and a[2:] not in inc:
                    inc.append(a[2:])
                elif a.startswith("-D") and a[2:] not in defs:
                    defs.append(a[2:])
                elif a.startswith("-mcpu="):
                    flags["cpu"] = a[6:]
                elif a.startswith("-mfloat-abi="):
                    flags["fabi"] = a[12:]
            if cflags is None and s.endswith(".c"):
                cflags = " ".join(a for a in t[1:] if re.match(r"-(std=|O|g|W|f)", a))
        elif "-o" in t and t[t.index("-o") + 1].endswith(".elf"):
            for i, a in enumerate(t):
                if a.startswith("-T"):
                    ld = a[2:] or t[i + 1]
                elif a.endswith(".a") or (a.startswith("-l") and len(a) > 2):
                    libs.append(a)
    return src, inc, defs, flags, ld, libs, cflags or ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True); ap.add_argument("--app", required=True)
    x = ap.parse_args()
    src, inc, defs, fl, ld, libs, cflags = parse(x.board, x.app)
    pd = boardlib.board_dir(x.board, REPO) / "eide" / x.app
    rel = lambda p: os.path.relpath(REPO / p, pd).replace(os.sep, "/")
    folders = {}
    for s in src:
        top = s.split("/")[0]
        folders.setdefault(top, []).append({"path": rel(s)})
    m0 = fl.get("cpu") == "cortex-m0plus"
    cfg = {
        "name": f"{x.board}_{x.app}", "type": "ARM", "dependenceList": [], "srcDirs": [], "outDir": "build",
        "deviceName": None, "packDir": None, "miscInfo": {"uid": uuid.uuid5(uuid.NAMESPACE_URL, f"dz/{x.board}/{x.app}").hex},
        "targets": {"Debug": {
            "excludeList": [], "toolchain": "GCC",
            "compileConfig": {"cpuType": CPU.get(fl.get("cpu"), "Cortex-M4"),
                              "floatingPointHardware": "none" if fl.get("fabi", "soft") == "soft" else "single",
                              "useCustomScatterFile": True, "scatterFilePath": rel(ld) if ld else "",
                              "storageLayout": {"RAM": [], "ROM": []}, "options": "null"},
            "uploader": "OpenOCD",
            "uploadConfig": {"bin": "", "target": "${workspaceFolderName}", "interface": "cmsis-dap" if m0 else "stlink",
                             "baseAddr": "0x00000000" if m0 else "0x08000000"},
            "custom_dep": {"name": "default", "incList": [rel(i) for i in inc], "libList": [], "defineList": defs},
            "builderOptions": {"GCC": {"version": 5, "beforeBuildTasks": [], "afterBuildTasks": [],
                                       "global": {"$float-abi-type": fl.get("fabi", "soft"), "output-debug-info": "enable", "misc-control": "--specs=nosys.specs --specs=nano.specs"},
                                       "c/cpp-compiler": {"language-c": "c11", "optimization": "level-size", "warnings": "all-warnings", "C_FLAGS": cflags},
                                       "asm-compiler": {"ASM_FLAGS": "-x assembler-with-cpp"},
                                       "linker": {"output-format": "elf", "remove-unused-input-sections": True,
                                                  "LIB_FLAGS": " ".join(rel(l) if l.endswith(".a") else l for l in libs)}}}}},
        "virtualFolder": {"name": "<virtual_root>", "files": [],
                          "folders": [{"name": k, "files": v, "folders": []} for k, v in folders.items()]},
        "version": "3.5",
    }
    (pd / ".eide").mkdir(parents=True, exist_ok=True)
    (pd / ".eide" / "eide.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (pd / "README.md").write_text(f"# EIDE 工程：{x.board} / {x.app}\n\n由 `tools/gen_eide.py --board {x.board} --app {x.app}` 从 make 的编译命令生成；"
                                  f"VS Code 装 EIDE 插件后“打开项目”选本目录。先在仓库根跑一次 `make BOARD={x.board} APP={x.app}` 生成 build/{x.board}/gen。\n"
                                  "【未测】未在 EIDE 里打开或编译过；以 make 为准。\n", encoding="utf-8")
    print(f"✓ {pd.relative_to(REPO)}/.eide/eide.json：{len(src)} 个源文件、{len(inc)} 个包含路径、链接脚本 {ld}（【未测】）")


if __name__ == "__main__":
    main()
