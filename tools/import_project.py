#!/usr/bin/env python3
"""import_project.py —— 把你自己的 CubeMX 工程（.ioc + Core/，Keil 或 GCC 生成都行）直接变成工作台板卡。

原则：顺着你的习惯，不要求你改。
  * 不用回 CubeMX 改 User Label：按引脚功能自动给出别名表 boards/<板>/aliases.yaml（AIN1→MOTOR_A_IN1、
    PWMA→PWM_MOTOR_A、编码器定时器→ENC_MOTOR_A…），你只需看一眼、不对就改这个小文件。.ioc 一个字不动。
  * 没有空闲节拍定时器也不用回 CubeMX：挑一个芯片上没用到的定时器由工作台自建（board.yaml timer.self_init）。
  * main.c 里你自己写的代码不删：整块搬进 boards/<板>/user_code/（不参与编译，原样保留，方便以后拆成子系统），
    再在 USER CODE 区里放三行钩子。USER CODE 标记被改坏时不猜：停下来给出修复 diff，--accept-repair 才写。
  * Keil(MDK-ARM) 生成的工程没有 GCC 链接脚本：自动从 ports/stm32-cubemx/ld/ 模板补；启动文件用 CMSIS 模板。
  * 你的原工程目录只读，所有改动都在 boards/<板>/ 的副本里。

用法：
  python3 tools/import_project.py <CubeMX工程目录> [--name 板名] [--app car_2wd] [--accept-repair] [--force]
结束时打印“还需要人做的事”清单（--report x.json 另存），tools/test_import_project.py 用它防回退。
"""
from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import re
import shutil
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ioc_import as ii  # noqa: E402
from boardlib import user_boards_dir  # noqa: E402

SKIP_DIRS = {"Core", "Drivers", "Middlewares", "MDK-ARM", "EWARM", "STM32CubeIDE", ".git", "build", "Debug", "Release"}
KEEP_TAGS = {"WHILE", "Header", "Error_Handler_Debug", "6", "Header_StartDefaultTask", "Callback 0"}
# 与移植层冲突、必须挪走的回调（ioc_import.check_project 同一份清单）
CONFLICT_CB = ("HAL_TIM_PeriodElapsedCallback", "HAL_UART_RxCpltCallback", "HAL_UART_ErrorCallback",
               "HAL_UARTEx_RxEventCallback", "HAL_UART_TxCpltCallback")
# 芯片 → (flash 上限 KB, SRAM KB, 有哪些通用/高级/基本定时器)
def chip_info(part: str) -> tuple[int, int, list[str]]:
    p = part.upper()
    m = re.match(r"STM32F10[0-7].([4-9A-G])", p)
    if m:
        d = m[1]
        fl = {"4": 16, "6": 32, "8": 64, "B": 128, "C": 256, "D": 384, "E": 512, "F": 768, "G": 1024}[d]
        ram = {"4": 6, "6": 10, "8": 20, "B": 20, "C": 48, "D": 64, "E": 64, "F": 96, "G": 96}[d]
        tims = [1, 2, 3] if d in "46" else [1, 2, 3, 4] if d in "8B" else [1, 2, 3, 4, 5, 6, 7, 8]
        return max(fl, 128) if d in "8B" else fl, ram, [f"TIM{t}" for t in tims]
    if re.match(r"STM32F4(05|07|15|17|27|29|37|39|46)", p):
        fl = {"E": 512, "G": 1024, "I": 2048}.get(p[10:11], 1024)
        return fl, 128, [f"TIM{t}" for t in range(1, 9)]
    if re.match(r"STM32F4(01|11)", p):
        return 512, 64 if p.startswith("STM32F401") else 128, ["TIM1", "TIM2", "TIM3", "TIM4", "TIM5"]
    raise SystemExit(f"✗ 还不认识芯片 {part}（import_project 目前支持 STM32F1 / F4）；手工流程见 docs/05")


TICK_PREF = ["TIM6", "TIM7", "TIM5", "TIM4", "TIM3", "TIM2", "TIM1", "TIM8"]


def slug(s: str) -> str:
    return ii.board_slug(s)


