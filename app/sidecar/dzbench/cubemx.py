"""CubeMX 无头生成代码（项目 ③ 从零新建：写出 .ioc 后自动 GENERATE CODE，不用你打开 CubeMX 点）。

找 CubeMX 用 vendored 的 mcp-stm32cubeide-server discovery.py（MIT，third_party/vendored/stm32_mcp_discovery/）；
生成脚本照搬同仓库 tools.py tool_generate_code：写一个命令脚本，`STM32CubeMX -q 脚本`。
找不到 CubeMX → available() 为 False，调用方退回“合成 Core + 你手动点一次 GENERATE”（gen_core.py）。
进程管理用同仓库 process.py（MIT，vendored 为 stm32_process.py）：子进程独立进程组、超时杀整个进程树（Windows taskkill /T，POSIX killpg）。
无头构建照搬同仓库 tools.py build_command（CubeIDE headlessbuild -import -build/-cleanBuild）。
⚠ 本机没装 CubeMX：脚本与调用方式按上游，真 CubeMX 未实测；测试用假 CubeMX 可执行文件。
"""
from __future__ import annotations

import os
import pathlib
import asyncio
import sys
import tempfile

_P = pathlib.Path(__file__).resolve().parents[3] / "third_party" / "vendored" / "stm32_mcp_discovery"
if _P.is_dir() and str(_P) not in sys.path:
    sys.path.insert(0, str(_P))

import stm32_discovery as D  # noqa: E402
import stm32_process as P  # noqa: E402


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


def find_cubeide() -> str | None:
    try:
        return D.get_tool("cubeide")
    except Exception:  # noqa: BLE001
        return None


def _run(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    """上游 process.run：超时杀整个进程树后抛 RuntimeError。侧车 op 在线程池里跑，这里自建事件循环。"""
    return asyncio.run(P.run(cmd, timeout=int(max(1, timeout))))


def generate(ioc: str | os.PathLike, toolchain: str = "keil", timeout: float = 180) -> dict:
    """在 .ioc 所在目录生成代码。返回 {ok, exe, out}；没装 CubeMX 返回 ok=False, why, reason_code。"""
    exe = find()
    if not exe:
        return {"ok": False, "reason_code": "missing_cubemx", "why": "没找到 STM32CubeMX（装好后或设 CUBEMX_PATH 再试）；先用合成 Core，之后手动 GENERATE 一次"}
    ioc = pathlib.Path(ioc).resolve()
    fd, sp = tempfile.mkstemp(suffix=".txt", prefix="cubemx_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(script(ioc, ioc.parent, toolchain))
    try:
        rc, so, se = _run([exe, "-q", sp], timeout)
        ok = rc == 0 and (ioc.parent / "Core" / "Src" / "main.c").exists()   # 上游写法：输出目录 = .ioc 所在目录
        return {"ok": ok, "exe": exe, "out": (so + se)[-4000:],
                **({} if ok else {"why": f"CubeMX 返回 {rc}，或没生成 Core/Src/main.c"})}
    except RuntimeError:
        return {"ok": False, "exe": exe, "reason_code": "tool_timeout", "why": f"CubeMX {timeout:g} s 没结束，已结束整个进程树"}
    finally:
        os.unlink(sp)


def build_command(cubeide: str, workspace: str, project_path: str, config: str = "Debug", clean: bool = False) -> list[str]:
    """与上游 tools.py build_command 一致。"""
    name = os.path.basename(os.path.normpath(project_path))
    return [cubeide, "--launcher.suppressErrors", "-nosplash",
            "-application", "org.eclipse.cdt.managedbuilder.core.headlessbuild",
            "-data", workspace, "-import", project_path,
            "-cleanBuild" if clean else "-build", f"{name}/{config}"]


def build(project_path: str | os.PathLike, config: str = "Debug", clean: bool = False, timeout: float = 300) -> dict:
    """CubeIDE 无头构建（不开界面）。workspace 放系统临时目录（上游做法），每台机器自适应，不写死路径。"""
    exe = find_cubeide()
    if not exe:
        return {"ok": False, "reason_code": "missing_cubeide", "why": "没找到 STM32CubeIDE"}
    ws = os.path.join(tempfile.gettempdir(), "dz_cubeide_ws")
    os.makedirs(ws, exist_ok=True)
    try:
        rc, so, se = _run(build_command(exe, ws, str(pathlib.Path(project_path).resolve()), config, clean), timeout)
    except RuntimeError:
        return {"ok": False, "exe": exe, "reason_code": "tool_timeout", "why": f"CubeIDE {timeout:g} s 没结束，已结束整个进程树"}
    errs = [ln for ln in (so + se).splitlines() if ": error:" in ln or "undefined reference" in ln]
    return {"ok": rc == 0, "exe": exe, "rc": rc, "errors": errs[:20], "out": (so + se)[-4000:]}


def status(tool_id: str) -> dict:
    if tool_id == "cubeide_build":
        return {"status": "available"} if find_cubeide() else {"status": "missing_dep", "reason_code": "missing_cubeide"}
    return {"status": "available"} if find() else {"status": "missing_dep", "reason_code": "missing_cubemx"}
