// llm_retry（模型服务繁忙自动重试）：Agent 流内联一句进度 + 「切到本地模型」；字段名映射见 fieldmap.ts
import type { Retry } from "./fieldmap";
export const LOCAL_LABEL = "切到本地模型";
export function retryText(r: Retry): string {
  const w = r.wait != null ? `，约 ${Math.max(1, Math.round(r.wait))} s` : "";
  return `模型服务繁忙，第 ${r.attempt}/${r.total} 次重试${w}`;
}
export const clearsRetry = (t: string) => t === "agent_delta" || t === "agent_reply" || t === "agent_done" || t === "agent_error";
