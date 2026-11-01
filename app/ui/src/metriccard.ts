import { coarseLabel } from "./plant";
import { PLANT_COARSE } from "./fieldmap";
// r9p6 通用指标卡：控制 / 测量 / 电源 / 其他题目共用。只按 items 渲染；task_kind 只影响排序和图表类型。
// 规则：结论只来自后端 verdict（达标 / 不达标 / 待标定），前端不判；缺值一律「—」；单位原样显示，不换算。
import { MC_X_F, EVIDENCE_ZH, MC_STOP_ZH, UNCHANGED_ZH, MC_F } from "./fieldmap";
import { reasonZh } from "./reasoncodes";
import { MC_EXPORT_OP, toMetricsCard, type McItem, type MetricsCard, type TaskKind } from "./fieldmap";
const D = "—";
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const fmt = (v: number | null | undefined) => v == null || !Number.isFinite(v) ? D : String(+(+v).toPrecision(5));
const u = (x: string) => x ? ` ${x}` : "";
export const VERDICT_LABEL: Record<McItem["verdict"], string> = { pass: "达标", fail: "不达标", partial: "未验题面幅度", unknown: "待标定" };
export const SOURCE_LABEL: Record<string, string> = { sim: "仿真标称", real: "实机实测", calibrated: "实机 · 已标定", manual: "人工录入", "": "来源未上报" };
const HOW_LABEL: Record<string, string> = { auto: "自动测量", manual: "人工测量", "": "" };
export const KIND_LABEL: Record<TaskKind, string> = { control: "控制类", measure: "测量类", power: "电源类", other: "其他" };
export const CHART_OF: Record<TaskKind, string> = { control: "step", measure: "spectrum", power: "trend", other: "trend" };
const CMP_ZH: Record<string, string> = { "<=": "≤", "<": "<", ">=": "≥", ">": ">", "==": "=", le: "≤", lt: "<", ge: "≥", gt: ">", eq: "=", abs_le: "|误差| ≤" };
export function targetText(it: McItem): string {
  if (!it.target || it.target.thr == null) return "按默认判定";
  return `${CMP_ZH[it.target.cmp] ?? it.target.cmp} ${fmt(it.target.thr)}${u(it.target.unit)}`;
}
export function measuredText(it: McItem): string {
  const m = it.measured; if (!m || m.value == null) return D;
  return `${fmt(m.value)}${it.unc != null ? ` ± ${fmt(it.unc)}` : ""}${u(m.unit)}`;
}
export function itemWarnings(it: McItem, kind: TaskKind): string[] {
  const w: string[] = [];
  if (kind === "measure" && it.measured?.value != null && it.unc == null) w.push("缺测量不确定度，无法判断读数是否可信");
  return w;
}
// 排序：不达标在前（最需要处理）→ 待标定 → 达标；测量题再按条款号；其余保持后端顺序
export function sortItems(c: MetricsCard): McItem[] {
  const rank = { fail: 0, partial: 1, unknown: 2, pass: 3 } as const;
  const ix = new Map(c.items.map((x, i) => [x, i]));
  return [...c.items].sort((a, b) => rank[a.verdict] - rank[b.verdict] || (c.kind === "measure" ? a.clause.localeCompare(b.clause, "zh") : 0) || ix.get(a)! - ix.get(b)!);
}
export function summary(c: MetricsCard): { pass: number; fail: number; partial: number; unknown: number; text: string } {
  const s = { pass: 0, fail: 0, partial: 0, unknown: 0 };
  c.items.forEach(i => s[i.verdict]++);
  return { ...s, text: c.items.length ? `${c.items.length} 项 · 达标 ${s.pass} · 不达标 ${s.fail}${s.partial ? ` · 未验题面幅度 ${s.partial}` : ""} · 待标定 ${s.unknown}` : "没有指标项" };
}
function tuningHtml(t: any): string {
  const best = t?.best ?? {}, ps = best.params && typeof best.params === "object" ? Object.entries(best.params) : [];
  const r0 = t?.round0?.metrics, iter = typeof best.iter === "number" ? `第 ${best.iter} 轮` : D;
  const pTxt = ps.length ? ps.map(([k, v]) => `<span class="mono"><i>${esc(k)}</i> ${esc(fmt(v as number))}</span>`).join("") : `<span>${D}</span>`;
  return `<div class="mc-tune"><span class="mc-k">调参结果 · 最好一组（${iter}）</span><div class="rc-ps">${pTxt}</div>${r0 ? "" : ""}</div>`;
}
function calibHtml(c: McItem["calib"]): string {
  if (!c) return "";
  return `<div class="mc-cal"><span class="mc-k">标定</span> 系数 ${c.coeffs.length ? c.coeffs.map(fmt).join(", ") : D} · 信号源 ${esc(c.signal || D)}</div>`;
}
export function metricCardHtml(src: any): string {
  const c = toMetricsCard(src); if (!c) return "";
  const s = summary(c), extra = mcExtrasHtml(src);
  const rows = sortItems(c).map(it => {
    const warn = itemWarnings(it, c.kind);
    const zh = VERDICT_LABEL[it.verdict];   // 标签固定三种；verdict_zh 作补充说明进依据行
    const basis = [it.verdictZh && it.verdictZh !== zh ? it.verdictZh : "", it.basis].filter(Boolean).join(" · ");
    const meth = [HOW_LABEL[it.how], it.measured?.method ?? "", it.measured?.n != null ? `${it.measured.n} 次` : ""].filter(Boolean).join(" · ");
    const ent = it.entry ? `<p class="mc-meth">人工录入 ${esc(fmt(it.entry.value))}${esc(u(it.measured?.unit ?? ""))} · ${esc(it.entry.by || "—")} · ${esc(it.entry.at || "—")}</p>` : "";
    const steps = (t: string, a: string[]) => a.length ? `<details class="mc-steps"><summary>${t}（${a.length} 步）</summary><ol>${a.map(x => `<li>${esc(x)}</li>`).join("")}</ol></details>` : "";
    return `<div class="mc-it ${it.verdict}">
  <div class="mc-h"><b class="mc-n">${esc(it.name || D)}</b>${it.clause ? `<span class="mc-cl">${esc(it.clause)}</span>` : ""}<span class="mc-v ${it.verdict}">${zh}</span>${it.model?.estimate === PLANT_COARSE ? coarseLabel(it.model.basis) : ""}</div>
  <p class="mc-spec">${esc(it.spec || "题目原文未提供")}</p>
  <div class="mc-row num"><span><i>目标</i>${esc(targetText(it))}</span><span><i>实测</i><b>${esc(measuredText(it))}</b></span><span class="mc-src ${it.source || "none"}">${esc(SOURCE_LABEL[it.source])}${it.srcNote ? ` · ${esc(it.srcNote)}` : ""}</span></div>
  ${meth ? `<p class="mc-meth">${esc(meth)}</p>` : ""}${ent}${steps("人工测量步骤", it.manualSteps)}${steps("评审测试步骤", it.procedure)}${basis ? `<p class="mc-basis">依据：${esc(basis)}</p>` : ""}
  ${it.amp ? `<p class="mc-amp num">${esc(`题面幅度 ${it.amp.spec}，实测幅度 ${it.amp.tested}`)}</p>` : ""}${it.warningZh ? `<p class="mc-warn partial">${esc(it.warningZh)}</p>` : ""}
  ${warn.map(w => `<p class="mc-warn">${esc(w)}</p>`).join("")}
  ${it.tuning ? tuningHtml(it.tuning) : ""}${calibHtml(it.calib)}
  ${it.evidence ? `<a class="mc-ev" href="#" data-evidence="${esc(it.evidence)}" title="${esc(it.evidence)}">打开录波</a>` : ""}
</div>`;
  }).join("");
  return `<wa-card class="mc" data-kind="${c.kind}" data-chart="${CHART_OF[c.kind]}"><div class="mc-top"><h4>指标卡 · ${KIND_LABEL[c.kind]}</h4>${extra && isUnchanged(src) ? "" : `<span class="mc-sum num">${esc(s.text)}</span>`}<span class="mc-exp"><wa-button size="small" appearance="outlined" data-mc-export="csv">导出 CSV</wa-button><wa-button size="small" appearance="outlined" data-mc-export="xlsx">导出 Excel</wa-button></span></div>${c.kindBasis ? `<p class="mc-kb">${esc(c.kindBasis)}</p>` : ""}${extra}<div class="mc-list">${rows}</div></wa-card>`;
}
export const exportArgs = (format: string) => ({ op: MC_EXPORT_OP, args: { format } });   // 文件由后端生成，前端不拼 CSV

