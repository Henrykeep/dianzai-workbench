// 本地服务 llm_retry 事件（模型服务限流 / 繁忙时自动重试）：Agent 流里内联一句进度 + 「切到本地模型」，不放光秃秃的转圈；成功出字后清掉
// 约定形状：{type:"llm_retry", attempt, total, wait_s, fix_action?}（attempt 从 1 计；fix_action 例 "llm_local" = 切到本地模型）
export type LlmRetry = { type: "llm_retry"; attempt: number; total: number; wait_s?: number; fix_action?: string | null; message_zh?: string };
export const LOCAL_LABEL = "切到本地模型";
export function retryText(m: LlmRetry): string {
  const w = Number.isFinite(m.wait_s) ? `，约 ${Math.max(1, Math.round(m.wait_s!))} s` : "";
  return `模型服务繁忙，第 ${m.attempt}/${m.total} 次重试${w}`;
}
// 哪些消息说明这一轮已经正常出结果（清掉重试提示）
export const clearsRetry = (t: string) => t === "agent_delta" || t === "agent_reply" || t === "agent_done" || t === "agent_error";
