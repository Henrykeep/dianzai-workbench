#!/usr/bin/env python3
"""ioc_import / boardlib 回归测试：用用户真实 CubeMX 工程（tools/testdata/real/*.ioc）锁住导入结果。

期望值 tools/testdata/real/*.expected.yaml 是对照 .ioc 逐行人工核对后写入的；导入逻辑一改，结果变了就会失败。
确实需要更新时：python3 tools/test_ioc_import.py --update，然后人工 diff 核对再提交。"""
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boardlib  # noqa: E402
import gen_board  # noqa: E402
import ioc_import as ii  # noqa: E402

REAL = HERE / "testdata/real"
fails = 0


def check(name, cond, detail=""):
    global fails
    fails += not cond
    print(f"{'✓' if cond else '✗'} {name}{'' if cond else '  ' + str(detail)}")


def snapshot(path):
    rep = ii.Rep()
    res, meta = ii.run(path, {}, rep)
    return {"resources": res, "meta": meta, "errors": sorted({c for c, _ in rep.errors}),
            "warnings": len(rep.warnings), "infos": rep.infos}


def main():
    update = "--update" in sys.argv
    for ioc in sorted(REAL.glob("*.ioc")):
        exp = ioc.with_suffix(".expected.yaml")
        got = snapshot(ioc)
        if update:
            exp.write_text(yaml.safe_dump(got, allow_unicode=True, sort_keys=False), encoding="utf-8")
            print(f"已更新 {exp.name}，请人工核对")
            continue
        want = yaml.safe_load(exp.read_text(encoding="utf-8"))
        check(f"real/{ioc.name} 与人工核对的期望一致", got == want,
              {k: (want.get(k), got.get(k)) for k in got if got.get(k) != want.get(k)})

    # 单项：这些都是真实 .ioc 暴露出来的坑
    check("ioc_int 表达式 2000-1", ii.ioc_int("2000-1") == 1999)
    check("ioc_int 拒绝非整数表达式", ii.ioc_int("__import__('os')") is None and ii.ioc_int("8/2") is None)
    p = ii.pins_of(ii.parse_ioc("PA0-WKUP.Signal=S_TIM2_CH1_ETR\nPC14-OSC32_IN.GPIO_Label=R3\n"))
    check("带复用后缀的引脚键（PA0-WKUP/PC14-OSC32_IN）", p == {"PA0": {"Signal": "S_TIM2_CH1_ETR"}, "PC14": {"GPIO_Label": "R3"}}, p)
    for part, kb in (("STM32F407VET6", 512), ("STM32F407VGTx", 1024), ("STM32F103C8T6", 64), ("STM32F103CBT6", 128),
                     ("STM32F407IGH6", 1024), ("MSPM0G3507", None)):
        check(f"stm32_flash_kb({part})={kb}", boardlib.stm32_flash_kb(part) == kb, boardlib.stm32_flash_kb(part))
    for part, d in (("STM32F407VETx", "STM32F407xx"), ("STM32F103C8T6", "STM32F103xB"), ("STM32F103RCT6", "STM32F103xE"),
                    ("STM32F103C6T6", "STM32F103x6"), ("STM32G431CBU6", "STM32G431xx")):
        check(f"cube_define({part})={d}", gen_board.cube_define(part) == d, gen_board.cube_define(part))

    # 变体：天空星 VET6 / VGT6 同一份 board.yaml
    sky = HERE.parent / "boards/stm32f407-skystar/board.yaml"
    b = boardlib.load_board(sky)
    check("天空星默认变体 VET6 / 512KB", (b["mcu"]["part"], b["mcu"]["flash_kb"]) == ("STM32F407VETx", 512), b["mcu"])
    b = boardlib.load_board(sky, "VGT6")
    check("天空星 VARIANT=VGT6 / 1024KB", (b["mcu"]["part"], b["mcu"]["flash_kb"]) == ("STM32F407VGTx", 1024), b["mcu"])
    check("VGT6 变体通过校验", not boardlib.check_board(b).errors, boardlib.check_board(b).errors)
    try:
        boardlib.load_board(sky, "ZZZ")
        check("不存在的变体被拒绝", False)
    except ValueError:
        check("不存在的变体被拒绝", True)
    b = boardlib.load_board(sky)
    b["mcu"]["flash_kb"] = 1024
    check("flash_kb 大于型号实际容量被拦截", any("flash_kb" in e for e in boardlib.check_board(b).errors))

    print(f"\ntest_ioc_import: 失败 {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
