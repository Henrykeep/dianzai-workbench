#!/usr/bin/env python3
"""依赖与分层检查器（tools/check_deps.py）。

用法：
  python3 tools/check_deps.py            # 检查整个仓库，违规时退出码 1
  python3 tools/check_deps.py --root DIR # 检查另一棵目录（违规样例自测用）
  python3 tools/check_deps.py --selftest # 跑 tools/fixtures/deps_* 违规样例，证明每条规则都能拦住

规则（详见 docs/02-分层与依赖.md）：
  L1  分层 #include 白名单：common ← pal ← algo ← framework ← drivers ← apps/examples，只能向下依赖。
  L2  芯片/厂商 API（HAL_xxx、DL_xxx、LL_xxx、stm32*.h、ti_msp_dl_config.h 等）只能出现在 ports/。
  L3  host_sim.h 只能在 ports/host-sim、tests/ 和 sim_setup.c 里出现。
  S1  子系统（examples/*/subsys/<n>/）不得 include pal.h / board_gen.h / 驱动 / io/ / 其它子系统目录的文件。
  S2  子系统只能写 project.yaml 里自己 owns 的共享状态段（检查 st->段.字段 = ...）。
  P1  STM32 移植层只许用 CubeMX + HAL（可用 HAL 附带的 LL 宏，但不许标准外设库 StdPeriph）：
      禁止 stm32f4xx_gpio.h 等 StdPeriph 头、GPIO_Init()/RCC_AHB1PeriphClockCmd() 等 StdPeriph 调用；
      禁止直接读写外设寄存器（TIM2->CNT、htim->Instance->CCR1、RCC->CR …），
      除非该行或上一行带注释 `DZ-REG-OK: <原因>`（官方 HAL 做不到时才允许，且必须写明原因）。
  P2  厂商 API 不得串用：HAL_/LL_ 只能在 ports/stm32*，DL_ 只能在 ports/mspm0*。
  V1  每个模块目录的 VERSION 必须与头文件里的 XXX_VERSION 宏一致。
"""
import argparse, os, re, sys

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

INC_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
VENDOR_CALL_RE = re.compile(r'\b(HAL_[A-Z]\w*|LL_[A-Z]\w*|DL_[A-Z]\w*)\s*\(')
VENDOR_HDR_RE = re.compile(r'^(stm32\w*\.h|ti_msp_dl_config\.h|ti/.*|gd32\w*\.h|core_cm\d\.h|cmsis_\w+\.h|main\.h)$')
STD_HDRS = {"stdint.h", "stdbool.h", "stddef.h", "string.h", "math.h", "stdio.h", "stdlib.h", "limits.h", "float.h", "stdarg.h", "assert.h"}

# 各层允许 include 的“层”。key 为层名，值为可依赖的层集合（含自身）。
LAYER_ALLOW = {
    "common":    {"common"},
    "pal":       {"common", "pal"},
    "algo":      {"common", "algo"},
    "framework": {"common", "algo", "framework"},
    "drivers":   {"common", "pal", "algo", "drivers"},
}


