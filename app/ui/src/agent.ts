import { setRound } from "./round";
// 内置 Agent 面板（docs/18）：离线阶跃分析、对话、文件改动卡片（diff → 确认 → 门禁 → git 提交 / 回滚）、大模型设置
import { Msg } from "./ws";

type Call = <T = any>(op: string, args?: Record<string, unknown>) => Promise<T>;
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const n = (v: number | null | undefined, d = 2, u = "") => v == null ? "—" : `${(+v).toFixed(d)}${u}`;

// 引导问题按当前 schema 生成，不写死某个对象（以前固定“速度环”“左轮比右轮慢”，倒立摆 / 云台上也这么问）
let lastFields: string[] = [];
export function agentIdle(fields: string[] = lastFields): string {
  lastFields = fields;
  const set = new Set(fields);
  const pair = [["_a", "_b"], ["_l", "_r"], ["_x", "_y"]].flatMap(([a, b]) =>
    fields.filter(f => f.endsWith(a) && set.has(f.slice(0, -a.length) + b)).map(f => [f, f.slice(0, -a.length) + b]))[0];
  const step = document.querySelector<HTMLElement>(".app")?.dataset.step ?? "调参";
  const BY: Record<string, [string, string[]]> = {      // 每页一句“我能替你干什么”+ 直接能点的说法
    项目: ["把题目 PDF 路径（和 CubeMX 工程目录，没有就从零新建）发我：五步一起预览，一张卡确认写入。", ["项目走到哪一步了", "推进项目 <题号>，题目 <PDF 路径>"]],
    烧录: ["我能编译、烧录（烧前出卡确认）、烧坏一键回滚。", ["编译一下看有没有错", "烧录"]],
    标定: ["先人推一下、再小幅点动，我判传感器 / 误差 / 输出方向。", ["检查一下极性"]],
    评分: ["我按评分项跑 N 次、最差一次算数，存证据、回写 requirements.yaml（都出卡确认）。", ["评分项 1 跑三遍留证据"]],
  };
  const [lead, qs] = BY[step] ?? ["点“分析阶跃”离线看超调 / 调节时间；或直接问。改参数和文件都要你确认，碰不到急停。",
    ["超调好大，怎么办", "仿真里自动调好", pair ? `为什么 ${pair[0]} 和 ${pair[1]} 不一样` : "最近的数据正常吗", "仿真里调好了，可以上车了吗"]];
  return `<div class="hint">
  ${esc(lead)}
  <div class="chips">${qs.map(q => `<button type="button" class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>`;
}
export const AGENT_IDLE = agentIdle();

export function initAgent(call: Call) {
  const feed = $("props");
  window.addEventListener("dz-step", () => { if (feed.querySelector(":scope > .hint") || !feed.children.length) feed.innerHTML = agentIdle(); });
  const add = (html: string, cls = "card") => {
    feed.querySelector(":scope > .hint")?.remove();
    const d = document.createElement("div"); d.className = cls; d.innerHTML = html; feed.prepend(d); return d;
  };

  // ---------------------------------------------------------------- 阶跃分析（不需要网络）
  async function tune(y?: string, sp?: string) {
    const r = await call("tune_analyze", { y, sp, seconds: 5 }).catch(() => null);
    if (!r) return;
    const m = r.metrics;
    const sel = (cur: string, opts: string[]) => opts.map(o => `<option ${o === cur ? "selected" : ""}>${esc(o)}</option>`).join("");
    const ys = r.pairs.map((p: string[]) => p[0]), sps = r.pairs.map((p: string[]) => p[1]);
    const d = add(`<div class="hd"><span class="dotk tune"></span><span class="t">阶跃分析</span><span class="lbl">规则 · 离线</span></div>
      <div class="row sm">反馈 <select class="in" data-k="y">${sel(r.y, ys.includes(r.y) ? ys : [r.y, ...ys])}</select>
        设定 <select class="in" data-k="sp">${sel(r.sp, sps.includes(r.sp) ? sps : [r.sp, ...sps])}</select></div>
      ${m.ok ? `<table class="met">
        <tr><td>目标</td><td>${n(m.y0)} → ${n(m.target)}</td><td>上升 10–90%</td><td>${n(m.rise_s, 3, " s")}</td></tr>
        <tr><td>超调</td><td>${n(m.overshoot_pct, 1, " %")}</td><td>调节 ±5%</td><td>${n(m.settling_s, 3, " s")}</td></tr>
        <tr><td>振荡</td><td>${m.oscillations} 次</td><td>稳态误差</td><td>${n(m.sse_pct, 1, " %")}</td></tr></table>` : `<p>${esc(m.reason)}</p>`}
      <div class="hints"></div>`);
    const hs = d.querySelector(".hints")!;
    r.hints.forEach((h: { level: string; text: string; changes: Record<string, number> }) => {
      const e = document.createElement("div"); e.className = "h " + h.level;
      const ch = Object.entries(h.changes).map(([k, v]) => `${esc(k)}→${+v.toPrecision(4)}`).join(" ");
      e.innerHTML = `<span>${esc(h.text)}</span>${ch ? `<button class="btn sm">提议 ${ch}</button>` : ""}`;
      e.querySelector("button")?.addEventListener("click", ev => { (ev.target as HTMLButtonElement).disabled = true; call("propose", { changes: h.changes, reason: h.text, source: "规则" }); });
      hs.append(e);
    });
    d.querySelectorAll<HTMLSelectElement>("select").forEach(s => s.onchange = () => {
      const v = (k: string) => d.querySelector<HTMLSelectElement>(`select[data-k=${k}]`)!.value;
      d.remove(); tune(v("y"), v("sp"));
    });
  }
  $("ag-tune").onclick = () => tune();

  // ---------------------------------------------------------------- 仿真搜索（缺口第 2 项）：开环阶跃 → 辨识 → 仿真 PSO/分阶段 → 实机逐个验 top-k
  async function simSearch() {
    const ask = (k: string, q: string, d: string) => { const v = window.prompt(q, localStorage.getItem(k) || d); if (v != null) localStorage.setItem(k, v); return v; };
    const y = ask("dz.search.y", "反馈通道（开环台阶时录的输出，如 spd_a）", "spd_a"); if (!y) return;
    const u = ask("dz.search.u", "控制量通道（台阶加在这一路，如 pwm_a）", "pwm_a"); if (!u) return;
    const mode = ask("dz.search.mode", "策略：pso / staged，加 ,wide 为宽范围（默认是 PID_Helper 原版窄范围）", "pso"); if (!mode) return;
    const [strategy, w] = mode.split(",").map(x => x.trim());
    const r = await call("tune_search", { y, u, seconds: 5, strategy, wide: w === "wide", top_k: 3 }).catch(() => null);
    if (!r) return;
    const md = r.model;
    const d = add(`<div class="hd"><span class="dotk tune"></span><span class="t">仿真搜索</span><span class="lbl">${esc(r.strategy)}${r.wide ? " · 宽范围" : ""} · ${r.evals} 次仿真</span></div>
      <p class="sm">模型 K=${n(md.K, 3)} τ=${n(md.tau_s, 3, " s")} L=${n(md.dead_s, 3, " s")}；初值来自${md.seed_from === "board" ? "板上当前参数" : "辨识"}。得分 1.0 = 和初值一样，越小越好。候选只是仿真结果：逐个上板验证，每次都要你确认。</p>
      <label class="sm"><input type="checkbox" class="vstep" checked> 全部采纳后自动做一次阶跃实验，显示护栏判定</label>
      <div class="hints"></div>`);
    const hs = d.querySelector(".hints")!;
    r.top.forEach((c: { gains: Record<string, number>; score: number }, i: number) => {
      const changes: Record<string, number> = {};
      Object.entries(c.gains).forEach(([k, v]) => { if (r.names[k]) changes[r.names[k]] = v; });
      const e = document.createElement("div"); e.className = "h info";
      e.innerHTML = `<span>#${i + 1} 得分 ${n(c.score, 3)}：${Object.entries(changes).map(([k, v]) => `${esc(k)}=${+v.toPrecision(4)}`).join(" ")}</span><button class="btn sm">上板验证</button>`;
      e.querySelector("button")!.addEventListener("click", ev => { (ev.target as HTMLButtonElement).disabled = true; call("propose", { changes, source: "仿真搜索", reason: `仿真搜索候选 #${i + 1}（${r.strategy}，得分 ${c.score}）`, verify_step: d.querySelector<HTMLInputElement>(".vstep")!.checked }); });
      hs.append(e);
    });
  }
  $("ag-search").onclick = () => simSearch();

  // ---------------------------------------------------------------- 文件改动卡片
  const cards = new Map<number, HTMLElement>();
  // diff 的 yaml 行很长，窄侧栏里真正改的数字在最右边看不到：先把“名字 旧 → 新”摘出来列在上面
  function defaults(diff: string): string {
    const pick = (sign: string) => new Map((diff || "").split("\n").filter(l => l.startsWith(sign) && !l.startsWith(sign.repeat(3)))
      .map(l => [/\bname:\s*(\w+)/.exec(l)?.[1], /\bdefault:\s*([^,}\s]+)/.exec(l)?.[1]] as const).filter(([n, v]) => n && v) as [string, string][]);
    const o = pick("-"), n = pick("+");
    const rows = [...n].filter(([k, v]) => o.get(k) !== v).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td class="mono dim">${esc(o.get(k) ?? "—")}</td><td>→</td><td class="mono acc">${esc(v)}</td></tr>`);
    return rows.length ? `<table class="defs">${rows.join("")}</table>` : "";
  }
  function renderChange(c: Msg) {
    let d = cards.get(c.id);
    if (!d) { d = add(""); cards.set(c.id, d); }
    const diff = esc(c.diff).split("\n").map(l => `<span class="${l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : ""}">${l}</span>`).join("\n");
    const st: Record<string, string> = { pending: "待确认", applying: "门禁运行中…", committed: "已提交", failed: "未通过，已还原", rejected: "已拒绝", reverted: "已回滚" };
    d.className = "card change " + c.status;
    if (c.status === "committed" && (c.files || []).some((f: string) => /\.ya?ml$/.test(f)))   // 流程条“定稿”只认真正提交了参数 yaml
      window.dispatchEvent(new CustomEvent("dz-final", { detail: c.commit }));
    d.innerHTML = `<div class="hd"><span class="dotk file"></span><span class="t">${esc(c.title)}</span><span class="lbl">${esc(c.layer)} · ${esc(c.source)}</span></div>
      <p>${esc(c.reason)}</p>${defaults(c.diff)}<pre class="diff">${diff}</pre>
      <div class="lbl">确认后：写入 → ${c.gates.length ? c.gates.map(esc).join(" → ") : "（无门禁）"} → git 提交</div>
      ${c.log && c.status !== "pending" ? `<details ${c.status === "failed" ? "open" : ""}><summary>门禁输出</summary><pre class="log">${esc(c.log)}</pre></details>` : ""}
      <div class="act">${c.status === "pending" ? `<button class="btn pri" data-a="1">确认并提交</button><button class="btn" data-a="0">拒绝</button>`
        : c.status === "committed" ? `<span class="lbl ok-t">${st[c.status]} ${esc(c.commit)}</span><button class="btn sm" data-rb="1">回滚</button>`
        : `<span class="lbl">${st[c.status] ?? esc(c.status)}</span>`}</div>`;
    d.querySelectorAll<HTMLButtonElement>("button[data-a]").forEach(b => b.onclick = () => {
      d!.querySelectorAll("button").forEach(x => (x as HTMLButtonElement).disabled = true);
      renderChange({ ...c, status: b.dataset.a === "1" ? "applying" : "rejected" });
      call("change_decide", { id: c.id, accept: b.dataset.a === "1" }).then(renderChange, () => renderChange(c));
    });
    d.querySelector<HTMLButtonElement>("button[data-rb]")?.addEventListener("click", async () => {
      if (!confirm(`回滚提交 ${c.commit}？（git revert，会新增一个回滚提交）`)) return;
      await call("rollback", { commit: c.commit }).then(() => renderChange({ ...c, status: "reverted" }), () => {});
    });
  }
  // 风险等级 human 的动作卡（烧录 / 实机阶跃 / 实机回滚）：人点了才执行
  const TOOL_CN: Record<string, string> = { flash: "烧录固件", erase: "擦除", mem_write: "写内存", run_step_test: "实机阶跃实验", run_sweep_test: "实机正弦扫频", rollback_best: "回滚到最好参数", flash_rollback: "回滚到烧前固件", flow_accept: "写入项目文件", project_apply: "一次写入项目各步", score_run: "跑评分项", score_save: "保存评分证据", score_writeback: "回写评分结果" };
  // 卡片内容由侧车 agent/cards.py 拼好（标题 / 一句话 / 每步：事实 + 旧→新 + 可展开 diff）；这里只排版，不认识具体工具
  const PRE: Record<string, string> = { link: "链路新鲜", channels: "实验通道在遥测里", env: "电池 / 温度门限", readback: "板上增益回读一致" };
  const CHG_KIND: Record<string, string> = { file: "文件", pin: "引脚", param: "参数", evidence: "证据" };
  const diffHtml = (t: string) => esc(t).split("\n").map(l => `<span class="${l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : ""}">${l}</span>`).join("\n");
  function changeRow(c: any): string {
    const old = c.old == null ? "" : `<s class="old">${esc(c.old)}</s><i>→</i>`;
    return `<li class="chg k-${esc(c.k)}"><span class="kd">${esc(CHG_KIND[c.k] ?? c.k)}</span><span class="nm" title="${esc(c.name)}">${esc(c.k === "file" ? c.name.split("/").pop() : c.name)}</span><span class="vv">${old}<b>${esc(c.new ?? "删除")}</b></span></li>`;
  }
  function stepRow(st: any, i: number, n: number): string {
    const ico = st.state === "fail" ? "✕" : st.state === "warn" ? "!" : "✓";
    const ORD: Record<string, number> = { pin: 0, param: 1, evidence: 2, file: 3 };       // 引脚 / 参数先看，文件放后
    const ch = [...(st.changes || [])].sort((x: any, y: any) => (ORD[x.k] ?? 9) - (ORD[y.k] ?? 9));
    const more = ch.length > 6 ? `<li class="lbl">还有 ${ch.length - 6} 项，展开看全部</li>` : "";
    const det = st.detail || ch.length > 6
      ? `<details><summary>查看改动</summary>${ch.length > 6 ? `<ul class="chgs">${ch.slice(6).map(changeRow).join("")}</ul>` : ""}${st.detail ? `<pre class="diff">${diffHtml(st.detail)}</pre>` : ""}</details>` : "";
    return `<li class="ast s-${esc(st.state)}"><span class="ico">${ico}</span><div class="bd">
      <div class="st"><span class="no">${n > 1 ? i + 1 : ""}</span>${esc(st.title)}</div>
      ${(st.facts || []).length ? `<div class="facts">${st.facts.map((f: string) => `<span>${esc(f)}</span>`).join("")}</div>` : ""}
      ${ch.length ? `<ul class="chgs">${ch.slice(0, 6).map(changeRow).join("")}${more}</ul>` : ""}${det}</div></li>`;
  }
  function renderAction(a: Msg) {
    const c = (a.preview ?? {}) as any, pa = c.prearm;
    const where = a.sim ? "仿真" : a.as_hw ? "仿真当实板" : "实机";
    const steps = (c.steps || []) as any[];
    const body = `<header class="ahd"><span class="pulse"></span><div><div class="at">${esc(c.title ?? TOOL_CN[a.tool] ?? a.tool)}</div>
        ${c.summary ? `<div class="as">${esc(c.summary)}</div>` : ""}</div><span class="where ${a.sim ? "sim" : "hw"}">${where}</span></header>
      ${c.error ? `<div class="aerr">${esc(c.error)}</div>` : ""}
      ${pa ? `<ul class="prearm">${(pa.checked as string[]).map(x => `<li class="ok-t">✓ ${esc(PRE[x] ?? x)}</li>`).join("")}${(pa.failed as string[]).map(f => `<li class="warn-t">✕ ${esc(f)}</li>`).join("")}</ul>` : ""}
      ${steps.length ? `<ol class="asteps">${steps.map((st, i) => stepRow(st, i, steps.length)).join("")}</ol>` : ""}
      <footer class="act"><span class="after">${esc(c.after ?? "")}${a.ttl_s ? ` · ${Math.round(a.ttl_s)} s 内有效` : ""}</span>
        <button class="btn" data-a="0">拒绝</button><button class="btn pri" data-a="1">执行</button></footer>`;
    const d = add(body, "card action pending");
    d.querySelectorAll<HTMLButtonElement>("button[data-a]").forEach(b => b.onclick = () => {
      d.querySelectorAll("button").forEach(x => (x as HTMLButtonElement).disabled = true);
      call("agent_action_decide", { id: a.id, accept: b.dataset.a === "1" })
        .then(r => { d.classList.replace("pending", r.status === "done" ? "done-ok" : "declined"); d.querySelector(".act")!.innerHTML = actionResult(r); },
              (e: any) => { d.querySelector(".act")!.innerHTML = `<span class="lbl warn-t">没有执行：${esc(e?.message ?? "见提示")}${e?.fix ? "。" + esc(e.fix) : ""}</span>`; });
    });
  }
  // 烧录/回滚的结果要把心跳校验讲清楚：“已执行”不等于板子起来了
  function actionResult(r: any): string {
    if (r.status !== "done") return `<span class="lbl">已拒绝</span>`;
    const v = r.result?.verify, w = r.result?.written;
    if (r.result?.failed) return `<span class="lbl warn-t">写到第 ${(w?.length ?? 0) + 1} 步（${esc(r.result.failed)}）停下：${esc(r.result.error)}</span>`;
    if (Array.isArray(w)) return `<span class="lbl ok-t">✓ 已写入 ${w.length} 步${r.result?.state?.human_todo ? " · 接下来要你：" + esc(r.result.state.human_todo) : ""}</span>`;
    if (!v) return `<span class="lbl ok-t">✓ 已执行</span>`;
    if (v.ok) return `<span class="lbl ok-t">已执行 · 心跳核对通过（schema ${esc(v.schema_hash)}）</span>`;
    if (v.ok === null) return `<span class="lbl warn-t">已执行 · ${esc(v.why)}</span>`;
    return `<span class="lbl warn-t">已执行，但${esc(v.why)}：${esc(v.fix ?? "")}</span>`;
  }
  const fwSt = (t: string) => { $("fw-st").textContent = t; };
  $("fw-build").onclick = () => { fwSt("编译中…"); call<any>("build").then(r => fwSt(r.ok ? `编译成功${r.flash_ready === true ? "，可以烧录" : "（" + (r.flash_ready || "") + "）"}` : `编译失败：${r.errors} 个错误`), () => fwSt("")); };
  $("fw-flash").onclick = () => call<any>("flash").then(() => fwSt("看下面的确认卡"), () => {});
  $("fw-rollback").onclick = () => call<any>("flash_rollback").then(() => fwSt("看下面的确认卡"), () => {});
  const VERDICT: Record<string, string> = { continue: "继续", done: "达标，结束", rollback: "变差，建议回滚到最好一轮", stop: "停止" };
  function renderRound(m: Msg) {
    const v = m.verdict, k = m.metrics;
    setRound({ verdict: v, metrics: k });
    // 建议卡永远对应最新一轮：旧轮的建议卡收起；变差 / 停止 → 本轮结论卡，主动作 = 回到最好一轮
    const props = document.getElementById("props");
    props?.querySelectorAll<HTMLElement>(":scope > .card.sugg, :scope > .card.worse").forEach(c => c.classList.add("stale"));
    if (v.action === "continue" && !v.advice) autoSuggest();
    if ((v.action === "rollback" || v.action === "stop") && props) {
      const c = document.createElement("div"); c.className = "card sugg worse";
      c.innerHTML = `<div class="sg-h"><span class="mono">第 ${v.round} 轮${v.action === "rollback" ? "变差" : "停止"}</span><span class="lbl">程序判定</span></div>
        <p class="why">超调 ${n(k.overshoot_pct, 1, "%")} · 调节 ${n(k.settling_s, 2, " s")}${v.best ? `；最好是第 ${v.best.round} 轮（评分 ${v.best.score ?? "—"}）` : ""}。${esc(v.reason || "")}</p>
        <div class="act"><button class="btn pri" type="button">回到最好一轮</button><button class="btn" type="button">留在本轮</button></div>`;
      const [go, stay] = c.querySelectorAll("button");
      go.onclick = () => { $("ag-best").click(); c.classList.add("stale"); };
      stay.onclick = () => c.classList.add("stale");
      props.prepend(c);
    }
    add(`<div class="hd"><span class="dotk"></span><span class="t">第 ${v.round} 轮阶跃：${esc(VERDICT[v.action] ?? v.action)}</span><span class="lbl">程序判定</span></div>
      <p>超调 ${n(k.overshoot_pct, 1, "%")} · 调节 ${n(k.settling_s, 3, " s")} · 稳态误差 ${n(k.sse_pct, 1, "%")} · 振荡 ${k.oscillations} · 评分 ${v.score}</p>
      ${v.best ? `<div class="lbl">最好：第 ${v.best.round} 轮 ${esc(JSON.stringify(v.best.gains))}${v.rolled_back ? "（仿真已自动回滚）" : ""}</div>` : ""}
      ${v.reason ? `<div class="lbl">${esc(v.reason)}</div>` : ""}`, "card round");
  }
  // 建议卡：离线规则（tune_analyze）给出的第一条带改动的建议 → 提议卡（右栏），采纳/驳回仍走 proposal_decide
  async function autoSuggest() {
    const r = await call<any>("tune_analyze", { seconds: 5 }).catch(() => null);
    const h = r?.hints?.find((x: any) => x.changes && Object.keys(x.changes).length);
    if (h) call("propose", { changes: h.changes, reason: h.text, source: "规则" }).catch(() => {});
  }
  function renderSweep(m: Msg) {
    const s = m.summary || {}, bad = new Set<number>(s.unreliable || []);
    const rows = (m.points || []).map((p: any) => `<tr${bad.has(p.f) ? ' class="bad" title="这个频点信号质量差，结果仅供参考"' : ""}><td>${n(p.f, 2, " Hz")}</td><td>${n(p.db, 1, " dB")}</td><td>${n(p.phase, 0, "°")}</td></tr>`).join("");
    add(`<div class="hd"><span class="dotk"></span><span class="t">扫频：带宽 ${s.bandwidth_hz ? n(s.bandwidth_hz, 2, " Hz") : "超出扫描范围"}</span><span class="lbl">程序测量</span></div>
      <p>谐振峰 ${n(s.peak_db, 1, " dB")}${s.peak_hz ? " @ " + n(s.peak_hz, 2, " Hz") : ""} · 相位滞后 90° ${s.lag90_hz ? n(s.lag90_hz, 2, " Hz") : "—"}</p>
      <table class="sweep"><tr><th>频率</th><th>增益</th><th>相位</th></tr>${rows}</table>
      ${(m.errors || []).length ? `<div class="lbl">${m.errors.length} 个频点没测出来（信号太弱或太快）</div>` : ""}
      <div class="lbl">峰 &gt; 3 dB 说明欠阻尼（超调大）；带宽低说明响应慢</div>`);
  }
  $("ag-sweep").onclick = (e) => {
    const b = e.currentTarget as HTMLButtonElement; b.disabled = true; b.textContent = "扫频中…";
    call("tune_sweep_test").catch(() => {}).finally(() => { b.disabled = false; b.textContent = "扫频"; });   // 结果走 sweep_result 事件
  };
  $("ag-step").onclick = () => call("tune_step_test").catch(() => {});          // 结果走 tune_round 事件 → renderRound
  $("ag-rule").onclick = () => call<any>("tune_rule_round").then(r => { if (r?.action === "OBSERVE") add(`<span class="lbl">规则建议：${esc(r.reason)}</span>`, "msg bot"); }, () => {});
  $("ag-best").onclick = async () => {
    // 回到… → 最好一轮：本次护栏有记录就回那一轮；侧车重启过（护栏清空）就回自动存的“自动-最好一轮”快照（同一个入口）
    const b = await call<any>("tune_best").catch(() => null);
    const g = b ? Object.entries(b.gains).map(([k, v]) => `${k}=${+(+(v as number)).toPrecision(4)}`).join(" ") : "";
    if (!window.confirm(b ? `回到第 ${b.round} 轮（得分 ${b.score}）：${g}？` : "本次没有护栏记录：回到上次自动存的最好一轮快照？")) return;
    call<any>("params_restore", { source: "best" }).then(r => add(`<span class="lbl">${r.source === "best" ? `已回到第 ${r.round} 轮：改了 ${r.applied.length} 个参数` : "已从“自动-最好一轮”快照恢复"}</span>`, "msg bot"), () => {});
  };
  // 调试探针设置：后端 / 探针类型 / 序列号（op probe_config_get / probe_config_set）
  const KIND: Record<string, string> = { stlink: "ST-Link", daplink: "DAPLink（CMSIS-DAP）", jlink: "J-Link" };
  async function probeFill(list = true, tool?: string) {
    const r = await call<any>("probe_config_get", { list }).catch(() => null);
    if (!r) return null;
    const t = tool ?? r.tool;
    $("pb-tool").innerHTML = r.tools.map((x: string) => `<option ${x === t ? "selected" : ""}>${esc(x)}</option>`).join("");
    $("pb-kind").innerHTML = `<option value="">默认（J-Link 后端 = jlink，其余 = ST-Link）</option>` +
      r.kinds.map((k: string) => `<option value="${k}" ${k === r.probe_kind ? "selected" : ""}>${esc(KIND[k] ?? k)}</option>`).join("");
    if (!tool) $<HTMLInputElement>("pb-serial").value = r.probe;
    const ps = r.list?.probes ?? [];
    $("pb-list").innerHTML = ps.map((p: any) => `<option value="${esc(p.uid)}">${esc(p.desc)}</option>`).join("");
    $("pb-found").innerHTML = !r.list ? "" : ps.length
      ? ps.map((p: any) => `<li><button class="btn" type="button" data-uid="${esc(p.uid)}" data-kind="${esc(p.kind)}">用这个</button> ${esc(p.uid)} · ${esc(p.desc)}</li>`).join("")
      : `<li>${esc(r.list.error || "没列到探针（" + r.list.via + "）")}</li>`;
    const st = r.status;
    $("pb-st").textContent = (st.ok ? (st.exe ? `${st.tool}：${st.exe}` : `${st.tool}`) : `${st.why}；${st.fix}`) +
      (r.project_overrides.length ? `　注意：工程 dzbench.json 写了 ${r.project_overrides.join("/")}，会盖住这里的设置` : "");
    return r;
  }
  $("fw-probe").onclick = async () => { if (await probeFill()) $<HTMLDialogElement>("probe-dlg").show(); };
  $("pb-scan").onclick = () => probeFill(true, $<HTMLSelectElement>("pb-tool").value);
  $("pb-found").addEventListener("click", e => {
    const b = (e.target as HTMLElement).closest<HTMLElement>("[data-uid]");
    if (!b) return;
    $<HTMLInputElement>("pb-serial").value = b.dataset.uid!;
    if (b.dataset.kind) $<HTMLSelectElement>("pb-kind").value = b.dataset.kind;
  });
  $<HTMLDialogElement>("probe-dlg").addEventListener("close", () => {
    if ($<HTMLDialogElement>("probe-dlg").returnValue !== "save") return;
    const values = { tool: $<HTMLSelectElement>("pb-tool").value, probe_kind: $<HTMLSelectElement>("pb-kind").value,
                     probe: $<HTMLInputElement>("pb-serial").value.trim() };
    call<any>("probe_config_set", { values }).then(r => fwSt(`调试后端：${r.tool}${r.probe_kind ? " / " + (KIND[r.probe_kind] ?? r.probe_kind) : ""}${r.probe ? " / " + r.probe : ""}`), () => {});
  });

  // 协处理器 SSH 部署（缺口 12）：op coproc_get / set / push / start / stop / status / log
  const CPF = ["host", "port", "user", "dir", "entry", "run", "key"];
  let cpPresets: Record<string, any> = {};
  const cpSt = (t: string) => { $("cp-st").textContent = t; };
  const cpErr = (e: any) => cpSt(`✗ ${e?.message ?? e}${e?.fix ? "；" + e.fix : ""}`);
  function cpShow(c: any) {
    $("cp-kind").innerHTML = Object.entries(cpPresets).map(([k, p]) => `<option value="${esc(k)}" ${k === c.kind ? "selected" : ""}>${esc(p.label)}</option>`).join("");
    for (const f of CPF) $<HTMLInputElement>("cp-" + f).value = String(c[f] ?? "");
  }
  const cpVals = () => {
    const v: Record<string, string> = { kind: $<HTMLSelectElement>("cp-kind").value };
    for (const f of CPF) v[f] = $<HTMLInputElement>("cp-" + f).value.trim();
    return v;
  };
  const cpSave = () => call<any>("coproc_set", { values: cpVals() }).then(c => { cpShow(c); return c; });
  const cpStatus = () => call<any>("coproc_status").then(r => cpSt(r.running ? `运行中（pid ${r.pid}）` : "没在跑"), cpErr);
  $("fw-coproc").onclick = async () => {
    const r = await call<any>("coproc_get").catch(() => null);
    if (!r) return;
    cpPresets = r.presets; cpShow(r.cfg); cpSt(""); $("cp-out").textContent = "";
    $<HTMLDialogElement>("cp-dlg").show();
    if (r.cfg.host) cpStatus();
  };
  $("cp-kind").onchange = () => {      // 换板子：带出该板默认用户 / 目录 / 启动命令
    const p = cpPresets[$<HTMLSelectElement>("cp-kind").value];
    if (p) { $<HTMLInputElement>("cp-user").value = p.user; $<HTMLInputElement>("cp-dir").value = p.dir; $<HTMLInputElement>("cp-run").value = p.run; }
  };
  $("cp-save").onclick = () => cpSave().then(() => cpSt("已保存"), cpErr);
  $("cp-push").onclick = () => { cpSt("推送中…"); cpSave().then(() => call<any>("coproc_push", { path: $<HTMLInputElement>("cp-src").value.trim() }))
    .then(r => cpSt(`已推送 ${r.pushed.join(", ")} → ${r.to}`), cpErr); };
  $("cp-start").onclick = () => cpSave().then(() => call<any>("coproc_start")).then(r => cpSt(`已启动 pid ${r.pid}：${r.run}`), cpErr);
  $("cp-stop").onclick = () => call<any>("coproc_stop").then(r => cpSt(r.stopped ? `已停止（${r.detail}）` : "本来就没在跑"), cpErr);
  $("cp-log").onclick = () => call<any>("coproc_log", { lines: 200 }).then(r => { $("cp-out").textContent = r.text || "（dz.log 为空）"; cpStatus(); }, cpErr);

  // 调参前问答（缺口 9）：问题由侧车给，人点“确认”才生效
  $("ag-pre").onclick = async () => {
    const r = await call<any>("pretune_get").catch(() => null);
    if (!r) return;
    const cur = r.current || {};
    $("pre-q").innerHTML = r.questions.map((q: any) => {
      const v = cur[q.key] ?? "";
      const inp = q.choices
        ? `<select class="in" name="${q.key}"><option value="">—</option>${Object.entries(q.choices).map(([k, t]) => `<option value="${esc(k)}" ${k === v ? "selected" : ""}>${esc(t as string)}</option>`).join("")}</select>`
        : `<input class="in" name="${q.key}" ${q.type === "number" ? 'type="number" min="0" max="100" step="0.5"' : ""} value="${esc(String(v))}">`;
      return `<label>${esc(q.q)}${inp}</label>`;
    }).join("");
    $<HTMLDialogElement>("pre-dlg").show();
  };
  $<HTMLDialogElement>("pre-dlg").addEventListener("close", () => {
    const d = $<HTMLDialogElement>("pre-dlg");
    if (d.returnValue === "cancel" || !d.returnValue) return;
    const answers: Record<string, string> = {};
    if (d.returnValue === "save")
      $("pre-q").querySelectorAll<HTMLInputElement | HTMLSelectElement>("[name]").forEach(e => { if (e.value.trim()) answers[e.name] = e.value.trim(); });
    call<any>("pretune_set", { answers: d.returnValue === "save" ? answers : null }).then(r => add(r.current
      ? `<span class="lbl">调参偏好已记下：${esc(r.current.summary)}${r.applied.length ? "；护栏：" + esc(r.applied.join("，")) : ""}</span>`
      : `<span class="lbl">调参偏好已清掉，回到默认策略</span>`, "msg bot"), () => {});
  });
  $("ag-guard").onclick = () => call("tune_reset").then(() => add(`<span class="lbl">调参护栏已重置：之前的轮次和“最好一轮”不再参考</span>`, "msg bot"), () => {});
  $("ag-new").onclick = () => call("agent_reset").then(() => { feed.innerHTML = AGENT_IDLE; }, () => {});
  $("ag-yaml").onclick = () => call("yaml_writeback").then(renderChange, () => {});

  // ---------------------------------------------------------------- 对话
  let tools: HTMLElement | null = null, mode: HTMLElement | null = null;
  // 示例问题：点一下直接问（第一次打开时最省事的入口）
  feed.addEventListener("click", e => {
    const q = (e.target as HTMLElement).closest<HTMLElement>(".chip")?.dataset.q;
    if (q) { $<HTMLInputElement>("ag-in").value = q; $<HTMLFormElement>("ag-form").requestSubmit(); }
  });
  $("ag-form").onsubmit = async e => {
    e.preventDefault();
    const inp = $<HTMLInputElement>("ag-in"), text = inp.value.trim();
    if (!text) return;
    inp.value = ""; $<HTMLButtonElement>("ag-send").disabled = true;
    add(esc(text), "msg me");
    const w = add(`<span class="lbl">思考中…</span><div class="tools"></div><div class="lbl mode"></div>`, "msg bot");
    tools = w.querySelector(".tools"); mode = w.querySelector(".mode"); planEl = null;
    try { const r = await call<string>("agent_ask", { text }); w.firstElementChild!.outerHTML = `<div>${esc(r).replace(/\n/g, "<br>")}</div>`; }
    catch { w.remove(); }
    // 不清 tools/mode：工具事件会比回答晚到（侧车线程 → 事件循环），留给这条消息直到下一问
    finally { $<HTMLButtonElement>("ag-send").disabled = false; }
  };

  // ---------------------------------------------------------------- 设置
  let provs: Record<string, { base_url: string; model: string }> = {};
  $("ag-cfg").onclick = async () => {
    const c = await call("agent_config").catch(() => null);
    if (!c) return;
    provs = c.providers;
    $("cfg-prov").innerHTML = Object.keys(provs).map(k => `<option ${k === c.provider ? "selected" : ""}>${esc(k)}</option>`).join("");
    $<HTMLInputElement>("cfg-url").value = c.base_url; $<HTMLInputElement>("cfg-model").value = c.model; $<HTMLInputElement>("cfg-repo").value = c.repo ?? "";
    const key = $<HTMLInputElement>("cfg-key"); key.value = ""; key.placeholder = c.has_key ? `已保存 ${c.key_hint}（留空 = 不改）` : "sk-…（Ollama 本地可留空）";
    $<HTMLDialogElement>("cfg").show();   // 非模态：设置开着时急停按钮也必须点得到
  };
  $("cfg-prov").onchange = () => { const p = provs[$<HTMLSelectElement>("cfg-prov").value]; if (p) { $<HTMLInputElement>("cfg-url").value = p.base_url; $<HTMLInputElement>("cfg-model").value = p.model; } };
  $<HTMLDialogElement>("cfg").onclose = () => {
    if ($<HTMLDialogElement>("cfg").returnValue !== "save") return;
    call("agent_config", { set: { provider: $<HTMLSelectElement>("cfg-prov").value, base_url: $<HTMLInputElement>("cfg-url").value, model: $<HTMLInputElement>("cfg-model").value, repo: $<HTMLInputElement>("cfg-repo").value, api_key: $<HTMLInputElement>("cfg-key").value } });
  };

  // ---------------------------------------------------------------- 计划 / 撤销
  let planEl: HTMLElement | null = null;
  function renderPlan(m: Msg) {
    const items = (m.items as { step: string; status: string }[]) ||
      (m.steps as string[]).map((s, i) => ({ step: s, status: i < m.current ? "completed" : i === m.current ? "in_progress" : "pending" }));
    const html = `<span class="lbl">计划</span><ol class="plan">${items.map((it) =>
      `<li class="${it.status === "completed" ? "done" : it.status === "in_progress" ? "cur" : ""}">${esc(it.step)}</li>`).join("")}</ol>`;
    if (planEl && planEl.isConnected) planEl.innerHTML = html; else planEl = add(html);
  }
  const undoBtn = $<HTMLButtonElement>("ag-undo");
  function renderJournal(items: any[]) {
    undoBtn.disabled = !items.length;
    const e = items[items.length - 1];
    undoBtn.title = e ? `撤销：${e.kind === "param" ? `${e.name} ${e.new} → 改回 ${e.old}` : `提交 ${e.commit} ${e.title}`}（共 ${items.length} 步可撤）` : "Agent 还没改过东西";
  }
  undoBtn.onclick = async () => {
    const r = await call<any>("agent_undo").catch(() => null);
    if (r) add(r.undone === "param" ? `已撤销：<b>${esc(r.name)}</b> 改回 ${n(r.value, 4)}（原来 ${n(r.was, 4)}）` : `已撤销提交 ${esc(r.reverted)}（新提交 ${esc(r.commit)}）`);
  };
  call<any[]>("agent_journal").then(renderJournal).catch(() => {});
  // Agent 调过的参数处于“试用中”，人确认保留或恢复原值
  let tuneEl: HTMLElement | null = null;
  function renderTune(m: Msg) {
    if (!m.pending) { tuneEl?.remove(); tuneEl = null; return; }
    const rows = (m.items as any[]).map((it) => `${esc(it.name)} ${n(it.orig, 4)} → ${n(it.now, 4)}`).join("，");
    const html = `<span class="lbl">试用中</span> Agent 改过：${rows}。<button class="btn sm" data-k="1">保留（存快照）</button> <button class="btn ghost sm" data-k="0">恢复原值</button>`;
    if (tuneEl && tuneEl.isConnected) tuneEl.innerHTML = html; else tuneEl = add(html);
    tuneEl.querySelectorAll<HTMLButtonElement>("button").forEach((b) => b.onclick = async () => {
      const r = await call<any>("agent_tune_finish", { keep: b.dataset.k === "1" }).catch(() => null);
      if (r) add(r.kept ? `已保留，快照 ${esc(String(r.snapshot).split(/[\\/]/).pop() || "")}` : `已恢复 ${r.restored.length} 个参数到调参前的值`);
    });
  }
  const wm = $<HTMLSelectElement>("ag-workmode");
  wm.onchange = async () => {
    const r = await call<any>("agent_set_mode", { mode: wm.value }).catch(() => null);
    if (r) add(`<span class="lbl">模式</span> 已切到「${esc(r.name)}」`);
  };

  return {
    onMsg(m: Msg) {
      if (m.type === "agent_plan") renderPlan(m);
      if (m.type === "agent_tune_pending") renderTune(m);
      if (m.type === "agent_journal") renderJournal(m.items);
      if (m.type === "change") renderChange(m);
      if (m.type === "agent_action") renderAction(m);
      if (m.type === "tune_round") renderRound(m);
      if (m.type === "sweep_result") renderSweep(m);
      if (m.type === "agent_mode" && mode) mode.textContent = m.mode === "offline" ? `${m.name} · 无需联网${m.fallback ? "（大模型连不上，已自动切换）" : ""}` : `大模型 ${m.name}`;
      if (m.type === "agent_tool" && tools) tools.insertAdjacentHTML("beforeend", `<span class="tool ${m.ok ? "" : "bad"}">${esc(m.name)}</span>`);
    },
    add,
  };
}
