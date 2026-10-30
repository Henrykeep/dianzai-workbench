#!/usr/bin/env python3
"""ADC 块采样 block 守护自测：合法定时器放行；被占用 / 非 TRGO 定时器 / MSPM0 非法 DMA 通道 / 冻结端口拒绝。"""
import copy, pathlib, sys, yaml
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import boardlib  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
def load(b): return yaml.safe_load((ROOT / f"boards/{b}/board.yaml").read_text(encoding="utf-8"))
f4, m0 = load("stm32f407-skystar-cubemx"), load("mspm0g3507-tianmengxing")
cases = [("F407 TIM2", f4, {}, False), ("F407 TIM3（PWM 占用）", f4, {"timer": "TIM3"}, True),
         ("F407 TIM5（不是 TRGO 触发源）", f4, {"timer": "TIM5"}, True),
         ("F103 TIM2（F1 只 TIM3/8）", f4, {"part": "STM32F103RCT6"}, True),
         ("G3507 TIMG6", m0, {}, False), ("G3507 TIMG8（QEI 占用）", m0, {"timer": "TIMG8"}, True),
         ("G3507 DMA 通道 9", m0, {"dma_ch": 9}, True), ("f4-hal 端口", f4, {"port": "stm32f4-hal"}, True)]
ok = True
for name, base, mod, want in cases:
    b = copy.deepcopy(base); blk = b["resources"]["adc"][0]["block"]
    if "part" in mod: b["mcu"]["part"] = mod["part"]
    if "port" in mod: b["port"] = mod["port"]
    for k in ("timer", "dma_ch"):
        if k in mod: blk[k] = mod[k]
    rep = boardlib.Report(); boardlib.check_adc_block(b, b["resources"], rep)
    hit = any("[ADC块]" in e for e in rep.errors)
    ok &= hit == want
    print(f"{'✓' if hit == want else '✗'} {name}: {'拒绝' if hit else '放行'}{' ' + rep.errors[0][:60] if hit else ''}")
sys.exit(0 if ok else 1)
