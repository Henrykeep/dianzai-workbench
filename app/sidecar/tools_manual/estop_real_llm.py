"""手动脚本（不进 CI）：真实大模型长 Agent 调用进行中按急停，重复 N 次，统计 点击→固件锁存确认(latched) 的 p50/p95。

用法（在 app/sidecar 下）：
    set -a; . /path/to/llm.env; set +a      # 只从环境变量读模型配置；本脚本不打印任何密钥/环境变量值
    PYTHONPATH=.:tests python3 tools_manual/estop_real_llm.py [N=20] [sim:car_2wd]
非 car_2wd 应用在固件修复前心跳没有 bit10：本地服务按 estop_cause 非空判锁存，latched 事件照样会来。
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time

os.environ.setdefault("DZBENCH_HOME", tempfile.mkdtemp(prefix="dz-estop-real-"))
from wsui import UI, ServerThread  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
PORT = sys.argv[2] if len(sys.argv) > 2 else "sim:car_2wd"
PROMPT = "请详细分析当前遥测，读参数表，给出完整的调参思路和每一步理由（尽量详细）。"


def main() -> int:
    print("模型配置：", "已设置" if any(k.startswith("DZ_LLM_") for k in os.environ) else "未设置 DZ_LLM_*（将走默认/可能失败）")
    st = ServerThread()
    ui = UI(st.port)
    lat, ws_lat, inflight = [], [], 0
    try:
        ui.ok("connect", port=PORT)
        t0 = time.monotonic()
        while not st.srv.session.params and time.monotonic() - t0 < 15:
            time.sleep(0.1)
        for i in range(N):
            m = ui.mark()
            ui.ws.send(json.dumps({"op": "agent_ask", "rid": 10000 + i, "text": PROMPT}))
            ui.wait(lambda e: e.get("type") == "agent_ack" and e.get("state") == "running", 10, m)
            time.sleep(1.5)                                  # 让请求真正打到模型上
            running = bool(st.srv.agent_running)
            inflight += running
            m = ui.mark()
            tc = time.monotonic()
            ui.ws.send(json.dumps({"op": "estop", "rid": 20000 + i, "src": "急停按钮"}))
            ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "requested", 5, m)
            tr = time.monotonic()
            ui.wait(lambda e: e.get("type") == "estop" and e.get("state") == "latched", 5, m)
            tl = time.monotonic()
            lat.append((tl - tc) * 1000)
            ws_lat.append((tr - tc) * 1000)
            print(f"#{i + 1:02d} 模型调用中={running} requested={ws_lat[-1]:.1f} ms latched={lat[-1]:.1f} ms", flush=True)
            ui.ok("cmd", c="R")
            t1 = time.monotonic()                            # 等这轮 Agent 结束（被锁存拒绝或答完）再下一轮
            while st.srv.agent_running and time.monotonic() - t1 < 120:
                time.sleep(0.2)
            time.sleep(0.5)
    finally:
        ui.close()
        st.stop()

    def pct(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, round(p / 100 * (len(xs) - 1)))]
    print(json.dumps({"n": len(lat), "llm_inflight": inflight,
                      "click→requested_ms": {"p50": round(statistics.median(ws_lat), 1), "p95": round(pct(ws_lat, 95), 1)},
                      "click→latched_ms": {"p50": round(statistics.median(lat), 1), "p95": round(pct(lat, 95), 1)}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
