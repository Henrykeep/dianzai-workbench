"""一键自检（restudy A7，思路参考 llm-pid-tuner doctor.py，代码自写）。

`python -m dzbench --doctor [--repo 工程]`，或 UI 顶栏“自检”。每项返回 {id, name, level: ok/warn/fail, msg, fix}：
fail = 这条流程走不通；warn = 某些功能不可用（如没探针只能串口调参）。只读检查，不改任何东西。
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import subprocess

from . import config, snapshots
from .flash import find_pack, list_probes, M0_PACK


def _item(id_, name, level, msg, fix=""):
    return {"id": id_, "name": name, "level": level, "msg": msg, "fix": fix}


def _ver(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (r.stdout or r.stderr).splitlines()[0].strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return None


def run(repo: str | None = None, which=shutil.which, probes=None) -> list[dict]:
    out: list[dict] = []
    # 1 Python 依赖
    for mod, name, need, fix in (("serial", "pyserial（串口）", True, "pip install pyserial"),
                                 ("websockets", "websockets（UI 通信）", True, "pip install websockets"),
                                 ("pyocd", "pyOCD（烧录 / RTT）", False, "pip install pyocd；不装也能串口调参，只是不能一键烧录")):
        ok = importlib.util.find_spec(mod) is not None
        out.append(_item(f"py_{mod}", name, "ok" if ok else ("fail" if need else "warn"), "已安装" if ok else "没装", "" if ok else fix))
    # 2 工具链
    gcc = which("arm-none-eabi-gcc")
    out.append(_item("arm_gcc", "arm-none-eabi-gcc（交叉编译）", "ok" if gcc else "warn",
                     (_ver([gcc, "--version"]) or gcc) if gcc else "没找到",
                     "" if gcc else "装 Arm GNU Toolchain 并加入 PATH；只用 Keil / CCS 编译可以忽略"))
    mk = which("make")
    out.append(_item("make", "make", "ok" if mk else "warn", mk or "没找到",
                     "" if mk else "Windows 装 MSYS2 或用 Keil/CCS 编译；仿真板（host-sim）需要 make + gcc"))
    cfg, cerr = None, ""
    try:
        cfg = config.load(repo)
    except config.ConfigError as e:
        cerr = str(e)
    out.append(_item("config", "工程配置 dzbench.json", "fail" if cerr else "ok",
                     cerr or (f"{pathlib.Path(repo) / 'dzbench.json'}" if repo and (pathlib.Path(repo) / "dzbench.json").exists() else "用默认值（没有 dzbench.json）"),
                     "按提示改 JSON 语法或把密钥挪到 ~/.dzbench/" if cerr else ""))
    cfg = cfg or config.DEFAULTS
    uv4 = (cfg.get("build") or {}).get("keil_uv4")
    if uv4:
        ok = pathlib.Path(uv4).is_file()
        out.append(_item("keil", "Keil UV4", "ok" if ok else "fail", uv4 if ok else f"配置的路径不存在：{uv4}",
                         "" if ok else "在 ~/.dzbench/machine.json 的 build.keil_uv4 写对 UV4.exe 路径（通常 C:\\Keil_v5\\UV4\\UV4.exe）"))
    # 3 器件包 / 目标
    target = (cfg.get("flash") or {}).get("target")
    if not target:
        out.append(_item("target", "烧录目标 flash.target", "warn", "没配置", "dzbench.json 里写 flash.target，如 mspm0g3507 / stm32f407vetx"))
    elif target.lower().startswith("mspm0"):
        p = find_pack(target)
        out.append(_item("pack", "MSPM0 器件包（DFP）", "ok" if p else "fail", str(p) if p else f"找不到 {M0_PACK}",
                         "" if p else "运行 tools/fetch_third_party.sh m0pack，或联网 pyocd pack install mspm0g3507，或设 DZBENCH_PACK=包路径"))
    # 3b 调试后端（flash.tool：pyocd / openocd / jlink / probe-rs，见 dzbench/probes.py）
    from .probes import tool_status
    ts = tool_status(cfg.get("flash") or {})
    if ts["tool"] != "pyocd":
        out.append(_item("dbgtool", f"调试后端 {ts['tool']}", "ok" if ts["ok"] else "fail", ts.get("exe") or ts.get("why", ""),
                         ts.get("fix", "")))
    # 4 探针
    if importlib.util.find_spec("pyocd") is not None or probes is not None:
        try:
            ps = probes if probes is not None else list_probes()
            want = (cfg.get("flash") or {}).get("probe")
            if not ps:
                out.append(_item("probe", "调试探针", "warn", "没插探针（或驱动没装）", "插 DAPLink / ST-Link / XDS110；Windows 上 ST-Link 要装 ST 驱动"))
            elif want and not any(p["uid"] == want for p in ps):
                out.append(_item("probe", "调试探针", "fail", f"配置的探针 {want} 没插：现在有 " + "、".join(p["uid"] for p in ps),
                                 "插上那个探针，或把 ~/.dzbench/machine.json 的 flash.probe 改成上面某个序列号"))
            elif len(ps) > 1 and not want:
                out.append(_item("probe", "调试探针", "warn", "插了多个探针：" + "、".join(f"{p['uid']}（{p['desc']}）" for p in ps),
                                 "烧录时不会猜：在 ~/.dzbench/machine.json 写 flash.probe = 序列号，或拔掉多余的"))
            else:
                out.append(_item("probe", "调试探针", "ok", "、".join(f"{p['uid']}（{p['desc']}）" for p in ps)))
        except Exception as e:  # noqa: BLE001 —— 驱动层异常也要变成一条可读结果
            out.append(_item("probe", "调试探针", "warn", f"枚举探针出错：{e}", "检查 USB 驱动（Windows 用 Zadig 给 CMSIS-DAP 装 WinUSB）"))
    # 5 串口
    try:
        from serial.tools import list_ports as lp
        ports = list(lp.comports())
        out.append(_item("ports", "串口", "ok" if ports else "warn",
                         "、".join(f"{p.device}（{p.description}）" for p in ports) or "没有串口",
                         "" if ports else "插 USB 转串口；CH340 要装驱动（设备管理器里出现 COMx 才算好）。没硬件可以选仿真板"))
    except ImportError:
        pass
    # 6 大模型
    try:
        from .agent import llm
        has = bool(llm.load_config().get("api_key"))
    except Exception:  # noqa: BLE001
        has = False
    out.append(_item("llm", "Agent 大模型 Key", "ok" if has else "warn", "已配置" if has else "没配：Agent 不可用（其它功能不受影响）",
                     "" if has else "在 ⚙ 里填 Key（只存在本机 ~/.dzbench/config.json）；不填也能用"))
    # 7 数据目录可写
    d = snapshots.base_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".doctor"; t.write_text("x"); t.unlink()
        out.append(_item("home", "数据目录", "ok", str(d)))
    except OSError as e:
        out.append(_item("home", "数据目录", "fail", f"{d} 不可写：{e}", "设 DZBENCH_HOME 到一个可写目录"))
    return out


def render(items: list[dict]) -> str:
    mark = {"ok": "✓", "warn": "!", "fail": "✗"}
    lines = [f"{mark[i['level']]} {i['name']}：{i['msg']}" + (f"\n    → {i['fix']}" if i["fix"] else "") for i in items]
    n = sum(i["level"] == "fail" for i in items)
    return "\n".join(lines + [f"\n{'有 ' + str(n) + ' 项必须处理' if n else '没有阻塞项'}（! 只影响部分功能）"])
