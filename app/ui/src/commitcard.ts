// #88 git 提交确认卡（通用）：列出文件和提交说明，「确认提交 / 取消」。字段名草案在 fieldmap.COMMIT_F
import { COMMIT_F } from "./fieldmap";
export type CommitReq = { files: { path: string; status: string }[]; message: string };
export function toCommitReq(raw: any): CommitReq {
  const fs = Array.isArray(raw?.[COMMIT_F.files]) ? raw[COMMIT_F.files] : [];
  return {
    files: fs.map((f: any) => typeof f === "string" ? { path: f, status: "" } : { path: String(f?.[COMMIT_F.path] ?? "—"), status: String(f?.[COMMIT_F.status] ?? "") }),
    message: typeof raw?.[COMMIT_F.msg] === "string" ? raw[COMMIT_F.msg] : "",
  };
}
const ST: Record<string, string> = { A: "新增", M: "修改", D: "删除", R: "重命名", added: "新增", modified: "修改", deleted: "删除" };
export function commitCardHtml(c: CommitReq, esc: (s: string) => string): string {
  const files = c.files.length ? `<ul class="cc-files mono">${c.files.map(f => `<li>${f.status ? `<span class="cc-st">${esc(ST[f.status] ?? f.status)}</span> ` : ""}${esc(f.path)}</li>`).join("")}</ul>` : `<p class="hint">后端没有列出文件</p>`;
  const msg = c.message ? `<pre class="mono cc-msg">${esc(c.message)}</pre>` : `<p class="hint">后端没有给提交说明</p>`;
  return `<div class="card cc"><b>确认 git 提交（${c.files.length} 个文件）</b>${files}<div class="lbl">提交说明</div>${msg}` +
    `<div class="act"><button class="btn pri" data-cc="ok"${c.files.length ? "" : " disabled"}>确认提交</button><button class="btn" data-cc="cancel">取消</button></div></div>`;
}
