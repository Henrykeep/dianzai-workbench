import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/inter-tight/400.css";
import "@fontsource/inter-tight/500.css";
import "./tokens.css";
import "./style.css";
import { Err, Link, Msg } from "./ws";
import { Plot, chColor } from "./plot";
import { matchNames } from "./names";
import { AGENT_IDLE, initAgent } from "./agent";
import { initRaw } from "./raw";
import { initFFT } from "./fft";
import { initSend } from "./send";

type Field = { name: string; type: string; unit?: string; enum?: string[] };
type Param = { name: string; type: string; min: number; max: number; unit?: string; desc?: string; default: number };
type Schema = { hash: string; fields: Field[]; params: Param[]; period_ms?: number };

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const fmt = (v: number | undefined, p: Param | Field) => v == null || Number.isNaN(v) ? "—" : p.type === "f32" ? (+v.toPrecision(6)).toString() : String(Math.round(v));

const q = new URLSearchParams(location.search);
const link = new Link(q.get("ws") ?? "ws://127.0.0.1:8765");
const plot = new Plot($("pb"));

const S = {
  schema: null as Schema | null,
  plotted: [] as Field[],       // 数值通道（画线）
  enums: [] as Field[],         // 枚举通道（只显示文字，如 state）
  visible: [] as boolean[],
  enumVal: {} as Record<string, number>,
  applied: {} as Record<string, number>,
  edit: {} as Record<string, string>,
  status: {} as Msg,
  ports: [] as { port: string; desc: string; kind: string; likely: boolean }[],
  lastRx: 0, lastRxT: 0, rate: 0,
};

// ---------------------------------------------------------------- 提示
function toast(e: Err | string, kind: "crit" | "ok" | "info" | "warn" = "crit", ms = 9000) {
  const er: Err = typeof e === "string" ? { code: "", message: e } : e;
  const d = document.createElement("div");
  d.className = `toast ${kind}`;
  d.innerHTML = `<b>${esc(er.message)}</b>${er.fix ? `<span>怎么办：${esc(er.fix)}</span>` : ""}`;
  d.onclick = () => d.remove();
  $("toasts").prepend(d);
  setTimeout(() => d.remove(), ms);
}
const call = async <T = any>(op: string, args: Record<string, unknown> = {}) => {
  try { return await link.rpc<T>(op, args); } catch (e) { toast(e as Err); throw e; }
};

