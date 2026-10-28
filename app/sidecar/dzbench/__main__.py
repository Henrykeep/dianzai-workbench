import argparse
import asyncio
import pathlib

from .server import Server


def main() -> None:
    ap = argparse.ArgumentParser(prog="dzbench", description="电赛工作台侧车（串口/仿真 ↔ WebSocket）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ui", type=pathlib.Path, help="同时用 HTTP 在 port+1 提供 UI 静态文件（浏览器模式）")
    a = ap.parse_args()
    try:
        asyncio.run(Server().serve(a.host, a.port, a.ui))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
