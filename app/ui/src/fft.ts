// 频谱视图：侧车按固件遥测周期算 FFT（去直流 + Hann），这里只负责画
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

export function initFFT(rpc: (op: string, a?: Record<string, unknown>) => Promise<any>) {
  let on = false, secs = 10, timer = 0, last: any = null;
  const cv = $<HTMLCanvasElement>("fft-cv");
  $("fft-win").querySelectorAll<HTMLElement>("span").forEach(x => x.onclick = () => {
    $("fft-win").querySelectorAll("span").forEach(y => y.classList.toggle("on", y === x)); secs = +x.dataset.s!; tick();
  });
  $("fft-log").onchange = () => draw();
  $("fft-ch").onchange = () => tick();

  async function tick() {
    const ch = $<HTMLSelectElement>("fft-ch").value;
    if (!on || !ch) return;
    last = await rpc("fft", { field: ch, seconds: secs }).catch(e => ({ ok: false, reason: e.message }));
    draw();
  }
  function draw() {
    const r = last, css = getComputedStyle(document.documentElement);
    const W = cv.clientWidth, H = cv.clientHeight, dpr = devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext("2d")!; g.scale(dpr, dpr); g.clearRect(0, 0, W, H);
    $("fft-warn").hidden = !(r && (r.warn || !r.ok));
    $("fft-warn").textContent = r ? (r.ok ? r.warn : r.reason) : "";
    if (!r?.ok) { $("fft-info").textContent = ""; return; }
    $("fft-info").textContent = `fs ${r.fs.toFixed(1)} Hz · N ${r.n}（${r.seconds.toFixed(1)} s）· 分辨率 ${r.df.toFixed(3)} Hz` +
      (r.peaks.length ? ` · 峰 ${r.peaks.map((p: any) => `${p.f.toFixed(2)} Hz`).join(" / ")}` : "");
    const L = 48, B = 22, pw = W - L - 12, ph = H - B - 10;
    const logy = $<HTMLInputElement>("fft-log").checked;
    const ys = r.amp.map((a: number) => logy ? Math.log10(a + 1e-9) : a);
    const lo = logy ? Math.max(Math.min(...ys), Math.max(...ys) - 5) : 0, hi = Math.max(...ys) || 1;
    const X = (f: number) => L + f / (r.fs / 2) * pw, Y = (v: number) => 10 + ph - (Math.max(v, lo) - lo) / (hi - lo || 1) * ph;
    g.strokeStyle = css.getPropertyValue("--grid-2"); g.fillStyle = css.getPropertyValue("--dim"); g.font = "10px " + css.getPropertyValue("--f-mono");
    for (let i = 0; i <= 5; i++) { const f = r.fs / 2 * i / 5; g.beginPath(); g.moveTo(X(f), 10); g.lineTo(X(f), 10 + ph); g.stroke(); g.fillText(`${f.toFixed(f < 10 ? 1 : 0)} Hz`, X(f) - 14, H - 6); }
    g.fillText(logy ? "log₁₀" : hi.toPrecision(3), 4, 18);
    g.strokeStyle = css.getPropertyValue("--acc"); g.lineWidth = 1.5; g.beginPath();
    ys.forEach((v: number, k: number) => { const x = X(r.f[k]), y = Y(v); k ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
    g.fillStyle = css.getPropertyValue("--ink");
    r.peaks.forEach((p: any) => { const x = X(p.f), y = Y(logy ? Math.log10(p.amp) : p.amp); g.beginPath(); g.arc(x, y, 3, 0, 7); g.fill(); g.fillText(`${p.f.toFixed(2)} Hz · ${p.amp.toPrecision(3)}`, x + 6, y - 4); });
  }
  return {
    setView(v: boolean) { on = v; $("fft").hidden = !v; clearInterval(timer); if (v) { tick(); timer = setInterval(tick, 1000) as unknown as number; } },
    setFields(names: string[]) {
      const cur = $<HTMLSelectElement>("fft-ch").value;
      $("fft-ch").innerHTML = names.map(n => `<option ${n === cur ? "selected" : ""}>${n}</option>`).join("");
    },
  };
}
