import { lastRound } from "./round";
import "./tokens.css";
import "./style.css";
import { createIcons, Activity, Ellipsis, Eraser, Download, Eye, PlugZap, Flag, Ruler, Play, Sparkles, FilePen, Hammer, History, ListChecks, MessageSquarePlus, RotateCcw, Settings, ShieldOff, SlidersHorizontal, Stethoscope, SunMoon, Undo2, Zap, FolderKanban, Cpu, Crosshair, ClipboardCheck, PackageCheck, PanelLeft, X, FileText } from "lucide";
import { initChrome, emptyState, notifySide } from "./chrome";
import { Err, Link, Msg } from "./ws";
import { LAYOUTS, Layout, Plot, chColor, num } from "./plot";
import { matchNames } from "./names";
import { Param, clampLocal, pendingOf, rangeLabel, noInitialGains } from "./params";
import { AGENT_IDLE, agentIdle, initAgent } from "./agent";
import { initRaw } from "./raw";
import { initFFT } from "./fft";
import { initSend } from "./send";
import { initAnalysis, Loop } from "./analysis";
import { Cal, calMap } from "./calib";
import { AcceptSpec } from "./accept";
import { initHbStrip } from "./hbstrip";
import { initTimeline, kindOf } from "./timeline";
import { Fixed, protectRows, UndoLog } from "./protect";
import { Alerts } from "./alerts";
import { humanize, humanHtml } from "./errors";
import { conn, onLinkState, linkStateActive } from "./conn";
import { linkView, runState, modeLabel } from "./linkmsg";
import { initPjAsk } from "./pjask";
import { estopText } from "./estop";
import { fetchProgress, render as renderProgress } from "./progress";
import type { Step } from "./steps";
import { initSteps } from "./steps";
import { initCalWiz } from "./calwiz";
import { initSymptoms } from "./symptoms";
import { initProjFlow } from "./projflow";
import { initScore } from "./score";

type Field = { name: string; type: string; unit?: string; enum?: string[]; na?: number; pin?: string; pin_with?: string[]; ref_for?: string; cal?: Cal };
type Schema = { hash: string; fields: Field[]; params: Param[]; period_ms?: number; accept?: AcceptSpec[]; loops?: Loop[]; protect_fixed?: Fixed[] };
let CAL = new Map<string, { f: (x: number) => number; unit: string }>();

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const fmt = (v: number | undefined, p: Param | Field) => v == null || Number.isNaN(v) || ("na" in p && p.na === v) ? "—" : p.type === "f32" ? (Math.abs(v) < 1e-30 ? "0" : (+v.toPrecision(6)).toString()) : String(Math.round(v));

const q = new URLSearchParams(location.search);
const link = new Link(q.get("ws") ?? "ws://127.0.0.1:8765");
const plot = new Plot($("pb"));
const UNDO = new UndoLog();   // 参数下发前的板上值（保护阈值表的“撤销”）
// 心跳条点格子：回放按 dzlog 时间跳；实时把曲线停在那一秒（缓冲里还有的话）
const jumpAt = async (c: { log_t: number | null; plot_t: number | null }) => {
  if (S.status.replay && c.log_t != null) { await call("replay_ctl", { seek: Math.max(c.log_t - 1, 0) }); return; }
  const where = c.log_t != null ? `dzlog ${c.log_t.toFixed(1)} s` : "（当时没在记录）";
  if (c.plot_t != null && plot.inBuffer(c.plot_t - 0.5)) { setRun(false); plot.jumpTo(c.plot_t - 0.5); toast(`已暂停在这一秒 · ${where}；按 P 继续`, "info", 4000); }
  else toast(`这一秒已滚出曲线缓冲：${where}，可以在底栏回放这份记录再点`, "warn", 6000);
};
const hb = initHbStrip($("hbstrip"), jumpAt);
const AL = new Alerts();
function renderAlerts() {
  const el = $("alerts"), l = AL.list;
  el.hidden = !l.length;
  // 急停/看门狗锁存：告警里写明“已急停 + 原因 + 怎么解除”，并点亮右上角唯一的「解除」按钮（不另开入口）
  const latched = l.some(e => e.kind === "estop" || e.kind === "watchdog");
  document.getElementById("cmd-r")?.classList.toggle("attn", latched);
  if (!l.length) { el.innerHTML = ""; return; }
  const last = l[l.length - 1];
  const isE = (e: any) => e.kind === "estop" || e.kind === "watchdog";
  // 急停：只显示侧车给的说明（estop.ts 兜底），不显示 dzlog 时间戳
  el.innerHTML = latched
    ? `<span class="al-n">${l.length}</span><span class="al-t" title="点击跳到这一刻"><b class="al-h">${esc(estopText(l.filter(isE).pop() as any))}</b></span>`
    : `<span class="al-n">${l.length}</span><b class="al-h">链路异常</b><span class="al-t" title="点击跳到这一刻">原因：${esc(last.text)}</span>`;
  el.innerHTML +=
    (l.length > 1 ? `<span class="al-more">${l.slice(0, -1).reverse().slice(0, 4).map(e => esc(e.text)).join(" · ")}</span>` : "") +
    `<span class="sp"></span>` + (S.status.tx_locked ? `<button class="btn sm" id="al-r" title="确认安全后发 R：板子解除急停锁存，侧车恢复发送">解除急停 R</button>` : "") +
    `<button class="btn sm" id="al-ack">知道了</button>`;
  el.querySelector<HTMLElement>(".al-t")!.onclick = () => jumpAt(last);
  const r = el.querySelector<HTMLElement>("#al-r"); if (r) r.onclick = async () => { await call("cmd", { c: "R" }); renderAlerts(); };
  $("al-ack").onclick = async () => { const r = await call("alert_ack", { upto: AL.top() }); AL.ack(r.upto); renderAlerts(); };
}
const tl = initTimeline($("tl"), e => jumpAt({ log_t: e.log_t, plot_t: e.plot_t != null ? e.plot_t + 0.5 : null }),
  evs => plot.setMarks(evs.filter(e => e.plot_t != null).map(e => ({ t: e.plot_t!, tag: kindOf(e.kind)[0], color: kindOf(e.kind)[1] }))));
