// Agent 等待看门狗 + 错误卡文案。发出即「思考中」计时；60 s 无任何事件 → 超时卡；agent_error → 出错卡。不让用户干等。
import { humanize } from "./errors";
import { resolveFix, Fix } from "./progress";
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
export type AgentErr = { code?: string; message?: string; detail?: string; fix?: string; fix_action?: string | null; retryable?: boolean };
export type Card = { title: string; why: string; fix: string; detail: string; retry: boolean; settings?: boolean; other?: Fix | null; otherId?: string };
export const timeoutCard = (): Card => ({
  title: "Agent 超过 60 秒未响应",
  why: "本地服务内部出错，或模型服务无响应",
  fix: "点「重试」重新发送；仍无响应请查看详情或在「大模型设置」中检查服务",
  detail: "60 秒内没有收到任何 Agent 事件（思考、工具调用、回复或报错）。",
  retry: true,
});
// fix_action 对照表（取值 = entrypoints.yaml 入口 id）：llm_cfg → 「大模型设置」；agent_chat 与 retryable 合并为一个「重试」；null → 无修复按钮
export const FIX_ACTIONS = { llm_cfg: "settings", agent_chat: "retry" } as const;
export function errorCard(m: AgentErr, has: (ui: string) => boolean = ui => typeof document !== "undefined" && !!document.getElementById(ui)): Card {
  // 只能由人做的操作（如切换运行模式）：不当成出错，写明要人确认，只给一个跳到封箱页的按钮（跳过去聚焦，不替人点）
  if (m.code === "human_only") return { title: "需在封箱页由人确认", why: m.message || "这个操作只能由人执行", fix: m.fix || "到封箱页由你本人确认",
    detail: "code: human_only", retry: false, settings: false, other: resolveFix("set_run_mode", has), otherId: "set_run_mode" };
  const fa = m.fix_action ? FIX_ACTIONS[m.fix_action as keyof typeof FIX_ACTIONS] : undefined;
  // 对照表以外的入口 id：交给统一的 resolveFix（未就绪置灰「等待固件支持」，未登记置灰写明原因）
  const other = m.fix_action && !fa ? resolveFix(m.fix_action, has) : null;
  const h = humanize([m.code, m.message].filter(Boolean).join(" "));
  const internal = m.code === "tool_schema";
  return {
    title: "Agent 出错：" + (internal ? "工具定义格式错误" : h?.what ?? "本轮未完成"),
    why: internal ? "这是工作台内部配置错误，不是你的操作问题" : (m.message || h?.why || "本地服务未给出原因"),
    fix: internal ? "可先重发一次或换个说法；反复出现请把「详情」发给开发者，其它功能不受影响" : (h?.fix ?? (fa === "settings" ? "在「大模型设置」中检查后重试" : "点「重试」重新发送")),
    detail: [m.code ? `code: ${m.code}` : "", internal && m.message ? m.message : "", m.detail || ""].filter(Boolean).join("\n") || "（本地服务未提供更多信息）",
    retry: fa === "retry" || m.retryable === true,
    settings: fa === "settings",
    other, otherId: other ? m.fix_action! : undefined,
  };
}
// 同一轮只出一张错误卡：已出 agent_error 就吞掉随后的 agent_unreachable
export class TurnGate { err = false; begin() { this.err = false; } error() { this.err = true; } allowUnreachable() { return !this.err; } }