# ---------------------------------------------------------------- 别名建议
def suggest_alias(ioc: dict) -> tuple[dict, list[str]]:
    """按引脚功能给出 引脚 → 约定标签。已经符合约定的标签不动。返回 (alias, 说明行)。"""
    rep = ii.Rep()
    res, _ = ii.extract(ioc, {}, rep)
    pins = ii.pins_of(ioc)
    alias, why = {}, []
    conv = re.compile(r"^(GPIO|PWM|ENC|UART|ADC|DAC)_")
    def lab(pin):
        return (pins.get(pin) or {}).get("GPIO_Label", "")
    def put(pin, new, how):
        if conv.match(lab(pin) or ""):
            return
        alias[pin] = new
        why.append(f"{pin}: {new:<22} # {how}")
    # PWM：标签里带 A/B、L/R 的先对号入座，其余按定时器通道顺序给 MOTOR_A、MOTOR_B
    want = ["MOTOR_A", "MOTOR_B"]
    pwm = res.get("pwm", [])
    used = set()
    def hint(name):
        n = name.upper()
        if re.search(r"(^|_)(A|L|LEFT)$|PWMA|^A$", n):
            return "MOTOR_A"
        if re.search(r"(^|_)(B|R|RIGHT)$|PWMB|^B$", n):
            return "MOTOR_B"
        return None
    plan = {}
    for r in pwm:
        h = hint(lab(r["pin"]) or "")
        if h and h not in used and "SERVO" not in (lab(r["pin"]) or "").upper():
            plan[r["pin"]] = h; used.add(h)
    for r in pwm:
        if r["pin"] not in plan and "SERVO" not in (lab(r["pin"]) or "").upper():
            free = [w for w in want if w not in used]
            if free:
                plan[r["pin"]] = free[0]; used.add(free[0])
    for r in pwm:
        if r["pin"] in plan:
            put(r["pin"], f"PWM_{plan[r['pin']]}", f"{r['timer']}_CH{r['channel']} PWM，原标签 {lab(r['pin']) or '无'}")
    # 编码器：按定时器编号给 MOTOR_A、MOTOR_B
    for i, r in enumerate(res.get("encoder", [])[:2]):
        n = want[i]
        put(r["pin_a"], f"ENC_{n}_A", f"{r['timer']} 编码器模式 A 相")
        put(r["pin_b"], f"ENC_{n}_B", f"{r['timer']} 编码器模式 B 相")
    # 串口：标签有提示用提示，否则 USART1（没有就编号最小的）当 LINK，下一个当 AUX
    hints = [(r"VIS|CAM|K230|MAIX|OPENMV", "VISION"), (r"IMU|JY|GYRO", "IMU"), (r"LINK|PC|DEBUG|BLE|BT|WIFI", "LINK")]
    uarts = sorted(res.get("uart", []), key=lambda r: (not r["instance"].startswith("USART"), int(re.sub(r"\D", "", r["instance"]) or 0)))
    names, taken = {}, set()
    for r in uarts:
        t = (lab(r["tx"]) or "") + (lab(r["rx"]) or "")
        for pat, n in hints:
            if re.search(pat, t.upper()) and n not in taken:
                names[r["instance"]] = n; taken.add(n); break
    for r in uarts:
        if r["instance"] not in names:
            for n in ("LINK", "AUX"):
                if n not in taken:
                    names[r["instance"]] = n; taken.add(n); break
    for r in uarts:
        if r["instance"] in names:
            n = names[r["instance"]]
            put(r["tx"], f"UART_{n}_TX", f"{r['instance']} TX（" + ("按原标签" if n not in ("LINK", "AUX") else "默认：第一个串口当上位机链路 LINK" if n == "LINK" else "默认：第二个串口当 AUX") + "）")
            put(r["rx"], f"UART_{n}_RX", f"{r['instance']} RX")
    # GPIO：TB6612/L298 方向脚、LED、蜂鸣器、待机脚
    for r in res.get("gpio", []):
        n = (lab(r["pin"]) or "").upper()
        m = re.fullmatch(r"([AB])_?IN_?([12])", n)
        if m:
            put(r["pin"], f"GPIO_MOTOR_{m[1]}_IN{m[2]}", f"原标签 {lab(r['pin'])}（TB6612 方向脚）")
        elif re.fullmatch(r"(LED\d?|BEEP|BUZZ(ER)?|STBY)", n):
            put(r["pin"], "GPIO_" + {"BEEP": "BUZZER", "BUZZ": "BUZZER"}.get(n, n if n != "STBY" else "MOTOR_STBY"), f"原标签 {lab(r['pin'])}")
    return alias, why


