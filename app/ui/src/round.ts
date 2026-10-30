// 最近一次“阶跃实验”的程序判定与指标（侧车 tune_round 事件）。agent.ts 写入，台账与建议卡读取。
export type RoundMsg = { verdict: any; metrics: any };
export let lastRound: RoundMsg | null = null;
export function setRound(r: RoundMsg) { lastRound = r; window.dispatchEvent(new CustomEvent("dz-round", { detail: r })); }
export const VERDICT_SHORT: Record<string, string> = { continue: "未过", done: "达标", rollback: "变差", stop: "停止" };
