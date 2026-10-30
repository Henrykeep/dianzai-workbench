# Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b discovery.py （MIT, Copyright (c) 2026 Helistana；原样，仅加这两行头）
# 经 app/sidecar/dzbench/cubemx.py 调用；见同目录 SOURCE.md
"""
Tool path discovery for STM32 development tools.

Lookup order for each tool:
  1. Environment variable (see _TOOL_ENV_VARS)
  2. PATH lookup (shutil.which)
  3. Windows registry (install dirs written by the installers)
  4. Known install locations (bounded glob, no full-disk recursion)

Results are cached.  The cache is invalidated automatically whenever a
cached path no longer exists on disk or the relevant env var changes.
"""

import glob
import os
import shutil
import sys
from pathlib import Path

# Map of tool key -> env var that can point to it directly.
_TOOL_ENV_VARS = {
    "cubeide": "CUBEIDE_PATH",
    "cubemx": "CUBEMX_PATH",
    "cubeprog": "CUBEPROG_PATH",
    "gdb": "ARM_GDB_PATH",
    "openocd": "OPENOCD_PATH",
    "openocd_scripts": "OPENOCD_SCRIPTS_PATH",
    "openocd_core_scripts": "OPENOCD_CORE_SCRIPTS_PATH",
}

_EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""

# Executable file names, used for PATH lookup.
_TOOL_EXE_NAMES = {
    "cubeide": "stm32cubeidec" + _EXE_SUFFIX,
    "cubemx": "STM32CubeMX" + _EXE_SUFFIX,
    "cubeprog": "STM32_Programmer_CLI" + _EXE_SUFFIX,
    "gdb": "arm-none-eabi-gdb" + _EXE_SUFFIX,
    "openocd": "openocd" + _EXE_SUFFIX,
}

# Relative glob patterns under each candidate install root.
# Patterns are bounded (no bare `**` over the whole drive).
if sys.platform == "win32":
    _ROOT_PATTERNS = {
        "cubeide": [
            "STM32CubeIDE_*/STM32CubeIDE/stm32cubeidec.exe",
            "STM32CubeIDE_*/stm32cubeidec.exe",
            "STM32CubeIDE/stm32cubeidec.exe",
        ],
        "cubemx": [
            "STM32CubeMX/STM32CubeMX.exe",
            "STM32CubeMX.exe",
        ],
        "cubeprog": [
            "STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe",
            "STM32CubeProgrammer/STM32_Programmer_CLI.exe",
        ],
        "gdb": [
            "STM32CubeIDE_*/STM32CubeIDE/plugins/*/tools/bin/arm-none-eabi-gdb.exe",
            "STM32CubeProgrammer/**/arm-none-eabi-gdb.exe",
        ],
        "openocd": [
            "STM32CubeIDE_*/STM32CubeIDE/plugins/*/tools/bin/openocd.exe",
            "STM32CubeProgrammer/**/openocd.exe",
        ],
    }
else:
    _ROOT_PATTERNS = {
        "cubeide": [
            "STM32CubeIDE_*/stm32cubeidec",
            "STM32CubeIDE_*/STM32CubeIDE/stm32cubeidec",
        ],
        "cubemx": [
            "STM32CubeMX/STM32CubeMX",
            "STM32CubeMX",
        ],
        "cubeprog": [
            "STM32CubeProgrammer/bin/STM32_Programmer_CLI",
            "STM32CubeProgrammer/STM32_Programmer_CLI",
        ],
        "gdb": [
            "STM32CubeIDE_*/STM32CubeIDE/plugins/*/tools/bin/arm-none-eabi-gdb",
        ],
        "openocd": [
            "STM32CubeIDE_*/STM32CubeIDE/plugins/*/tools/bin/openocd",
        ],
    }

# Fallback search roots used only when the bounded scan finds nothing.
if sys.platform == "win32":
    _FALLBACK_ROOTS = [
        "C:/ST",
        "C:/Program Files/STMicroelectronics",
        "C:/Program Files (x86)/STMicroelectronics",
        "D:/Program Files",
    ]
