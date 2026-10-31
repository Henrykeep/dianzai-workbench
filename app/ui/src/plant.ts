import { PLANT_F, PLANT_EST_ZH, PLANT_COARSE, COARSE_ZH, toMetricsCard } from "./fieldmap";
export type PlantView = { tag: string; kind: string; basis: string; unit: string; uUnit: string } | null;
const s = (v: unknown) => (v == null ? "" : String(v));
export function toPlant(src: any): PlantView {
  const p = src?.[PLANT_F.obj] ?? src;
  if (!p || typeof p !== "object") return null;
  const kind = s(p[PLANT_F.estimate]); if (!kind) return null;
  return { kind, tag: PLANT_EST_ZH[kind] ?? kind, basis: s(p[PLANT_F.basis]), unit: s(p[PLANT_F.unit]), uUnit: s(p[PLANT_F.uUnit]) };
}
export function plantTagHtml(v: PlantView, esc: (x: string) => string): string {
  if (!v) return "";
  const unit = v.unit || v.uUnit ? ` · ${esc(v.uUnit)}${v.uUnit && v.unit ? " → " : ""}${esc(v.unit)}` : "";   // 单位原样
  return `<span class="lbl plant-tag ${v.kind === "coarse" ? "warn-t" : "ok-t"}" title="${esc(v.basis || "后端未给依据")}">对象模型：${esc(v.tag)}${unit}</span>${v.basis ? `<span class="hint plant-basis">${esc(v.basis)}</span>` : ""}`;
}
// 结果卡「仅仿真粗估」：指标卡里任一项 model.estimate === coarse；依据（model.basis）进悬停
export function coarseItems(r: any): { name: string; basis: string }[] {
  const c = toMetricsCard(r); if (!c) return [];
  return c.items.filter(it => it.model?.estimate === PLANT_COARSE).map(it => ({ name: it.name, basis: it.model!.basis }));
}
export const isCoarse = (r: any) => coarseItems(r).length > 0;
const esc0 = (t: string) => t.replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" } as any)[ch]);
export const coarseLabel = (basis: string) => `<span class="lbl warn-t rc-coarse" title="${esc0(basis || "后端未给依据")}">${COARSE_ZH}</span>`;
export function coarseTagHtml(r: any): string {
  const xs = coarseItems(r); if (!xs.length) return "";
  return coarseLabel([...new Set(xs.map(x => x.basis).filter(Boolean))].join("；"));
}
