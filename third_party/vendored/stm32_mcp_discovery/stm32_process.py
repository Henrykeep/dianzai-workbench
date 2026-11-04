# Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b process.py （MIT, Copyright (c) 2026 Helistana；原样，仅加这两行头）
# 经 app/sidecar/dzbench/cubemx.py 调用；见同目录 SOURCE.md
"""
Subprocess execution helpers and OpenOCD session management.

Highlights:
  * run() kills the whole process tree on timeout (taskkill /T /F on Windows),
    preventing orphaned CubeIDE / OpenOCD processes.
  * OpenOCDSession polls the GDB port for readiness instead of sleeping a
    fixed duration, and avoids port collisions by bumping to a free port.
"""

import asyncio
import locale
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time

from stm32_discovery import get_tool  # 改：上游模块名 discovery，本仓库改名 stm32_discovery

_DEBUG_LOG = os.environ.get("ST_DEBUG_LOG", "")


def _trace(msg: str) -> None:
    if _DEBUG_LOG:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.monotonic():.2f}] {msg}\n")


def _decode(data: bytes) -> str:
    """Best-effort decode of tool output (handles UTF-8 and GBK)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode(locale.getpreferredencoding(False),
                               errors="replace")
        except LookupError:
            return data.decode("utf-8", errors="replace")


def _process_kwargs() -> dict:
    """Extra kwargs so child processes can be killed as a group."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill a process and its whole child tree."""
    if proc is None or proc.pid is None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


async def run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a command asynchronously, return (returncode, stdout, stderr).

    On timeout the whole process tree is killed and RuntimeError raised.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **_process_kwargs(),
    )
    _trace(f"gdb_run: started pid={proc.pid}")
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        _trace(f"gdb_run: finished rc={proc.returncode}")
    except asyncio.TimeoutError:
        _kill_tree(proc)
        try:
            await proc.wait()
        except Exception:
            pass
        raise RuntimeError(f"命令超时（{timeout}s）: {' '.join(cmd)}")
    return (
        proc.returncode,
        _decode(stdout),
        _decode(stderr),
    )


async def gdb_run(commands: list[str], elf_path: str = "",
                  timeout: int = 30) -> str:
    """Run GDB in batch mode with the given commands (via a temp script).

    Returns combined stdout + stderr.
    """
    gdb = get_tool("gdb")

    fd, script_path = tempfile.mkstemp(suffix=".gdb", prefix="gdb_cmd_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(commands))

        cmd = [gdb, "-batch", "-x", script_path]
        if elf_path:
            cmd.append(elf_path)

        returncode, stdout, stderr = await run(cmd, timeout=timeout)
        return stdout + "\n" + stderr
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


# ── port helpers ───────────────────────────────────────────────────────────

def find_free_port(start: int, tries: int = 20) -> int:
    """Return the first free TCP port at or above `start`."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"端口 {start}~{start + tries - 1} 均被占用")


async def _tcp_connect_ok(host: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError:
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return True


# ── OpenOCD session ────────────────────────────────────────────────────────

class OpenOCDSession:
    """A managed OpenOCD background process with ready-polling and cleanup."""

    def __init__(self, gdb_port: int = 3333, telnet_port: int = 4444):
        self.proc: asyncio.subprocess.Process | None = None
        self.gdb_port = gdb_port
        self.telnet_port = telnet_port
        self.stderr_tail = ""
        self._stderr_task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, mcu_family: str,
                    ready_timeout: float = 15.0) -> tuple[int, int]:
        """Start OpenOCD for the given MCU family. Returns (gdb, telnet) ports."""
        if self.running:
            return self.gdb_port, self.telnet_port

        openocd = get_tool("openocd")
        scripts = get_tool("openocd_scripts")
        core_scripts = get_tool("openocd_core_scripts")

        # Prefer the new direct-SWD st-link adapter (stlink-dap.cfg); the legacy
        # hla adapter (stlink.cfg) recurses with modern OpenOCD builds.
        iface_cfg = os.path.join(scripts, "interface", "stlink-dap.cfg")
        if not os.path.isfile(iface_cfg):
            iface_cfg = os.path.join(scripts, "interface", "stlink.cfg")
        target_cfg = os.path.join(scripts, "target", mcu_family)
        if not os.path.isfile(target_cfg):
            raise FileNotFoundError(f"未找到 OpenOCD 目标配置: {target_cfg}")

        self.gdb_port = find_free_port(3333)
        self.telnet_port = find_free_port(4444)

        cmd = [
            openocd,
            "-s", core_scripts,
            "-s", scripts,
            "-f", iface_cfg,
            "-f", target_cfg,
            "-c", f"gdb_port {self.gdb_port}",
            "-c", f"telnet_port {self.telnet_port}",
        ]
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_process_kwargs(),
        )
        _trace(f"openocd: started pid={self.proc.pid} rc={self.proc.returncode} cmd={' '.join(cmd)}")
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._wait_ready(ready_timeout)
        _trace(f"openocd: ready on {self.gdb_port}, stderr_tail_len={len(self.stderr_tail)}")
        return self.gdb_port, self.telnet_port

    async def _drain_stderr(self) -> None:
        chunks: list[bytes] = []
        try:
            while True:
                data = await self.proc.stderr.read(4096)
                if not data:
                    break
                chunks.append(data)
                _trace(f"openocd: stderr +{len(data)}B (total {sum(len(c) for c in chunks)})")
        except Exception as exc:
            _trace(f"openocd: drain exception {type(exc).__name__}: {exc}")
        self.stderr_tail = b"".join(chunks)[-4000:].decode(errors="replace")

    async def _wait_ready(self, timeout: float) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.proc.returncode is not None:
                raise RuntimeError(
                    f"OpenOCD 启动失败: {self.stderr_tail or '进程退出'}"
                )
            if await _tcp_connect_ok("127.0.0.1", self.gdb_port):
                return
            await asyncio.sleep(0.2)
        raise RuntimeError(
            f"OpenOCD 启动超时（{timeout}s），端口 {self.gdb_port} 未就绪"
        )

    async def stop(self) -> None:
        if self.proc is None:
            return
        _kill_tree(self.proc)
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=5)
        except Exception:
            pass
        if self._stderr_task is not None:
            self._stderr_task.cancel()
        self.proc = None
        self._stderr_task = None
