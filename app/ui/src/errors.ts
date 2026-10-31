import { errWhy, NO_REASON_ZH } from "./fieldmap";
// 报错翻译层：git / 门禁、模型服务、侧车报错 → 「发生了什么 · 原因 · 处理」，原文进可展开的「详情」。
export type Human = { what: string; why: string; fix: string; raw: string };
const RULES: [RegExp, Omit<Human, "raw">][] = [
  [/\b403\b|forbidden|1010/i, { what: "模型服务拒绝请求", why: "API Key 无权限、余额不足或访问被服务方拦截（如 403 / 1010）", fix: "在「大模型设置」中检查 Key 与接口地址，或切换服务商" }],
  [/\b401\b|unauthori[sz]ed|invalid api key/i, { what: "模型服务认证失败", why: "API Key 无效或已过期", fix: "在「大模型设置」中重新填写 Key" }],
  [/\b429\b|rate limit|too many requests/i, { what: "模型服务限流", why: "请求过于频繁或额度用尽", fix: "稍后重试，或切换服务商 / 本地模型" }],
  [/timed? ?out|timeout|ETIMEDOUT/i, { what: "请求超时", why: "网络不通或服务响应过慢", fix: "检查网络后重试；离线时可切换本地模型" }],
  [/ECONNREFUSED|connection refused|无法连接/i, { what: "无法连接服务", why: "目标服务未启动或地址错误", fix: "确认服务地址与端口后重试" }],
  [/merge conflict|CONFLICT/i, { what: "Git 合并冲突", why: "同一文件被两处同时修改", fix: "在编辑器中解决冲突后再提交" }],
  [/non-fast-forward|\[rejected\]|failed to push/i, { what: "Git 推送被拒绝", why: "远端有本地没有的提交", fix: "先拉取并合并远端更新，再推送" }],
  [/check_[a-z_]+\.py|make check|门禁/i, { what: "门禁检查未通过", why: "提交内容不符合仓库规则", fix: "展开详情查看未通过的条目，按提示修改" }],
  [/unknown op|未知操作/i, { what: "本地服务不支持该操作", why: "本地服务版本较旧", fix: "更新并重启本地服务" }],
  [/Broken ?pipe|ConnectionClosed|no close frame/i, { what: "与本地服务的连接中断", why: "本地服务进程退出或重启", fix: "等待本地服务恢复；状态栏恢复为「已连接」后重试" }],
];
export function humanize(raw: string): Human | null {
  for (const [re, h] of RULES) if (re.test(raw)) return { ...h, raw };
  return null;
}
export const humanHtml = (h: Human, esc: (s: string) => string) =>
  `<b>${esc(h.what)}</b> · 原因：${esc(h.why)} · 处理：${esc(h.fix)}<details class="raw"><summary>详情</summary><pre class="mono">${esc(h.raw)}</pre></details>`;

// batch-1：每条报错都是三段（发生了什么 / 原因 / 处理），原始代码收进「详情」
export function errParts(er: { code?: string; message: string; fix?: string; why?: string; cause_zh?: string; message_zh?: string; reason_zh?: string }): Human {
  const h = !er.fix ? humanize(`${er.code ?? ""} ${er.message}`) : null;
  if (h) return h;
  // #72 原始英文 / 代码只进「详情」，正文永远是中文三段
  const ascii = (t?: string) => !t || /^[\x00-\x7f]*$/.test(t);
  const raw = er.code ? (er.message && ascii(er.message) ? `${er.code} · ${er.message}` : er.code) : er.message;
  const zh = er.message_zh && !ascii(er.message_zh) ? er.message_zh : !ascii(er.message) ? er.message : "";
  return { what: zh || "操作没有完成", why: errWhy(er) || NO_REASON_ZH, fix: !ascii(er.fix) ? er.fix! : "按下面的按钮处理；没有按钮就稍后重试", raw };
}
export const partsHtml = (h: Human, esc: (s: string) => string, btn = "") =>
  `<b>${esc(h.what)}</b><span>原因：${esc(h.why)}</span><span>处理：${esc(h.fix)}</span>${btn}<details class="raw"><summary>详情</summary><pre class="mono">${esc(h.raw)}</pre></details>`;
