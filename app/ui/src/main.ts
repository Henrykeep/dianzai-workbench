import "./tokens.css";
import "./style.css";
import { createIcons, Activity, Ellipsis, Eraser, Flag, Ruler, Play, Sparkles, FilePen, Hammer, History, ListChecks, MessageSquarePlus, RotateCcw, Settings, ShieldOff, SlidersHorizontal, Stethoscope, SunMoon, Undo2, Zap } from "lucide";
import { initChrome, emptyState, notifySide } from "./chrome";
import { Err, Link, Msg } from "./ws";
import { Plot, chColor, num } from "./plot";
import { matchNames } from "./names";
import { Param, clampLocal, pendingOf, rangeLabel } from "./params";
import { AGENT_IDLE, agentIdle, initAgent } from "./agent";
import { initRaw } from "./raw";
import { initFFT } from "./fft";
import { initSend } from "./send";
import { initAnalysis } from "./analysis";

type Field = { name: string; type: string; unit?: string; enum?: string[]; na?: number; pin?: string; pin_with?: string[]; ref_for?: string };
type Schema = { hash: string; fields: Field[]; params: Param[]; period_ms?: number };

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const fmt = (v: number | undefined, p: Param | Field) => v == null || Number.isNaN(v) || ("na" in p && p.na === v) ? "—" : p.type === "f32" ? (Math.abs(v) < 1e-30 ? "0" : (+v.toPrecision(6)).toString()) : String(Math.round(v));

const q = new URLSearchParams(location.search);
const link = new Link(q.get("ws") ?? "ws://127.0.0.1:8765");
const plot = new Plot($("pb"));
const ana = initAnalysis(plot, () => S.applied, notifySide);
const showXDiv = () => { const d = plot.xDiv(); $("xdiv").textContent = `${d < 1 ? d * 1000 + " ms" : d + " s"}/div`; };

