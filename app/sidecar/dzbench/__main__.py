import argparse
import errno
import sys
import asyncio
import pathlib

from .server import Server

EXIT_PORT_IN_USE = 3        # 外壳（Tauri）看到这个退出码就不再重启侧车


def main() -> None:
    ap = argparse.ArgumentParser(prog="dzbench", description="芯台本地服务（串口/仿真 ↔ WebSocket）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ui", type=pathlib.Path, help="同时用 HTTP 在 port+1 提供 UI 静态文件（浏览器模式）")
    ap.add_argument("--doctor", action="store_true", help="自检工具链 / 探针 / 器件包 / 串口 / 配置，打印修复提示后退出")
    ap.add_argument("--repo", help="--doctor 时检查哪个工程的 dzbench.json")
    a = ap.parse_args()
    if a.doctor:
        from . import doctor
        items = doctor.run(a.repo)
        print(doctor.render(items))
        sys.exit(1 if any(i["level"] == "fail" for i in items) else 0)
    import signal

    def _term(*_):
        from . import lastsession
        lastsession.clear()            # 先删记录：后面退得慢也不会误报崩溃
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)       # 正常结束（kill/任务管理器“结束任务”以外）也算干净退出
    try:
        asyncio.run(Server().serve(a.host, a.port, a.ui))
    except KeyboardInterrupt:
        from . import lastsession
        lastsession.clear()                    # 人为停掉 ≠ 崩溃，下次启动不报“意外退出”
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)) or "address already in use" in str(e).lower():
            print(f"dzbench: 端口 {a.port} 已被占用——多半已经开着一个工作台（本地服务）。"
                  "请用已经打开的那个窗口；确实没有的话在任务管理器里结束 dzbench 再开。", file=sys.stderr, flush=True)
            sys.exit(EXIT_PORT_IN_USE)
        raise


if __name__ == "__main__":
    main()
