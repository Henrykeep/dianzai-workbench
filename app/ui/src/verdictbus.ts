// #75 唯一结论源：结果卡（后端 verdict / verdict_zh）算出的结论，台账最近一轮、右栏建议卡都只读这里
export type SharedVerdict = { v: string; text: string; short: string };
let cur: SharedVerdict | null = null;
export const shortOf = (v: string) => v === "pass" ? "达标" : v === "fail" ? "未达标" : "未判定";
export function setVerdict(x: { v: string; text: string } | null) {
  const n = x ? { v: x.v, text: x.text, short: shortOf(x.v) } : null;
  if (JSON.stringify(n) === JSON.stringify(cur)) return;
  cur = n; if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("dz-verdict"));
}
export const getVerdict = () => cur;
// 台账「判定」：有统一结论时最近一轮跟它一致；验收规格模式仍按评委口径
export const ledgerJudge = (isLatest: boolean, own: string | undefined) => isLatest && cur ? cur.short : own ?? "—";
