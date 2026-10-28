"""UI 截图（无需硬件）：起侧车 + 仿真板，用 playwright 驱动真实界面。
用法：python3 app/tools/shot.py [输出目录]   需要先 (cd app/ui && npm run build)
"""
import json, os, pathlib, subprocess, sys, tempfile, time
from playwright.sync_api import sync_playwright

APP = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/ui-ref")
env = dict(os.environ, DZBENCH_HOME=tempfile.mkdtemp(), PYTHONPATH=str(APP / "sidecar"))
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
            ws.onopen = () => { const t = setInterval(() => { ws.send(JSON.stringify({op:'send_data', rid:++k, id:1, hex:hex(...seq[Math.floor(i/10)%4])}));
               if (++i >= 48) { clearInterval(t); ws.close(); r(); } }, 100); }; })""")
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
        pg.click("#estop")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / "app-estop.png"))
        pg.click("#connect"); pg.wait_for_timeout(600)
        pg.select_option("#port", "/dev/ttyS0") if pg.locator("#port option[value='/dev/ttyS0']").count() else None
        pg.click("#connect"); pg.wait_for_timeout(3500)
        pg.screenshot(path=str(OUT / "app-error.png"))
        b.close()
finally:
    srv.terminate()
print("ok", OUT)
