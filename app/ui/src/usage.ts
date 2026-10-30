// Agent 用量：解析回复 / 事件里的 usage{tokens_in,tokens_out,elapsed_ms}，只存不显示 token；界面只显示本轮耗时。
export type Usage = { tokens_in?: number; tokens_out?: number; elapsed_ms?: number };
export const usageLog: Usage[] = [];
const n = (v: unknown) => (typeof v === "number" && isFinite(v) ? v : undefined);
// 主来源：agent_usage 事件 {type:"agent_usage", usage:{elapsed_ms, tokens_in?, tokens_out?}}；兼容旧的 prompt/completion 写法
export function parseUsage(x: any): Usage | null {
  const u = x?.usage ?? (x?.type === "agent_usage" ? { tokens_in: x.prompt, tokens_out: x.completion, elapsed_ms: x.elapsed_ms } : null);
  if (!u || typeof u !== "object") return null;
  const r = { tokens_in: n(u.tokens_in), tokens_out: n(u.tokens_out), elapsed_ms: n(u.elapsed_ms) };
  return r.tokens_in == null && r.tokens_out == null && r.elapsed_ms == null ? null : r;
}
// 侧车给了 elapsed_ms 就用它，否则用前端计时
export const elapsedOf = (u: Usage | null, localMs: number) => u?.elapsed_ms ?? localMs;
export const fmtElapsed = (ms: number) => `本轮耗时 ${ms < 1000 ? Math.round(ms) + " ms" : (ms / 1000).toFixed(1) + " s"}`;
