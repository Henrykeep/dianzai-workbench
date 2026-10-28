// 原始监视器：串口收发原始字节，文本 / HEX 两种看法（思路参考 SerialWeb，代码自写）
import { Msg } from "./ws";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const MAX_LINES = 3000;

export function initRaw(rpc: (op: string, a?: Record<string, unknown>) => Promise<any>, onView: (raw: boolean) => void) {
  let fmt: "txt" | "hex" = "txt", on = false, rx = 0, tx = 0, lines = 0;
  const list = $("raw-list");
  const dec = new TextDecoder("utf-8", { fatal: false });
  let partial = "";                        // 文本模式下未换行的半行

  const seg = (id: string, attr: string, f: (v: string) => void) => $(id).querySelectorAll<HTMLElement>("span").forEach(x => x.onclick = () => {
    $(id).querySelectorAll("span").forEach(y => y.classList.toggle("on", y === x)); f(x.dataset[attr]!);
  });
  seg("view", "v", v => { on = v === "raw"; $("raw").hidden = !on; rpc("raw_monitor", { on }).catch(() => {}); onView(on); });
  seg("raw-fmt", "f", v => { fmt = v as "txt" | "hex"; });
  $("raw-clr").onclick = () => { list.innerHTML = ""; lines = 0; partial = ""; };

  function line(t: number, d: number, text: string) {
    const e = document.createElement("div");
    e.className = d ? "tx" : "rx";
    e.innerHTML = `${$<HTMLInputElement>("raw-ts").checked ? `<i>${t.toFixed(3)}</i>` : ""}<b>${d ? "TX" : "RX"}</b>`;
    e.append(text);
    list.append(e);
    if (++lines > MAX_LINES) { list.firstElementChild?.remove(); lines--; }
  }

  return {
    onMsg(m: Msg) {
      if (m.type !== "raw" || !on) return;
      const stick = list.scrollTop + list.clientHeight >= list.scrollHeight - 4;
      for (const [t, d, hex] of m.c as [number, number, string][]) {
        const bytes = new Uint8Array(hex.match(/../g)!.map(h => parseInt(h, 16)));
        d ? (tx += bytes.length) : (rx += bytes.length);
        if (d && !$<HTMLInputElement>("raw-tx").checked) continue;
        if (fmt === "hex" || d) { line(t, d, hex.match(/../g)!.join(" ").toUpperCase()); continue; }
        // 文本：按换行切行；不可见字符显示成 ·
        const s = (partial + dec.decode(bytes, { stream: true })).replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "·");
        const parts = s.split(/\r?\n/);
        partial = parts.pop()!;
        if (partial.length > 200) { parts.push(partial); partial = ""; }
        parts.forEach(p => line(t, 0, p));
      }
      $("raw-stat").textContent = `RX ${rx} B · TX ${tx} B`;
      if (stick) list.scrollTop = list.scrollHeight;
    },
  };
}
