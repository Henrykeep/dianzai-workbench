#!/usr/bin/env python3
"""DAC 资源守护自测（PAL 1.7.0）：有 DAC 的芯片放行，没有的（F103C8、MSPM0G3105、F411）和冻结端口拒绝（ioc_import 认 DAC 脚由 make check 的 .ioc --check 覆盖）。"""
import copy, pathlib, sys, yaml
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import boardlib  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ok = True
def load(b): return yaml.safe_load((ROOT / f"boards/{b}/board.yaml").read_text(encoding="utf-8"))
f4, m0 = load("stm32f407-skystar-cubemx"), load("mspm0g3507-tianmengxing")
cases = [("F407 cubemx", f4, {}, False), ("F103C8 cubemx", f4, {"part": "STM32F103C8T6"}, True),
         ("F103RC cubemx", f4, {"part": "STM32F103RCT6"}, False), ("F411 cubemx", f4, {"part": "STM32F411CEU6"}, True),
         ("H743 cubemx", f4, {"part": "STM32H743VIT6", "inst": "DAC1"}, False),
         ("G3507 mspm0", m0, {}, False), ("G3105 mspm0", m0, {"part": "MSPM0G3105"}, True),
         ("f4-hal 端口", f4, {"port": "stm32f4-hal"}, True), ("通道 3", f4, {"ch": 3}, True)]
for name, base, mod, want in cases:
    b = copy.deepcopy(base)
    if "part" in mod: b["mcu"]["part"] = mod["part"]
    if "port" in mod: b["port"] = mod["port"]
    if "inst" in mod: b["resources"]["dac"][0]["instance"] = mod["inst"]
    if "ch" in mod: b["resources"]["dac"][0]["channel"] = mod["ch"]
    rep = boardlib.Report(); boardlib.check_dac(b, b["resources"], rep)
    hit = any("[DAC]" in e for e in rep.errors)
    ok &= hit == want
    print(f"{'✓' if hit == want else '✗'} {name}: {'拒绝' if hit else '放行'}{' ' + rep.errors[0][:60] if hit else ''}")
sys.exit(0 if ok else 1)
