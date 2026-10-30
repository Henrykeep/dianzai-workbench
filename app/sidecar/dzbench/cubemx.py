"""CubeMX 无头生成代码（项目 ③ 从零新建：写出 .ioc 后自动 GENERATE CODE，不用你打开 CubeMX 点）。

找 CubeMX 用 vendored 的 mcp-stm32cubeide-server discovery.py（MIT，third_party/vendored/stm32_mcp_discovery/）；
生成脚本照搬同仓库 tools.py tool_generate_code：写一个命令脚本，`STM32CubeMX -q 脚本`。
找不到 CubeMX → available() 为 False，调用方退回“合成 Core + 你手动点一次 GENERATE”（gen_core.py）。
⚠ 本机没装 CubeMX：脚本与调用方式按上游，真 CubeMX 未实测；测试用假 CubeMX 可执行文件。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

_P = pathlib.Path(__file__).resolve().parents[3] / "third_party" / "vendored" / "stm32_mcp_discovery"
if _P.is_dir() and str(_P) not in sys.path:
    sys.path.insert(0, str(_P))

import stm32_discovery as D  # noqa: E402

TOOLCHAIN = {"keil": "MDK-ARM V5", "cubeide": "STM32CubeIDE", "cmake": "CMake", "makefile": "Makefile"}


def find() -> str | None:
    try:
        return D.get_tool("cubemx")
    except Exception:  # noqa: BLE001  上游找不到时抛 FileNotFoundError 等
        return None


def script(ioc: pathlib.Path, out: pathlib.Path, toolchain: str = "keil") -> str:
    """与上游 tool_generate_code 逐行一致（project name = 输出目录名，project path = 输出目录）。"""
    return (f"config load {ioc}\nproject toolchain {TOOLCHAIN.get(toolchain, toolchain)}\n"
            f"project name {out.name or ioc.stem}\nproject path {out}\nproject generate\nexit\n")


def generate(ioc: str | os.PathLike, toolchain: str = "keil", timeout: float = 180) -> dict:
    """在 .ioc 所在目录生成代码。返回 {ok, exe, out}；没装 CubeMX 返回 ok=False, why。"""
    exe = find()
    if not exe:
        return {"ok": False, "why": "没找到 STM32CubeMX（装好后或设 CUBEMX_PATH 再试）；先用合成 Core，之后手动 GENERATE 一次"}
    ioc = pathlib.Path(ioc).resolve()
    fd, sp = tempfile.mkstemp(suffix=".txt", prefix="cubemx_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(script(ioc, ioc.parent, toolchain))
    try:
        p = subprocess.run([exe, "-q", sp], capture_output=True, text=True, timeout=timeout)
        ok = p.returncode == 0 and (ioc.parent / "Core" / "Src" / "main.c").exists()   # 上游写法：输出目录 = .ioc 所在目录
        return {"ok": ok, "exe": exe, "out": (p.stdout + p.stderr)[-4000:],
                **({} if ok else {"why": f"CubeMX 返回 {p.returncode}，或没生成 Core/Src/main.c"})}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exe": exe, "why": f"CubeMX {timeout:g} s 没结束"}
    finally:
        os.unlink(sp)
