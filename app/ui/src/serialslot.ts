// 串口工具挂载点（适配层）：工具本体由 vendor-tools 分支放到 app/ui/public 下的一个固定路径（SERIAL_VENDOR_PATH），这里不放任何第三方代码。
// 挂载时把一段自写的桥接脚本（navigator.serial 的同形接口）注入工具页面，收发全部经本地服务（ws.ts：connect / send_raw / raw_monitor / serial_lines_set / serial_modem），
// 桌面版和网页版走同一条路，不用浏览器 Web Serial。以后换别的串口工具，只改这一个文件。
import type { Mount } from "./toolbox";
export const SERIAL_VENDOR_PATH = "vendor/serialweb/index.html";
export type Rpc = (op: string, a?: Record<string, unknown>) => Promise<any>;
export interface SerialBackend { open(baud: number): Promise<void>; write(hex: string): Promise<void>; setSignals(s: { dtr?: boolean; rts?: boolean }): Promise<void>; close(): Promise<void>; onData(f: (hex: string) => void): () => void; isReal?(): boolean }
/** 本地服务串口后端：已连着板子就复用这条连接，不抢；没连就用顶栏选中的端口去连 */
export function sidecarSerial(rpc: Rpc, subscribe: (f: (m: any) => void) => () => void, cur: () => { connected: boolean; port: string }): SerialBackend {
  return {
    async open(baud) { if (!cur().connected) { if (!cur().port) throw { code: "no_board", message: "顶栏还没选串口" }; await rpc("connect", { port: cur().port, baud }); } await rpc("raw_monitor", { on: true }); },
    async write(hex) { await rpc("send_raw", { hex }); },
    async setSignals(s) { await rpc("serial_lines_set", s); },
    async close() { /* 不断开本地服务的连接：别的页面还在用 */ },
    isReal() { const p = cur().port; return !!p && !/^(sim:|replay:|rtt:|tcp:)/.test(p); },
    onData(f) { return subscribe(m => { if (m?.type === "raw") for (const [, d, hex] of m.c as [number, number, string][]) if (!d) f(hex); }); },
  };
}
// 注入到工具页面里的桥（自写，MIT 同仓库许可）：把 navigator.serial 换成经 postMessage 转给本地服务的同形对象
// 适配层里 toHost 发给的是外层页面（postMessage 消息 open/close/write/signals），不是侧车 op；外层再转成 connect/send_raw/serial_lines_set
export const BRIDGE_JS = `(()=>{const P=window.parent;let seq=0;const W={};addEventListener("message",e=>{const m=e.data||{};if(m.dzs==="res"&&W[m.id]){W[m.id](m);delete W[m.id];}if(m.dzs==="data"&&port._c){const b=new Uint8Array(m.hex.match(/../g).map(h=>parseInt(h,16)));window.__dzSniff&&window.__dzSniff(b);try{port._c.enqueue(b)}catch(_){}}});
const toHost=(op,a)=>new Promise((ok,no)=>{const id=++seq;W[id]=m=>m.ok?ok(m.r):no(Object.assign(new Error(m.message||op),{code:m.code}));P.postMessage({dzs:"req",id,op,a},"*")});
const port={_c:null,readable:null,writable:null,getInfo(){return{usbVendorId:undefined,usbProductId:undefined}},
async open(o){await toHost("open",{baud:(o&&o.baudRate)||115200});this.readable=new ReadableStream({start:c=>{port._c=c}});this.writable=new WritableStream({write:ch=>toHost("write",{hex:Array.from(ch,b=>b.toString(16).padStart(2,"0")).join("")})});},
async close(){try{port._c&&port._c.close()}catch(_){}port._c=null;this.readable=null;this.writable=null;await toHost("close",{})},
async setSignals(s){if(!(window.__DZ&&window.__DZ.real))return;await toHost("signals",{dtr:s.dataTerminalReady,rts:s.requestToSend,brk:s.break})},async getSignals(){return{}},addEventListener(){},removeEventListener(){}};
const serial={async requestPort(){return port},async getPorts(){return[port]},addEventListener(){},removeEventListener(){}};
try{Object.defineProperty(navigator,"serial",{value:serial,configurable:true})}catch(_){}})();`;
// 嵌入增强（只加不改上游文件）：
// · 主题：把它的 CSS 变量映射到芯台 tokens（浅/深各一套，取外层页面当前计算值），只留「发送」一个主按钮
// · 非真串口（仿真板/回放/RTT）：DTR/RTS/BREAK 置灰，就地写原因，不再事后报错
// · 收到的头 256 字节不像文本（UTF-8 不合法或控制字符多）→ 自动勾上「十六进制接收」，顶部一行提示怎么切回
export function isProbablyBinary(b: Uint8Array): boolean {
  if (!b.length) return false;
  let ctrl = 0; for (const x of b) if (x < 9 || (x > 13 && x < 32) || x === 127) ctrl++;
  if (ctrl / b.length > 0.1) return true;
  try { new TextDecoder("utf-8", { fatal: true }).decode(b.length > 4 ? b.subarray(0, b.length - 3) : b); return false; } catch { return true; }
}
export type Tok = Record<string, string>;
export function themeCss(t: Tok): string {
  const v = (k: string, d: string) => t[k] || d;
  return `:root,:root.theme-dark,body,body.theme-dark{--bg:${v("bg", "#fff")}!important;--bg-elevated:${v("surface-1", "#fff")}!important;--bg-panel:${v("surface-1", "#fff")}!important;--bg-panel-strong:${v("surface-1", "#fff")}!important;--bg-terminal:${v("surface-2", "#f1f3f5")}!important;--border:${v("border", "#e3e5e9")}!important;--border-strong:${v("border-strong", "#cdd1d7")}!important;--text:${v("text-primary", "#1c2024")}!important;--text-soft:${v("text-secondary", "#555a63")}!important;--accent:${v("accent", "#0d74ce")}!important;--accent-strong:${v("accent-hover", "#0b68b9")}!important;--accent-soft:${v("accent-subtle", "#e6f1fb")}!important;--signal:${v("accent", "#0d74ce")}!important;--danger:${v("danger", "#ce2c31")}!important;--warning:${v("warning", "#d97706")}!important;--shadow:none!important;--shadow-soft:none!important;--radius:8px!important;--radius-small:4px!important;--scrollbar-thumb:${v("border-strong", "#cdd1d7")}!important;--scrollbar-thumb-hover:${v("text-muted", "#656a73")}!important;--font-ui:${v("font-sans", "system-ui")}!important;--font-mono:${v("font-mono", "monospace")}!important}
body{background:var(--bg)!important}
.primary-btn,#connect-btn,#connect-btn.is-disconnect,#connect-btn.is-release-hold,#connect-btn.is-hint-error{background:var(--bg-panel)!important;color:var(--text)!important;border:1px solid var(--border-strong)!important;box-shadow:none!important}
#connect-btn.is-disconnect{color:var(--danger)!important}
.wide-send-btn{background:var(--accent)!important;color:#fff!important;box-shadow:none!important}
.primary-btn:hover,.secondary-btn:hover,.ghost-btn:hover,.icon-btn:hover,.wide-send-btn:hover,.mini-btn:hover{transform:none!important}
.secondary-btn,.icon-btn,.mini-btn,body.theme-dark .secondary-btn,body.theme-dark .icon-btn,body.theme-dark .mini-btn{background:var(--bg-panel)!important}
.live-bar::before,.timeline-live-bar::before{background:linear-gradient(90deg,transparent,var(--accent),transparent)!important;opacity:.5}
.timeline-live-bar,.live-bar{background:var(--accent-soft)!important}
.dz-off{opacity:.45;pointer-events:none}
.dz-note{font-size:12px;line-height:16px;color:var(--text-soft);margin:4px 0 0}
.dz-hint{display:flex;gap:8px;align-items:center;padding:6px 12px;font-size:12px;color:var(--text);background:var(--accent-soft);border-bottom:1px solid var(--border)}
.dz-hint button{all:unset;cursor:pointer;color:var(--accent);font-weight:600}`;
}
export const ENHANCE_JS = `(()=>{const C=window.__DZ||{};
function sig(){if(C.real)return;const ids=["signal-dtr","signal-rts","signal-break"];let last=null;for(const id of ids){const i=document.getElementById(id);if(!i)continue;i.disabled=true;const chip=document.getElementById(id+"-chip")||i.closest("label");if(chip){chip.classList.add("dz-off");chip.title=C.sigWhy;last=chip}}
if(last&&!document.querySelector(".dz-note")){const n=document.createElement("p");n.className="dz-note";n.textContent=C.sigWhy;(last.parentElement||last).after(n)}}
let sniffed=false,buf=[];window.__dzSniff=b=>{if(sniffed)return;for(const x of b){if(buf.length<256)buf.push(x)}if(buf.length<32)return;sniffed=true;if(!C.isBin(new Uint8Array(buf)))return;const cb=document.getElementById("rx-display-mode");if(cb&&!cb.checked){cb.checked=true;cb.dispatchEvent(new Event("change",{bubbles:true}));cb.dispatchEvent(new Event("input",{bubbles:true}))}
const h=document.createElement("div");h.className="dz-hint";h.innerHTML='<span>收到的数据不是文本，已切到十六进制显示。</span><button type="button">改回文本</button>';h.querySelector("button").onclick=()=>{if(cb){cb.checked=false;cb.dispatchEvent(new Event("change",{bubbles:true}))}h.remove()};document.body.prepend(h)};
const go=()=>{const st=document.createElement("style");st.textContent=C.css;document.head.append(st);sig()};if(document.readyState==="loading")addEventListener("DOMContentLoaded",go);else go()})();`;
export function readTokens(): Tok {
  const cs = getComputedStyle(document.documentElement), o: Tok = {};
  for (const k of ["bg", "surface-1", "surface-2", "border", "border-strong", "text-primary", "text-secondary", "text-muted", "accent", "accent-hover", "accent-subtle", "danger", "warning", "font-sans", "font-mono"]) { const x = cs.getPropertyValue("--" + k).trim(); if (x) o[k] = x; }
  return o;
}
export const SIG_WHY = "当前连的是仿真板 / 回放 / RTT，没有 DTR、RTS、BREAK 线；接上 USB 转串口后可用";
// 嵌入时：主题跟芯台（写进它自己的偏好键）、不弹上游的版本说明框；上游文件本身不改
export function prefsJs(theme: "light" | "dark", ver: string): string {
  return `try{var k="serialweb:prefs",p=JSON.parse(localStorage.getItem(k)||"{}");p.theme=${JSON.stringify(theme)};localStorage.setItem(k,JSON.stringify(p));localStorage.setItem("serialweb:version-modal-seen",${JSON.stringify(ver)})}catch(e){}`;
}
export function injectBridge(html: string, theme?: "light" | "dark", o: { real?: boolean; tokens?: Tok } = {}): string {
  const ver = /const VERSION = '([^']+)'/.exec(html)?.[1] ?? "";
  const cfg = `window.__DZ=${JSON.stringify({ real: !!o.real, sigWhy: SIG_WHY, css: themeCss(o.tokens ?? {}) }).replace(/</g, "\\u003c")};window.__DZ.isBin=${isProbablyBinary.toString()};`;
  const tag = `<script>${theme ? prefsJs(theme, ver) : ""}${cfg}${BRIDGE_JS}${ENHANCE_JS}</script>`;
  const i = html.search(/<head[^>]*>/i);
  if (i < 0) return tag + html;
  const j = html.indexOf(">", i) + 1;
  return html.slice(0, j) + tag + html.slice(j);
}
export function makeSerialMount(be: SerialBackend, fallback: Mount, fetchText: (p: string) => Promise<string | null> = async p => { try { const r = await fetch(p, { cache: "no-store" }); return r.ok ? await r.text() : null; } catch { return null; } }): Mount {
  return (el, api) => {
    let inner: (() => void) | void, alive = true, off: (() => void) | null = null, fr: HTMLIFrameElement | null = null;
    el.innerHTML = `<div class="dash-wait"><wa-spinner></wa-spinner><span>正在载入串口工具…</span></div>`;
    const onMsg = async (e: MessageEvent) => {
      const m = e.data; if (!fr || e.source !== fr.contentWindow || m?.dzs !== "req") return;
      const reply = (p: any) => fr?.contentWindow?.postMessage({ dzs: "res", id: m.id, ...p }, "*");
      try {
        if (m.op === "open") { await be.open(Number(m.a?.baud) || 115200); off?.(); off = be.onData(hex => fr?.contentWindow?.postMessage({ dzs: "data", hex }, "*")); api.clearError(); }
        else if (m.op === "write") await be.write(String(m.a?.hex ?? ""));
        else if (m.op === "signals") { if (be.isReal?.() === false) throw { code: "not_serial" }; await be.setSignals({ dtr: m.a?.dtr, rts: m.a?.rts }); }
        else if (m.op === "close") { off?.(); off = null; await be.close(); }
        reply({ ok: true, r: null });
      } catch (err: any) { api.showError(String(err?.code || "error"), err?.message); reply({ ok: false, code: err?.code, message: err?.message }); }
    };
    addEventListener("message", onMsg);
    void fetchText(SERIAL_VENDOR_PATH).then(html => {
      if (!alive) return;
      if (!html) { inner = fallback(el, api); return; }   // 原版工具还没合入：用自写的串口调试（同一个后端）
      fr = document.createElement("iframe"); fr.className = "tb-embed"; fr.title = "串口调试"; fr.srcdoc = injectBridge(html, document.documentElement.dataset.theme === "dark" ? "dark" : "light", { real: be.isReal?.() ?? true, tokens: readTokens() }); el.innerHTML = ""; el.append(fr);
    });
    return () => { alive = false; inner?.(); off?.(); removeEventListener("message", onMsg); };
  };
}
