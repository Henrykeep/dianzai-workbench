# Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b project.py
"""
STM32 project helpers: locate .ioc / .elf, summarize a project, and
discover CubeIDE projects inside a workspace directory.
"""

import glob
import os
import xml.etree.ElementTree as ET

# Directories never containing a project root (pruned during traversal).
_SKIP_DIRS = {
    "Debug", "Release",
    "build", "cmake-build-debug", "cmake-build-release",
    "Drivers", "Middlewares", "Core",
    ".git", ".settings", ".metadata",
}


def find_ioc(project_path: str) -> str | None:
    """Find the .ioc file in the project directory."""
    matches = glob.glob(os.path.join(project_path, "*.ioc"))
    return matches[0] if matches else None


def find_elf(project_path: str, config: str = "Debug") -> str | None:
    """Find the built .elf in the project's build output directory."""
    matches = glob.glob(os.path.join(project_path, config, "*.elf"))
    return matches[0] if matches else None


def parse_project_info(project_path: str) -> str:
    """Human-readable summary of a CubeIDE project (MCU, configs, sources)."""
    if not os.path.isdir(project_path):
        return f"工程路径不存在: {project_path}"

    lines = [f"工程: {os.path.basename(project_path)}"]

    cproject = os.path.join(project_path, ".cproject")
    if os.path.isfile(cproject):
        try:
            root = ET.parse(cproject).getroot()
            configs = [
                cc.get("name", "?")
                for cc in root.iter("configuration")
            ]
            if configs:
                lines.append(f"构建配置: {', '.join(configs)}")
            for tool in root.iter("tool"):
                if "gnu.c.compiler" in (tool.get("superClass", "") or ""):
                    lines.append("编译器: arm-none-eabi-gcc")
                    break
        except ET.ParseError:
            lines.append("(.cproject 解析失败)")

    ioc_file = find_ioc(project_path)
    if ioc_file:
        try:
            root = ET.parse(ioc_file).getroot()
            mcu = root.get("Mcu.Name") or root.get("Mcu", "未知")
            lines.append(f"MCU: {mcu}")
        except (ET.ParseError, AttributeError):
            pass
        lines.append(f"ioc 文件: {os.path.basename(ioc_file)}")

    src_files = []
    for ext in ("*.c", "*.cpp", "*.h", "*.s"):
        src_files.extend(
            glob.glob(os.path.join(project_path, "**", ext), recursive=True)
        )
    lines.append(f"源文件数: {len(src_files)}")

    return "\n".join(lines)


def list_projects(root: str) -> list[str]:
    """Find CubeIDE projects (dirs with .project/.cproject) under root."""
    if not os.path.isdir(root):
        return []

    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        if ".project" in filenames or ".cproject" in filenames:
            results.append(os.path.abspath(dirpath))
            dirnames[:] = []  # don't descend into a project
    return results
