#!/usr/bin/env python3
"""对 mcp.json 里每个服务做冒烟：stdio 起进程 → initialize → tools/list；打印工具数或失败原因。退出码 = 失败个数。"""
import asyncio
import json
import os
import sys


async def one(name: str, c: dict, timeout: float = 60) -> tuple[bool, str]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    if not os.path.exists(c["command"]):
        return False, f"没有可执行文件 {c['command']}"
    prm = StdioServerParameters(command=c["command"], args=c.get("args", []), cwd=c.get("cwd"), env={**os.environ, **c.get("env", {})})

    async def go():
        async with stdio_client(prm, errlog=open(os.devnull, "w")) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            return [t.name for t in (await s.list_tools()).tools]
    try:
        names = await asyncio.wait_for(go(), timeout)
    except BaseException as e:  # noqa: BLE001
        while isinstance(e, BaseExceptionGroup) and e.exceptions:
            e = e.exceptions[0]
        return False, f"{type(e).__name__}: {e}"[:300]
    return True, f"{len(names)} 个工具：{', '.join(names[:8])}{' …' if len(names) > 8 else ''}"


async def main(path: str) -> int:
    cfg = json.load(open(path, encoding="utf-8"))["mcpServers"]
    bad = 0
    for n, c in cfg.items():
        ok, msg = await one(n, c)
        bad += not ok
        print(f"{'✓' if ok else '✗'} {n}: {msg}", flush=True)
    return bad


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1])))