const ana = initAnalysis(plot, () => S.applied, notifySide);
const showXDiv = () => { const d = plot.xDiv(); $("xdiv").textContent = `${d < 1 ? d * 1000 + " ms" : d + " s"}/div`; };

const S = {
  nsnap: 0 as number,
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
  // 侧车已给出 fix 的按原样显示；否则过翻译层（发生了什么 · 原因 · 处理 + 详情）
  const h = !er.fix && kind !== "ok" && kind !== "info" ? humanize(`${er.code} ${er.message}`) : null;
  d.innerHTML = h ? humanHtml(h, esc) : `<b>${esc(er.message)}</b>${er.fix ? `<span>处理：${esc(er.fix)}</span>` : ""}`;
  d.onclick = e => { if (!(e.target as Element).closest("details")) d.remove(); };
  $("toasts").prepend(d);
  setTimeout(() => d.remove(), ms);
}
const call = async <T = any>(op: string, args: Record<string, unknown> = {}) => {
  try { return await link.rpc<T>(op, args); } catch (e) { toast(e as Err); throw e; }
};

// ---------------------------------------------------------------- 急停：永远可点，不依赖任何状态
function estop(src = "按钮") {
  link.fire("estop", { src });
  const b = $("estop"); b.classList.add("hit"); setTimeout(() => b.classList.remove("hit"), 400);
  if (!link.open) toast({ code: "estop", message: "侧车未连接：急停没有送达！", fix: "立刻断电 / 拔电池" });
}
$("estop").onclick = () => estop("急停按钮");
addEventListener("keydown", e => {
  const el = e.target as HTMLElement;
  const typing = el.matches("input,select,textarea");
  // Esc / 空格是急停快捷键；但 Esc 在下拉框、输入框、弹窗、展开菜单里是“关闭”，空格在按钮上是“点它”——
  // 这些情况按急停会让新用户一连上就看到锁存的急停告警，所以交给浏览器默认行为（急停按钮永远可点）。
  const closing = typing || !!el.closest("details[open]") || !!document.querySelector("dialog:modal");
  const pressing = el.matches("button,summary,a,[role=button]");
  if ((e.key === "Escape" && !closing) || (e.code === "Space" && !typing && !pressing)) {
    e.preventDefault(); estop(e.key === "Escape" ? "Esc 键" : "空格键"); return;
  }
  if (typing && !(e.ctrlKey || e.metaKey)) return;
  if (e.key === "p" || e.key === "P") setRun(!plot.running);
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); sendPending(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveSnap(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") { e.preventDefault(); toggleConnect(); }
});

// ---------------------------------------------------------------- 端口
function renderPorts(keep = true) {
  const sel = $<HTMLSelectElement>("port"), cur = sel.value;
  // 排序：可能是板子的 USB 串口 → 仿真板 → 其余（板载 ttyS0/COM1 放最后）
  const rank = (p: { kind: string; likely?: boolean }) => p.likely ? 0 : p.kind === "sim" ? 1 : 2;
  S.ports = [...S.ports].sort((a, b) => rank(a) - rank(b));
  sel.innerHTML = S.ports.map(p => `<option value="${esc(p.port)}">${esc(p.kind === "sim" ? p.desc : `${p.port} · ${p.desc}`)}</option>`).join("")
    || `<option value="">没有找到串口 — 插上 USB 转串口</option>`;
  // 零配置：USB 串口优先；没有就选仿真板（板载 ttyS0/COM1 几乎不会是你的板子，不默认选）
  const last = localStorage.getItem("dz-port") ?? "";   // 记住上次连接的端口
  const pick = (keep && S.ports.some(p => p.port === cur) && cur) || S.ports.find(p => p.likely)?.port || (S.ports.some(p => p.port === last) && last) || S.ports.find(p => p.kind === "sim")?.port || S.ports[0]?.port || "";
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
    localStorage.setItem("dz-port", port);
    if (r?.baud) $<HTMLSelectElement>("baud").value = String(r.baud);
    plot.clear();
  } catch { /* toast 已显示 */ } finally { btn.disabled = false; }
}
$("connect").onclick = toggleConnect;
// 串口线控（缺口 14）：DTR/RTS 实时开关、复位 / 进 BOOT 脉冲、CTS/DSR、卡死检测
const lnShow = (r: any) => {
  $<HTMLInputElement>("ln-dtr").checked = !!r.dtr; $<HTMLInputElement>("ln-rts").checked = !!r.rts;
  const b = (v: boolean | null) => v == null ? "?" : v ? "1" : "0";
  $("ln-modem").textContent = `CTS ${b(r.cts)} · DSR ${b(r.dsr)} · RI ${b(r.ri)} · CD ${b(r.cd)}`;
};
const lnErr = (e: any) => { $("ln-st").textContent = `✗ ${e?.message ?? e}`; };
$("lines-btn").onclick = async () => {
  $("ln-st").textContent = ""; $<HTMLInputElement>("ln-stall").value = String(S.status.stall_s ?? 0);
  $<HTMLDialogElement>("ln-dlg").show();
  link.rpc("serial_modem", {}).then(lnShow, lnErr);
};
for (const k of ["dtr", "rts"]) $(`ln-${k}`).onchange = e => link.rpc("serial_lines_set", { [k]: (e.target as HTMLInputElement).checked }).then(lnShow, lnErr);
$("ln-dlg").addEventListener("click", e => {
  const b = (e.target as HTMLElement).closest<HTMLElement>("[data-pulse]");
  if (!b || !window.confirm(`${b.textContent}：会拨 DTR/RTS，板子可能复位。继续？`)) return;
  link.rpc("serial_pulse", { name: b.dataset.pulse! }).then(r => { lnShow(r); $("ln-st").textContent = `已执行 ${b.textContent}`; }, lnErr);
});
$("ln-stall").onchange = e => link.rpc("serial_stall", { s: +(e.target as HTMLInputElement).value || 0 }).then(r => { $("ln-st").textContent = r.stall_s ? `卡死检测：${r.stall_s} s` : "卡死检测已关"; }, lnErr);