def strip_comments(src):
    src = re.sub(r'/\*.*?\*/', lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    return re.sub(r'//[^\n]*', '', src)


def lineno(src, pos):
    return src.count("\n", 0, pos) + 1


class Checker:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.errors = []
        self.header_layer = {}   # 头文件名 -> 层名（firmware/ 内）
        self.header_dir = {}     # 头文件名 -> 相对目录

    def err(self, rule, path, line, msg):
        self.errors.append(f"{os.path.relpath(path, self.root)}:{line}: [{rule}] {msg}")

    def files(self, sub, exts=(".c", ".h")):
        base = os.path.join(self.root, sub)
        for d, dirs, fs in os.walk(base):
            dirs[:] = [x for x in dirs if x not in ("build", "third_party", "fixtures", "__pycache__")]
            for f in sorted(fs):
                if f.endswith(exts):
                    yield os.path.join(d, f)

    def layer_of(self, path):
        rel = os.path.relpath(path, self.root).split(os.sep)
        if rel[0] == "firmware" and len(rel) > 1 and rel[1] in LAYER_ALLOW:
            return rel[1]
        return None

    def index_headers(self):
        for p in self.files("firmware", (".h",)):
            self.header_layer[os.path.basename(p)] = self.layer_of(p)
            self.header_dir[os.path.basename(p)] = os.path.relpath(os.path.dirname(p), self.root)

    # ---------------------------------------------------------------- L1/L2/L3
    def check_file(self, path):
        raw = open(path, encoding="utf-8", errors="replace").read()
        src = strip_comments(raw)
        rel = os.path.relpath(path, self.root)
        top = rel.split(os.sep)[0]
        in_ports = top == "ports"
        in_tests = top == "tests" or f"{os.sep}tests{os.sep}" in rel
        is_sim_setup = os.path.basename(path) == "sim_setup.c"
        layer = self.layer_of(path)

        for m in INC_RE.finditer(src):
            hdr = m.group(1)
            base = os.path.basename(hdr)
            ln = lineno(src, m.start())
            if base in STD_HDRS:
                continue
            if VENDOR_HDR_RE.match(hdr) and not in_ports:
                self.err("L2", path, ln, f"芯片/厂商头文件 {hdr} 只能在 ports/ 中使用")
            if base == "host_sim.h" and not (in_ports or in_tests or is_sim_setup):
                self.err("L3", path, ln, "host_sim.h 只能出现在 ports/host-sim、tests/ 或 sim_setup.c")
            if layer:
                if base == "board_gen.h":
                    self.err("L1", path, ln, f"{layer} 层不得依赖 board_gen.h（板级资源由应用层传入）")
                    continue
                tgt = self.header_layer.get(base)
                if tgt and tgt not in LAYER_ALLOW[layer]:
                    self.err("L1", path, ln, f"{layer} 层不得 include {tgt} 层的 {base}（只能向下依赖：{sorted(LAYER_ALLOW[layer])}）")
                if base in ("app.h", "project_gen.h"):
                    self.err("L1", path, ln, f"{layer} 层不得依赖应用层头文件 {base}")
        if not in_ports:
            for m in VENDOR_CALL_RE.finditer(src):
                self.err("L2", path, lineno(src, m.start()), f"直接调用厂商 API {m.group(1)}()，应通过 PAL")

    # ---------------------------------------------------------------- P1/P2
    STDPERIPH_HDR = re.compile(r'^stm32[a-z]\d+xx_(gpio|rcc|tim|usart|adc|dma|exti|spi|i2c|misc|syscfg|flash)\.h$')
    STDPERIPH_CALL = re.compile(r'\b(GPIO_Init|GPIO_SetBits|GPIO_ResetBits|GPIO_StructInit|TIM_TimeBaseInit|TIM_OCInit|TIM_Cmd|USART_Init|USART_Cmd|USART_SendData|ADC_Init|DMA_Init|NVIC_Init|RCC_\w+PeriphClockCmd)\s*\(')
    REG_ACCESS = re.compile(r'\b(?:(?:GPIO[A-K]|TIM\d+|USART\d|UART\d|RCC|ADC\d|ADC|DMA\d_Stream\d|DMA\d|EXTI|SYSCFG|FLASH|PWR|SPI\d|I2C\d|SCB|NVIC|SysTick|DWT|CoreDebug)\s*->|(?:->|\.)\s*Instance\s*->)\s*\w+')

    def check_port(self, path):
        rel = os.path.relpath(path, self.root).split(os.sep)
        if rel[0] != "ports" or len(rel) < 2:
            return
        port = rel[1]
        raw = open(path, encoding="utf-8", errors="replace").read()
        lines = raw.splitlines()
        src = strip_comments(raw)
        if port.startswith("stm32"):
            for m in INC_RE.finditer(src):
                if self.STDPERIPH_HDR.match(os.path.basename(m.group(1))):
                    self.err("P1", path, lineno(src, m.start()), f"禁止标准外设库头文件 {m.group(1)}，STM32 统一 CubeMX+HAL")
            for m in self.STDPERIPH_CALL.finditer(src):
                self.err("P1", path, lineno(src, m.start()), f"禁止标准外设库调用 {m.group(1)}()，改用 HAL_xxx")
            for m in self.REG_ACCESS.finditer(src):
                ln = lineno(src, m.start())
                ctx = " ".join(lines[max(0, ln - 2):ln])
                if "DZ-REG-OK:" not in ctx or re.search(r'DZ-REG-OK:\s*($|\*/)', ctx):
                    self.err("P1", path, ln, f"直接访问寄存器 `{m.group(0)}`；必须用 HAL，确需寄存器时在该行或上一行注明 `DZ-REG-OK: 原因`")
        for m in VENDOR_CALL_RE.finditer(src):
            api = m.group(1)
            if api.startswith("DL_") and not port.startswith("mspm0"):
                self.err("P2", path, lineno(src, m.start()), f"DriverLib 调用 {api}() 只能在 ports/mspm0*")
            if api.startswith(("HAL_", "LL_")) and not port.startswith("stm32"):
                self.err("P2", path, lineno(src, m.start()), f"STM32 HAL/LL 调用 {api}() 只能在 ports/stm32*")

    # ---------------------------------------------------------------- S1/S2
    def check_project(self, proj_dir):
        yml = os.path.join(proj_dir, "project.yaml")
        owns = {}
        sections = set()
        if yaml and os.path.exists(yml):
            cfg = yaml.safe_load(open(yml, encoding="utf-8")) or {}
            sections = set((cfg.get("state") or {}).keys())
            for s in cfg.get("subsystems") or []:
                owns[s["name"]] = set(s.get("owns") or [])
        sub_root = os.path.join(proj_dir, "subsys")
        if not os.path.isdir(sub_root):
            return
        names = sorted(d for d in os.listdir(sub_root) if os.path.isdir(os.path.join(sub_root, d)))
        own_headers = {}
        for n in names:
            for p in self.files(os.path.relpath(os.path.join(sub_root, n), self.root), (".h",)):
                own_headers[os.path.basename(p)] = n
        for n in names:
            sd = os.path.join(sub_root, n)
            for p in self.files(os.path.relpath(sd, self.root)):
                if f"{os.sep}tests{os.sep}" in p:
                    continue
                src = strip_comments(open(p, encoding="utf-8", errors="replace").read())
                for m in INC_RE.finditer(src):
                    hdr = m.group(1); base = os.path.basename(hdr); ln = lineno(src, m.start())
                    if base in ("pal.h", "board_gen.h") or self.header_layer.get(base) in ("pal", "drivers"):
                        self.err("S1", p, ln, f"子系统 {n} 不得接触硬件（{base}），硬件读写放在 io/ 胶水层")
                    elif base in own_headers and own_headers[base] != n:
                        self.err("S1", p, ln, f"子系统 {n} 不得 include 子系统 {own_headers[base]} 的 {base}，只能通过共享状态交换数据")
                    elif hdr.startswith("..") or "/subsys/" in hdr or hdr.startswith("io/") or base == "hooks.h":
                        self.err("S1", p, ln, f"子系统 {n} 不得用相对路径/跨目录 include {hdr}")
                if owns:
                    if n not in owns:
                        self.err("S2", p, 1, f"目录 subsys/{n} 在 project.yaml 中没有声明")
                        continue
                    for m in re.finditer(r'\b(\w+)\s*->\s*(\w+)\s*(?:\.\s*\w+(?:\[[^\]]*\])?\s*)*(=|\+=|-=|\*=|/=|\|=|&=|\+\+|--)(?!=)', src):
                        sec = m.group(2)
                        if sec in sections and sec not in owns[n]:
                            self.err("S2", p, lineno(src, m.start()), f"子系统 {n} 写了不属于自己的共享状态段 {sec}（owns={sorted(owns[n])}）")
                    for m in re.finditer(r'\(\s*(?:st_\w+_t|shared_state_t)\s*\*\s*\)\s*&?\s*\w+\s*->\s*(\w+)', src):
                        sec = m.group(1)
                        if sec in sections and sec not in owns[n]:
                            self.err("S2", p, lineno(src, m.start()), f"子系统 {n} 通过强制转换获得了 {sec} 的可写指针")

    # ---------------------------------------------------------------- V1
    def check_versions(self):
        for d, dirs, fs in os.walk(self.root):
            dirs[:] = [x for x in dirs if x not in ("build", "third_party", ".git", "fixtures")]
            if "VERSION" not in fs:
                continue
            vpath = os.path.join(d, "VERSION")
            ver = open(vpath).read().strip()
            if not re.fullmatch(r'\d+\.\d+\.\d+', ver):
                self.err("V1", vpath, 1, f"VERSION 内容 '{ver}' 不是 MAJOR.MINOR.PATCH")
                continue
            for h in fs:
                if not h.endswith(".h"):
                    continue
                txt = open(os.path.join(d, h), encoding="utf-8", errors="replace").read()
                for m in re.finditer(r'#\s*define\s+(\w+_VERSION)\s+"([^"]+)"', txt):
                    if m.group(2) != ver:
                        self.err("V1", os.path.join(d, h), lineno(txt, m.start()),
                                 f"{m.group(1)}={m.group(2)} 与 VERSION 文件 {ver} 不一致")

    def run(self):
        self.index_headers()
        for top in ("firmware", "apps", "examples", "ports", "boards"):
            for p in self.files(top):
                self.check_file(p)
                self.check_port(p)
        ex = os.path.join(self.root, "examples")
        if os.path.isdir(ex):
            for e in sorted(os.listdir(ex)):
                if os.path.isdir(os.path.join(ex, e)):
                    self.check_project(os.path.join(ex, e))
        self.check_versions()
        return self.errors


def selftest(root):
    fx = os.path.join(root, "tools", "fixtures")
    ok = True
    cases = sorted(d for d in os.listdir(fx) if d.startswith("deps_"))
    for c in cases:
        expect = open(os.path.join(fx, c, "EXPECT")).read().split()
        errs = Checker(os.path.join(fx, c)).run()
        got = sorted({re.search(r'\[(\w+)\]', e).group(1) for e in errs})
        good = sorted(set(expect)) == got
        ok &= good
        print(f"{'✓' if good else '✗'} {c}: 期望拦截 {sorted(set(expect))}，实际 {got}")
        if not good:
            for e in errs:
                print("    " + e)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest(os.path.abspath(a.root)) else 1)
    errs = Checker(a.root).run()
    for e in errs:
        print(e)
    print(f"check_deps: {'通过' if not errs else f'{len(errs)} 处违规'}")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