def pick_ctrl(ioc: dict, part: str, rtos: bool) -> tuple[str, str]:
    """节拍定时器：.ioc 里已有“开中断、没引脚”的定时器就用它；否则挑芯片上没被用到的，由工作台自建。"""
    rep = ii.Rep()
    res, meta = ii.extract(ioc, {}, rep)
    t = res.get("timer") or []
    if t:
        return t[0]["instance"], f"沿用你 .ioc 里已开中断、没接引脚的 {t[0]['instance']}"
    ips = {v for k, v in ioc.items() if re.fullmatch(r"Mcu\.IP\d+", k)}
    tb = meta.get("hal_timebase", "SysTick")
    _, _, have = chip_info(part)
    for c in TICK_PREF:
        if c in have and c not in ips and c != tb and not (c == "TIM6" and "DAC" in ips):
            return c + ":self", f"{c} 在你的工程里没用到，由工作台自建（不用回 CubeMX 加定时器）"
    raise SystemExit("✗ 芯片上所有定时器都被占用了：在 CubeMX 里让出一个（Clock Source=Internal + 开更新中断），或把一路 PWM 挪到别的定时器")


# ---------------------------------------------------------------- USER CODE 处理（按字节、latin-1 往返，保留 GBK/UTF-8 原样）
TOK = re.compile(r"/\* USER CODE (BEGIN|END) ([^*]+?) \*/")


def blocks(text: str):
    """返回 [(tag, 内容起点, 内容终点)]；标记不成对/交叉时返回 (None, 问题描述)。"""
    out, stack = [], []
    for m in TOK.finditer(text):
        kind, tag = m[1], m[2].strip()
        if kind == "BEGIN":
            if stack:
                return None, f"USER CODE BEGIN {tag} 出现在 BEGIN {stack[-1][0]} 还没 END 的地方（第 {text[:m.start()].count(chr(10)) + 1} 行）"
            stack.append((tag, m.end()))
        else:
            if not stack or stack[-1][0] != tag:
                exp = stack[-1][0] if stack else "（无）"
                return None, f"第 {text[:m.start()].count(chr(10)) + 1} 行 USER CODE END {tag} 与前面的 BEGIN {exp} 对不上"
            t, s = stack.pop()
            out.append((t, s, m.start()))
    if stack:
        return None, f"USER CODE BEGIN {stack[-1][0]} 没有对应的 END"
    return out, ""


def repair_while(text: str) -> str | None:
    """最常见的损坏：把 while(1) 整段写在 BEGIN WHILE … END 3 之间，删掉了 END WHILE / BEGIN 3。
    修复只补回 CubeMX 的标记和 while 骨架，你的代码一字不改地落进 USER CODE 3（随后整块搬进 user_code/）。"""
    m = re.search(r"(/\* USER CODE BEGIN WHILE \*/)(.*?)(\n[ \t]*/\* USER CODE END 3 \*/)", text, re.S)
    if not m or "USER CODE END WHILE" in m[2] or "USER CODE BEGIN 3" in m[2]:
        return None
    body = m[2]
    skel = "\n  while (1)\n  {\n    /* USER CODE END WHILE */\n\n    /* USER CODE BEGIN 3 */" + body + "\n  }"
    return text[:m.end(1)] + skel + text[m.start(3):]


