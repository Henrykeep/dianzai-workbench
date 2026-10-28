"""UI 截图（无需硬件）：起侧车 + 仿真板，用 playwright 驱动真实界面。
用法：python3 app/tools/shot.py [输出目录]   需要先 (cd app/ui && npm run build)
"""
import json, os, pathlib, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from playwright.sync_api import sync_playwright

APP = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/ui-ref")
HOME = pathlib.Path(tempfile.mkdtemp())
# Agent 截图改的是临时克隆，不碰本仓库；门禁 make check 是真跑的
REPO = HOME / "repo"
subprocess.run(["git", "clone", "-q", str(APP.parent), str(REPO)], check=True)
(REPO / "third_party").symlink_to(APP.parent / "third_party")      # SDK 不进 git，克隆里借用本机已下载的


class FakeLLM(BaseHTTPRequestHandler):
    """假的 OpenAI 兼容接口：第一轮调 step_analysis 工具，第二轮给结论（截图用，不联网）。"""
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body["messages"][-1]["role"] == "user":
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "list_params", "arguments": "{}"}},
                {"id": "c2", "type": "function", "function": {"name": "step_analysis", "arguments": "{}"}}]}
        else:
            msg = {"role": "assistant", "content": "看了最近一次阶跃：A 轮能跟上，但稳态差一截（见上面的阶跃分析卡）。"
                   "建议先把 ki 加 30%，下发后再给一个阶跃确认；如果开始振荡就退回快照。"}
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({"choices": [{"message": msg}]}).encode())

    def log_message(self, *a):
        pass


llm = HTTPServer(("127.0.0.1", 0), FakeLLM)
threading.Thread(target=llm.serve_forever, daemon=True).start()
(HOME / "config.json").write_text(json.dumps({"provider": "custom", "base_url": f"http://127.0.0.1:{llm.server_port}/v1",
                                              "model": "mock", "api_key": "sk-mock-0000"}))
env = dict(os.environ, DZBENCH_HOME=str(HOME), DZBENCH_REPO=str(REPO), PYTHONPATH=str(APP / "sidecar"))
srv = subprocess.Popen([sys.executable, "-m", "dzbench", "--port", "18901", "--ui", str(APP / "ui" / "dist")], env=env)
time.sleep(1.0)
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto("http://127.0.0.1:18902/?ws=ws://127.0.0.1:18901")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=str(OUT / "app-first-run.png"))
        pg.select_option("#port", "sim:car_2wd")
        pg.click("#connect")
        pg.wait_for_selector(".prow", timeout=15000)
        # 阶跃测试：左右轮设定 0 → 3 → 1.5 → -2 r/s（car_2wd DATA id=1：两个 f32）
        pg.evaluate("""() => new Promise(r => { const ws = new WebSocket('ws://127.0.0.1:18901');
            const hex = (a,b) => { const d = new DataView(new ArrayBuffer(8)); d.setFloat32(0,a,true); d.setFloat32(4,b,true);
              return [...new Uint8Array(d.buffer)].map(x=>x.toString(16).padStart(2,'0')).join(''); };
            const seq = [[3,2.5],[1.5,1.5],[-2,-1],[2,2]]; let i = 0, k = 0;
            ws.onopen = () => { const t = setInterval(() => { ws.send(JSON.stringify({op:'send_data', rid:++k, id:1, hex:hex(...seq[Math.min(Math.floor(i/10),3)])}));
               if (++i === 45) r(); }, 100); }; })""")  # 之后一直保持最后一档 2 r/s，供阶跃分析
        first = pg.locator(".prow input").first
        first.fill("9.5"); pg.locator(".prow input").nth(1).click()
        pg.evaluate("""() => new Promise(r => { const ws = new WebSocket('ws://127.0.0.1:18901');
            ws.onopen = () => { ws.send(JSON.stringify({op:'agent_tool', rid:1, tool:'list_params', args:{}})); };
            ws.onmessage = e => { const m = JSON.parse(e.data); if (m.rid === 1) {
               const p = m.data[0]; ws.send(JSON.stringify({op:'propose', rid:2, name:p.name, value:(p.value ?? p.default)*1.1,
                 reason:'示例提议（截图脚本发出）：最近 2 s 超调偏大，小幅加阻尼。', source:'agent'})); }
               if (m.rid === 2) { ws.close(); r(); } }; })""")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(OUT / "app-live.png"))
        # ---- Agent：离线阶跃分析 → 对话（假 LLM）→ 写回 yaml 的 diff → 确认（真跑 make check）→ 已提交
        pg.evaluate("""() => new Promise(r => { const ws = new WebSocket('ws://127.0.0.1:18901');
            ws.onopen = () => ws.send(JSON.stringify({op:'param_set', rid:1, name:'ki', value:1.95}));
            ws.onmessage = e => { if (JSON.parse(e.data).rid === 1) { ws.close(); r(); } }; })""")
        pg.click("#ag-tune"); pg.wait_for_selector(".card .hd >> text=阶跃分析", timeout=5000); pg.wait_for_timeout(300)
        pg.screenshot(path=str(OUT / "app-tune.png"))
        pg.fill("#ag-in", "A 轮跟不上设定，帮我看看怎么调"); pg.click("#ag-send")
        pg.wait_for_selector(".msg.bot >> text=稳态", timeout=8000); pg.wait_for_timeout(300)
        pg.screenshot(path=str(OUT / "app-agent.png"))
        pg.click("#ag-yaml"); pg.wait_for_selector(".change.pending", timeout=5000); pg.wait_for_timeout(200)
        pg.screenshot(path=str(OUT / "app-diff.png"))
        pg.click(".change.pending button[data-a='1']"); pg.wait_for_selector(".change.committed", timeout=120000); pg.wait_for_timeout(200)
        pg.screenshot(path=str(OUT / "app-commit.png"))
        pg.click("#ag-cfg"); pg.wait_for_timeout(300)
        pg.screenshot(path=str(OUT / "app-llm.png"))
        pg.click("#cfg button[value=cancel]")
        pg.click("#view span[data-v=raw]"); pg.click("#raw-fmt span[data-f=hex]"); pg.wait_for_timeout(800)
        pg.screenshot(path=str(OUT / "app-raw.png"))
        pg.click("#view span[data-v=fft]"); pg.select_option("#fft-ch", "spd_a"); pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / "app-fft.png"))
        pg.click("#view span[data-v=plot]")
        pg.click("#estop")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / "app-estop.png"))
        pg.click("#connect"); pg.wait_for_timeout(600)
        pg.select_option("#port", "/dev/ttyS0") if pg.locator("#port option[value='/dev/ttyS0']").count() else None
        pg.click("#connect"); pg.wait_for_timeout(3500)
        pg.screenshot(path=str(OUT / "app-error.png"))
        # 回放 + 时间轴拖动
        pg.locator(".toast").evaluate_all("ts => ts.forEach(t => t.remove())")
        pg.click("#replay"); pg.wait_for_timeout(1500)
        pg.evaluate("""() => new Promise(r => { const ws = new WebSocket('ws://127.0.0.1:18901');
            ws.onopen = () => ws.send(JSON.stringify({op:'replay_ctl', rid:1, seek:4.0, speed:0.5}));
            ws.onmessage = e => { if (JSON.parse(e.data).rid === 1) { ws.close(); r(); } }; })""")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(OUT / "app-replay.png"))
        b.close()
finally:
    srv.terminate(); llm.shutdown()
print("ok", OUT)
