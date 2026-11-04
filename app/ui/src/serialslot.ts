// 串口工具挂载点（适配层）：工具本体由 vendor-tools 分支放到 app/ui/public 下的一个固定路径（SERIAL_VENDOR_PATH），这里不放任何第三方代码。
// 挂载时把一段自写的桥接脚本（navigator.serial 的同形接口）注入工具页面，收发全部经本地服务（ws.ts：connect / send_raw / raw_monitor / serial_lines_set / serial_modem），
// 桌面版和网页版走同一条路，不用浏览器 Web Serial。以后换别的串口工具，只改这一个文件。
import type { Mount } from "./toolbox";
export const SERIAL_VENDOR_PATH = "vendor/serialweb/index.html";
export type Rpc = (op: string, a?: Record<string, unknown>) => Promise<any>;
export interface SerialBackend { open(baud: number): Promise<void>; write(hex: string): Promise<void>; setSignals(s: { dtr?: boolean; rts?: boolean }): Promise<void>; close(): Promise<void>; onData(f: (hex: string) => void): () => void }
/** 本地服务串口后端：已连着板子就复用这条连接，不抢；没连就用顶栏选中的端口去连 */
export function sidecarSerial(rpc: Rpc, subscribe: (f: (m: any) => void) => () => void, cur: () => { connected: boolean; port: string }): SerialBackend {
  return {
    async open(baud) { if (!cur().connected) { if (!cur().port) throw { code: "no_board", message: "顶栏还没选串口" }; await rpc("connect", { port: cur().port, baud }); } await rpc("raw_monitor", { on: true }); },
    async write(hex) { await rpc("send_raw", { hex }); },
    async setSignals(s) { await rpc("serial_lines_set", s); },
    async close() { /* 不断开本地服务的连接：别的页面还在用 */ },
    onData(f) { return subscribe(m => { if (m?.type === "raw") for (const [, d, hex] of m.c as [number, number, string][]) if (!d) f(hex); }); },
  };
}
// 注入到工具页面里的桥（自写，MIT 同仓库许可）：把 navigator.serial 换成经 postMessage 转给本地服务的同形对象
// 适配层里 toHost 发给的是外层页面（postMessage 消息 open/close/write/signals），不是侧车 op；外层再转成 connect/send_raw/serial_lines_set
export const BRIDGE_JS = `(()=>{const P=window.parent;let seq=0;const W={};addEventListener("message",e=>{const m=e.data||{};if(m.dzs==="res"&&W[m.id]){W[m.id](m);delete W[m.id];}if(m.dzs==="data"&&port._c){const b=new Uint8Array(m.hex.match(/../g).map(h=>parseInt(h,16)));try{port._c.enqueue(b)}catch(_){}}});
const toHost=(op,a)=>new Promise((ok,no)=>{const id=++seq;W[id]=m=>m.ok?ok(m.r):no(Object.assign(new Error(m.message||op),{code:m.code}));P.postMessage({dzs:"req",id,op,a},"*")});
const port={_c:null,readable:null,writable:null,getInfo(){return{usbVendorId:undefined,usbProductId:undefined}},
async open(o){await toHost("open",{baud:(o&&o.baudRate)||115200});this.readable=new ReadableStream({start:c=>{port._c=c}});this.writable=new WritableStream({write:ch=>toHost("write",{hex:Array.from(ch,b=>b.toString(16).padStart(2,"0")).join("")})});},
async close(){try{port._c&&port._c.close()}catch(_){}port._c=null;this.readable=null;this.writable=null;await toHost("close",{})},
async setSignals(s){await toHost("signals",{dtr:s.dataTerminalReady,rts:s.requestToSend})},async getSignals(){return{}},addEventListener(){},removeEventListener(){}};
const serial={async requestPort(){return port},async getPorts(){return[port]},addEventListener(){},removeEventListener(){}};
try{Object.defineProperty(navigator,"serial",{value:serial,configurable:true})}catch(_){}})();`;
export function injectBridge(html: string): string {
  const tag = `<script>${BRIDGE_JS}</script>`;
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
        else if (m.op === "signals") await be.setSignals({ dtr: m.a?.dtr, rts: m.a?.rts });
        else if (m.op === "close") { off?.(); off = null; await be.close(); }
        reply({ ok: true, r: null });
      } catch (err: any) { api.showError(String(err?.code || "error"), err?.message); reply({ ok: false, code: err?.code, message: err?.message }); }
    };
    addEventListener("message", onMsg);
    void fetchText(SERIAL_VENDOR_PATH).then(html => {
      if (!alive) return;
      if (!html) { inner = fallback(el, api); return; }   // 原版工具还没合入：用自写的串口调试（同一个后端）
      fr = document.createElement("iframe"); fr.className = "tb-embed"; fr.title = "串口调试"; fr.srcdoc = injectBridge(html); el.innerHTML = ""; el.append(fr);
    });
    return () => { alive = false; inner?.(); off?.(); removeEventListener("message", onMsg); };
  };
}
