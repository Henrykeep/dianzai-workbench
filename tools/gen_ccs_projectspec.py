#!/usr/bin/env python3
"""gen_ccs_projectspec.py —— 为 MSPM0 板 + 应用生成 CCS 可导入的 .projectspec（tiarmclang / TICLANG）。

格式照抄 TI MSPM0 SDK 2.11 的 empty_LP_MSPM0G3507_nortos_ticlang.projectspec；工作台源文件以 action="link"
链接（不复制，改了直接回到仓库），.syscfg 复制进工程由 CCS 的 SysConfig 生成 ti_msp_dl_config.{c,h}。
【未验证】未在 CCS 里导入/编译过。

用法：
    gen_ccs_projectspec.py --board mspm0g3507-tianmengxing --app car_2wd          写 boards/<板>/ccs/<板>_<应用>.projectspec
    gen_ccs_projectspec.py ... --check                                            只比对，不一致返回 1（make check 用）
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
from xml.sax.saxutils import quoteattr

ROOT = pathlib.Path(__file__).resolve().parent.parent


def make_vars(board: str, app: str) -> dict[str, str]:
    out = subprocess.run(["make", "-s", f"BOARD={board}", f"APP={app}", "vars"], cwd=ROOT,
                         check=True, capture_output=True, text=True).stdout
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def render(board: str, app: str) -> tuple[pathlib.Path, str]:
    v = make_vars(board, app)
    ccs = ROOT / "boards" / board / "ccs"
    rel = lambda p: os.path.relpath(ROOT / p, ccs).replace(os.sep, "/")
    gen = v["GEN"]
    incs = "".join(f"\n            -I${{PROJECT_LOC}}/{rel(i)}" for i in v["INC"].split())
    defs = "".join(f"\n            {d}" for d in v["DEFS"].split())
    files = []
    for s in v["SRCS"].split():
        folder = "dz/" + ("gen" if s.startswith(gen) else s.rsplit("/", 1)[0].split("/", 1)[0])
        files.append(f'        <file path={quoteattr(rel(s))} targetDirectory="{folder}" action="link"/>')
    syscfg = next(ccs.glob("*.syscfg")).name
    # 掉电保存区（board.yaml mcu.nvm_kb>0）：用 tools/gen_ide_nvm.py 生成的 dz_nvm_linker.cmd（FLASH 截短）替 SysConfig 的链接文件
    import yaml
    mcu = yaml.safe_load((ROOT / "boards" / board / "board.yaml").read_text(encoding="utf-8")).get("mcu", {})
    nvm = int(mcu.get("nvm_kb", 0) or 0)
    nvm_file = ""
    if nvm:
        if not (ccs / "dz_nvm_linker.cmd").exists():
            raise SystemExit(f"✗ {board}/ccs/dz_nvm_linker.cmd 不存在：先跑 tools/gen_ide_nvm.py")
        if "ProjectConfig.genLinker" not in (ccs / syscfg).read_text(encoding="utf-8"):
            raise SystemExit(f"✗ {syscfg} 要写 ProjectConfig.genLinker = false（否则 SysConfig 再生成一份链接文件，两份 MEMORY 冲突）")
        defs += f"\n            -DDZ_NVM_KB={nvm}u\n            -DDZ_FLASH_KB={int(mcu['flash_kb'])}u"
        nvm_file = '\n        <file path="dz_nvm_linker.cmd" openOnCreation="false" excludeFromBuild="false" action="copy"/>'
    name = f"{board}_{app}"
    text = f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- 由 tools/gen_ccs_projectspec.py 生成，勿手改；改源文件列表后重跑。【未验证】未在 CCS 中导入编译。
     导入前先在仓库根目录跑：make BOARD={board} APP={app} gen   （生成 {gen}/board_gen.c） -->
<projectSpec>
    <applicability>
        <when>
            <context deviceFamily="ARM" deviceId="MSPM0G3507"/>
        </when>
    </applicability>

    <project
        title="{name}"
        name="{name}"
        configurations="Debug"
        toolChain="TICLANG"
        connection="TIXDS110_Connection.xml"
        device="MSPM0G3507"
        ignoreDefaultDeviceSettings="true"
        ignoreDefaultCCSSettings="true"
        products="MSPM0-SDK;sysconfig"
        compilerBuildOptions="
            -I${{PROJECT_ROOT}}
            -I${{PROJECT_ROOT}}/${{ConfigName}}{incs}
            -O2
            @device.opt
            -I${{COM_TI_MSPM0_SDK_INSTALL_DIR}}/source/third_party/CMSIS/Core/Include
            -I${{COM_TI_MSPM0_SDK_INSTALL_DIR}}/source
            -mcpu=cortex-m0plus
            -march=thumbv6m
            -mfloat-abi=soft
            -mthumb
            -std=c11
            -Wall{defs}
        "
        linkerBuildOptions="
            -ldevice.cmd.genlibs
            -L${{COM_TI_MSPM0_SDK_INSTALL_DIR}}/source
            -L${{PROJECT_ROOT}}
            -L${{PROJECT_BUILD_DIR}}/syscfg
            -Wl,--rom_model
            -Wl,--warn_sections
            -L${{CG_TOOL_ROOT}}/lib
            -llibc.a
        "
        sysConfigBuildOptions="
            --output .
            --product ${{COM_TI_MSPM0_SDK_INSTALL_DIR}}/.metadata/product.json
            --compiler ticlang
        "
        sourceLookupPath="${{COM_TI_MSPM0_SDK_INSTALL_DIR}}/source/ti/driverlib"
        description="dianzai-workbench：{board} + {app}">
        <property name="buildProfile" value="release"/>
        <property name="isHybrid" value="true"/>
        <file path="{syscfg}" openOnCreation="true" excludeFromBuild="false" action="copy"/>
        <file path="${{COM_TI_MSPM0_SDK_INSTALL_DIR}}/source/ti/devices/msp/m0p/startup_system_files/ticlang/startup_mspm0g350x_ticlang.c" openOnCreation="false" excludeFromBuild="false" targetDirectory="ticlang" action="copy"/>{nvm_file}
{chr(10).join(files)}
    </project>
</projectSpec>
'''
    return ccs / f"{name}.projectspec", text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True)
    ap.add_argument("--app", required=True)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    path, text = render(a.board, a.app)
    if a.check:
        ok = path.exists() and path.read_text(encoding="utf-8") == text
        print(f"{'✓' if ok else '✗'} {path.relative_to(ROOT)}{'' if ok else ' 过期：重跑 tools/gen_ccs_projectspec.py'}")
        return 0 if ok else 1
    path.write_text(text, encoding="utf-8")
    print(f"写入 {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
