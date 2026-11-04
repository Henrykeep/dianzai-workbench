// 串口调试（自写，交互参考 SerialWeb：文本/HEX、时间戳、发送框、收发计数；有界显示缓冲 + 丢弃计数参考 TaishanPi 的做法，未搬代码）。
// 收发全部经本地服务（serialslot.SerialBackend），桌面版和网页版一样。vendor-tools 合入后 serialslot 会优先挂原版工具。
import type { Mount } from "./toolbox";
import type { SerialBackend } from "./serialslot";
export const DISPLAY_CAP = 8192;   // 显示缓冲上限（字节）；超出从头丢，丢了多少计数显示
export type Chunk = { t: number; dir: 0 | 1; bytes: Uint8Array };
export class BoundedLog {
  chunks: Chunk[] = []; size = 0; dropped = 0; rx = 0; tx = 0;
  constructor(public cap = DISPLAY_CAP) {}
  push(c: Chunk) {
    c.dir ? (this.tx += c.bytes.length) : (this.rx += c.bytes.length);
    if (c.bytes.length > this.cap) { this.dropped += c.bytes.length - this.cap; c = { ...c, bytes: c.bytes.slice(c.bytes.length - this.cap) }; }
    this.chunks.push(c); this.size += c.bytes.length;
    while (this.size > this.cap) {
      const f = this.chunks[0], over = this.size - this.cap;
      if (f.bytes.length <= over) { this.chunks.shift(); this.size -= f.bytes.length; this.dropped += f.bytes.length; }
      else { this.chunks[0] = { ...f, bytes: f.bytes.slice(over) }; this.size -= over; this.dropped += over; }
    }
  }
  clear() { this.chunks = []; this.size = 0; this.dropped = 0; }
}
export const toHex = (b: Uint8Array) => Array.from(b, x => x.toString(16).padStart(2, "0").toUpperCase()).join(" ");
export function parseHexInput(s: string): { ok: true; hex: string } | { ok: false; error: string } {
  const h = s.replace(/0x/gi, "").replace(/[\s,]+/g, "");
  if (!h) return { ok: false, error: "发送内容是空的" };
  if (!/^[0-9a-fA-F]+$/.test(h)) return { ok: false, error: "HEX 模式只能填 0-9、A-F，字节之间可以用空格分开" };
  if (h.length % 2) return { ok: false, error: "HEX 位数要是偶数（每个字节两位）" };
  return { ok: true, hex: h.toLowerCase() };
}
export const textToHex = (s: string, eol: string) => Array.from(new TextEncoder().encode(s + eol), b => b.toString(16).padStart(2, "0")).join("");
const EOL: Record<string, string> = { none: "", lf: "\n", crlf: "\r\n" };
const esc = (s: string) => s.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]!));
export function render(log: BoundedLog, hex: boolean, ts: boolean): string {
  const dec = new TextDecoder("utf-8", { fatal: false });
  return log.chunks.map(c => `<div class="st-l ${c.dir ? "tx" : "rx"}">${ts ? `<i>${new Date(c.t).toLocaleTimeString("zh-CN", { hour12: false })}.${String(c.t % 1000).padStart(3, "0")}</i>` : ""}<b>${c.dir ? "发" : "收"}</b><span>${esc(hex ? toHex(c.bytes) : dec.decode(c.bytes).replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "·"))}</span></div>`).join("");
}
export function makeSerialTerm(be: SerialBackend, opts: { baud: () => number }): Mount {
  return (el, api) => {
    const log = new BoundedLog();
    let hex = false, ts = true, paused = false, open = false, dirty = true;
    el.innerHTML = `<div class="st">
      <div class="st-bar"><span class="st-seg" id="st-fmt"><button type="button" data-f="txt" class="on">文本</button><button type="button" data-f="hex">HEX</button></span>
        <wa-switch size="small" id="st-ts" checked>时间戳</wa-switch><wa-switch size="small" id="st-pause">暂停显示</wa-switch>
        <span class="st-sp"></span><span class="st-cnt" id="st-cnt"></span><wa-button size="small" appearance="plain" id="st-clr">清屏</wa-button></div>
      <div class="st-out" id="st-out" role="log" aria-live="off"></div>
      <div class="st-send"><wa-input id="st-in" size="small" placeholder="要发送的内容，回车发送"></wa-input>
        <wa-select id="st-mode" size="small" value="txt"><wa-option value="txt">文本</wa-option><wa-option value="hex">HEX</wa-option></wa-select>
        <wa-select id="st-eol" size="small" value="crlf"><wa-option value="none">不加结尾</wa-option><wa-option value="lf">\\n</wa-option><wa-option value="crlf">\\r\\n</wa-option></wa-select>
        <wa-button size="small" appearance="outlined" id="st-go">发送</wa-button></div></div>`;
    const $ = (id: string) => el.querySelector<any>("#" + id)!;
    const out = $("st-out");
    const paint = () => {
      $("st-cnt").textContent = `收 ${log.rx} B · 发 ${log.tx} B${log.dropped ? ` · 显示已丢弃 ${log.dropped} B（上限 8 KB）` : ""}`;
      if (paused || !dirty) return; dirty = false;
      const stick = out.scrollTop + out.clientHeight >= out.scrollHeight - 8;
      out.innerHTML = log.chunks.length ? render(log, hex, ts) : `<div class="st-empty">${open ? "已连接，等待数据…" : "还没开始。点上方「开始监视」"}</div>`;
      if (stick) out.scrollTop = out.scrollHeight;
    };
    $("st-fmt").addEventListener("click", (e: Event) => { const b = (e.target as HTMLElement).closest<HTMLElement>("[data-f]"); if (!b) return; hex = b.dataset.f === "hex"; el.querySelectorAll("#st-fmt button").forEach(x => x.classList.toggle("on", x === b)); dirty = true; paint(); });
    $("st-ts").addEventListener("change", () => { ts = !!$("st-ts").checked; dirty = true; paint(); });
    $("st-pause").addEventListener("change", () => { paused = !!$("st-pause").checked; dirty = true; paint(); });
    $("st-clr").addEventListener("click", () => { log.clear(); dirty = true; paint(); });
    const send = async () => {
      if (!open) return api.showError("no_board", "先点「开始监视」连上串口");
      const v = String($("st-in").value ?? "");
      let h: string;
      if ($("st-mode").value === "hex") { const r = parseHexInput(v); if (!r.ok) return api.showError("bad_arg", r.error); h = r.hex; }
      else { if (!v && $("st-eol").value === "none") return api.showError("bad_arg", "发送内容是空的"); h = textToHex(v, EOL[$("st-eol").value] ?? ""); }
      try { await be.write(h); api.clearError(); log.push({ t: Date.now(), dir: 1, bytes: new Uint8Array(h.match(/../g)!.map(x => parseInt(x, 16))) }); dirty = true; paint(); }
      catch (e: any) { api.showError(String(e?.code || "error"), e?.message); }
    };
    $("st-go").addEventListener("click", send);
    $("st-in").addEventListener("keydown", (e: KeyboardEvent) => { if (e.key === "Enter") void send(); });
    const off = be.onData(h => { log.push({ t: Date.now(), dir: 0, bytes: new Uint8Array(h.match(/../g)!.map(x => parseInt(x, 16))) }); dirty = true; });
    const iv = setInterval(paint, 100);
    paint();
    be.open(opts.baud()).then(() => { open = true; dirty = true; paint(); api.showResult("已开始监视。收发经本地服务，桌面版和网页版一样。"); }, (e: any) => api.showError(String(e?.code || "error"), e?.message));
    return () => { off(); clearInterval(iv); void be.close(); };
  };
}
