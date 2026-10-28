#!/usr/bin/env python3
"""audit_port.py —— 第三方代码（网上的驱动/算法库/往届代码）移植入库前的静态审计。

对照 docs/04-入库检查清单.md 的“第三方移植”一节，逐文件找出会破坏可移植性的写法，并给出改法：
  A1 芯片头文件/标准库/HAL 调用（应改为 PAL 或依赖注入的回调）   A2 直接寄存器访问
  A3 阻塞延时 delay_ms/HAL_Delay/while 等标志                       A4 动态内存 malloc/free
  A5 printf/sprintf 到串口（改为返回数据，由应用决定输出）          A6 double 运算（M4F 只有单精度 FPU）
  A7 定义中断入口 *_IRQHandler（中断属于移植层）                    A8 可写全局/静态变量（应收进实例结构体）
  A9 缺 LICENSE/出处说明                                            A10 缺 README/VERSION/selftest（三件套）
输出：问题清单 + 风险分级（高/中/低）。退出码：有“高”风险项为 1。

用法：audit_port.py <目录>     audit_port.py --selftest
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RULES = [
    ("A1", "高", re.compile(r'#\s*include\s*[<"](stm32\w*|gd32\w*|ti_msp_dl_config|ti/driverlib/\w*|msp430\w*|reg52|main)\.h[>"]'),
     "芯片/工程头文件：改为只依赖 pal.h 或由调用者注入函数指针"),
    ("A1", "高", re.compile(r'\b(GPIO_(Set|Reset)Bits|GPIO_Init|HAL_\w+|LL_\w+|DL_\w+|RCC_\w+Cmd)\s*\('),
     "厂商库调用：改为 PAL 接口（pal_gpio_write 等）"),
    ("A2", "高", re.compile(r'\b(GPIO[A-K]|TIM\d+|USART\d|RCC|ADC\d|SPI\d|I2C\d)\s*->\s*\w+'), "寄存器直接访问：改为 PAL"),
    ("A3", "中", re.compile(r'\b(delay_ms|delay_us|HAL_Delay|Delay|osDelay)\s*\('), "阻塞延时：改为状态机 + pal_millis() 判时"),
    ("A4", "中", re.compile(r'\b(malloc|calloc|realloc|free)\s*\('), "动态内存：改为调用者提供的静态缓冲"),
    ("A5", "低", re.compile(r'\b(printf|sprintf|puts)\s*\('), "直接打印：改为返回数据/回调，由应用输出"),
    ("A6", "低", re.compile(r'\bdouble\b|\b\d+\.\d+(?![fF\w])'), "双精度：常量加 f 后缀，类型用 float"),
    ("A7", "高", re.compile(r'\bvoid\s+\w+_IRQHandler\s*\('), "中断入口属于移植层：改为提供 xxx_on_irq() 由移植层调用"),
    ("A8", "中", re.compile(r'^(?:static\s+)?(?!const\b)(?:volatile\s+)?(?:unsigned\s+|signed\s+)?(?:int|char|float|uint\d+_t|int\d+_t|bool)\s+\w+(?:\[[^\]]*\])?\s*(?:=[^;(]*)?;', re.M),
     "可写全局/静态状态：收进 xxx_t 实例结构体，支持多实例"),
]


def strip_comments(s):
    s = re.sub(r'/\*.*?\*/', lambda m: "\n" * m.group(0).count("\n"), s, flags=re.S)
    return re.sub(r'//[^\n]*', '', s)


def audit(d: pathlib.Path, third_party: bool = True):
    found = []
    for f in sorted(list(d.rglob("*.c")) + list(d.rglob("*.h"))):
        src = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        nostr = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', src)   # 字符串内容不参与 A2~A8
        for code, lvl, rx, fix in RULES:
            for m in rx.finditer(src if code == "A1" else nostr):
                found.append((code, lvl, f"{f.relative_to(d)}:{src.count(chr(10), 0, m.start()) + 1}", m.group(0).strip()[:50], fix))
    names = {p.name.upper() for p in d.iterdir()}
    if third_party and not names & {"LICENSE", "LICENSE.TXT", "LICENSE.MD", "COPYING", "SOURCE.MD"}:
        found.append(("A9", "高", str(d), "-", "补 LICENSE 或 SOURCE.md（出处 URL、作者、许可证）；许可证不明不得入库"))
    for need in ("README.MD", "VERSION"):
        if need not in names:
            found.append(("A10", "中", str(d), need, "按模块三件套补齐（docs/03-模块三件套.md）"))
    if not any("selftest" in p.read_text(encoding="utf-8", errors="replace") for p in d.rglob("*.c")):
        found.append(("A10", "中", str(d), "selftest", "补 <模块>_selftest()"))
    return found


def report(d, found):
    for code, lvl, where, what, fix in found:
        print(f"[{lvl}] {code} {where}  `{what}`\n      → {fix}")
    hi = sum(1 for x in found if x[1] == "高")
    print(f"{'✗' if hi else '✓'} {d}: 高 {hi} / 中 {sum(1 for x in found if x[1] == '中')} / 低 {sum(1 for x in found if x[1] == '低')}")
    return 1 if hi else 0


def selftest() -> int:
    got = {c for c, *_ in audit(ROOT / "tools/fixtures/audit_bad")}
    want = {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"}
    ok1 = got == want
    print(f"{'✓' if ok1 else '✗'} audit_bad: 期望 {sorted(want)}，实际 {sorted(got)}")
    clean = [x for x in audit(ROOT / "firmware/algo/pid", third_party=False) if x[1] in ("高", "中")]
    ok2 = not clean
    print(f"{'✓' if ok2 else '✗'} firmware/algo/pid 无高/中风险项{'' if ok2 else ': ' + str(clean)}")
    return 0 if ok1 and ok2 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?", type=pathlib.Path)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.dir:
        ap.error("需要目录")
    return report(a.dir, audit(a.dir))


if __name__ == "__main__":
    sys.exit(main())