// ---------------------------------------------------------------- 急停：永远可点，不依赖任何状态
function estop() {
  link.fire("estop");
  const b = $("estop"); b.classList.add("hit"); setTimeout(() => b.classList.remove("hit"), 400);
  if (!link.open) toast({ code: "estop", message: "侧车未连接：急停没有送达！", fix: "立刻断电 / 拔电池" });
}
$("estop").onclick = estop;
addEventListener("keydown", e => {
  const typing = (e.target as HTMLElement).matches("input,select,textarea");
  if (e.key === "Escape" || (e.code === "Space" && !typing)) { e.preventDefault(); estop(); return; }
  if (typing && !(e.ctrlKey || e.metaKey)) return;
  if (e.key === "p" || e.key === "P") setRun(!plot.running);
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); sendPending(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveSnap(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") { e.preventDefault(); toggleConnect(); }
});

// ---------------------------------------------------------------- 端口
function renderPorts(keep = true) {
  const sel = $<HTMLSelectElement>("port"), cur = sel.value;
  sel.innerHTML = S.ports.map(p => `<option value="${esc(p.port)}">${esc(p.kind === "sim" ? p.desc : `${p.port} · ${p.desc}`)}</option>`).join("")
    || `<option value="">没有找到串口 — 插上 USB 转串口</option>`;
  // 零配置：USB 串口优先；没有就选仿真板（板载 ttyS0/COM1 几乎不会是你的板子，不默认选）
  const pick = (keep && S.ports.some(p => p.port === cur) && cur) || S.ports.find(p => p.likely)?.port || S.ports.find(p => p.kind === "sim")?.port || S.ports[0]?.port || "";
  sel.value = pick;
}
async function refreshPorts() {
  if (!link.open || S.status.connected) return;
  const old = new Set(S.ports.map(p => p.port));
  S.ports = await link.rpc("list_ports").catch(() => S.ports);
  const fresh = S.ports.filter(p => p.kind === "serial" && !old.has(p.port));
  renderPorts();
  if (old.size && fresh.length) { $<HTMLSelectElement>("port").value = fresh[0].port; toast(`检测到新串口 ${fresh[0].port}，已选中`, "info", 4000); }
}
setInterval(refreshPorts, 2000);

async function toggleConnect() {
  if (S.status.connected) { await call("disconnect"); return; }
  const port = $<HTMLSelectElement>("port").value;
  if (!port) return toast({ code: "", message: "没有可用端口", fix: "插上 USB 转串口；或选 sim: 仿真板先熟悉界面" });
  const btn = $<HTMLButtonElement>("connect");
  btn.disabled = true; btn.textContent = $<HTMLSelectElement>("baud").value === "auto" && !port.startsWith("sim:") ? "探测波特率…" : "连接中…";
  try {
    const r = await call("connect", { port, baud: $<HTMLSelectElement>("baud").value });
    if (r?.baud) $<HTMLSelectElement>("baud").value = String(r.baud);
    plot.clear();
  } catch { /* toast 已显示 */ } finally { btn.disabled = false; }
}
$("connect").onclick = toggleConnect;

// ---------------------------------------------------------------- 通道
function applySchema(s: Schema | null) {
  S.schema = s;
  if (!s) return;
  S.plotted = s.fields.filter(f => f.name !== "t_ms" && !f.enum);
  S.enums = s.fields.filter(f => f.enum);
  S.visible = S.plotted.map((_, i) => i < 4);
  plot.setChannels(S.plotted.map(f => f.name), S.plotted.map(f => f.unit ?? ""), S.visible);
  $("chan-n").textContent = `${S.plotted.length} 路 · ${s.period_ms ?? "?"} ms`;
  $("plot-sub").textContent = `schema ${s.hash}`;
  renderChans(); renderParams(); loadSnaps(); fft.setFields(S.plotted.map(f => f.name));
}
function renderChans() {
  $("chans").innerHTML = S.enums.map(f => `<div class="ch en"><span class="k">${esc(f.name)}</span><b id="ev-${f.name}" class="mono">—</b></div>`).join("")
    + S.plotted.map((f, i) => `<label class="ch ${S.visible[i] ? "on" : ""}" data-i="${i}" title="点击显示/隐藏">
      <span class="sw" style="--c:${chColor(i)}"></span><span class="k">${esc(f.name)}</span><b id="cv-${i}" class="mono">—</b><i>${esc(f.unit ?? "")}</i></label>`).join("");
  $("chans").querySelectorAll<HTMLElement>("label.ch").forEach(el => el.onclick = () => {
    const i = +el.dataset.i!; S.visible[i] = !S.visible[i]; el.classList.toggle("on", S.visible[i]); plot.show(i, S.visible[i]);
  });
}
// 按名字画：输入 "bb_* err" 回车，只显示匹配的通道；空回车恢复默认前 4 路
$<HTMLInputElement>("chan-q").onkeydown = e => {
  if (e.key !== "Enter") return;
  e.stopPropagation();
  S.visible = matchNames((e.target as HTMLInputElement).value, S.plotted.map(f => f.name));
  S.visible.forEach((on, i) => plot.show(i, on)); renderChans();
};
setInterval(() => {   // 读数 10 Hz 足够，别跟着 60 Hz 抖
  S.plotted.forEach((f, i) => { const el = document.getElementById(`cv-${i}`); if (el) el.textContent = fmt(plot.last(i), f); });
  S.enums.forEach(f => {
    const el = document.getElementById(`ev-${f.name}`), v = S.enumVal[f.name];
    if (el && v != null) { const name = f.enum![v] ?? String(v); el.textContent = name; el.className = `mono st-${name}`; }
  });
}, 100);

// ---------------------------------------------------------------- 参数
function clampLocal(p: Param, v: number) { let c = Math.min(Math.max(v, p.min), p.max); if (p.type !== "f32") c = Math.round(c); return c; }
function pending() {
  return (S.schema?.params ?? []).filter(p => p.name in S.edit && S.edit[p.name] !== "" && +S.edit[p.name] !== S.applied[p.name]);
}
function renderParams() {
  const ps = S.schema?.params ?? [];
  $("plist").innerHTML = ps.map(p => `<div class="prow" title="${esc(p.desc ?? "")}">
    <span class="k">${esc(p.name)}<i>${esc(p.desc ?? "")}</i></span>
    <input class="in" id="pi-${p.name}" data-n="${p.name}" inputmode="decimal" autocomplete="off">
    <span class="rng mono" id="pr-${p.name}" data-r="${fmt(p.min, p)}…${fmt(p.max, p)}${p.unit ? " " + esc(p.unit) : ""}"></span></div>`).join("")
    || `<div class="hint">连上板子并识别出数据格式后，这里会列出可调参数。</div>`;
  $("plist").querySelectorAll<HTMLInputElement>("input").forEach(inp => {
    inp.oninput = () => { S.edit[inp.dataset.n!] = inp.value; markParams(); };
    inp.onkeydown = e => {
      if (e.key === "Enter" && !e.ctrlKey) { e.preventDefault(); sendPending([inp.dataset.n!]); }
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {   // ↑↓ 按 1% 量程微调，Shift ×10
        e.preventDefault();
        const p = ps.find(x => x.name === inp.dataset.n)!, step = (p.max - p.min) / 100 * (e.shiftKey ? 10 : 1);
        const v = clampLocal(p, (+inp.value || 0) + (e.key === "ArrowUp" ? step : -step));
        inp.value = fmt(v, p); S.edit[p.name] = inp.value; markParams();
      }
    };
    inp.onblur = () => {
      const p = ps.find(x => x.name === inp.dataset.n)!;
      if (inp.value === "" || Number.isNaN(+inp.value)) { delete S.edit[p.name]; inp.value = fmt(S.applied[p.name], p); markParams(); return; }
      const c = clampLocal(p, +inp.value);
      if (c !== +inp.value) { toast(`${p.name} 超出范围，已限幅到 ${fmt(c, p)}`, "warn", 3000); inp.value = fmt(c, p); S.edit[p.name] = inp.value; markParams(); }
    };
  });
  syncParams();
}
function syncParams() {
  (S.schema?.params ?? []).forEach(p => {
    const inp = document.getElementById(`pi-${p.name}`) as HTMLInputElement | null;
    // 没在改的格子一律跟随板上值（含其他客户端 / Agent 改的），聚焦也跟随
    if (inp && !(p.name in S.edit)) inp.value = fmt(S.applied[p.name], p);
  });
  markParams();
}
function markParams() {
  const pend = new Set(pending().map(p => p.name));
  (S.schema?.params ?? []).forEach(p => {
    document.getElementById(`pi-${p.name}`)?.classList.toggle("chg", pend.has(p.name));
    // 草稿 ≠ 板上真值时，范围位置改显示板子回报的生效值（ACK/读回），避免把草稿当成已生效
    const r = document.getElementById(`pr-${p.name}`);
    if (r) { r.classList.toggle("brd", pend.has(p.name)); r.textContent = pend.has(p.name) ? `板上 ${fmt(S.applied[p.name], p)}` : r.dataset.r!; }
  });
  $("pend").textContent = pend.size ? `${pend.size} 项待下发` : "";
  $<HTMLButtonElement>("p-send").disabled = !pend.size;
  $<HTMLButtonElement>("p-revert").disabled = !Object.keys(S.edit).length;
}
async function sendPending(only?: string[]) {
  const list = pending().filter(p => !only || only.includes(p.name));
  for (const p of list) {
    try {
      const r = await call("param_set", { name: p.name, value: clampLocal(p, +S.edit[p.name]) });
      delete S.edit[p.name];
      S.applied[p.name] = r.applied;
      if (r.status === "clamped") toast(`${p.name} 被限幅为 ${fmt(r.applied, p)}`, "warn", 4000);
    } catch { break; }
  }
  syncParams();
}
$("p-send").onclick = () => sendPending();
$("p-revert").onclick = () => { S.edit = {}; syncParams(); };
$("p-read").onclick = async () => { await call("param_read_all"); };
$("p-def").onclick = async () => { if (confirm("把全部参数恢复成固件默认值？")) { await call("snapshot_restore", { defaults: true }); toast("已恢复默认参数", "ok", 3000); } };

// ---------------------------------------------------------------- 快照
async function loadSnaps(list?: any[]) {
  if (!S.schema) return;
  list ??= await link.rpc("snapshot_list").catch(() => []);
  $("snaps").innerHTML = list!.slice(0, 8).map(s => `<div class="hv"><span class="tag">${esc(s.time.slice(5, 16))}</span><span>${esc(s.name)}</span>
     <button class="btn ghost sm" data-s="${esc(s.name)}">恢复</button></div>`).join("") || `<div class="hint">调到好用的一组就存一下，翻车时一键恢复。</div>`;
  $("snaps").querySelectorAll<HTMLButtonElement>("button").forEach(b => b.onclick = async () => {
    await call("snapshot_restore", { name: b.dataset.s }); toast(`已恢复快照 ${b.dataset.s}`, "ok", 3000);
  });
}
async function saveSnap() {
  const name = $<HTMLInputElement>("snap-name").value.trim() || new Date().toTimeString().slice(0, 8).replace(/:/g, "");
  const r = await call("snapshot_save", { name }); $<HTMLInputElement>("snap-name").value = ""; loadSnaps(r.snapshots); toast(`快照已保存：${name}`, "ok", 2500);
}
$("snap-save").onclick = saveSnap;

// ---------------------------------------------------------------- 命令 / 回放 / 曲线控制
$("cmd-r").onclick = () => call("cmd", { c: "R" });
$("cmd-send").onclick = () => { const c = $<HTMLInputElement>("cmd-c").value, n = $<HTMLInputElement>("cmd-n").value; if (c) call("cmd", { c, n: n === "" ? null : +n }); };
$("win").querySelectorAll<HTMLElement>("span").forEach(s => s.onclick = () => {
  $("win").querySelectorAll("span").forEach(x => x.classList.toggle("on", x === s)); plot.win = +s.dataset.w!; plot.redraw();
});
function setRun(on: boolean) { plot.running = on; $("run").querySelectorAll<HTMLElement>("span").forEach(x => x.classList.toggle("on", (x.dataset.r === "1") === on)); }
$("run").querySelectorAll<HTMLElement>("span").forEach(s => s.onclick = () => setRun(s.dataset.r === "1"));
async function loadLogs() {
  const logs: any[] = await link.rpc("log_list").catch(() => []);
  $("logs").innerHTML = logs.map(l => `<option value="${esc(l.path)}">${esc(l.path.split(/[\\/]/).pop())} · ${(l.size / 1024).toFixed(0)} kB</option>`).join("") || `<option value="">（还没有记录）</option>`;
}
$("replay").onclick = async () => { const p = $<HTMLSelectElement>("logs").value; if (p) { await call("replay", { path: p }); plot.clear(); } };

// ---------------------------------------------------------------- 提议卡片（Agent 接缝）
function renderProposal(m: Msg) {
  $("props").querySelector(":scope > .hint")?.remove();
  const p = S.schema?.params.find(x => x.name === m.name);
  const d = document.createElement("div");
  d.className = "card";
  d.innerHTML = `<div class="hd"><span class="dotk"></span><span class="t">${esc(m.name)} ${p ? fmt(m.current, p) : m.current} → <em>${p ? fmt(m.value, p) : m.value}</em></span><span class="lbl">${esc(m.source)}</span></div>
    <p>${esc(m.reason)}${m.clamped ? "（已按范围限幅）" : ""}</p>
    <div class="act"><button class="btn pri" data-a="1">采纳 <kbd>Y</kbd></button><button class="btn" data-a="0">拒绝 <kbd>N</kbd></button></div>`;
  d.querySelectorAll<HTMLButtonElement>("button").forEach(b => b.onclick = async () => {
    try {
      const r = await call("proposal_decide", { id: m.id, accept: b.dataset.a === "1" });
      d.classList.add("done"); d.querySelector(".act")!.innerHTML = `<span class="lbl">${r.status === "applied" ? "已采纳 · 下发 " + r.applied : "已拒绝"}</span>`;
    } catch { /* toast */ }
  });
  $("props").prepend(d);
}

// ---------------------------------------------------------------- 状态
function renderStatus(st: Msg) {
  const was = S.status.connected;
  S.status = st;
  const now = performance.now();
  if (now - S.lastRxT > 900) { S.rate = st.rx_bytes >= S.lastRx ? (st.rx_bytes - S.lastRx) / ((now - S.lastRxT) / 1000) : 0; S.lastRx = st.rx_bytes; S.lastRxT = now; }
  $("led").className = "led " + (st.alive ? "ok" : st.connected ? "warn" : "");
  $("ro-link").innerHTML = st.connected ? `${esc(st.port.replace(/^replay:.*[\\/]/, "回放 "))}<i>${st.reconnecting ? "重连中…" : st.baud || ""}</i>` : "未连接";
  $("ro-schema").innerHTML = st.schema ? `${st.schema}<i>${st.schema_ok ? "已识别" : "未知"}</i>` : "—";
  $("ro-rx").innerHTML = st.connected ? `${(S.rate / 1024).toFixed(1)} kB/s<i>${st.good} 帧${st.bad ? ` · 坏 ${st.bad}` : ""}</i>` : "—";
  $("rec").hidden = !st.log;
  $("st-log").textContent = st.replay ? `回放 ${(st.replay_progress * 100).toFixed(0)}%` : st.log ? `记录到 ${st.log}` : "未记录";
  $("st-hint").textContent = st.hint ?? "";
  $("rp").hidden = !st.replay;
  if (st.replay) {
    if (!rpDrag) rpPos.value = String(Math.round(st.replay_progress * 1000));
    $("rp-t").textContent = `${st.replay_pos.toFixed(1)} / ${st.replay_len.toFixed(1)} s`;
    $("rp-play").textContent = st.replay_paused ? "▶" : "⏸";
    if (document.activeElement !== $("rp-speed")) $<HTMLSelectElement>("rp-speed").value = String(st.replay_speed);
  }
  $("connect").innerHTML = st.connected ? "断开 <kbd>⌃O</kbd>" : "连接 <kbd>⌃O</kbd>";
  $("connect").classList.toggle("pri", !st.connected);
  $<HTMLSelectElement>("port").disabled = $<HTMLSelectElement>("baud").disabled = !!st.connected;
  $("empty").hidden = !!st.connected && !!S.schema;
  $("empty").innerHTML = `<div>${st.connected ? (st.hint ? esc(st.hint) : "等待板子心跳…") : "选端口，点 <b>连接</b>。<br>没有硬件？选 <b>仿真板</b> 先熟悉界面。"}</div>`;
  if (was && !st.connected) { applyNone(); loadLogs(); }
}
function applyNone() {
  S.schema = null; S.applied = {}; S.edit = {}; S.plotted = []; S.enums = []; S.enumVal = {};
  plot.setChannels([], [], []); $("chans").innerHTML = ""; $("chan-n").textContent = ""; $("plot-sub").textContent = "";
  $("snaps").innerHTML = ""; renderParams();
  $("props").innerHTML = AGENT_IDLE;
}

const agent = initAgent(call);
const fft = initFFT((op, a) => link.rpc(op, a ?? {}));
const send = initSend((op, a) => link.rpc(op, a ?? {}), e => toast(e as Err));
const raw = initRaw((op, a) => link.rpc(op, a ?? {}), v => fft.setView(v === "fft"));
// 回放时间轴：拖动 = 跳转（旧样本清掉，曲线从新位置画）
let rpDrag = false;
const rpPos = $<HTMLInputElement>("rp-pos");
rpPos.oninput = () => { rpDrag = true; };
rpPos.onchange = async () => { rpDrag = false; await call("replay_ctl", { seek: +rpPos.value / 1000 * (S.status.replay_len || 0) }); };
$("rp-play").onclick = () => call("replay_ctl", { pause: !S.status.replay_paused });
$("rp-speed").onchange = () => call("replay_ctl", { speed: +$<HTMLSelectElement>("rp-speed").value });
$("export").onclick = async (e: MouseEvent) => {
  const p = $<HTMLSelectElement>("logs").value;
  if (!p) return toast("还没有记录可导出：连上板子会自动记录", "info");
  const r = await call("log_export", { path: p, fmt: e.shiftKey ? "plotjuggler" : "excel" }).catch(() => null);
  if (r) toast(`已导出 ${r.rows} 行 → ${r.path}`, "ok", 12000);
};
$("props").innerHTML = AGENT_IDLE;
link.on(m => {
  agent.onMsg(m); raw.onMsg(m); send.onMsg(m);
  switch (m.type) {
    case "telem": {
      plot.push(m.t, m.y);
      S.enums.forEach(f => { const a = m.y[f.name]; if (a?.length) S.enumVal[f.name] = a[a.length - 1]; });
      break;
    }
    case "status": renderStatus(m); break;
    case "schema": applySchema(m.schema); break;
    case "param": S.applied[m.name] = m.value; syncParams(); break;
    case "proposal": renderProposal(m); break;
    case "error": toast(m as unknown as Err); break;
    case "seeked": plot.clear(); break;
    case "reconnected": toast(m.message, "ok", 5000); break;
    case "estop": toast(m.message, m.sent ? "info" : "crit", m.sent ? 2500 : 15000); break;
  }
});
link.onState = async open => {
  $("st-ws").textContent = open ? "侧车 已连接" : "侧车 未连接";
  $("banner").hidden = open;
  $("banner").innerHTML = "侧车（dzbench）没有响应，正在重连…  开发模式请先运行 <code>python -m dzbench</code>";
  if (!open) return;
  const h = await link.rpc("hello");
  S.ports = h.ports; renderPorts(false);
  if (h.schema) { applySchema(h.schema); S.applied = h.params; syncParams(); }
  renderStatus(h.status); loadLogs();
};
renderParams();