// ---------------------------------------------------------------- 通道
function applySchema(s: Schema | null) {
  S.schema = s;
  queueMicrotask(() => score.refresh());
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
  // 单位标定（schema 字段的 cal）：进曲线前换成物理单位；原始帧视图不变
  CAL = calMap(s.fields);
  plot.setChannels(S.plotted.map(f => f.name), S.plotted.map(f => CAL.get(f.name)?.unit ?? f.unit ?? ""), S.visible, refFor);
  ana.setSpec(s.accept ?? [], s.loops ?? [], l => { pq.value = l ? (l.gains ?? []).map(g => "=" + g).join(" ") : ""; filterParams(); });
  ana.reset(); showXDiv();
  $("chan-n").textContent = `${S.plotted.length} 路 · ${s.period_ms ?? "?"} ms`;
  $("plot-sub").textContent = `schema ${s.hash}`;
  renderChans(); renderParams(); loadSnaps(); calwiz?.refresh(); { const tg = new Set(S.plotted.map(f => f.ref_for).filter(Boolean)), nm = (f: Field) => f.name;   // 被控量（有设定值指向的）排最前，设定值放最后：默认选中的是要找振荡的那个量
    fft.setFields([...S.plotted.filter(f => tg.has(f.name)).map(nm), ...S.plotted.filter(f => !tg.has(f.name) && !f.ref_for).map(nm), ...S.plotted.filter(f => f.ref_for).map(nm)]); }
  raw.binary();
}
function renderChans() {
  $("chans").innerHTML = S.enums.map(f => `<div class="ch en"><span class="k">${esc(f.name)}</span><b id="ev-${f.name}" class="mono">—</b></div>`).join("")
    + S.plotted.map((f, i) => `<label class="ch ${S.visible[i] ? "on" : ""}" data-i="${i}" title="点击显示/隐藏">
      <span class="sw" style="--c:${chColor(i)}"></span><span class="k">${esc(f.name)}</span><b id="cv-${i}" class="mono">—</b><i title="${CAL.has(f.name) ? "已按 schema cal 标定（原始 " + esc(f.unit ?? "") + "）" : ""}">${esc(CAL.get(f.name)?.unit ?? f.unit ?? "")}</i></label>`).join("");
  $("chans").querySelectorAll<HTMLElement>("label.ch").forEach(el => el.onclick = () => {
    const i = +el.dataset.i!; S.visible[i] = !S.visible[i]; el.classList.toggle("on", S.visible[i]); plot.show(i, S.visible[i]);
  });
}
// 按名字画：输入 "sp_* err" 回车，只显示匹配的通道；空回车恢复默认前 4 路
// 参数筛选：真实赛题工程常有几十个参数（2026H 有 52 个，机械常数排在前面），要调的几个得能一下找到
const pq = $<HTMLInputElement>("p-q");
function filterParams() {
  const rows = [...$("plist").querySelectorAll<HTMLElement>(".prow")], q = pq.value.trim();
  pq.hidden = rows.length <= 8 && !q;           // 选了串级层时即使参数少也显示，好让人看见并清掉筛选
  // 每个词：=名字 精确，带 * 按通配，否则子串（名字或说明里有就算）；多个词取并集。“ki” 能找到 ball_ki。
  const toks = q.split(/[\s,，]+/).filter(Boolean).map(t => t.startsWith("=") ? new RegExp("^" + t.slice(1).replace(/[.+?^${}()|[\]\\*]/g, "\\$&") + "$", "i") : t.includes("*") ? new RegExp("^" + t.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$", "i") : t.toLowerCase());
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
    <div class="pr"><span class="k mono" title="${esc(p.name)}">${esc(p.name)}</span><span class="bv mono" id="pb-${p.name}"></span>
      <input class="in" id="pi-${p.name}" data-n="${p.name}" inputmode="decimal" autocomplete="off"><span class="u">${esc(p.unit ?? "")}</span></div>
    ${p.desc ? `<div class="pdesc">${esc(p.desc)}</div>` : ""}
    <div class="ruler"><i class="def" style="--x:${pos(p, p.default)}"></i><i class="brd" id="pk-${p.name}"></i><i class="span" id="ps-${p.name}"></i><i class="new" id="pn-${p.name}"></i></div>
    <div class="rgx mono"><span>${fmt(p.min, p)}</span><span class="sp"></span><span>${fmt(p.max, p)}</span></div></div>`).join("")
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
  renderProtect();
  syncParams();
}
// 保护阈值表（protect.ts）：输入框和参数面板共用草稿 S.edit；“撤销”= 把上一次下发前的板上值当草稿再下发一次
function renderProtect() {
  const rows = protectRows((S.schema?.params ?? []) as any, S.schema?.protect_fixed ?? []);
  $("ptab").innerHTML = rows.length ? `<table><thead><tr><th>保护项</th><th>参数</th><th>板上</th><th>改为</th><th>量程</th><th></th></tr></thead><tbody>${rows.map(r => r.p
    ? `<tr title="${esc(r.p.desc ?? "")}"><td>${esc(r.cat)}</td><td class="mono">${esc(r.p.name)}</td><td class="mono" id="pt-v-${r.p.name}"></td>
        <td><input class="in" id="pt-${r.p.name}" data-n="${r.p.name}" inputmode="decimal" autocomplete="off"></td><td class="mono">${fmt(r.p.min, r.p)}–${fmt(r.p.max, r.p)} ${esc(r.p.unit ?? "")}</td>
        <td><button class="btn ghost sm" data-u="${r.p.name}" title="撤销：恢复上一次下发前的板上值">撤销</button></td></tr>`
    : `<tr class="fixed" title="编译期常量，改要重烧：${esc(r.fixed!.where ?? "")}"><td>${esc(r.cat)}</td><td class="mono">—</td><td class="mono">${esc(String(r.fixed!.value))} ${esc(r.fixed!.unit ?? "")}</td><td colspan="3" class="lbl">固件常量 · ${esc(r.fixed!.where ?? "")}</td></tr>`).join("")}</tbody></table>`
    : emptyState("sliders", "这个对象没有声明保护阈值：在 app.yaml 的参数上加 protect: 分类（如 倾倒角）");
  $("ptab").querySelectorAll<HTMLInputElement>("input").forEach(inp => {
    inp.oninput = () => { S.edit[inp.dataset.n!] = inp.value; markParams(); };
    inp.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); sendPending([inp.dataset.n!]); } };
  });
  $("ptab").querySelectorAll<HTMLButtonElement>("button[data-u]").forEach(b => b.onclick = async () => {
    const n = b.dataset.u!, p = (S.schema?.params ?? []).find(x => x.name === n)!, v = UNDO.pop(n);
    if (v == null) { toast(`${n} 这次会话里还没下发过，没有可撤销的`, "info", 3000); return; }
    S.edit[n] = String(v); await sendPending([n], true); toast(`${n} 已撤销为 ${fmt(v, p)}`, "ok", 3000);
  });
}
// 增益全 0 时“无初值一键起步”与“阶跃实验”互换位置：起步成为操作条主按钮，阶跃收进“更多实验”
// （同一组元素搬位置，入口仍各只有一个，操作条顶层按钮数不变）
function syncRelaySlot() {
  const relay = document.getElementById("ag-relay"), step = document.getElementById("ag-step"), pop = document.querySelector("#tune-more .pop");
  if (!relay || !step || !pop) return;
  const zero = noInitialGains(S.schema?.params ?? [], S.applied);
  if (zero === (relay.parentElement !== pop)) return;
  if (zero) { step.replaceWith(relay); pop.prepend(step); relay.className = "btn go"; step.className = "mi"; }
  else { relay.replaceWith(step); pop.prepend(relay); step.className = "btn go"; relay.className = "mi"; }
}
function syncParams() {
  syncRelaySlot();
  (S.schema?.params ?? []).forEach(p => {
    const inp = document.getElementById(`pi-${p.name}`) as HTMLInputElement | null;
    // 没在改的格子一律跟随板上值（含其他客户端 / Agent 改的），聚焦也跟随
    if (inp && !(p.name in S.edit)) inp.value = fmt(S.applied[p.name], p);
    const pt = document.getElementById(`pt-${p.name}`) as HTMLInputElement | null, pv = document.getElementById(`pt-v-${p.name}`);
    if (pt && document.activeElement !== pt) pt.value = p.name in S.edit ? S.edit[p.name] : fmt(S.applied[p.name], p);
    if (pv) pv.textContent = fmt(S.applied[p.name], p);
    document.querySelector<HTMLButtonElement>(`button[data-u="${p.name}"]`)?.toggleAttribute("disabled", UNDO.peek(p.name) == null);
  });
  markParams();
}
function markParams() {
  const pend = new Set(pending().map(p => p.name));
  (S.schema?.params ?? []).forEach(p => {
    document.getElementById(`pi-${p.name}`)?.classList.toggle("chg", pend.has(p.name));
    document.getElementById(`pt-${p.name}`)?.classList.toggle("chg", pend.has(p.name));
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
  life();
}
// 参数生命周期条：草稿 → 板上 RAM → 快照 → flash → app.yaml，每一格写当前状态，点一下去对应入口
function life() {
  const ps = S.schema?.params ?? [], n = pending().length;
  const off = ps.filter(p => S.applied[p.name] != null && Math.abs(+S.applied[p.name] - +p.default) > 1e-9).length;
  const st: Record<string, string> = { edit: n ? `${n} 待下发` : "无草稿", ram: off ? `${off}≠默认` : "=默认", snap: `${S.nsnap ?? 0} 个`, flash: "去封箱", yaml: "去封箱" };
  $("life").querySelectorAll<HTMLElement>("[data-l]").forEach(e => { e.querySelector("i")!.textContent = st[e.dataset.l!]; e.classList.toggle("hot", (e.dataset.l === "edit" && n > 0) || (e.dataset.l === "ram" && off > 0)); });
}
// 参数栏“更多”：保护 / 快照 收进菜单，标签行只留当前页名
document.querySelectorAll<HTMLElement>("#dock-more [data-d2]").forEach(b => b.onclick = () => {
  document.querySelector<HTMLElement>(`#dock-tabs [data-d="${b.dataset.d2}"]`)?.click(); ($("dock-more") as HTMLDetailsElement).open = false; });
$("life").querySelectorAll<HTMLElement>("[data-l]").forEach(e => e.onclick = () => {
  const l = e.dataset.l;
  if (l === "edit" || l === "ram") (document.querySelector('#dock-tabs [data-d="params"]') as HTMLElement)?.click();
  else if (l === "snap") (document.querySelector('#dock-tabs [data-d="snaps"]') as HTMLElement)?.click();
  else (document.querySelector('#steps [data-step="封箱"]') as HTMLElement)?.click();
});
async function sendPending(only?: string[], undoing = false) {
  const list = pending().filter(p => !only || only.includes(p.name));
  for (const p of list) {
    try {
      const before = S.applied[p.name];
      const r = await call("param_set", { name: p.name, value: clampLocal(p, +S.edit[p.name]) });
      if (!undoing) UNDO.push(p.name, before);
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
$("p-rb").onclick = async () => { const r = await call("params_readback", {}); toast(`已回读到 ${r.path}`, "ok", 5000); };
$("p-def").onclick = async () => { if (confirm("把全部参数恢复成固件默认值？")) { await call("params_restore", { source: "default" }); toast("已恢复默认参数", "ok", 3000); } };

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
  // “自动-最好一轮”只走“回到… → 最好一轮”这一个入口，快照列表不再重复列
  list = list!.filter(s => s.name !== "自动-最好一轮"); S.nsnap = list.length; life();
  $("snaps").innerHTML = list!.slice(0, 8).map(s => `<div class="hv"><span class="tag">${esc(s.time.slice(5, 16))}</span>${s.mode ? `<span class="tag">${s.mode === "speed" ? "速度环" : "位置环"}</span>` : ""}<span>${esc(s.name)}</span>
     <button class="btn ghost sm" data-s="${esc(s.name)}">恢复</button></div>`).join("") || `<div class="hint">调到好用的一组就存一下，翻车时一键恢复。</div>`;
  $("snaps").querySelectorAll<HTMLButtonElement>("button").forEach(b => b.onclick = async () => {
    const ramp_s = Math.max(0, Math.min(10, Number($<HTMLInputElement>("snap-ramp").value) || 0));
    await call("params_restore", { source: "snapshot", name: b.dataset.s, ramp_s }); toast(`已恢复快照 ${b.dataset.s}${ramp_s ? `（${ramp_s} s 平滑过渡）` : ""}`, "ok", 3000);
  });
}
async function saveSnap() {
  const name = $<HTMLInputElement>("snap-name").value.trim() || new Date().toTimeString().slice(0, 8).replace(/:/g, "");
  const r = await call("snapshot_save", { name, mode: $<HTMLSelectElement>("snap-mode").value }); $<HTMLInputElement>("snap-name").value = ""; loadSnaps(r.snapshots); toast(`快照已保存：${name}`, "ok", 2500);
}
$("snap-save").onclick = saveSnap;

// ---------------------------------------------------------------- 命令 / 回放 / 曲线控制
$("cmd-r").onclick = () => call("cmd", { c: "R" });
$("cmd-send").onclick = () => { const c = $<HTMLInputElement>("cmd-c").value, n = $<HTMLInputElement>("cmd-n").value; if (c) call("cmd", { c, n: n === "" ? null : +n }); };
$("win").querySelectorAll<HTMLElement>("span").forEach(s => s.onclick = () => {
  $("win").querySelectorAll("span").forEach(x => x.classList.toggle("on", x === s)); plot.win = +s.dataset.w!; showXDiv(); plot.redraw();
});
// 分格布局（缺口 13），记在 localStorage
const setLayout = (l: string) => {
  if (!(LAYOUTS as string[]).includes(l)) l = "split";
  $("layout").querySelectorAll<HTMLElement>("span").forEach(x => x.classList.toggle("on", x.dataset.l === l));
  localStorage.setItem("dz-layout", l); plot.setLayout(l as Layout);
};
$("layout").onclick = (e: MouseEvent) => { const s = (e.target as HTMLElement).closest<HTMLElement>("[data-l]"); if (s) setLayout(s.dataset.l!); };
setLayout(localStorage.getItem("dz-layout") ?? "split");
function setRun(on: boolean) { plot.running = on; if (on) plot.view = null; $("run").querySelectorAll<HTMLElement>("span").forEach(x => x.classList.toggle("on", (x.dataset.r === "1") === on)); }
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
  // 建议卡（v6 稿）：参数 旧 → 新、最近一轮实测 vs 护栏目标、一句理由、采纳 / 驳回
  const R = lastRound, k = R?.metrics, tg = R?.verdict?.target ?? {};
  const n1 = (v: any, d: number, u: string) => v == null || !Number.isFinite(+v) ? "—" : (+v).toFixed(d) + u;
  const rows = k?.ok ? `<table class="sg"><tr><th></th><th>实测 #${esc(R!.verdict.round)}</th><th>目标</th></tr>
      <tr><td>超调</td><td>${n1(k.overshoot_pct, 1, "%")}</td><td class="ok-t">${tg.overshoot_pct != null ? "≤ " + n1(tg.overshoot_pct, 0, "%") : "—"}</td></tr>
      <tr><td>调节</td><td>${n1(k.settling_s, 2, " s")}</td><td>—</td></tr>
      <tr><td>稳态误差</td><td>${n1(k.sse_pct, 1, "%")}</td><td class="ok-t">${tg.sse_pct != null ? "≤ " + n1(tg.sse_pct, 1, "%") : "—"}</td></tr></table>` : "";
  d.className = "card sugg";
  d.innerHTML = `<div class="sg-h"><span class="mono">${esc(m.name)}</span><span class="sg-v">${p ? fmt(m.current, p) : m.current} → <em>${p ? fmt(m.value, p) : m.value}</em></span></div>
    ${rows}<p>${esc(m.reason)}${m.clamped ? "（已按范围限幅）" : ""}</p><div class="lbl">来源：${esc(m.source)}</div>
    <div class="act"><button class="btn pri" data-a="1">采纳 <kbd>Y</kbd></button><button class="btn" data-a="0">驳回 <kbd>N</kbd></button></div>`;
  d.querySelectorAll<HTMLButtonElement>("button").forEach(b => b.onclick = async () => {
    try {
      const r = await call("proposal_decide", { id: m.id, accept: b.dataset.a === "1" });
      d.classList.add("done"); d.querySelector(".act")!.innerHTML = `<span class="lbl">${r.status === "applied" ? "已采纳 · 下发 " + r.applied : "已驳回"}</span>`;
    } catch { /* toast */ }
  });
  if (m.source === "标定") { document.querySelector("#cal-props > .hint")?.remove(); $("cal-props").prepend(d); return; }   // 标定页的提议卡就地确认
  $("props").prepend(d);
  notifySide("agent");
}

// ---------------------------------------------------------------- 状态
function renderStatus(st: Msg) {
  const was = S.status.connected;
  if (!conn.get().sidecar) st = { ...st, connected: false, alive: false };   // 侧车断开时不信旧 status
  const relock = S.status?.tx_locked !== st.tx_locked;
  S.status = st;
  if (!linkStateActive()) conn.set({ board: !!st.connected, alive: !!st.alive });   // 有 link.state 时以它为准
  if (relock) renderAlerts();   // 急停锁存变化：告警条上的“解除急停 R”跟着出现/消失
  const now = performance.now();
  if (now - S.lastRxT > 900) { S.rate = st.rx_bytes >= S.lastRx ? (st.rx_bytes - S.lastRx) / ((now - S.lastRxT) / 1000) : 0; S.lastRx = st.rx_bytes; S.lastRxT = now; }
  $("led").className = "led " + (st.alive ? "ok" : st.connected ? "warn" : "");
  $("ro-link").innerHTML = st.connected ? `${esc(st.port.replace(/^replay:.*[\\/]/, "回放 "))}<i>${st.reconnecting ? `重连中…${st.reconnect_attempt ? "（第 " + st.reconnect_attempt + " 次）" : ""}` : st.baud || ""}</i>` : "未连接";
  $("ro-schema").innerHTML = st.schema ? `${st.schema}<i>${st.schema_ok ? "已识别" : "未知"}</i>` : "—";
  // 心跳 status 字（dzctl 0.5.0）：复位原因 + 安全态/堵转/急停标志；旧固件没有 → 不显示
  $("ro-schema").title = st.reset ? `板子复位原因：${st.reset}${st.hb_flags?.length ? "；" + st.hb_flags.join("、") : ""}` : "";
  if (st.hb_flags?.length) $("ro-schema").innerHTML += `<i class="hb-flag">${esc(st.hb_flags.join("·"))}</i>`;
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
  // 曲线区空状态即引导：说明这一页做什么 + 一个主按钮（点的是已有入口，不新增功能入口）
  $("empty").innerHTML = st.connected
    ? `<div class="es"><b>等待目标板心跳</b><p>${st.hint ? esc(st.hint) : "曲线将在收到第一帧数据后显示。"}</p></div>`
    : `<div class="es"><b>未连接</b><p>曲线区显示目标板实时数据。连接目标板，或选择「仿真板」在无硬件时开始。</p><button class="btn pri" data-go="sim">开始仿真</button></div>`;
  $("empty").querySelector<HTMLElement>("[data-go=sim]")?.addEventListener("click", () => {
    const sel = $<HTMLSelectElement>("port"), o = [...sel.options].find(x => x.value.startsWith("sim:"));
    if (o) sel.value = o.value; $("connect").click();
  });
  if (!was && st.connected) { call("health").then(h => hb.set(h)).catch(() => {}); call("timeline").then(r => { tl.set(r.events); AL.ack(r.acked); r.events.forEach((x: any) => AL.offer(x)); renderAlerts(); }).catch(() => {}); }   // 刷新页面/新窗口：补回已有的格子
  if (was && !st.connected) { applyNone(); loadLogs(); hb.clear(); tl.clear(); AL.reset(); renderAlerts(); }
}
function applyNone() {
  S.schema = null; UNDO.clear(); S.applied = {}; S.edit = {}; S.plotted = []; S.enums = []; S.enumVal = {};
  plot.setChannels([], [], []); $("chans").innerHTML = emptyState("activity", "连上后列出通道"); $("chan-n").textContent = ""; $("plot-sub").textContent = "";
  $("snaps").innerHTML = ""; renderParams();
  document.querySelectorAll(".ro.pin").forEach(e => e.remove());   // 断开后不留上一个对象的状态块
  $("props").innerHTML = AGENT_IDLE;
}

const agent = initAgent(call);
const calwiz = initCalWiz(call, () => S.plotted.map(f => f.name), () => S.schema?.params ?? [], t => toast(t, "warn", 3000));
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
  const r = await call("log_export", { path: p, fmt: e.shiftKey ? "plotjuggler" : $<HTMLSelectElement>("exp-fmt").value }).catch(() => null);
  if (r) toast(`已导出 ${r.rows} 行 → ${r.path}${r.channels ? "（列顺序 " + r.channels.join(", ") + "）" : ""}`, "ok", 12000);
};
$("import").onclick = async () => {
  const path = window.prompt("要导入的文件路径（CSV 或 VOFA+ 文本）", localStorage.getItem("dz.import") || "");
  if (!path) return;
  localStorage.setItem("dz.import", path);
  const r = await call("log_import", { path: path.trim().replace(/^"|"$/g, "") }).catch(() => null);
  if (!r) return;
  toast(`已导入 ${r.rows} 行 · ${r.channels.length} 路（${r.fmt}，${r.seconds} s），开始回放`, "ok", 8000);
  await loadLogs(); await call("replay", { path: r.path }); plot.clear();
};
$("chans").innerHTML = emptyState("activity", "连上后列出通道");
$("props").innerHTML = AGENT_IDLE;
link.on(m => {
  agent.onMsg(m); raw.onMsg(m); send.onMsg(m);
  switch (m.type) {
    case "telem": {
      if (CAL.size) { const y = { ...m.y }; CAL.forEach((c, k) => { if (y[k]) y[k] = y[k].map(c.f); }); plot.push(m.t, y); } else plot.push(m.t, m.y);
      S.enums.forEach(f => { const a = m.y[f.name]; if (a?.length) S.enumVal[f.name] = a[a.length - 1]; });
      break;
    }
    case "status": runState.fromBoard(m as any); renderStatus(m); hb.add(m.hb); break;
    case "event": tl.add(m as any); if (AL.offer(m as any)) renderAlerts(); break;
    case "alert_ack": AL.ack(m.upto); renderAlerts(); break;   // 另一个窗口点了“知道了”
    case "schema": applySchema(m.schema); break;
    case "param": S.applied[m.name] = m.value; syncParams(); break;
    case "proposal": renderProposal(m); break;
    case "error": toast(m as unknown as Err); break;
    case "progress.changed": renderProgress(m as any, goStepRef); break;   // 侧车推送：状态变化即刷新（轮询仍兜底）
    case "link.state": onLinkState(m as any); showLink(m as any); break;
    case "seeked": plot.clear(); break;
    case "reconnected": toast(m.message, "ok", 5000); break;
    case "port_moved": toast(m.message, "warn", 8000); break;
    case "reconnecting": if (m.attempt >= 5) toast(`${m.port} 还没回来：已试 ${m.attempt} 次，每 ${m.next_s} s 再试；不想等就点“断开”`, "info", 4000); break;
    case "estop": toast(m.message, m.sent ? "info" : "crit", m.sent ? 2500 : 15000); break;
  }
});
link.onState = async open => {
  conn.set({ sidecar: open });
  if (!open && S.status.connected) renderStatus({ ...S.status });   // 状态栏同步成未连接
  if (!open) return;
  const h = await link.rpc("hello");
  if ((h as any)?.link) { onLinkState((h as any).link); showLink((h as any).link); }
  S.ports = h.ports; renderPorts(false);
  const applyFramedef = () => {
    const kind = $<HTMLSelectElement>("framedef").value;
    const n = Math.max(1, Math.min(32, Number($<HTMLInputElement>("framedef-n").value) || 4));
    let def: unknown = null;
    if (kind === "justfloat" || kind === "firewater") def = { preset: kind, n };
    else if (kind === "custom") {
      const txt = window.prompt('帧结构 JSON，例：{"header":"AA55","checksum":"sum8","check_from":2,"endian":"little","fields":[{"name":"speed","type":"i16","scale":0.01}]}', localStorage.getItem("dz.framedef") || "");
      if (!txt) return;
      try { def = JSON.parse(txt); } catch { alert("不是合法 JSON"); return; }
      localStorage.setItem("dz.framedef", txt);
    }
    call("framedef_set", { def }).then(() => fdStatus()).catch(() => {});   // 出错 call 自己弹提示（中文原因）
  };
  const fdStatus = () => call<{ fields: string[]; bad: number }>("framedef_status").then(st => {
    $<HTMLSelectElement>("framedef").title = `当前 ${st.fields.length} 个通道；校验错/帧尾不对 ${st.bad} 帧（悬停刷新）`;
  }).catch(() => {});
  $<HTMLSelectElement>("framedef").onmouseenter = fdStatus;
  $<HTMLSelectElement>("framedef").onchange = applyFramedef;
  $<HTMLInputElement>("framedef-n").onchange = applyFramedef;
  $<HTMLInputElement>("auto-rc").onchange = e => { call("auto_reconnect", { on: (e.target as HTMLInputElement).checked }).catch(() => {}); };
  if (h.recovered && !h.status.connected) {   // 侧车刚崩过：说清楚，预选上次的口，但不自动连（第一个动作交给人）
    toast({ code: "recovered", message: h.recovered.message, fix: "" }, "warn", 30000);
    if (S.ports.some(p => p.port === h.recovered.port)) $<HTMLSelectElement>("port").value = h.recovered.port;
  }
  if (h.schema) { applySchema(h.schema); S.applied = h.params; syncParams(); }
  renderStatus(h.status); loadLogs();
};
renderParams();

// 赛前全绿检查（侧车 precontest.py）：按 电脑 / 板子 / 工程 分组，全部 ✓ 才算全绿
function renderPre(r: any) {
  const mk: Record<string, string> = { ok: "✓", warn: "!", fail: "✗" };
  $("pre-sum").className = "pre-sum " + (r.all_green ? "ok" : r.fails ? "fail" : "warn");
  $("pre-sum").textContent = r.all_green ? `全绿 · ${r.t}` : `未全绿：✗ ${r.fails} 项必须处理，! ${r.warns} 项建议处理 · ${r.t}`;
  const order: Record<string, number> = { fail: 0, warn: 1, ok: 2 };
  $("pre-list").innerHTML = [...r.items].sort((a: any, b: any) => order[a.level] - order[b.level]).map((i: any) =>
    `<li class="d-${i.level}"><b>${mk[i.level]} [${esc(i.group)}] ${esc(i.name)}</b>：${esc(i.msg)}${i.fix ? `<br><i>→ ${esc(i.fix)}</i>` : ""}</li>`).join("");
}
const runPre = async () => { const r = await call("precontest", { strict: $<HTMLInputElement>("pre-strict").checked }).catch(() => null); if (r) renderPre(r); };
$("pre").onclick = async () => { $("pre-list").innerHTML = "<li>检查中…</li>"; $<HTMLDialogElement>("predlg").show(); await runPre(); };
$("pre-re").onclick = runPre;
$("pre-bbtn").onclick = async () => {
  const r: any[] | null = await call("blackbox", {}).catch(() => null);
  if (!r) return;
  $("pre-bb").hidden = false;
  $("pre-bb").innerHTML = r.length ? r.map((e) => `<li><b>${(e.t_ms / 1000).toFixed(3)} s</b> ${esc(e.text)}</li>`).join("")
    : "<li>板子没回黑匣子记录（固件 dzctl < 0.6.0，或应用没接 blackbox）</li>";
};
$("pre-save").onclick = async () => {
  const ok = await call("cmd", { c: "W" }).catch(() => false);
  toast(ok ? "已让板子存参数：读黑匣子看“参数已存进 flash”（没有保存区/没停车会写失败原因）" : "没连板子", ok ? "ok" : "warn", 8000);
};
$("pre-exp").onclick = async () => { const r = await call("precontest_export", { strict: $<HTMLInputElement>("pre-strict").checked }).catch(() => null); if (r) { renderPre(r); toast(`封箱清单已导出 → ${r.path}`, r.all_green ? "ok" : "warn", 12000); } };

$("doctor").onclick = async () => {
  const items: any[] = await call("doctor", {}).catch(() => null) || [];
  const mk: Record<string, string> = { ok: "✓", warn: "!", fail: "✗" };
  $("doc-list").innerHTML = items.map(i => `<li class="d-${i.level}"><b>${mk[i.level]} ${esc(i.name)}</b>：${esc(i.msg)}${i.fix ? `<br><i>→ ${esc(i.fix)}</i>` : ""}</li>`).join("");
  $<HTMLDialogElement>("doc").show();
};

createIcons({ icons: { Activity, Ellipsis, Eraser, Download, Eye, PlugZap, Flag, Ruler, Play, Sparkles, FilePen, Hammer, History, ListChecks, MessageSquarePlus, RotateCcw, Settings, ShieldOff, SlidersHorizontal, Stethoscope, SunMoon, Undo2, Zap, FolderKanban, Cpu, Crosshair, ClipboardCheck, PackageCheck, PanelLeft, X, FileText } });
// 对话框原来写在右栏 <aside> 里：分页后右栏在 项目/烧录/标定/封箱 页隐藏，自检、赛前检查等对话框跟着看不见 → 统一挪到 body 下
document.querySelectorAll("dialog").forEach(d => document.body.append(d));
initChrome();
conn.on(c => {
  if (!c.board) {   // 侧车停或板子 lost/disconnected：状态栏左侧、速率、连接按钮同步切换，清掉旧速率
    $("ro-link").textContent = c.sidecar ? "未连接" : "侧车无响应";
    $("ro-rx").textContent = "—"; S.rate = 0;
    $("led").className = "led";
    $("connect").innerHTML = "连接 <kbd>⌃O</kbd>"; $("connect").classList.add("pri");
  }
  $<HTMLButtonElement>("ag-send").disabled = !c.sidecar;
  $("st-ws").textContent = c.sidecar ? "侧车 已连接" : "侧车 未连接";
  $("banner").hidden = c.sidecar;
  $("banner").innerHTML = "侧车无响应 · 原因：dzbench 进程未运行或已退出 · 处理：程序将自动重启并重连；开发模式请运行 <code>python -m dzbench</code>。目标板 1 s 未收到心跳将自动急停。";
});
// link.state reason 横幅（中性/告警）+ 端口下拉高亮；急停锁存告警在 #alerts，独立于连接状态，重连后照常显示
function showLink(m: any) {
  runState.onLink(m.board);
  const v = linkView(m), b = $("lk-banner");
  b.hidden = !v.text; b.textContent = v.text; b.className = "lk-banner" + (v.tone ? " " + v.tone : "");
  $("port").classList.toggle("attn", v.portAttn);
  const md = modeLabel(m); $("ro-mode").hidden = !md; $("ro-mode").textContent = md;
  renderAlerts();
}
let goStepRef: (s: any) => void = () => {};
window.addEventListener("dz-goto", e => goStepRef((e as CustomEvent).detail));   // 其它模块（Agent 错误卡）请求切页
const goStep = initSteps(() => !!S.status.connected); goStepRef = goStep;
// 项目进度：接口优先、否则前端推断；每秒或切步时刷新
const refreshProgress = async () => renderProgress(await fetchProgress(op => link.rpc(op, {}), {   // 不走 call()：接口未上线时不弹报错
  current: (document.querySelector<HTMLElement>(".app")!.dataset.step || "项目") as Step,
  connected: conn.get().board,
  estop: AL.list.some(e => e.kind === "estop" || e.kind === "watchdog"),
  gainsZero: noInitialGains(S.schema?.params ?? [], S.applied),
  paramsDirty: pending().length > 0,
  selftestFail: false,
  visited: new Set(JSON.parse(localStorage.getItem("dz.visited") || "[]")),
}), goStep);
window.addEventListener("dz-step", () => void refreshProgress());
initPjAsk(call, goStep);
setInterval(() => void refreshProgress(), 1500);
initSymptoms(s => goStep(s as Parameters<typeof goStep>[0]));
initProjFlow(call, (t, k) => toast(t, k ?? "info", 6000));
const score: { refresh(): void } = initScore(call, plot, () => S.schema?.accept ?? [], (t, k) => toast(t, k ?? "info", 9000));
// 跨页入口：回到… 菜单里的“某个快照 / 烧前固件”、工具箱“波形测量”
$("gb-snap").onclick = () => { goStep("调参"); (document.querySelector('#dock-tabs [data-d="snaps"]') as HTMLElement)?.click(); };
$("gb-fw").onclick = () => goStep("烧录");
$("tb-meas").onclick = () => { goStep("联调"); (document.querySelector('#view [data-v="fft"]') as HTMLElement)?.click(); };

document.querySelector<HTMLElement>('#rail [data-side="score"]')?.addEventListener("click", () => score.refresh());