def process_file(path: pathlib.Path, inserts: dict[str, str], move_all: bool, moved: list, label: str):
    """把 USER CODE 块里的用户代码搬走（move_all=False 时只搬含冲突回调的块），并在指定块里放钩子。"""
    text = path.read_bytes().decode("latin-1")
    bl, err = blocks(text)
    if bl is None:
        return err
    out, pos = [], 0
    for tag, s, e in bl:
        content = text[s:e]
        has_code = bool(re.sub(r"\s+", "", re.sub(r"/\*.*?\*/|//[^\n]*", "", content, flags=re.S)))
        conflict = any(re.search(rf"\b{cb}\s*\(", content) and re.search(rf"^\s*void\s+{cb}\s*\(", content, re.M) for cb in CONFLICT_CB)
        new = content
        if tag not in KEEP_TAGS and has_code and (move_all or conflict):
            tail = ""
            if tag == "3":
                # CubeMX 把 while(1) 的右花括号生成在 USER CODE 3 里：它属于骨架，留下
                k = content.rstrip().rfind("}")
                if k >= 0 and not content.rstrip()[k + 1:].strip():
                    content, tail = content.rstrip()[:k], "\n  }\n  "
            moved.append((label, tag, content))
            new = "\n" + tail
        if tag in inserts and inserts[tag].strip() not in new:
            ind = "  " if tag not in ("Includes",) else ""
            new = "\n" + "".join(ind + ln + "\n" for ln in inserts[tag].split("\n")) + (new.lstrip("\n") if new.strip() else "  ")
        out.append(text[pos:s] + new)
        pos = e
    out.append(text[pos:])
    path.write_bytes("".join(out).encode("latin-1"))
    return ""


