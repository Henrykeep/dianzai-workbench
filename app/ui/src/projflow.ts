// 项目页引导流程（产品逻辑重组 · 项目页）：① 读题 → ② 方案选型 → ③ 导入你的工程 → ④ 资源分配 → ⑤ 生成工程 / IDE 文件。
// 每步“运行”只在侧车暂存区跑现成的命令行工具（req.py / scheme.py / import_project.py / alloc.py / gen_project.py / keil_inject.py），
// 输出原样显示；点“确认写入”才写到题目目录 / boards/ / build/（侧车 dzbench/projflow.py）。没确认之前什么都不写。
type Call = <T = any>(op: string, a?: Record<string, unknown>) => Promise<T>;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
export type ReqItem = { id: string; part?: string; score?: number | null; text: string; metrics?: any[]; [k: string]: unknown };

// 表格行 ↔ 评分项（纯函数，单测用）：只改 id / part / score / text 四列，其余字段（metrics、needs…）原样保留
export function editItems(items: ReqItem[], rows: { id: string; part: string; score: string; text: string; del?: boolean }[]): ReqItem[] {
  // 空格子 = 不写这个字段（schema 里 score 必须是数，null 会让 scheme.py 拒收）
  return rows.flatMap((r, i) => {
    if (r.del || !r.id.trim()) return [];
    const x: ReqItem = { ...(items[i] ?? {}), id: r.id.trim(), text: r.text };
    delete x.part; delete x.score;
    if (r.part.trim()) x.part = r.part.trim();
    if (r.score.trim() !== "" && Number.isFinite(Number(r.score))) x.score = Number(r.score);
    return [x];
  });
}
export const STEPS_FLOW = ["req", "scheme", "import", "alloc", "gen"] as const;

// 题号默认从 PDF 文件名猜：“H题_xxx.pdf” → 当年 + H（2026H）；猜不出就留空让人填。
export function codeFromName(fn: string, year = new Date().getFullYear()): string {
  const m = /(?:^|[^A-Za-z])([A-Za-z])\s*题/.exec(fn) || /^(\d{4}[A-Za-z])/.exec(fn);
  return m ? (m[1].length === 1 ? `${year}${m[1].toUpperCase()}` : m[1].toUpperCase()) : "";
}