else:
    _FALLBACK_ROOTS = [
        "/opt/st",
        os.path.expanduser("~/ST"),
    ]

# Windows registry locations that may hold install dirs / exe paths.
# (subkey, [value names]) — value may be a directory or a full exe path.
_REGISTRY_QUERIES = [
    (r"STMicroelectronics\STM32CubeMX", ["Install_Dir", "Path", "Default"]),
    (r"STMicroelectronics\STM32CubeIDE", ["Install_Dir", "Path", "Default"]),
    (r"STMicroelectronics\STM32CubeProgrammer", ["Install_Dir", "Path", "Default"]),
    (r"STMicroelectronics\STM32CubeMX\stm32cubemx", ["Default"]),
]


def _known_roots() -> list[str]:
    """Default install roots that actually exist on this machine."""
    roots: list[str] = []
    for root in _FALLBACK_ROOTS:
        expanded = os.path.expandvars(root)
        if os.path.isdir(expanded) and expanded not in roots:
            roots.append(expanded)
    return roots


def _registry_roots() -> list[str]:
    """Best-effort Windows registry lookup for ST tool install dirs."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    roots: list[str] = []
    for rel, value_names in _REGISTRY_QUERIES:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for base in ("SOFTWARE", r"SOFTWARE\WOW6432Node"):
                full = base + "\\" + rel
                try:
                    with winreg.OpenKey(hive, full) as key:
                        for value_name in value_names:
                            try:
                                value, _ = winreg.QueryValueEx(key, value_name)
                            except OSError:
                                continue
                            if not isinstance(value, str) or not value.strip():
                                continue
                            expanded = os.path.expandvars(value.strip())
                            if expanded not in roots:
                                roots.append(expanded)
                            break
                except OSError:
                    continue
    return roots


def _scan_roots(roots: list[str]) -> dict[str, str]:
    """Glob the bounded patterns under each root. First match wins."""
    found: dict[str, str] = {}
    for tool, patterns in _ROOT_PATTERNS.items():
        for root in roots:
            for pattern in patterns:
                matches = glob.glob(os.path.join(root, pattern), recursive=True)
                if matches:
                    found[tool] = matches[0]
                    break
            if tool in found:
                break
    return found


def _openocd_scripts_for(exe: str) -> str | None:
    """Locate the OpenOCD scripts dir for a given openocd executable.

    Handles both layout generations used by STM32CubeIDE:
      * older: <plugins>/...externaltools.openocd.*/tools/share/openocd/scripts
      * 1.19+: <plugins>/...debug.openocd.*/resources/openocd/st_scripts
    """
    if not exe:
        return None
    bin_dir = Path(exe).parent

    for candidate in (
        bin_dir / ".." / "share" / "openocd" / "scripts",
        bin_dir / "scripts",
    ):
        if candidate.is_dir() and (candidate / "interface").is_dir() \
                and (candidate / "target").is_dir():
            return str(candidate.resolve())

    # Climb up to the <install>/STM32CubeIDE/plugins directory.
    plugins_dir = bin_dir
    for _ in range(8):
        if plugins_dir.name == "plugins":
            break
        if plugins_dir.parent == plugins_dir:
            plugins_dir = None
            break
        plugins_dir = plugins_dir.parent
    if plugins_dir is not None and plugins_dir.is_dir():
        for plugin in plugins_dir.glob("*openocd*"):
            for marker in ("st_scripts", "scripts"):
                for candidate in plugin.glob(f"**/{marker}"):
                    if (candidate / "interface").is_dir() \
                            and (candidate / "target").is_dir():
                        return str(candidate.resolve())
    return None


def _openocd_core_scripts_for(exe: str, st_scripts: str | None) -> str | None:
    """Locate the standard OpenOCD scripts dir (interface/target/swj-dp.tcl).

    On CubeIDE 1.19+ the ST-specific ``st_scripts`` lacks core scripts such
    as ``target/swj-dp.tcl``; those live in the externaltools openocd package
    (``<plugins>/...externaltools.openocd.*/tools/scripts``).  On older layouts
    the ST scripts dir already *is* the full scripts tree, so it is reused.
    """
    if st_scripts and os.path.isfile(os.path.join(st_scripts, "target", "swj-dp.tcl")):
        return st_scripts
    if exe:
        bin_dir = Path(exe).parent
        for candidate in (
            bin_dir / ".." / "scripts",
            bin_dir / ".." / "share" / "openocd" / "scripts",
            bin_dir / "scripts",
        ):
            if candidate.is_dir() \
                    and os.path.isfile(candidate / "target" / "swj-dp.tcl"):
                return str(candidate.resolve())
    return None


def _search_openocd_scripts(roots: list[str]) -> str | None:
    """Fallback: search for any directory containing interface/ and target/."""
    for root in roots:
        for candidate in glob.glob(os.path.join(root, "**", "scripts"), recursive=True):
            iface = os.path.join(candidate, "interface")
            tgt = os.path.join(candidate, "target")
            if os.path.isdir(iface) and os.path.isdir(tgt):
                return candidate
    return None


_discovery_cache: dict[str, str] | None = None
_discovery_env_snapshot: tuple[str, ...] | None = None


def reset_cache() -> None:
    """Force re-discovery on the next get_tool() call."""
    global _discovery_cache, _discovery_env_snapshot
    _discovery_cache = None
    _discovery_env_snapshot = None


def _env_snapshot() -> tuple[str, ...]:
    """Snapshot the env vars that affect discovery (for cache invalidation)."""
    return tuple(
        os.environ.get(key, "")
        for key in sorted(set(_TOOL_ENV_VARS.values()))
    )


def _discover_all() -> dict[str, str]:
    global _discovery_cache, _discovery_env_snapshot

    snapshot = _env_snapshot()
    if _discovery_cache is not None and _discovery_env_snapshot == snapshot:
        return _discovery_cache

    roots = _known_roots() + _registry_roots()
    result = _scan_roots(roots)

    # PATH lookup fills gaps (and beats registry/glob for user-installed tools).
    for tool in ("gdb", "openocd", "cubeprog", "cubemx", "cubeide"):
        if tool in result:
            continue
        resolved = shutil.which(_TOOL_EXE_NAMES[tool])
        if resolved:
            result[tool] = resolved

    # OpenOCD scripts: derive from found openocd, else fallback search.
    scripts = _openocd_scripts_for(result.get("openocd"))
    if not scripts:
        scripts = _search_openocd_scripts(roots)
    result["openocd_scripts"] = scripts
    result["openocd_core_scripts"] = _openocd_core_scripts_for(
        result.get("openocd"), scripts)

    _discovery_cache = result
    _discovery_env_snapshot = snapshot
    return result


def get_tool(tool: str) -> str:
    """Resolve the path to a tool.

    Order: env var -> cached discovery -> fresh discovery.

    Raises FileNotFoundError with an actionable Chinese message if missing.
    """
    env_key = _TOOL_ENV_VARS.get(tool)
    if env_key:
        env_val = os.environ.get(env_key)
        if env_val and os.path.exists(env_val):
            return env_val

    discovered = _discover_all().get(tool)
    if discovered and os.path.exists(discovered):
        return discovered

    if discovered and not os.path.exists(discovered):
        # Stale cache entry — rediscover once.
        reset_cache()
        discovered = _discover_all().get(tool)
        if discovered and os.path.exists(discovered):
            return discovered

    raise FileNotFoundError(
        f"未找到 {tool}。请设置环境变量 {env_key} 指向可执行文件路径，"
        f"或将工具安装在默认位置。"
    )


def discover_all() -> dict[str, str]:
    """Return the full discovery map (for the discover_tools tool)."""
    return dict(_discover_all())
