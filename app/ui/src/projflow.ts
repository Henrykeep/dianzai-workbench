// 项目页引导流程（产品逻辑重组 · 项目页）：① 读题 → ② 方案选型 → ③ 导入你的工程 → ④ 资源分配 → ⑤ 生成工程 / IDE 文件。
// 每步“运行”只在侧车暂存区跑现成的命令行工具（req.py / scheme.py / import_project.py / alloc.py / gen_project.py / keil_inject.py），
// 输出原样显示；点“确认写入”才写到题目目录 / boards/ / build/（侧车 dzbench/projflow.py）。没确认之前什么都不写。
import { writeScopeNote } from "./fieldmap";
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

// 题号默认从 PDF 文件名猜：“H题_xxx.pdf” → 当年 + H（如 2026 年 H 题）；猜不出就留空让人填。
export function codeFromName(fn: string, year = new Date().getFullYear()): string {
  const m = /(?:^|[^A-Za-z])([A-Za-z])\s*题/.exec(fn) || /^(\d{4}[A-Za-z])/.exec(fn);
  return m ? (m[1].length === 1 ? `${year}${m[1].toUpperCase()}` : m[1].toUpperCase()) : "";
}

export function initProjFlow(call: Call, toast: (t: string, k?: "ok" | "warn") => void) {
  const root = document.getElementById("pflow"); if (!root) return;
  const v = (id: string) => (document.getElementById(id) as HTMLInputElement).value.trim();
  const base = () => ({ code: v("pf-code") || "题目", dest: v("pf-dest") || undefined });
  // 进度：完成几步、下一步是哪张卡（卡片 .ok 即完成）
  const prog = () => {
    const cs = [...root.querySelectorAll<HTMLElement>(".pf-card")], n = cs.filter(c => c.classList.contains("ok")).length;
    const nx = cs.find(c => !c.classList.contains("ok")); cs.forEach(c => c.classList.toggle("cur", c === nx));
    const bar = document.querySelector<HTMLElement>("#pj-prog i"), t = document.getElementById("pj-prog-t");
    if (bar) bar.style.width = `${(n / cs.length) * 100}%`;
    if (t) t.textContent = `${n} / ${cs.length} 完成` + (nx ? ` · 下一步：${nx.querySelector("h4")?.firstChild?.textContent ?? ""}` : " · 全部就绪");
  };
  queueMicrotask(prog);
  const done = (k: string, txt: string) => { const c = root.querySelector<HTMLElement>(`[data-f="${k}"]`)!; c.classList.add("ok"); c.querySelector(".st")!.textContent = "✓ " + txt; prog(); };
  const out = (k: string, r: any) => { const o = root.querySelector<HTMLElement>(`[data-f="${k}"] .pf-out`)!; o.hidden = false; o.textContent = `$ ${r.cmd}\n${r.out}${r.rc ? `\n（退出码 ${r.rc}）` : ""}`; };
  const res = (k: string) => root.querySelector<HTMLElement>(`[data-f="${k}"] .pf-res`)!;
  const filesView = (fs: Record<string, string>, show: string[]) => Object.keys(fs).length ? `<p class="hint">将写入的文件：${Object.keys(fs).map(esc).join("、")}</p>` +
    show.filter(f => fs[f] != null).map(f => `<details${f === show[0] ? " open" : ""}><summary class="mono">${esc(f)}</summary><pre class="mono pf-pre">${esc(fs[f])}</pre></details>`).join("") : "";
  const confirmBtn = (k: string, label: string, fn: () => Promise<void>, preview?: any) => {
    const b = document.createElement("button"); b.className = "btn pri"; b.type = "button"; b.textContent = label;
    b.onclick = async () => { b.disabled = true; try { await fn(); } catch { b.disabled = false; } };
    res(k).append(b);
    const note = writeScopeNote(preview);   // #88 scope=write_only 才写这句（字段名在 fieldmap.WRITE_F）
    if (note) { const n = document.createElement("p"); n.className = "hint wo-note"; n.textContent = note; res(k).append(n); }
  };
  const inp = (id: string) => document.getElementById(id) as HTMLInputElement;
  // 确认一步后自动跑下一步的预览（预览只写暂存区，不算替人做决定）；下一步缺输入就只把光标放过去。
  const next = (k: string) => {
    const n = STEPS_FLOW[STEPS_FLOW.indexOf(k as any) + 1]; if (!n) return;
    const c = root.querySelector<HTMLElement>(`[data-f="${n}"]`)!; c.scrollIntoView?.({ block: "nearest" });
    if (n === "import" && !v("pf-proj")) { fork(); return; }
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
    }, r);
  };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); const f = e.dataTransfer?.files[0]; if (f) readPdf(f); };
  drop.onclick = () => fin.click();
  fin.onchange = () => { if (fin.files?.[0]) readPdf(fin.files[0]); };

  // ② 方案选型
  btn("scheme", async () => {
    const r = await call<any>("flow_preview", { step: "scheme", ...base() }); out("scheme", r);
    const ch = r.choices; const R = res("scheme");
    const opt = (o: any, pick: string) => `<option value="${esc(o.id)}"${o.id === pick ? " selected" : ""}>${esc(o.name)}（${esc(o.status)}）${o.pros?.length ? " · " + esc(o.pros.join("；")) : ""}</option>`;
    R.innerHTML = (ch ? `<p class="hint">每个能力选一个器件：按仓库支持程度排序（上板 > 仿真 > 编译 > 无驱动），第一项是默认；理由可不填（写“待定”）。</p>
      <table class="pf-tab"><tr><th>能力</th><th>牵涉</th><th>选用</th><th>理由</th></tr>${ch.needs.map((n: any) => `<tr data-need="${esc(n.need)}"><td class="mono">${esc(n.need)}</td><td>${n.score} 分（${esc(n.items.join("、") || "规则要求")}）</td><td>${n.options.length ? `<select class="in">${n.options.map((o: any) => opt(o, n.pick)).join("")}</select>` : `<span class="hint">库里没有候选：加进 tools/catalog/parts.yaml，或回第 1 步确认是否必须</span>`}${n.banned.length ? `<div class="hint">${n.banned.map((x: any) => `✗ ${esc(x.name)}：被 ${esc(x.why)} 禁用`).join("<br>")}</div>` : ""}</td><td><input class="in" placeholder="待定"></td></tr>`).join("")}
      <tr data-need=""><td class="mono">主控</td><td></td><td><select class="in">${ch.mcus.map((o: any) => opt(o, ch.mcu)).join("")}</select></td><td><input class="in" placeholder="待定"></td></tr></table>` : "")
      + filesView({ "options.md": r.files["options.md"] ?? "" }, ["options.md"]) + `<details><summary class="hint">直接改 scheme.yaml（一般不用）</summary><textarea class="in mono pf-ta" rows="10">${esc(r.files["scheme.yaml"] ?? "")}</textarea></details>`;
    if (r.rc) return;
    confirmBtn("scheme", "确认写入 scheme.yaml", async () => {
      const picks: Record<string, string> = {}, reasons: Record<string, string> = {}; let mcu: string | undefined, mcu_reason = "";
      R.querySelectorAll<HTMLTableRowElement>("tr[data-need]").forEach(tr => { const sel = tr.querySelector("select"), why = tr.querySelector<HTMLInputElement>("input")!.value.trim(), n = tr.dataset.need!;
        if (!n) { mcu = sel?.value; mcu_reason = why; return; } if (sel) picks[n] = sel.value; if (why) reasons[n] = why; });
      let y = R.querySelector<HTMLTextAreaElement>("textarea")!.value; if (mcu_reason) y = y.replace(/^mcu_reason:.*$/m, `mcu_reason: ${JSON.stringify(mcu_reason)}`);
      written("scheme", await call("flow_accept", { step: "scheme", ...base(), scheme_yaml: y, picks, reasons, mcu }));
    }, r);
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
    }, r);
  };
  // ③ 分叉：没有现成工程 → 从零新建（alloc 自动分配 → 生成 .ioc → 装了 CubeMX 就无头 GENERATE，没装才要人点一次 → 自动接着导入）
  let poll = 0;
  const fork = async () => {
    const r0 = await call<any>("flow_preview", { step: "scratch", ...base() }).catch(() => null); if (!r0) { inp("pf-proj").focus(); return; }
    const R = res("import"), ok = [...r0.options.filter((o: any) => o.ok && o.fit !== false), ...r0.options.filter((o: any) => o.ok)];
    R.innerHTML = `<p class="hint">没填现成工程目录。二选一：有 CubeMX/Keil 工程就在上面填目录（导入已有工程）；没有就在这里从零新建——按方案的主控排序，第一项是默认。</p>
      <select class="in" id="pf-scr">${r0.options.map((o: any, i: number) => `<option value="${i}"${o.ok ? "" : " disabled"}>${esc(o.label)}${o.ok && o.fit !== false ? "" : "（" + esc(o.why) + "）"}</option>`).join("")}</select><div id="pf-scr-res"></div>`;
    const sel = R.querySelector<HTMLSelectElement>("#pf-scr")!; if (ok.length) sel.value = String(r0.options.indexOf(ok[0]));
    const runS = async () => {
      const o = r0.options[+sel.value]; const r = await call<any>("flow_preview", { step: "scratch", ...base(), mcu: o.mcu, tpl: o.tpl, name: v("pf-board") || undefined }); out("import", r);
      const S = R.querySelector<HTMLElement>("#pf-scr-res")!;
      if (r.kind === "syscfg") {   // MSPM0：SysConfig 求解器分好引脚，板目录直接进 boards/，不用等外部工具
        S.innerHTML = `<p class="hint">引脚 / 外设由 TI SysConfig 求解器分配，已生成 ${esc(r.name)}.syscfg + ti_msp_dl_config.[ch] 和 board.yaml（syscfg_import 回核）。确认后写到 ${esc(r.target)}。</p>`
          + (r.overwrite ? `<label class="hint"><input type="checkbox" id="pf-scr-ow"> 已存在：覆盖</label>` : "") + filesView(r.files, ["board.yaml", `ccs/${r.name}.syscfg`, "alloc.md"]);
        if (r.rc) return;
        const b = document.createElement("button"); b.className = "btn pri"; b.type = "button"; b.textContent = `确认从零新建（写 boards/${r.name}/）`; S.append(b);
        b.onclick = async () => { b.disabled = true;
          const w = await call<any>("flow_accept", { step: "scratch", ...base(), name: r.name, overwrite: (document.getElementById("pf-scr-ow") as HTMLInputElement | null)?.checked }).catch(() => null); if (!w) { b.disabled = false; return; }
          inp("pf-board").value = r.name; if (!v("pf-app")) inp("pf-app").value = "port_selftest"; written("import", w);
        };
        return;
      }
      S.innerHTML = `<p class="hint">引脚 / 定时器 / DMA 已按芯片知识表自动分配（alloc.md），并生成 CubeMX 工程 ${esc(r.name)}.ioc（工具链 MDK-ARM）。确认后写到 ${esc(r.ioc)}。</p>` + filesView(r.files, ["alloc.md", `${r.name}.ioc`]);
      if (r.rc) return;
      const b = document.createElement("button"); b.className = "btn pri"; b.type = "button"; b.textContent = `确认从零新建（写 ${r.name}.ioc）`; S.append(b);
      b.onclick = async () => { b.disabled = true;
        const w = await call<any>("flow_accept", { step: "scratch", ...base(), name: r.name, cubemx_dir: r.target }).catch(() => null); if (!w) { b.disabled = false; return; }
        inp("pf-board").value = r.name; inp("pf-proj").value = lastProj = r.target;
        S.innerHTML = w.cubemx?.ok
          ? `<p class="hint">已用本机 STM32CubeMX 无头生成代码（<span class="mono">${esc(w.cubemx.exe)}</span>），正在自动导入。</p>`
          : `<p class="hint">已按 .ioc 写了一份<b>合成 Core</b>（非 CubeMX 输出，能直接编译，正在自动导入）。${w.cubemx?.why ? esc(w.cubemx.why) + "。" : ""}<b>上板前建议做一次：</b>用 STM32CubeMX 打开 <span class="mono">${esc(r.ioc)}</span> 点 GENERATE CODE 覆盖它，再回来重跑导入。</p>`;
        toast(`已写入：${w.written.join("、")}`, "ok");
        clearInterval(poll); poll = window.setInterval(async () => {
          const q = await call<any>("flow_preview", { step: "scratch_ready", ...base(), cubemx_dir: r.target }).catch(() => null);
          if (q?.ready) { clearInterval(poll); runImport(false); }
        }, 3000);
      };
    };
    sel.onchange = runS; if (ok.length) runS();
  };
  btn("import", () => v("pf-proj") ? runImport(false) : fork());
  let lastProj = "";   // 失焦也会触发 change：同一个目录不重跑（否则正要点“确认导入”时结果被清掉）
  inp("pf-proj").addEventListener("change", () => { if (v("pf-proj") && v("pf-proj") !== lastProj) (lastProj = v("pf-proj"), root.querySelector<HTMLButtonElement>('[data-f="import"] .pf-run')!.click()); });

  // ④ 资源分配
  btn("alloc", async () => {
    const r = await call<any>("flow_preview", { step: "alloc", ...base(), board: v("pf-board") || undefined }); out("alloc", r);
    res("alloc").innerHTML = filesView(r.files, ["alloc.md", "board.yaml", "cubemx.md"]);
    if (!r.rc) confirmBtn("alloc", "确认写入 alloc/", async () => written("alloc", await call("flow_accept", { step: "alloc", ...base() })), r);
  });

  // ⑤ 生成工程 / IDE 文件
  btn("gen", async () => {
    const uv = v("pf-uv") || undefined, gb = { board: v("pf-board") || undefined, app: v("pf-app") || undefined, uvprojx: uv };
    const r = await call<any>("flow_preview", { step: "gen", ...base(), ...gb }); out("gen", r);
    const G = res("gen"), d = r.draft;
    G.innerHTML = (d ? `<p class="hint">题目目录还没有 project.yaml，按能力标签起稿：${d.chosen.length ? d.chosen.map((c: any) => `<b>${esc(c.name)}</b>（${esc(c.tags.join("、"))}，来自 ${esc(c.path)}）`).join("、") : "没有匹配的现成子系统（先留空）"}。${d.missing.length ? `这些能力没有现成子系统，之后用 tools/new_subsys.py 新建：${esc(d.missing.join("、"))}。` : ""}确认后只补 ${esc(d.target)} 里没有的文件。</p>` + filesView(d.files, ["project.yaml", "io/io_auto.c"]) : "")
      + filesView(r.files, ["project_gen.h"]);
    if (r.rc) return;
    const keil = () => {
      if (!r.keil || r.keil.rc) return;
      const k = document.createElement("div");
      k.innerHTML = `<p class="hint">Keil：上面是 keil_inject --dry-run 的改动。真改会动你的工程文件 ${esc(r.keil.uvprojx)}，原文件先备份到 ${esc(r.keil.bak)}。</p>`;
      const b1 = document.createElement("button"); b1.className = "btn"; b1.type = "button"; b1.textContent = "改 Keil 工程…";
      b1.onclick = () => {
        b1.disabled = true;
        const b2 = document.createElement("button"); b2.className = "btn pri"; b2.type = "button"; b2.textContent = `确认修改 ${r.keil.uvprojx.split(/[\\/]/).pop()}（备份 .bak）`;
        b2.onclick = async () => { b2.disabled = true; try { const w = await call<any>("flow_accept", { step: "keil", ...base(), ...gb, confirm_uvprojx: r.keil.uvprojx }); done("gen", "Keil 已改"); toast(`已改 ${w.written[0]}；原文件备份在 ${w.bak}`, "ok"); k.append(Object.assign(document.createElement("p"), { className: "hint", textContent: `原文件备份：${w.bak}` })); } catch { b2.disabled = false; } };
        k.append(b2);
      };
      k.append(b1); G.append(k);
    };
    confirmBtn("gen", d ? "确认写入 project.yaml 草稿并生成" : "确认生成", async () => {
      const w = await call<any>("flow_accept", { step: "gen", ...base(), ...gb }); written("gen", w); keil();
      if (w.build) {   // 生成后自动交叉编译 + 出 IDE 工程（EIDE；MSPM0 另有 CCS / Keil）
        const p = document.createElement("div");
        p.innerHTML = `<p class="hint">${w.build.rc ? "✗ 编译失败" : "✓ 编译通过"}：<span class="mono">${esc(w.build.cmd)}</span></p>` + (w.build.rc ? `<pre class="mono">${esc(w.build.out.slice(-1500))}</pre>` : "")
          + w.ide.map((i: any) => `<p class="hint">${i.rc ? "✗" : "✓"} ${esc((i.out.trim().split("\n").pop() || i.cmd).replace(/^[✓✗]\s*/, ""))}</p>`).join("");
        G.append(p); if (!w.build.rc) done("gen", "编译通过");
      }
    }, r);
  });

  function btn(k: string, fn: () => Promise<void>) {
    root!.querySelector<HTMLButtonElement>(`[data-f="${k}"] .pf-run`)!.onclick = async e => {
      const b = e.currentTarget as HTMLButtonElement; b.disabled = true; res(k).innerHTML = "";
      try { await fn(); } catch { /* 侧车错误已弹 toast */ } finally { b.disabled = false; }
    };
  }
}
