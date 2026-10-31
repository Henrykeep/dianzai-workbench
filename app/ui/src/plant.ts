import { PLANT_F, PLANT_EST_ZH, COARSE_F, COARSE_ZH } from "./fieldmap";
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
export const isCoarse = (r: any) => !!r && (r[COARSE_F.flag] === true || r[COARSE_F.est] === COARSE_F.coarse || r?.[PLANT_F.obj]?.[PLANT_F.estimate] === COARSE_F.coarse);
export const coarseTagHtml = (r: any) => isCoarse(r) ? `<span class="lbl warn-t rc-coarse">${COARSE_ZH}</span>` : "";
