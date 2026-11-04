#!/usr/bin/env python3
"""mcp-hardware-tools 启动包装：原版 main() 一启动就连 HWTOOLS_SCOPE_HOST 的真示波器，没有仪器就退出，助手挂不上。
这里：设了 HWTOOLS_SCOPE_HOST → 原版 main()（真 DS1054Z）；没设 → 用它自带的 SimulatedScope（仿真 1 kHz 正弦）起同一个服务，
工具清单一样，结果标明是仿真。上游代码不改。"""
import os

from hwtools.tools.server import build_server, main

if __name__ == "__main__":
    if os.environ.get("HWTOOLS_SCOPE_HOST"):
        main()
    else:
        from hwtools.drivers.simulated import SimulatedScope, Sine
        from hwtools.model.ids import ChannelId
        from hwtools.session import ScopeSession
        build_server(ScopeSession(SimulatedScope({ChannelId.CH1: Sine(amplitude_v=1.0, frequency_hz=1_000.0)}))).run()