export function initProjFlow(call: Call, toast: (t: string, k?: "ok" | "warn") => void) {
  const root = document.getElementById("pflow"); if (!root) return;
  const v = (id: string) => (document.getElementById(id) as HTMLInputElement).value.trim();
  const base = () => ({ code: v("pf-code") || "题目", dest: v("pf-dest") || undefined });
  const done = (k: string, txt: string) => { const c = root.querySelector<HTMLElement>(`[data-f="${k}"]`)!; c.classList.add("ok"); c.querySelector(".st")!.textContent = "✓ " + txt; };
  const out = (k: string, r: any) => { const o = root.querySelector<HTMLElement>(`[data-f="${k}"] .pf-out`)!; o.hidden = false; o.textContent = `$ ${r.cmd}\n${r.out}${r.rc ? `\n（退出码 ${r.rc}）` : ""}`; };
  const res = (k: string) => root.querySelector<HTMLElement>(`[data-f="${k}"] .pf-res`)!;
  const filesView = (fs: Record<string, string>, show: string[]) => Object.keys(fs).length ? `<p class="hint">将写入的文件：${Object.keys(fs).map(esc).join("、")}</p>` +
    show.filter(f => fs[f] != null).map(f => `<details${f === show[0] ? " open" : ""}><summary class="mono">${esc(f)}</summary><pre class="mono pf-pre">${esc(fs[f])}</pre></details>`).join("") : "";
  const confirmBtn = (k: string, label: string, fn: () => Promise<void>) => {
    const b = document.createElement("button"); b.className = "btn pri"; b.type = "button"; b.textContent = label;
    b.onclick = async () => { b.disabled = true; try { await fn(); } catch { b.disabled = false; } };
    res(k).append(b);
  };
  const inp = (id: string) => document.getElementById(id) as HTMLInputElement;
  // 确认一步后自动跑下一步的预览（预览只写暂存区，不算替人做决定）；下一步缺输入就只把光标放过去。
  const next = (k: string) => {
    const n = STEPS_FLOW[STEPS_FLOW.indexOf(k as any) + 1]; if (!n) return;
    const c = root.querySelector<HTMLElement>(`[data-f="${n}"]`)!; c.scrollIntoView?.({ block: "nearest" });
    if (n === "import" && !v("pf-proj")) { inp("pf-proj").focus(); return; }
    c.querySelector<HTMLButtonElement>(".pf-run")?.click();
  };
  const written = (k: string, r: { written: string[] }) => { done(k, "已写入"); toast(`已写入：${r.written.join("、")}`, "ok"); next(k); };

  // ① 读题
  let items: ReqItem[] = [];
  const drop = root.querySelector<HTMLElement>("#pf-drop")!, fin = root.querySelector<HTMLInputElement>("#pf-file")!;
  const readPdf = async (f: File) => {
    const b64 = await new Promise<string>(ok => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.readAsDataURL(f); });
    if (!v("pf-code")) inp("pf-code").value = codeFromName(f.name);
    drop.textContent = `题目：${f.name}（解析中…）`;
    const r = await call<any>("flow_preview", { step: "req", ...base(), pdf_b64: b64, filename: f.name }).catch(() => null);
    drop.textContent = `题目：${f.name}`; if (!r) return;
    out("req", r); items = r.items;
    res("req").innerHTML = `<p class="hint">起稿 ${items.length} 条评分项、${r.constraints.length} 条疑似约束；改表格后确认，写到 ${esc(r.target)}。分值、指标要对照原文填。</p>
      <table class="pf-tab"><tr><th>编号</th><th>基本/发挥</th><th>分值</th><th>原文</th><th>删</th></tr>${items.map((it, i) => `<tr data-i="${i}"><td><input class="in" value="${esc(it.id)}"></td><td><input class="in" value="${esc(it.part ?? "")}"></td><td><input class="in" value="${esc(it.score ?? "")}"></td><td><textarea class="in" rows="2">${esc(it.text)}</textarea></td><td><input type="checkbox"></td></tr>`).join("")}</table>`;
    confirmBtn("req", "确认写入 requirements.yaml", async () => {
      const rows = [...res("req").querySelectorAll<HTMLTableRowElement>("tr[data-i]")].map(tr => { const x = tr.querySelectorAll<HTMLInputElement>("input,textarea"); return { id: x[0].value, part: x[1].value, score: x[2].value, text: x[3].value, del: x[4].checked }; });
      written("req", await call("flow_accept", { step: "req", ...base(), items: editItems(items, rows) }));
    });
  };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); const f = e.dataTransfer?.files[0]; if (f) readPdf(f); };
  drop.onclick = () => fin.click();
  fin.onchange = () => { if (fin.files?.[0]) readPdf(fin.files[0]); };

  // ② 方案选型
  btn("scheme", async () => {
    const r = await call<any>("flow_preview", { step: "scheme", ...base() }); out("scheme", r);
    res("scheme").innerHTML = filesView({ "options.md": r.files["options.md"] ?? "" }, ["options.md"]) + `<p class="hint">scheme.yaml（按排序第一名起稿、全标“待定”；在这里改 picks / reasons）：</p><textarea class="in mono pf-ta" rows="10">${esc(r.files["scheme.yaml"] ?? "")}</textarea>`;
    if (r.rc) return;
    confirmBtn("scheme", "确认写入 scheme.yaml", async () => written("scheme", await call("flow_accept", { step: "scheme", ...base(), scheme_yaml: res("scheme").querySelector<HTMLTextAreaElement>("textarea")!.value })));
  });

  // ③ 导入你的 CubeMX / Keil 工程
  const runImport = async (accept_repair = false) => {
    const r = await call<any>("flow_preview", { step: "import", ...base(), project: v("pf-proj"), name: v("pf-board") || undefined, accept_repair }); out("import", r);
    inp("pf-board").value = r.name;
    if (r.uvprojx && !v("pf-uv")) inp("pf-uv").value = r.uvprojx;
    const R = res("import");
    if (r.need_repair) {
      R.innerHTML = `<p class="hint">main.c 的 USER CODE 标记坏了：上面是建议的修复 diff（只补标记和 while 骨架，你的代码一字不改）。接受后在暂存区重跑。</p>`;
      const b = document.createElement("button"); b.className = "btn"; b.type = "button"; b.textContent = "接受修复并重跑"; b.onclick = () => runImport(true); R.append(b); return;
    }
    if (r.rc) { R.innerHTML = `<p class="hint">导入没成功，按上面的输出处理后再运行。</p>`; return; }
    R.innerHTML = `<p class="hint">自动别名表（boards/${esc(r.name)}/aliases.yaml）：按引脚功能猜的，不对就改右列；你的 .ioc 和原工程不动。</p>
      <table class="pf-tab"><tr><th>引脚 / 外设</th><th>工作台逻辑名</th><th>说明（原标签）</th></tr>${r.aliases.map((a: any) => `<tr><td class="mono">${esc(a.key)}</td><td><input class="in mono" data-k="${esc(a.key)}" value="${esc(a.alias)}"></td><td class="hint">${esc(a.note)}</td></tr>`).join("")}</table>
      ${r.overwrite ? `<label class="hint"><input type="checkbox" id="pf-ow"> boards/${esc(r.name)}/ 已存在：覆盖（你改过的别名表会保留）</label>` : ""}`;
    confirmBtn("import", `确认导入到 boards/${r.name}/`, async () => {
      const ed: Record<string, string> = {};
      R.querySelectorAll<HTMLInputElement>("input[data-k]").forEach(x => { const a = r.aliases.find((y: any) => y.key === x.dataset.k); if (a && a.alias !== x.value.trim()) ed[x.dataset.k!] = x.value.trim(); });
      const w = await call<any>("flow_accept", { step: "import", ...base(), name: r.name, alias_edits: ed, overwrite: (document.getElementById("pf-ow") as HTMLInputElement | null)?.checked });
      if (!v("pf-app")) inp("pf-app").value = "port_selftest";   // import_project 自己建议的下一步：先跑板卡自检
      written("import", w);
    });
  };
  btn("import", () => runImport(false));
  let lastProj = "";   // 失焦也会触发 change：同一个目录不重跑（否则正要点“确认导入”时结果被清掉）
  inp("pf-proj").addEventListener("change", () => { if (v("pf-proj") && v("pf-proj") !== lastProj) (lastProj = v("pf-proj"), root.querySelector<HTMLButtonElement>('[data-f="import"] .pf-run')!.click()); });

  // ④ 资源分配
  btn("alloc", async () => {
    const r = await call<any>("flow_preview", { step: "alloc", ...base(), board: v("pf-board") || undefined }); out("alloc", r);
    res("alloc").innerHTML = filesView(r.files, ["alloc.md", "board.yaml", "cubemx.md"]);
    if (!r.rc) confirmBtn("alloc", "确认写入 alloc/", async () => written("alloc", await call("flow_accept", { step: "alloc", ...base() })));
  });

  // ⑤ 生成工程 / IDE 文件
  btn("gen", async () => {
    const uv = v("pf-uv") || undefined, gb = { board: v("pf-board") || undefined, app: v("pf-app") || undefined, uvprojx: uv };
    const r = await call<any>("flow_preview", { step: "gen", ...base(), ...gb }); out("gen", r);
    res("gen").innerHTML = filesView(r.files, ["project_gen.h"]) + (r.keil ? `<p class="hint">Keil：上面是 keil_inject --dry-run 的改动；确认后真改 ${esc(r.keil.uvprojx)}（先备份 .uvprojx.bak）。</p>` : "");
    if (!r.rc || r.keil) confirmBtn("gen", "确认生成", async () => written("gen", await call("flow_accept", { step: "gen", ...base(), ...gb })));
  });

  function btn(k: string, fn: () => Promise<void>) {
    root!.querySelector<HTMLButtonElement>(`[data-f="${k}"] .pf-run`)!.onclick = async e => {
      const b = e.currentTarget as HTMLButtonElement; b.disabled = true; res(k).innerHTML = "";
      try { await fn(); } catch { /* 侧车错误已弹 toast */ } finally { b.disabled = false; }
    };
  }
}
