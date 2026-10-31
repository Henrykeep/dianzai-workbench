// #88 git 提交确认卡（通用）：commit_confirm_request → 卡片「保存到工程版本 / 取消」→ op commit_confirm；拒绝 / 超时 → commit_declined。字段名只在 fieldmap
import { COMMIT_F, COMMIT_OP, COMMIT_DECL_F, NO_REASON_ZH, COMMIT_BTN_ZH, COMMIT_SUB_ZH, COMMIT_REASON_KEYS, COMMIT_REASON_HOSTS, COMMIT_USER_F, USER_DECLINED_ZH } from "./fieldmap";
export type CommitReq = { id: string; branch: string; files: { path: string; status: string }[]; message: string; messageZh: string };
const s = (v: unknown) => typeof v === "string" ? v : "";
export function toCommitReq(raw: any): CommitReq {
  const fs = Array.isArray(raw?.[COMMIT_F.files]) ? raw[COMMIT_F.files] : [];
  return {
    id: raw?.[COMMIT_F.id] != null ? String(raw[COMMIT_F.id]) : "",
    branch: s(raw?.[COMMIT_F.branch]),
    files: fs.map((f: any) => typeof f === "string" ? { path: f, status: "" } : { path: String(f?.[COMMIT_F.path] ?? "—"), status: String(f?.[COMMIT_F.status] ?? "") }),
    message: s(raw?.[COMMIT_F.msg]), messageZh: s(raw?.[COMMIT_F.msgZh]),
  };
}
const ST: Record<string, string> = { A: "新增", M: "修改", D: "删除", R: "重命名", "??": "新增", added: "新增", modified: "修改", deleted: "删除", renamed: "重命名" };
export function commitCardHtml(c: CommitReq, esc: (s: string) => string): string {
  const files = c.files.length ? `<ul class="cc-files mono">${c.files.map(f => `<li>${f.status ? `<span class="cc-st">${esc(ST[f.status] ?? f.status)}</span> ` : ""}${esc(f.path)}</li>`).join("")}</ul>` : `<p class="hint">后端没有列出文件</p>`;
  const msg = c.message ? `<pre class="mono cc-msg">${esc(c.message)}</pre>` : `<p class="hint">后端没有给提交说明</p>`;
  const ok = c.files.length && c.id;
  return `<div class="card cc" data-cc-id="${esc(c.id)}"><b>保存到工程版本（${c.files.length} 个文件）</b><p class="cc-sub">${COMMIT_SUB_ZH}</p>` +
    `<div class="lbl">分支 <span class="mono cc-br">${c.branch ? esc(c.branch) : "—"}</span></div>${c.messageZh ? `<p class="cc-zh">${esc(c.messageZh)}</p>` : ""}${files}<div class="lbl">提交说明</div>${msg}` +
    `<div class="act"><button class="btn pri" data-cc="ok"${ok ? "" : " disabled"}>${COMMIT_BTN_ZH}</button><button class="btn" data-cc="cancel"${c.id ? "" : " disabled"}>取消</button><span class="lbl cc-res"></span></div></div>`;
}
// 点击 → op 参数
export const commitOpArgs = (id: string, approve: boolean) => ({ op: COMMIT_OP.name, args: { [COMMIT_OP.id]: id, [COMMIT_OP.approve]: approve } });
// #110：原因按 COMMIT_REASON_KEYS 顺序，在顶层 / data / error 里找第一个非空字符串
export function declReason(raw: any): string {
  for (const k of COMMIT_REASON_KEYS) for (const h of COMMIT_REASON_HOSTS) { const o = h ? raw?.[h] : raw; const v = o?.[k]; if (typeof v === "string" && v.trim()) return v.trim(); }
  return "";
}
// commit_declined → 原因 + 修复动作
export function toDeclined(raw: any): { id: string; reason: string; fix: string } {
  const r = declReason(raw);
  return { id: raw?.[COMMIT_F.id] != null ? String(raw[COMMIT_F.id]) : "", reason: r || (raw?.[COMMIT_USER_F] ? USER_DECLINED_ZH : NO_REASON_ZH), fix: s(raw?.[COMMIT_DECL_F.fix]) || s(raw?.data?.[COMMIT_DECL_F.fix]) || s(raw?.error?.[COMMIT_DECL_F.fix]) };
}
// 挂到 DOM：点一下两个按钮都禁用，结果写在卡上
export function mountCommitCard(el: HTMLElement, c: CommitReq, send: (op: string, args: any) => Promise<any>) {
  const btns = [...el.querySelectorAll<HTMLButtonElement>("button[data-cc]")], res = el.querySelector<HTMLElement>(".cc-res")!;
  btns.forEach(b => b.onclick = async () => {
    btns.forEach(x => x.disabled = true);
    const approve = b.dataset.cc === "ok", { op, args } = commitOpArgs(c.id, approve);
    res.textContent = approve ? "已确认，等待提交…" : "已取消";
    try { await send(op, args); if (approve) res.textContent = "已确认，提交中"; } catch (e: any) { res.textContent = `没有发出去：${e?.message_zh ?? e?.message ?? "见提示"}`; }
  });
}
// 被拒绝 / 超时：卡上写中文原因，修复按钮走已有的 fix_action 机制（resolveFix / runAction）
export function declinedHtml(d: { reason: string; fix: string }, esc: (s: string) => string, fix: { kind: string; label: string; note?: string } | null): string {
  const btn = fix ? `<button class="btn" data-cc-fix="${esc(d.fix)}"${fix.kind === "run" ? "" : " disabled"} title="${esc(fix.note ?? "")}">${esc(fix.label)}</button>` : "";
  return `<span class="lbl warn-t cc-decl">未提交：${esc(d.reason)}</span>${btn}`;
}
export function showDeclined(el: HTMLElement, d: { reason: string; fix: string }, esc: (s: string) => string, resolve: (a: string) => any, run: (a: string) => void, pre?: string) {
  el.querySelectorAll<HTMLButtonElement>("button[data-cc]").forEach(b => b.disabled = true);
  el.classList.add("declined");
  const act = el.querySelector<HTMLElement>(".act") ?? el;
  act.querySelector(".cc-res")!.innerHTML = (pre ?? "") + declinedHtml(d, esc, d.fix ? resolve(d.fix) : null);
  act.querySelector<HTMLButtonElement>("[data-cc-fix]")?.addEventListener("click", () => run(d.fix));
}
// 状态：pending → committed / rejected / failed（同一事件再推一次，或 commit_confirm 的回复）
export type CommitState = "pending" | "committed" | "rejected" | "failed";
export function commitResult(raw: any): { state: CommitState; commit: string; decl?: { id: string; reason: string; fix: string } } {
  const st = raw?.[COMMIT_F.state], code = raw?.[COMMIT_DECL_F.code], commit = s(raw?.[COMMIT_DECL_F.commit]);
  if (code === COMMIT_DECL_F.failed || st === "failed") return { state: "failed", commit, decl: toDeclined(raw) };
  if (code === COMMIT_DECL_F.declined || st === "rejected" || raw?.[COMMIT_DECL_F.ok] === false) return { state: "rejected", commit, decl: toDeclined(raw) };
  if (st === "committed" || raw?.[COMMIT_DECL_F.ok] === true) return { state: "committed", commit };
  return { state: "pending", commit };
}
export const committedHtml = (commit: string, esc: (s: string) => string) => `<span class="lbl ok-t cc-done">已提交${commit ? ` <span class="mono">${esc(commit)}</span>` : ""}</span>`;
