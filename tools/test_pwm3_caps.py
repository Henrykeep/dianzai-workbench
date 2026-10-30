#!/usr/bin/env python3
"""三相 PWM 组（board.yaml pwm3，PAL 1.8.0）校验自测：cubemx / mspm0 的合法写法放行，跨定时器、通道重复、频率不一致、
不能中心对齐的定时器、MSPM0 非 TIMA0、冻结端口、引用不存在的 pwm 都拒绝；生成的 g_pal_pwm3 表按 pwm 序号。"""
import copy, pathlib, sys, yaml
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import boardlib  # noqa: E402
import gen_board  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ok = True
def load(b): return yaml.safe_load((ROOT / f"boards/{b}/board.yaml").read_text(encoding="utf-8"))

def with_pwm3(base, tim, chans, freqs=(20000, 20000, 20000), tims=None):
    b = copy.deepcopy(base)
    b["resources"]["pwm"] = [{"name": f"P{i}", "timer": (tims or [tim] * 3)[i], "channel": chans[i], "pin": f"PX{i}", "freq_hz": freqs[i]} for i in range(3)]
    b["resources"]["pwm3"] = [{"name": "FOC", "phases": ["P0", "P1", "P2"]}]
    return b

cm, m0 = load("stm32f407-skystar-cubemx"), load("mspm0g3507-tianmengxing")
cases = [
    ("cubemx TIM1 ch1-3", with_pwm3(cm, "TIM1", [1, 2, 3]), False),
    ("cubemx TIM8", with_pwm3(cm, "TIM8", [1, 2, 3]), False),
    ("cubemx TIM3", with_pwm3(cm, "TIM3", [1, 2, 3]), False),
    ("cubemx TIM9（不能中心对齐）", with_pwm3(cm, "TIM9", [1, 2, 3]), True),
    ("cubemx 跨定时器", with_pwm3(cm, "TIM1", [1, 2, 3], tims=["TIM1", "TIM1", "TIM8"]), True),
    ("cubemx 通道重复", with_pwm3(cm, "TIM1", [1, 1, 3]), True),
    ("cubemx 频率不一致", with_pwm3(cm, "TIM1", [1, 2, 3], freqs=(20000, 20000, 10000)), True),
    ("mspm0 TIMA0 ch0-2", with_pwm3(m0, "TIMA0", [0, 1, 2]), False),
    ("mspm0 TIMG0", with_pwm3(m0, "TIMG0", [0, 1, 2]), True),
    ("mspm0 TIMA0 ch5", with_pwm3(m0, "TIMA0", [0, 1, 5]), True),
]
f4 = with_pwm3(cm, "TIM1", [1, 2, 3]); f4["port"] = "stm32f4-hal"; cases.append(("f4-hal 端口", f4, True))
bad = with_pwm3(cm, "TIM1", [1, 2, 3]); bad["resources"]["pwm3"][0]["phases"][2] = "NOPE"; cases.append(("引用不存在的 pwm", bad, True))
for name, b, want in cases:
    rep = boardlib.Report(); boardlib.check_pwm3(b, b["resources"], rep)
    hit = any("[PWM3]" in e for e in rep.errors)
    ok &= hit == want
    print(f"{'✓' if hit == want else '✗'} {name}: {'拒绝' if hit else '放行'}{' ' + rep.errors[0][:60] if hit else ''}")
# 低频警告
rep = boardlib.Report(); b = with_pwm3(cm, "TIM1", [1, 2, 3], freqs=(8000,) * 3); boardlib.check_pwm3(b, b["resources"], rep)
ok &= any("[PWM3]" in w for w in rep.warnings); print("✓ 8 kHz 给出噪声警告" if rep.warnings else "✗ 8 kHz 没警告")
# 生成表：host-sim 板的 FOC 组指向 FOC_U/V/W 的序号
hs = load("host-sim"); names = [r["name"] for r in hs["resources"]["pwm"]]
want = f"{{ {{ {names.index('FOC_U')}u, {names.index('FOC_V')}u, {names.index('FOC_W')}u }} }}"
txt = gen_board.gen_pwm3(hs); good = want in txt and "g_pal_pwm3[]" in txt
ok &= good; print(("✓" if good else "✗") + " gen_pwm3 表序号")
none = gen_board.gen_pwm3(m0); good = "g_pal_pwm3[1];" in none
ok &= good; print(("✓" if good else "✗") + " 没有 pwm3 的板生成占位表")
sys.exit(0 if ok else 1)
