// Agent 等待看门狗 + 错误卡文案。发出即「思考中」计时；60 s 无任何事件 → 超时卡；agent_error → 出错卡。不让用户干等。
import { humanize } from "./errors";
export const AGENT_TIMEOUT_MS = 60_000;
export class Watch {
  t0 = 0; last = 0; on = false; fired = false;
  start(now: number) { this.t0 = this.last = now; this.on = true; this.fired = false; }
  touch(now: number) { if (this.on) this.last = now; }
  stop() { this.on = false; }
  // 返回要显示的计时文本；超时只触发一次
  tick(now: number): { label: string; timeout: boolean } {
    const timeout = this.on && !this.fired && now - this.last > AGENT_TIMEOUT_MS;
    if (timeout) this.fired = true;
    return { label: `思考中… ${Math.floor((now - this.t0) / 1000)} s`, timeout };
  }
}
export type AgentErr = { code?: string; message?: string; detail?: string; fix_action?: string; retryable?: boolean };
export type Card = { title: string; why: string; fix: string; detail: string; retry: boolean; settings?: boolean };
export const timeoutCard = (): Card => ({
  title: "Agent 超过 60 秒未响应",
  why: "侧车内部出错，或模型服务无响应",
  fix: "点「重试」重新发送；仍无响应请查看详情或在「大模型设置」中检查服务",
  detail: "60 秒内没有收到任何 Agent 事件（思考、工具调用、回复或报错）。",
  retry: true,
});
export function errorCard(m: AgentErr): Card {
  const raw = [m.code, m.message, m.detail].filter(Boolean).join(" · ");
  const h = humanize(raw);
  return {
    title: "Agent 出错：" + (h?.what ?? m.message ?? "未知错误"),
    why: h?.why ?? m.message ?? "侧车未给出原因",
    fix: h?.fix ?? (m.retryable === false ? "请按详情排查后再试" : "点「重试」重新发送"),
    detail: [m.code ? `code: ${m.code}` : "", m.detail ?? m.message ?? ""].filter(Boolean).join("\n"),
    retry: m.retryable !== false,
    settings: /setting|config|key|llm/i.test(m.fix_action ?? ""),   // fix_action 是动作码，不直接当文案；配置类 → 给「大模型设置」
  };
}