def show(s: str) -> str:
    """latin-1 往返的文本按 UTF-8 / GBK 还原给人看。"""
    try:
        b = s.encode("latin-1")
    except UnicodeEncodeError:
        return s
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=pathlib.Path, help="你的 CubeMX 工程目录（有 .ioc 和 Core/）")
    ap.add_argument("--name", help="板名（默认由目录名转成 a-z0-9-）")
    ap.add_argument("--app", help="顺便检查这个应用的 requires（如 car_2wd）")
    ap.add_argument("--root", type=pathlib.Path, default=ROOT, help="工作台根目录（测试用）")
    ap.add_argument("--accept-repair", action="store_true", help="USER CODE 标记损坏时，接受打印出的修复")
    ap.add_argument("--force", action="store_true", help="板卡目录已存在时覆盖（别名表 aliases.yaml 若已存在会保留）")
    ap.add_argument("--report", type=pathlib.Path, help="把“还需要人做的事”写成 JSON")
    a = ap.parse_args()

    src = a.project.resolve()
    iocs = sorted(src.glob("*.ioc"))
    if len(iocs) != 1:
        raise SystemExit(f"✗ {src} 下应有且只有一个 .ioc，找到 {[p.name for p in iocs]}")
    if not (src / "Core/Src/main.c").exists():
        raise SystemExit(f"✗ {src}/Core/Src/main.c 不存在：CubeMX 里 Generate Code 后再导入")
    name = a.name or slug(src.name)
    if name == "my-board":
        name = slug(iocs[0].stem)
    dest = user_boards_dir() / name           # #29：用户板卡写 $DZ_BOARDS_DIR（默认 $DZBENCH_HOME/boards），不进仓库 boards/
    keep_alias = None
    if dest.exists():
        if not a.force:
            raise SystemExit(f"✗ {dest} 已存在（--force 覆盖；别名表会保留）")
        if (dest / "aliases.yaml").exists():
            keep_alias = (dest / "aliases.yaml").read_text(encoding="utf-8")
        shutil.rmtree(dest)
    cube = dest / "cubemx"
    cube.mkdir(parents=True)
    shutil.copy2(iocs[0], cube / iocs[0].name)
    shutil.copytree(src / "Core", cube / "Core")
    todo: list[dict] = []        # 还需要人做的事：kind = confirm（看一眼确认）/ edit（必须动手改）/ observe（上板看）

    # 用户自己的源码目录原样备份（不编译）：APP/、HARDWARE/、User/ …
    n_user = 0
    for f in src.rglob("*"):
        rel = f.relative_to(src)
        if f.is_file() and f.suffix.lower() in (".c", ".h", ".cpp", ".hpp", ".s") and rel.parts[0] not in SKIP_DIRS:
            d = dest / "user_code" / "orig" / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, d)
            n_user += 1

    ioc = ii.parse_ioc((cube / iocs[0].name).read_text(encoding="utf-8", errors="replace"))
    part = ioc.get("Mcu.CPN") or ioc.get("Mcu.UserName", "")
    flash_max, ram_kb, _ = chip_info(part)

    # 1) 别名表
    if keep_alias is not None:
        (dest / "aliases.yaml").write_text(keep_alias, encoding="utf-8")
        alias = ii.load_alias(dest / "aliases.yaml")
        why = ["（沿用已有 aliases.yaml）"]
    else:
        alias, why = suggest_alias(ioc)
        (dest / "aliases.yaml").write_text(
            "# 引脚别名表（tools/import_project.py 按引脚功能自动生成）：引脚 → 工作台逻辑标签。\n"
            "# 你的 .ioc 不用改；哪一行猜错了（比如左右电机反了），改这里，然后\n"
            f"#   python3 tools/ioc_import.py {dest}/cubemx/{iocs[0].name} --out {dest}/board.yaml --base {dest}/board.yaml\n"
            "pins:\n" + "".join(f"  {w}\n" for w in why), encoding="utf-8")
    if alias:
        todo.append({"kind": "confirm", "what": f"看一眼 {dest}/aliases.yaml 的 {len(alias)} 条自动别名（电机 A/B、LINK 串口是按顺序猜的）"})

    # 2) 节拍定时器 + board.yaml
    meta0 = ii.extract(ii.apply_alias(ioc, alias), {}, ii.Rep())[1]
    rtos = bool(meta0.get("rtos"))
    ctrl, ctrl_why = pick_ctrl(ii.apply_alias(ioc, alias), part, rtos)
    rep = ii.Rep()
    res, meta = ii.extract(ii.apply_alias(ioc, alias), {"CTRL": ctrl}, rep)
    for t in res.get("timer", []):
        if t.get("self_init") and rtos:
            t["irq_priority"] = 5
    board = ii.build_board(res, meta, None, f"cubemx/{iocs[0].name}")
    board["name"] = name
    board["description"] = f"由 tools/import_project.py 从 {src.name} 导入（用户原工程，未改 .ioc）"
    board["config_source"]["alias"] = "aliases.yaml"
    (dest / "board.yaml").write_text("# 由 tools/import_project.py 生成；引脚改 .ioc 或 aliases.yaml 后用 ioc_import --base 重新导入\n"
                                     + yaml.safe_dump(board, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for c, e in rep.errors:
        todo.append({"kind": "edit", "what": f"[{c}] {e}"})
    if meta.get("hse_hz") in (None, "TODO") or any("HSE_VALUE" in w for w in rep.warnings):
        todo.append({"kind": "observe", "what": "晶振按默认 8 MHz，对照板上晶振丝印确认"})

    # 3) 链接脚本
    notes = [f"节拍定时器 CTRL：{ctrl_why}"]
    if not list(cube.glob("*_FLASH.ld")):
        fam = meta["family"]
        tpl = ROOT / "ports/stm32-cubemx/ld" / f"{fam}_FLASH.ld.in"
        if not tpl.exists():
            todo.append({"kind": "edit", "what": f"没有 {fam} 的链接脚本模板：CubeMX 里 Toolchain 选 Makefile 再生成一次，把 *_FLASH.ld 放进 cubemx/"})
        else:
            t = tpl.read_text(encoding="utf-8").replace("@FLASH_MAX_KB@", str(flash_max)).replace("@RAM_KB@", str(ram_kb))
            (cube / f"{part[:11].upper()}_FLASH.ld").write_text(t, encoding="utf-8")
            notes.append(f"工程是 Keil 生成的、没有 GCC 链接脚本：已按 {part}（Flash ≤{flash_max} KB，SRAM {ram_kb} KB）从模板补上")

    # 4) main.c / freertos.c：搬走用户代码 + 放钩子
    moved: list = []
    main_c = cube / "Core/Src/main.c"
    tim_tb = meta.get("hal_timebase", "SysTick") != "SysTick"
    ins = {"Includes": '#include "dz_cubemx.h"', "2": "dz_cubemx_start();"}
    if not rtos:
        ins["3"] = "  dz_cubemx_loop();"
    if tim_tb:
        ins["Callback 1"] = "dz_cubemx_tim_callback(htim);"
    t = main_c.read_bytes().decode("latin-1")
    bl, err = blocks(t)
    if bl is None:
        fixed = repair_while(t)
        print(f"✗ main.c 的 USER CODE 标记被改坏了：{err}")
        if fixed is None:
            print("  认不出损坏方式，不猜。请在 CubeMX 生成的结构里把 BEGIN/END 补成对，再导入。")
            shutil.rmtree(dest)
            return 2
        diff = difflib.unified_diff(t.split("\n"), fixed.split("\n"), "main.c（你的）", "main.c（修复后）", lineterm="", n=2)
        print("\n".join(show(x) for x in diff))
        if not a.accept_repair:
            print("\n上面是建议的修复：只补回 CubeMX 的 USER CODE 标记和 while 骨架，你的循环体一字不改、随后整段搬进 user_code/ 保留。确认后加 --accept-repair 重跑。")
            shutil.rmtree(dest)
            return 3
        main_c.write_bytes(fixed.encode("latin-1"))
        todo.append({"kind": "confirm", "what": "已按你的确认修复 main.c 的 USER CODE 标记（--accept-repair）"})
    e = process_file(main_c, ins, True, moved, "main.c")
    if e:
        raise SystemExit(f"✗ main.c：{e}")
    if rtos:
        fr = cube / "Core/Src/freertos.c"
        if fr.exists():
            e = process_file(fr, {"Includes": '#include "dz_cubemx.h"',
                                  "StartDefaultTask": "for (;;)\n{\n  dz_cubemx_loop();\n  osDelay(1);\n}"}, True, moved, "freertos.c")
            if e:
                raise SystemExit(f"✗ freertos.c：{e}")
    for f in sorted((cube / "Core/Src").glob("*.c")):
        if f.name not in ("main.c", "freertos.c"):
            e = process_file(f, {}, False, moved, f.name)
            if e:
                todo.append({"kind": "edit", "what": f"{f.name} 的 USER CODE 标记不成对（{e}），没动它"})
    if moved:
        uc = dest / "user_code"
        uc.mkdir(exist_ok=True)
        hdr = (f"/* 你原工程 Core/ 里 USER CODE 区的代码，由 tools/import_project.py 原样搬来（不参与编译，一行没删）。\n"
               " * 以后把它们拆成子系统：python3 tools/new_subsys.py <题目目录> <名字>，再把逻辑贴进 step()。\n"
               f" * 你自己的驱动源码（APP/、HARDWARE/…）备份在 user_code/orig/（{n_user} 个文件）。 */\n\n").encode("utf-8")
        for file, tag, c in moved:
            hdr += f"/* ===== {file} · USER CODE {tag} ===== */\n".encode("utf-8") + c.strip("\n").encode("latin-1") + b"\n\n"
        (uc / "from_core_user_code.c.txt").write_bytes(hdr)
        notes.append(f"搬走了 {len(moved)} 块你写在 Core/ 里的代码 → user_code/from_core_user_code.c.txt（不编译、不删）")

    # 5) 核对
    rep2 = ii.Rep()
    ii.check_project(cube, rep2, rtos=rtos, tim_timebase=tim_tb)
    for c, e in rep2.errors:
        todo.append({"kind": "edit", "what": f"[{c}] {e}"})
    if a.app:
        import subprocess
        app = next((p for p in (a.root / "apps" / a.app, a.root / "examples" / a.app) if p.exists()), None)
        if app and (app / "app.yaml").exists():
            r = subprocess.run([sys.executable, str(ROOT / "tools/validate_board.py"), str(dest / "board.yaml"), "--app", str(app / "app.yaml"), "-q"],
                               capture_output=True, text=True)
            for ln in (r.stdout + r.stderr).splitlines():
                if "缺资源" in ln:
                    todo.append({"kind": "edit", "what": ln.strip() + "（在 aliases.yaml 里给对应引脚起这个名字）"})

    print(f"✓ 已导入 {dest}/（原工程 {src} 未改动）")
    for n in notes:
        print(f"  · {n}")
    for w in why:
        print(f"  别名 {w}")
    edits = [t for t in todo if t["kind"] == "edit"]
    print(f"\n还需要人做的事：动手改 {len(edits)} 处，确认 {sum(t['kind'] == 'confirm' for t in todo)} 处，上板观察 {sum(t['kind'] == 'observe' for t in todo)} 处")
    for t in todo:
        print(f"  [{t['kind']}] {t['what']}")
    print(f"\n下一步：make BOARD={name} APP={a.app or 'port_selftest'}")
    if a.report:
        a.report.write_text(json.dumps({"board": name, "todo": todo, "moved_blocks": len(moved), "alias": alias,
                                        "ctrl": ctrl}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if edits else 0


if __name__ == "__main__":
    sys.exit(main())
