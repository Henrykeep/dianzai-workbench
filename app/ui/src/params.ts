// 参数面板的纯逻辑（无 DOM，可单测）：限幅、待下发判定、范围位文字
export type Param = { name: string; type: string; min: number; max: number; unit?: string; desc?: string; default: number };
export const fmtP = (v: number | undefined, p: { type: string }) => v == null || Number.isNaN(v) ? "—" : p.type === "f32" ? (+v.toPrecision(6)).toString() : String(Math.round(v));
export function clampLocal(p: Param, v: number) { let c = Math.min(Math.max(v, p.min), p.max); if (p.type !== "f32") c = Math.round(c); return c; }
export function pendingOf(ps: Param[], edit: Record<string, string>, applied: Record<string, number>) {
  return ps.filter(p => p.name in edit && edit[p.name] !== "" && +edit[p.name] !== applied[p.name]);
}
// 草稿 ≠ 板上：输入框显示草稿（可能已被限幅），范围位显示“板上 x”（板子回报的生效值）
export function rangeLabel(p: Param, pending: boolean, applied: number | undefined) {
  return pending ? `板上 ${fmtP(applied, p)}` : `${fmtP(p.min, p)}…${fmtP(p.max, p)}${p.unit ? " " + p.unit : ""}`;
}
