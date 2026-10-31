// 事件时间线（侧车 events.py）：曲线下方一排事件，点哪条跳到哪（同心跳条的跳转）；在视图内的事件同时在曲线上画竖线。
import { evText, evColor } from "./estophist";
export type Ev = { i: number; kind: string; text: string; log_t: number | null; plot_t: number | null; cause_zh?: string | null; message_zh?: string | null; fix_hint_zh?: string | null };
export const KIND: Record<string, [string, string]> = {   // kind → [短名, 颜色变量]
  connect: ["连接", "--muted"], estop_clear: ["解除", "--muted"], param: ["参数", "--acc-t"], estop: ["急停", "--crit"], watchdog: ["看门狗", "--crit"],
  crc: ["CRC", "--warn"], step: ["阶跃", "--ok"], agent: ["Agent", "--acc-t"],
};
export const kindOf = (k: string): [string, string] => KIND[k] || [k, "--muted"];
export function mergeEv(have: Ev[], add: Ev[], keep = 2000): Ev[] {
  const seen = new Set(have.map(e => e.i)), out = have.concat(add.filter(e => !seen.has(e.i)));
  out.sort((a, b) => a.i - b.i);
  return out.length > keep ? out.slice(out.length - keep) : out;
}
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const when = (e: Ev) => e.log_t != null ? `${e.log_t.toFixed(1)} s` : "—";

export function initTimeline(el: HTMLElement, onJump: (e: Ev) => void, onChange: (evs: Ev[]) => void, isLatched: () => boolean = () => false) {
  let evs: Ev[] = [];
  const render = () => {
    el.hidden = !evs.length;
    const lat = isLatched(), lastE = evs.filter(x => x.kind === "estop" || x.kind === "watchdog").pop();
    el.innerHTML = evs.slice(-80).map(e => { const [n, c0] = kindOf(e.kind), c = evColor(e.kind, c0, lat && e === lastE), tx = evText(e);
      return `<span class="tl-e" data-i="${e.i}" style="--c:var(${c})" title="${esc(tx)} · dzlog ${when(e)}（点击跳到这一刻）"><b>${n}</b>${esc(tx)}<i>${when(e)}</i></span>`; }).join("");
    el.scrollLeft = el.scrollWidth;
    onChange(evs);
  };
  el.onclick = ev => {
    const i = (ev.target as HTMLElement).closest<HTMLElement>(".tl-e")?.dataset.i;
    const e = i != null ? evs.find(x => x.i === +i) : undefined;
    if (e) onJump(e);
  };
  return {
    add(e: Ev) { evs = mergeEv(evs, [e]); render(); },
    set(a: Ev[]) { evs = mergeEv([], a); render(); },
    clear() { evs = []; render(); },
    refresh() { render(); },
    all: () => evs,
  };
}
