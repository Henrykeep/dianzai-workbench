#!/usr/bin/env python3
"""写 mcp.json（标准 mcpServers 格式）：芯台自己的服务 + 原样搬进 third_party/vendored/ 的 5 个开源 MCP 服务。"""
import argparse
import json
import pathlib


def config(root: pathlib.Path, py: str, bindir: pathlib.Path) -> dict:
    v = root / "third_party/vendored"
    s = {
        "xintai": {"command": py, "args": ["-m", "dzbench.mcp_server"], "cwd": str(root / "app/sidecar"),
                   "env": {"PYTHONPATH": str(root / "app/sidecar")}},
        "embedded-debugger": {"command": str(bindir / "embedded-debugger-mcp"), "args": ["serve"]},
        "hardware-tools": {"command": py, "args": [str(root / "tools/mcp/hwtools_launch.py")], "env": {"PYTHONPATH": str(v / "mcp_hardware_tools/src")}},
        "stm32cubeide": {"command": py, "args": [str(v / "stm32_mcp_discovery/server.py")], "cwd": str(v / "stm32_mcp_discovery"),
                         "env": {"PYTHONPATH": str(v / "stm32_mcp_discovery")}},
        "serial": {"command": py, "args": ["-m", "serial_mcp_server.server"], "env": {"PYTHONPATH": str(v / "serial_mcp_server")}},
        "sigrok": {"command": str(bindir / "sigrok-mcp-server"), "args": []},
    }
    return {"mcpServers": s}


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--root", required=True)
    a.add_argument("--python", required=True)
    a.add_argument("--bin", required=True)
    a.add_argument("-o", required=True)
    o = a.parse_args()
    pathlib.Path(o.o).write_text(json.dumps(config(pathlib.Path(o.root), o.python, pathlib.Path(o.bin)), indent=1, ensure_ascii=False), "utf-8")