const S = {
  lastLog: "" as string,
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
    const low = $<HTMLSelectElement>("lines").value === "low";
    await call("serial_lines", low ? { dtr: false, rts: false } : { dtr: null, rts: null });
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
  if ($("props").querySelector(":scope > .hint")) $("props").innerHTML = agentIdle(s.fields.map(f => f.name));
  document.querySelectorAll(".ro.pin").forEach(e => e.remove());
  $("stats").insertAdjacentHTML("beforeend", S.enums.filter(f => f.pin).map(f =>
    `<div class="ro pin" title="${esc(f.name)}"><span class="lbl">${esc(f.pin!)}</span><span class="v" id="pin-${f.name}">—</span></div>`).join(""));
  // 设定值通道（schema 里写了 ref_for）叠在被控量 lane 上画虚线，不单独占 lane，也不占“默认显示前 4 条”的名额
  const refFor = S.plotted.map(f => S.plotted.findIndex(p => p.name === f.ref_for));
  let shown = 0;
  S.visible = S.plotted.map((_, i) => refFor[i] >= 0 || shown++ < 4);
  plot.setChannels(S.plotted.map(f => f.name), S.plotted.map(f => f.unit ?? ""), S.visible, refFor);
  ana.reset(); showXDiv();
  $("chan-n").textContent = `${S.plotted.length} 路 · ${s.period_ms ?? "?"} ms`;
  $("plot-sub").textContent = `schema ${s.hash}`;
  renderChans(); renderParams(); loadSnaps(); { const tg = new Set(S.plotted.map(f => f.ref_for).filter(Boolean)), nm = (f: Field) => f.name;   // 被控量（有设定值指向的）排最前，设定值放最后：默认选中的是要找振荡的那个量
    fft.setFields([...S.plotted.filter(f => tg.has(f.name)).map(nm), ...S.plotted.filter(f => !tg.has(f.name) && !f.ref_for).map(nm), ...S.plotted.filter(f => f.ref_for).map(nm)]); }
  raw.binary();
}
function renderChans() {
  $("chans").innerHTML = S.enums.map(f => `<div class="ch en"><span class="k">${esc(f.name)}</span><b id="ev-${f.name}" class="mono">—</b></div>`).join("")
    + S.plotted.map((f, i) => `<label class="ch ${S.visible[i] ? "on" : ""}" data-i="${i}" title="点击显示/隐藏">
      <span class="sw" style="--c:${chColor(i)}"></span><span class="k">${esc(f.name)}</span><b id="cv-${i}" class="mono">—</b><i>${esc(f.unit ?? "")}</i></label>`).join("");
  $("chans").querySelectorAll<HTMLElement>("label.ch").forEach(el => el.onclick = () => {
    const i = +el.dataset.i!; S.visible[i] = !S.visible[i]; el.classList.toggle("on", S.visible[i]); plot.show(i, S.visible[i]);
  });
}
// 按名字画：输入 "sp_* err" 回车，只显示匹配的通道；空回车恢复默认前 4 路
// 参数筛选：真实赛题工程常有几十个参数（2026H 有 52 个，机械常数排在前面），要调的几个得能一下找到
const pq = $<HTMLInputElement>("p-q");
function filterParams() {
  const rows = [...$("plist").querySelectorAll<HTMLElement>(".prow")], q = pq.value.trim();
  pq.hidden = rows.length <= 8;
  // 每个词：带 * 按通配，否则子串（名字或说明里有就算）；多个词取并集。“ki” 能找到 ball_ki。
  const toks = q.split(/[\s,，]+/).filter(Boolean).map(t => t.includes("*") ? new RegExp("^" + t.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$", "i") : t.toLowerCase());
  const hit = (r: HTMLElement) => toks.some(t => typeof t === "string" ? (r.id.slice(4) + " " + r.title).toLowerCase().includes(t) : t.test(r.id.slice(4)));
  const on2 = rows.map(r => !toks.length || hit(r));
  rows.forEach((r, i) => { r.hidden = !on2[i]; });
}
pq.oninput = filterParams;
pq.onkeydown = e => { e.stopPropagation(); if (e.key === "Escape") { pq.value = ""; filterParams(); pq.blur(); } };
document.addEventListener("keydown", e => { if (e.key === "/" && !(e.target instanceof HTMLInputElement) && !pq.hidden) { e.preventDefault(); pq.focus(); } });
$<HTMLInputElement>("chan-q").onkeydown = e => {
  if (e.key !== "Enter") return;
  e.stopPropagation();
  S.visible = matchNames((e.target as HTMLInputElement).value, S.plotted.map(f => f.name));
  S.visible.forEach((on, i) => plot.show(i, on)); renderChans();
};
// ELF 变量观察：输入时联想符号名（来自 ELF），“开始”后样本走虚拟通道，和普通遥测一样画线
let elfTypes: Record<string, string> = {};
$<HTMLInputElement>("elf-q").oninput = async e => {
  const w = (e.target as HTMLInputElement).value.split(/\s+/).pop()!.split(":")[0];
  if (w.length < 2) return;
  const r: any[] | null = await call("elf_symbols", { q: w }).catch(() => null);
  if (!r) return;
  r.forEach(x => elfTypes[x.name] = x.type);
  $("elf-list").innerHTML = r.map(x => `<option value="${esc(x.name)}">${x.addr} · ${x.size} B</option>`).join("");
};
$("elf-go").onclick = async () => {
  const vars = $<HTMLInputElement>("elf-q").value.split(/[\s,]+/).filter(Boolean)
    .map(w => { const [name, type] = w.split(":"); return { name, type: type || elfTypes[name] || "f32" }; });
  if (!vars.length) return toast("先输入变量名", "info");
  const r = await call("watch_start", { vars, period_ms: 20 }).catch(() => null);
  if (r) { $("elf-n").textContent = `${r.fields.length} 个 · ${r.period_ms} ms`; toast("开始读 " + r.fields.map((f: any) => `${f.name}@${f.addr}`).join(", "), "ok"); }
};
$("elf-stop").onclick = async () => { await call("watch_stop", {}).catch(() => null); $("elf-n").textContent = ""; };
setInterval(() => {   // 读数 10 Hz 足够，别跟着 60 Hz 抖
  S.plotted.forEach((f, i) => {
    const v = plot.last(i), cv = document.getElementById(`cv-${i}`), lv = document.getElementById(`lv-${i}`);
    if (cv) cv.textContent = fmt(v, f);
    // lane 读数用 4 位有效数字的定宽格式，避免 -0.461538 这种抖动的长串
    if (lv) lv.innerHTML = v == null || Number.isNaN(v) ? "—" : (f.type === "f32" ? num(v) : String(Math.round(v))) + (f.unit ? `<small>${esc(f.unit)}</small>` : "");
  });
  S.enums.forEach(f => {
    const el = document.getElementById(`ev-${f.name}`), v = S.enumVal[f.name];
    if (el && v != null) { const name = f.enum![v] ?? String(v); el.textContent = name; el.className = `mono st-${name}`; }
  });
  // schema 里标了 pin 的枚举字段放到顶栏（视觉链路、通信、模式……由题目自己声明，界面不认字段名）
  for (const f of S.enums) {
    if (!f.pin || S.enumVal[f.name] == null) continue;
    const name = f.enum![S.enumVal[f.name]] ?? "?";
    const extra = (f.pin_with ?? []).map(n => {
      const k = S.plotted.findIndex(p => p.name === n); const v = k < 0 ? null : plot.last(k);
      return v == null ? "" : ` · ${Math.round(v)}${S.plotted[k].unit ? " " + S.plotted[k].unit : ""}`;
    }).join("");
    const el = document.getElementById(`pin-${f.name}`);
    if (el) el.innerHTML = `<b class="st-${name}">${esc(name)}</b><i>${esc(extra.replace(/^ · /, ""))}</i>`;
  }
}, 100);

// ---------------------------------------------------------------- 参数
function pending() {
  return pendingOf(S.schema?.params ?? [], S.edit, S.applied);
}
const pos = (p: Param, v: number) => p.max > p.min ? String(Math.min(Math.max((v - p.min) / (p.max - p.min), 0), 1)) : "0";
function renderParams() {
  const ps = S.schema?.params ?? [];
  // 参数（docs/26 §6）：名字 + 数值同一行；下面一把刻度尺：板上值（实线）、默认值（○）、草稿（黄铜，连一段改动范围）、量程两端。
  // 全部来自 schema 的 params（名字 / 量程 / 单位 / 说明），界面不认任何题目的参数名。
  $("plist").innerHTML = ps.length ? ps.map(p => `<div class="prow" id="row-${p.name}" title="${esc(p.desc ?? "")}">
    <div class="pr"><span class="k mono">${esc(p.name)}</span><span class="bv mono" id="pb-${p.name}"></span>
      <input class="in" id="pi-${p.name}" data-n="${p.name}" inputmode="decimal" autocomplete="off"><span class="u">${esc(p.unit ?? "")}</span></div>
    <div class="ruler"><i class="def" style="--x:${pos(p, p.default)}"></i><i class="brd" id="pk-${p.name}"></i><i class="span" id="ps-${p.name}"></i><i class="new" id="pn-${p.name}"></i></div>
    <div class="rgx mono"><span>${fmt(p.min, p)}</span><span class="ds">${esc(p.desc ?? "")}</span><span>${fmt(p.max, p)}</span></div></div>`).join("")
    : emptyState("sliders", "连上后列出可调参数");
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
  filterParams();
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
    // 草稿 ≠ 板上真值：行变成“待下发”，旧值划掉留在左边，刻度尺上黄铜标出新值和改动范围（板上始终是板子回报的生效值）
    const on = pend.has(p.name), b = document.getElementById(`pb-${p.name}`), v = S.applied[p.name];
    document.getElementById(`row-${p.name}`)?.classList.toggle("dirty", on);
    if (b) b.textContent = on ? fmt(v, p) : "";
    const set = (id: string, k: string, x: string) => document.getElementById(id)?.style.setProperty(k, x);
    if (v != null) set(`pk-${p.name}`, "--x", pos(p, v));
    if (on && v != null) { const n = clampLocal(p, +S.edit[p.name]); set(`pn-${p.name}`, "--x", pos(p, n)); set(`ps-${p.name}`, "--a", pos(p, Math.min(v, n))); set(`ps-${p.name}`, "--b", pos(p, Math.max(v, n))); }
  });
  const pl = pending();
  $("pend").innerHTML = pl.map(p => `<span>${esc(p.name)}</span><span>${fmt(S.applied[p.name], p)} → <b>${fmt(clampLocal(p, +S.edit[p.name]), p)}</b></span>`).join("");
  flow();
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

// 顶栏流程：连接 → 调参 → 阶跃 → 判读 → 定稿，按当前状态点亮（done = 已经过，now = 下一步该做的）
// 定稿 = 本次会话里参数 yaml 已经 git 提交（写回卡片确认 + 门禁通过）。之后再改参数就回到“调参”。
let finalSha = "";
window.addEventListener("dz-final", e => { finalSha = String((e as CustomEvent).detail || "✓"); flow(); });
function flow() {
  const c = !!S.status.connected && !!S.schema, pend = pending().length > 0, runs = ana.runs(), mk = ana.marked();
  if (pend) finalSha = "";
  const now = !c ? "conn" : pend ? "tune" : finalSha ? "end" : !mk ? "step" : runs ? "read" : "step";
  const order = ["conn", "tune", "step", "read", "save", "end"], k = order.indexOf(now);
  const sv = $("flow").querySelector<HTMLElement>('[data-s="save"]')!;
  sv.title = finalSha ? `已写回并提交 ${finalSha.slice(0, 7)}` : "定稿：把板上当前参数写回 app.yaml 的 default（先看 diff，确认后跑门禁并 git 提交）";
  $("flow").querySelectorAll<HTMLElement>("span").forEach((s, i) => { s.className = i < k ? "done" : i === k ? "now" : ""; });
}
setInterval(flow, 1000);
$("flow").querySelector<HTMLElement>('[data-s="save"]')!.onclick = () => {
  (document.querySelector('#rail [data-side="agent"]') as HTMLElement)?.click();
  $("ag-yaml").click();
};

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
  $("win").querySelectorAll("span").forEach(x => x.classList.toggle("on", x === s)); plot.win = +s.dataset.w!; showXDiv(); plot.redraw();
});
function setRun(on: boolean) { plot.running = on; $("run").querySelectorAll<HTMLElement>("span").forEach(x => x.classList.toggle("on", (x.dataset.r === "1") === on)); }
$("run").querySelectorAll<HTMLElement>("span").forEach(s => s.onclick = () => setRun(s.dataset.r === "1"));
// 回放列表只列当前端口 / 仿真应用的记录（文件名带端口标签，见 session.start_log）；“其他端口”收在最后一项
let logsAll = false;
const portTag = (p: string) => p.split("/").pop()!.replace(/[^0-9A-Za-z_+-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
async function loadLogs() {
  const logs: any[] = await link.rpc("log_list").catch(() => []);
  const tag = portTag(S.status?.connected ? S.status.port : $<HTMLSelectElement>("port").value || "");
  const mine = logs.filter(l => tag && String(l.path).replace(/\.dzlog$/, "").endsWith("_" + tag));
  const shown = logsAll ? logs : mine, others = logs.length - mine.length;
  $("logs").innerHTML = (shown.map(l => `<option value="${esc(l.path)}">${esc(l.path.split(/[\\/]/).pop())} · ${(l.size / 1024).toFixed(0)} kB${l.recording ? " · 记录中" : ""}</option>`).join("")
    || `<option value="">没有记录</option>`) + (!logsAll && others ? `<option value="__all">其他端口的 ${others} 个记录…</option>` : "");
}
$("logs").addEventListener("change", () => { if ($<HTMLSelectElement>("logs").value === "__all") { logsAll = true; loadLogs(); } });
$("port").addEventListener("change", () => { logsAll = false; loadLogs(); });
$("replay").onclick = async () => { const p = $<HTMLSelectElement>("logs").value; if (p && p !== "__all") { await call("replay", { path: p }); plot.clear(); } };

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
  notifySide("agent");
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
  if (st.log && st.log !== S.lastLog) { S.lastLog = st.log; loadLogs(); }   // 新开的记录马上出现在回放列表
  $("st-log").textContent = st.replay ? `回放 ${(st.replay_progress * 100).toFixed(0)}%` : st.log ? `记录到 ${st.log}` : "未记录";
  $("st-hint").textContent = [st.hint, st.clients > 1 ? `另有 ${st.clients - 1} 个窗口也连着侧车：参数以最后一次下发为准，急停哪个窗口按都有效` : ""].filter(Boolean).join("  ·  ");
  $("rp").hidden = !st.replay;
  if (st.replay) {
    if (!rpDrag) rpPos.value = String(Math.round(st.replay_progress * 1000));
    $("rp-t").textContent = `${st.replay_pos.toFixed(1)} / ${st.replay_len.toFixed(1)} s`;
    $("rp-play").textContent = st.replay_paused ? "▶" : "⏸";
    if (document.activeElement !== $("rp-speed")) $<HTMLSelectElement>("rp-speed").value = String(st.replay_speed);
  }
  $("connect").innerHTML = st.connected ? "断开 <kbd>⌃O</kbd>" : "连接 <kbd>⌃O</kbd>";
  $("connect").classList.toggle("pri", !st.connected);
  $<HTMLSelectElement>("port").disabled = $<HTMLSelectElement>("baud").disabled = $<HTMLSelectElement>("lines").disabled = !!st.connected;
  $("empty").hidden = !!st.connected && !!S.schema;
  $("empty").innerHTML = `<div>${st.connected ? (st.hint ? esc(st.hint) : "等待板子心跳…") : "选端口，点 <b>连接</b>。<br>没有硬件？选 <b>仿真板</b> 先熟悉界面。"}</div>`;
  if (was && !st.connected) { applyNone(); loadLogs(); }
}
function applyNone() {
  S.schema = null; S.applied = {}; S.edit = {}; S.plotted = []; S.enums = []; S.enumVal = {};
  plot.setChannels([], [], []); $("chans").innerHTML = emptyState("activity", "连上后列出通道"); $("chan-n").textContent = ""; $("plot-sub").textContent = "";
  $("snaps").innerHTML = ""; renderParams();
  document.querySelectorAll(".ro.pin").forEach(e => e.remove());   // 断开后不留上一个对象的状态块
  $("props").innerHTML = AGENT_IDLE;
}

const agent = initAgent(call);
const fft = initFFT((op, a) => link.rpc(op, a ?? {}));
const send = initSend((op, a) => link.rpc(op, a ?? {}), e => toast(e as Err));
const raw = initRaw((op, a) => link.rpc(op, a ?? {}), v => { fft.setView(v === "fft"); document.querySelector<HTMLElement>(".scope")!.dataset.view = v; });   // 只属于示波的控件在原始/频谱里收起
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
$("chans").innerHTML = emptyState("activity", "连上后列出通道");
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
    case "port_moved": toast(m.message, "warn", 8000); break;
    case "estop": toast(m.message, m.sent ? "info" : "crit", m.sent ? 2500 : 15000); break;
  }
});
link.onState = async open => {
  $("st-ws").textContent = open ? "侧车 已连接" : "侧车 未连接";
  $("banner").hidden = open;
  $("banner").innerHTML = "侧车（dzbench）没有响应：程序会自动把它重启，界面自动重连。板子 1 秒收不到心跳会自己急停。开发模式请先运行 <code>python -m dzbench</code>";
  if (!open) return;
  const h = await link.rpc("hello");
  S.ports = h.ports; renderPorts(false);
  $<HTMLInputElement>("auto-rc").onchange = e => { call("auto_reconnect", { on: (e.target as HTMLInputElement).checked }).catch(() => {}); };
  if (h.recovered && !h.status.connected) {   // 侧车刚崩过：说清楚，预选上次的口，但不自动连（第一个动作交给人）
    toast({ code: "recovered", message: h.recovered.message, fix: "" }, "warn", 30000);
    if (S.ports.some(p => p.port === h.recovered.port)) $<HTMLSelectElement>("port").value = h.recovered.port;
  }
  if (h.schema) { applySchema(h.schema); S.applied = h.params; syncParams(); }
  renderStatus(h.status); loadLogs();
};
renderParams();

$("doctor").onclick = async () => {
  const items: any[] = await call("doctor", {}).catch(() => null) || [];
  const mk: Record<string, string> = { ok: "✓", warn: "!", fail: "✗" };
  $("doc-list").innerHTML = items.map(i => `<li class="d-${i.level}"><b>${mk[i.level]} ${esc(i.name)}</b>：${esc(i.msg)}${i.fix ? `<br><i>→ ${esc(i.fix)}</i>` : ""}</li>`).join("");
  $<HTMLDialogElement>("doc").show();
};

createIcons({ icons: { Activity, Ellipsis, Eraser, Flag, Ruler, Play, Sparkles, FilePen, Hammer, History, ListChecks, MessageSquarePlus, RotateCcw, Settings, ShieldOff, SlidersHorizontal, Stethoscope, SunMoon, Undo2, Zap } });
initChrome();
