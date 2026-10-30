// 当前项目：hello / progress.get / progress.changed 的 project {path, name} | null（契约见后端 progress.py）。
// 顶栏显示项目名；为 null 时读题页给空状态：「新建项目」聚焦一句话输入，「打开项目」走 project.list → project.open {code}。
// 契约（sidecar e051341）：project.list → {projects:[{code,name,updated_at(ISO8601)}], current}；project.open {code} → {project:{path,name}} 并推 progress.changed；
// 失败码 project_code_missing / project_code_invalid / project_not_found 带 fix_action: project_list（重新拉列表）。侧车不认这个 op 时按钮置灰并写明原因。
export type Project = { path: string; name: string } | null;
export type ProjItem = { code: string; name: string; updated_at: string };
type Rpc = (op: string, a?: any) => Promise<any>;
export const isMissingOp = (e: any) => /bad_op|unknown op|未知操作|not supported|no such op|unknown_op/i.test(`${e?.code ?? ""} ${e?.message ?? e ?? ""}`);
export const NO_API = "侧车暂不支持打开项目（project.list 接口未就绪）";
export const topLabel = (p: Project) => (p ? p.name || p.path.split(/[\\/]/).filter(Boolean).pop() || p.path : "");
// 探测「打开项目」是否可用：只读调用，不改任何状态
export const fmtTime = (iso: string) => { const d = new Date(iso); if (isNaN(+d)) return iso ?? ""; const z = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}`; };
const errNote = (e: any) => [e?.message ?? String(e), e?.fix].filter(Boolean).join(" · ");
export async function probeOpen(rpc: Rpc): Promise<{ ok: boolean; note?: string; items?: ProjItem[]; current?: string | null }> {
  try { const r = await rpc("project.list"); return { ok: true, items: Array.isArray(r) ? r : (r?.projects ?? []), current: r?.current ?? null }; }
  catch (e) { return isMissingOp(e) ? { ok: false, note: NO_API } : { ok: true, note: errNote(e) }; }
}
export async function openProject(rpc: Rpc, code: string): Promise<{ ok: boolean; note?: string; project?: Project; relist?: boolean }> {
  try { const r = await rpc("project.open", { code }); return { ok: true, project: r?.project ?? null }; }
  catch (e: any) { return isMissingOp(e) ? { ok: false, note: "侧车暂不支持打开项目（project.open 接口未就绪）" } : { ok: false, note: errNote(e), relist: e?.fix_action === "project_list" }; }
}

let cur: Project | undefined;
export function initProject(rpc: Rpc, esc: (s: string) => string, onOpened: () => void) {
  const $ = (id: string) => document.getElementById(id)!;
  const empty = $("pj-empty"), list = $("pj-list"), note = $("pj-empty-note");
  const bOpen = $("pj-open") as HTMLButtonElement;
  $("pj-new").onclick = () => { const i = document.getElementById("pj-ask-in") as HTMLInputElement | null; i?.focus(); i?.scrollIntoView({ block: "center" }); };
  const disable = (why: string) => { bOpen.disabled = true; bOpen.title = why; note.textContent = why; };
  const relist = async (keep = "") => {
    const r = await probeOpen(rpc);
    if (!r.ok) return disable(r.note!);
    note.textContent = keep || r.note || (r.items!.length ? "" : "还没有已保存的项目，先新建一个");
    list.innerHTML = (r.items ?? []).map(p => `<button type="button" class="pj-item" data-code="${esc(p.code)}"${p.code === r.current ? ' aria-current="true"' : ""}><b>${esc(p.name)}</b><span class="mono">${esc(p.code)} · ${esc(fmtTime(p.updated_at))}</span></button>`).join("");
    list.hidden = !r.items?.length;
  };
  bOpen.onclick = () => relist();
  list.onclick = async e => {
    const code = (e.target as HTMLElement).closest<HTMLElement>(".pj-item")?.dataset.code; if (!code) return;
    const r = await openProject(rpc, code);
    if (!r.ok) { if (/未就绪/.test(r.note!)) return disable(r.note!); return r.relist ? relist(r.note!) : void (note.textContent = r.note!); }
    list.hidden = true; showProject(r.project ?? null); onOpened();
  };
  // 空状态一出现就探测一次，接口不存在时不等用户点了才发现
  return {
    async show(p: Project) {
      const was = cur; showProject(p);
      if (p === null && was !== null) { const r = await probeOpen(rpc); if (!r.ok) disable(r.note!); else { bOpen.disabled = false; bOpen.title = ""; note.textContent = ""; } }
      empty.hidden = p !== null;
    },
  };
}
export function showProject(p: Project) {
  cur = p;
  const t = document.getElementById("top-proj"); if (!t) return;
  t.hidden = !p; t.textContent = topLabel(p); t.title = p ? `当前项目：${p.path}` : "";
}
