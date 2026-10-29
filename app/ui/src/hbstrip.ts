// 链路心跳条：侧车每秒一格（linkhealth.py），底栏画最近 N 格；点格子跳到那一秒：
// 回放 → 按 dzlog 时间 seek；实时 → 暂停曲线并把视图移到那一秒（A 光标落在那里），同时提示 dzlog 时间。
export type Cell = { i: number; dt: number; fps: number; crc: number; drops: number; bytes: number; log_t: number | null; plot_t: number | null };
export type Level = "ok" | "warn" | "bad" | "off";

// 判级：没帧 = off；有坏帧/丢帧 = bad；帧率掉到近期中位数一半以下 = warn（板子卡顿、阻塞打印）
export function level(c: Cell, ref: number): Level {
  if (c.fps <= 0) return "off";
  if (c.crc > 0 || c.drops > 0) return "bad";
  if (ref > 0 && c.fps < ref * 0.5) return "warn";
  return "ok";
}
export function median(a: number[]): number {
  if (!a.length) return 0;
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
// 合并：按 i 去重（hello 的 status 和广播可能各拿到一次），保留最后 keep 格
export function merge(have: Cell[], add: Cell[], keep = 600): Cell[] {
  if (!add.length) return have;
  const seen = new Set(have.map(c => c.i)), out = have.concat(add.filter(c => !seen.has(c.i)));
  out.sort((a, b) => a.i - b.i);
  return out.length > keep ? out.slice(out.length - keep) : out;
}
export function tip(c: Cell): string {
  return `${c.fps} 帧/s · CRC 坏 ${c.crc} · 丢 ${c.drops} · ${(c.bytes / 1024).toFixed(1)} kB` +
    (c.log_t != null ? ` · dzlog ${c.log_t.toFixed(1)} s` : " · 未记录") + "（点击跳到这一秒）";
}

export function initHbStrip(el: HTMLElement, onJump: (c: Cell) => void, show = 60) {
  let cells: Cell[] = [];
  const render = () => {
    const tail = cells.slice(-show), ref = median(cells.slice(-30).map(c => c.fps).filter(f => f > 0));
    el.innerHTML = tail.map(c => `<i class="hb-${level(c, ref)}" data-i="${c.i}" title="${tip(c)}"></i>`).join("");
  };
  el.onclick = e => {
    const i = (e.target as HTMLElement).dataset?.i;
    const c = i != null ? cells.find(x => x.i === +i) : undefined;
    if (c) onJump(c);
  };
  return {
    add(a: Cell[] | undefined) { if (a?.length) { cells = merge(cells, a); render(); } },
    set(a: Cell[]) { cells = merge([], a); render(); },
    clear() { cells = []; el.innerHTML = ""; },
  };
}
