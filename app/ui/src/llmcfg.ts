// 大模型首次配置：模型列表（agent_models）的状态与文案。纯函数，便于单测；DOM 写入在 agent.ts。
export type Reason = "unsupported" | "auth" | "error" | "contest_mode" | "empty";
export type FixAction = "manual_model" | "check_key" | "retry";
export type ModelList = { ok: boolean; models?: string[]; reason?: Reason; fix_action?: FixAction; message?: string };
/** focus：状态出来后焦点放到哪个输入框；retry：是否显示「重试」；auto：地址 / Key 变更时是否允许再自动拉取。 */
export type ModelView = { cls: "busy" | "ok" | "bad" | "warn"; html: string; options: string[]; model: string; placeholder: string;
  focus: "model" | "key" | null; retry: boolean; auto: boolean };

const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

/** 把文本里出现的 Key（及其 Bearer 形式）替换掉：本地服务或网络层的报错原文可能回显请求头。 */
export function redactKey(text: unknown, key: string): string {
  let s = String(text ?? "");
  const k = key.trim();
  if (k.length >= 4) s = s.split(k).join("••••");
  return s.replace(/\b(sk|ak|key)-[A-Za-z0-9_\-]{8,}/g, "$1-••••").replace(/(Bearer\s+)\S+/gi, "$1••••");
}

export const LOADING_HTML = `<span class="spin"></span>正在获取可用模型…`;

/** 根据 agent_models 结果决定状态行、候选项和输入框。preset 为服务商预设默认模型，仅作最后兜底。没有 reason 的旧返回按 unsupported 处理。 */
export function modelView(r: ModelList, current: string, preset: string, key: string): ModelView {
  const ids = (r.models || []).map(String), cur = current.trim();
  const ph = "请按服务商文档填写模型名";
  if (r.ok && ids.length) {
    const keep = ids.includes(cur);
    return { cls: "ok", options: ids, model: keep ? cur : "", placeholder: "请从列表中选择模型", focus: "model", retry: false, auto: true,
      html: `已获取 ${ids.length} 个可用模型${keep ? `，当前为 ${esc(cur)}` : "，请在“模型”中选择"}` };
  }
  const fallback = cur || preset;
  const tail = fallback && !cur ? `已填入预设模型 ${esc(preset)}，请按服务商文档确认。` : "请手动填写模型名。";
  const why = esc(redactKey(r.message || "", key)).replace(/[。.]$/, "");
  const base = { options: [] as string[], model: fallback, placeholder: ph };
  const reason: Reason = r.reason || (r.ok ? "empty" : "unsupported");
  switch (reason) {
    case "contest_mode":
      return { ...base, cls: "warn", focus: "model", retry: false, auto: false,
        html: `比赛模式下未启用云端，不请求外部服务。${tail}` };
    case "auth":
      return { ...base, cls: "bad", focus: "key", retry: false, auto: true,
        html: `<b>鉴权失败</b>${why ? ` · ${why}` : ""}<br><span class="fix">→ 请检查 API Key 是否正确、是否有该服务的权限，修改后将自动重新获取。</span>` };
    case "error":
      return { ...base, cls: "bad", focus: null, retry: true, auto: true,
        html: `<b>获取模型列表失败</b>${why ? ` · ${why}` : ""}<br><span class="fix">→ 请检查网络与接口地址后点「重试」；也可直接手动填写模型名。</span>` };
    case "empty":
      return { ...base, cls: "warn", focus: "model", retry: false, auto: true, html: `该服务返回的模型列表为空。${tail}` };
    default:
      return { ...base, cls: "warn", focus: "model", retry: false, auto: true,
        html: `${why || "该服务未提供模型列表接口"}。${tail}` };
  }
}

/** DOM 侧最小接口，便于单测用假元素替代。 */
export type El = { value: string; placeholder: string; innerHTML: string; className: string; hidden: boolean; disabled: boolean; focus(): void };
export type ListerDeps = {
  call: (op: string, args: Record<string, unknown>) => Promise<ModelList>;
  el: (id: "cfg-st" | "cfg-models" | "cfg-model" | "cfg-key" | "cfg-list" | "cfg-retry") => El;
  form: () => Record<string, unknown> & { api_key?: string };
  preset: () => string;
};

/** 拉取模型列表。返回 load（手动 / 重试）和 auto（地址或 Key 变更时，仅在允许自动拉取时调用）。并发请求只认最后一次。 */
export function modelLister(d: ListerDeps) {
  let seq = 0, autoOk = true;
  async function load() {
    const my = ++seq, f = d.form(), key = String(f.api_key || "");
    const st = d.el("cfg-st"), btn = d.el("cfg-list"), retry = d.el("cfg-retry");
    st.className = "cst busy"; st.innerHTML = LOADING_HTML; btn.disabled = true; retry.hidden = true;
    const r = await d.call("agent_models", { form: f })
      .catch((e: Error) => ({ ok: false, models: [], reason: "error" as const, fix_action: "retry" as const, message: String(e?.message || e) }));
    if (my !== seq) return;
    btn.disabled = false;
    const model = d.el("cfg-model"), v = modelView(r, model.value, d.preset(), key);
    d.el("cfg-models").innerHTML = v.options.map(i => `<option value="${esc(i)}">`).join("");
    model.value = v.model; model.placeholder = v.placeholder;
    st.className = "cst " + v.cls; st.innerHTML = v.html;
    retry.hidden = !v.retry; autoOk = v.auto;
    if (v.focus) d.el(v.focus === "key" ? "cfg-key" : "cfg-model").focus();
  }
  return { load, auto: () => { if (autoOk) return load(); } };
}