// 指标卡补充：原因证据列表（后端判几个就列几个，前端不挑）、未改参说明 + 余量、停止原因
const mcObj = (src: any) => src?.[MC_F.obj] ?? src?.args?.[MC_F.obj] ?? src?.preview?.[MC_F.obj] ?? null;
export const isUnchanged = (src: any) => mcObj(src)?.[MC_X_F.unchanged] === true;
const marginText = (x: any) => {
  if (typeof x?.[MC_X_F.marginZh] === "string" && x[MC_X_F.marginZh]) return x[MC_X_F.marginZh];
  const m = x?.[MC_X_F.margin], v = m && typeof m === "object" ? m[MC_X_F.value] : m, un = m && typeof m === "object" ? m[MC_X_F.unit] : x?.target?.unit;
  return typeof v === "number" && Number.isFinite(v) ? `余量 ${+v.toPrecision(4)}${un ? (un === "%" ? "%" : " " + un) : ""}` : "余量未上报";
};
export function mcExtrasHtml(src: any): string {
  const o = mcObj(src); if (!o) return "";
  const out: string[] = [];
  const cs = Array.isArray(o[MC_X_F.causes]) ? o[MC_X_F.causes].filter((c: any) => c && typeof c === "object") : [];
  if (cs.length) {
    const vz = typeof o[MC_X_F.verdictZh] === "string" ? o[MC_X_F.verdictZh] : "";
    out.push(`<div class="mc-causes">${vz ? `<p class="mc-cz">${esc(vz)}</p>` : ""}<ul>${cs.map((c: any) => `<li><b>${esc(reasonZh(String(c[MC_X_F.code] ?? ""), {}))}</b><span class="mc-evd ${esc(String(c[MC_X_F.ev] ?? ""))}">${esc(EVIDENCE_ZH[c[MC_X_F.ev]] ?? "证据强度未上报")}</span>${c[MC_X_F.basis] ? `<span class="mc-cb">${esc(String(c[MC_X_F.basis]))}</span>` : ""}</li>`).join("")}</ul></div>`);
  }
  if (o[MC_X_F.unchanged] === true) {
    const its = Array.isArray(o.items) ? o.items : [];
    out.push(`<div class="mc-unch"><p>${UNCHANGED_ZH}</p><ul>${its.map((x: any) => `<li>${esc(String(x?.[MC_X_F.name] ?? "—"))}：${esc(marginText(x))}</li>`).join("")}</ul></div>`);
  }
  const st = o[MC_X_F.stop];
  if (typeof st === "string" && st) out.push(`<p class="mc-stop" data-stop="${esc(st)}">${esc(typeof o[MC_X_F.stopZh] === "string" && o[MC_X_F.stopZh] ? o[MC_X_F.stopZh] : MC_STOP_ZH[st] ?? reasonZh(st, {}))}</p>`);
  return out.join("");
}
