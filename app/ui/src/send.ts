// 发送栏 + 常用指令（单发 / 定时）；真正发送都在侧车里，急停后侧车拒发（思路参考 SerialWeb，代码自写）
import { Msg } from "./ws";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

export function initSend(rpc: (op: string, a?: Record<string, unknown>) => Promise<any>, err: (e: unknown) => void) {
  const k = $<HTMLSelectElement>("snd-k"), eol = $<HTMLSelectElement>("snd-eol"), inp = $<HTMLInputElement>("snd-in");
  const ms = $<HTMLInputElement>("snd-ms"), box = $("snd-presets");
  const unesc = (s: string) => s.replace(/\\r/g, "\r").replace(/\\n/g, "\n");
  const go = () => {
    const v = inp.value;
    const a = k.value === "hex" ? { hex: v.replace(/\s|0x/g, "") } : { text: v + unesc(eol.value) };
    rpc("send_raw", a).catch(err);
  };
  $("snd-go").onclick = go;
  inp.onkeydown = e => { if (e.key === "Enter") go(); };
  $("snd-save").onclick = () => {
    const name = prompt("常用指令名", inp.value.slice(0, 12)); if (!name) return;
    rpc("preset_save", { preset: { name, kind: k.value, payload: inp.value, eol: unesc(eol.value) } }).then(render).catch(err);
  };
  function render(list: any[]) {
    box.innerHTML = "";
    for (const p of list) {
      const b = document.createElement("button"); b.className = "btn ghost sm"; b.textContent = p.name;
      b.title = `${p.kind}: ${p.payload}`; b.onclick = () => rpc("preset_send", { name: p.name }).catch(err);
      const t = document.createElement("button"); t.className = "btn ghost sm" + (p.timer ? " on" : ""); t.textContent = p.timer ? "■" : "⟳";
      t.title = p.timer ? "停止定时" : `每 ${ms.value} ms 发一次`;
      t.onclick = () => rpc("preset_timer", { name: p.name, on: !p.timer, period_ms: +ms.value }).then(() => rpc("preset_list").then(render)).catch(err);
      const g = document.createElement("button"); g.className = "btn ghost sm" + (p.trigger ? " on" : "");
      g.textContent = p.trigger ? `⚡${p.trigger.field}${p.trigger.op}${p.trigger.value}·${p.trigger.fired}` : "⚡";
      g.title = p.trigger ? "取消触发" : "遥测满足条件时发一次（如 lock >= 1）";
      g.onclick = () => {
        if (p.trigger) { rpc("preset_trigger", { name: p.name, on: false }).then(render).catch(err); return; }
        const r = prompt("触发条件：字段 比较符 值（> < >= <= ==）", "lock >= 1"); if (!r) return;
        const mm = r.trim().match(/^(\w+)\s*(>=|<=|==|>|<)\s*(-?[\d.eE+-]+)$/);
        if (!mm) { err({ code: "bad_trigger", message: "格式：字段 比较符 值，例如 lock >= 1" }); return; }
        rpc("preset_trigger", { name: p.name, field: mm[1], op_: mm[2], value: +mm[3], cooldown_ms: 200 })
          .then(() => rpc("preset_list").then(render)).catch(err);
      };
      const x = document.createElement("button"); x.className = "btn ghost sm"; x.textContent = "×"; x.title = "删除";
      x.onclick = () => rpc("preset_delete", { name: p.name }).then(render).catch(err);
      box.append(b, t, g, x);
    }
  }
  rpc("preset_list").then(render).catch(() => {});
  return {
    onMsg(m: Msg) {
      if (m.type === "sender") render(m.presets as any[]);
      if (m.type === "tx_locked") { inp.disabled = !!m.on; inp.placeholder = m.on ? "急停中：发送已锁定，解除急停后恢复" : "要发的内容，回车发送"; }
    },
  };
}
