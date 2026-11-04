// 数据看板：把侧车推来的通道（telem，经帧格式解析后的同一份数据）摆成数值卡 + 迷你曲线。通道名、个数全部来自数据本身，不写死题目或板子。
import type { Mount } from "./toolbox";
export type Chan = { name: string; last: number; min: number; max: number; hist: number[] };
const N = 120;
export function feed(chs: Map<string, Chan>, y: Record<string, number[]>) {
  for (const [k, arr] of Object.entries(y)) {
    if (!Array.isArray(arr) || !arr.length) continue;
    const c = chs.get(k) ?? { name: k, last: NaN, min: Infinity, max: -Infinity, hist: [] };
    for (const v of arr) if (Number.isFinite(v)) { c.last = v; c.min = Math.min(c.min, v); c.max = Math.max(c.max, v); c.hist.push(v); }
    if (c.hist.length > N) c.hist.splice(0, c.hist.length - N);
    chs.set(k, c);
  }
}
export const fmt = (v: number) => !Number.isFinite(v) ? "—" : Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0) ? v.toExponential(2) : v.toFixed(Math.abs(v) >= 100 ? 1 : 3);
export function spark(h: number[], w = 160, ht = 36): string {
  if (h.length < 2) return "";
  const lo = Math.min(...h), hi = Math.max(...h), r = hi - lo || 1;
  return h.map((v, i) => `${(i / (h.length - 1) * w).toFixed(1)},${(ht - (v - lo) / r * ht).toFixed(1)}`).join(" ");
}
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
export function makeDashboard(subscribe: (f: (m: any) => void) => () => void): Mount {
  return (el, api) => {
    const chs = new Map<string, Chan>();
    el.innerHTML = `<div class="dash-wait"><wa-spinner></wa-spinner><span>等待数据…（连着板子时，通道一到就显示）</span></div>`;
    let t0 = performance.now(), dirty = false;
    const draw = () => {
      if (!dirty) { if (!chs.size && performance.now() - t0 > 5000) api.showError("no_data", "5 秒内没收到任何通道。看一下帧格式是否和板子发的一致，或板子是否在发数据"); return; }
      dirty = false; api.clearError();
      el.innerHTML = `<div class="dash">${[...chs.values()].map(c => `<div class="dash-c"><span class="dash-n">${esc(c.name)}</span><b>${fmt(c.last)}</b>
        <svg viewBox="0 0 160 36" preserveAspectRatio="none"><polyline points="${spark(c.hist)}"/></svg><span class="dash-r">最小 ${fmt(c.min)} · 最大 ${fmt(c.max)}</span></div>`).join("")}</div>`;
    };
    const off = subscribe(m => { if (m?.type === "telem" && m.y) { feed(chs, m.y); dirty = true; } });
    const iv = setInterval(draw, 250);
    return () => { off(); clearInterval(iv); };
  };
}
