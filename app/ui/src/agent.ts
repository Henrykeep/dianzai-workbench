import { setRound } from "./round";
// 内置 Agent 面板（docs/18）：离线阶跃分析、对话、文件改动卡片（diff → 确认 → 门禁 → git 提交 / 回滚）、大模型设置
import { retryText, clearsRetry, LOCAL_LABEL } from "./llmretry";
import { isRetry, toRetry, agentState, sourceLabel, AGENT_F } from "./fieldmap";
import { dropFlashBlockers, isFlashNotice } from "./flashnag";
import { Msg } from "./ws";
import { runAction, resolveFix } from "./progress";
import { Receipts, RECEIPT_LABEL, newMsgId, blockedCard, newBlockers, noticeView, NoticeGate, Notice } from "./receipt";
import { TurnGate, Watch, timeoutCard, errorCard, Card } from "./agentwatch";
import { parseUsage, usageLog, elapsedOf, fmtElapsed, Usage } from "./usage";
import { modelLister, type El } from "./llmcfg";

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
    烧录: ["我能编译、烧录（烧前出卡确认）、烧坏一键回滚。", ["编译并检查报错", "烧录"]],
    标定: ["先用手推动、再小幅点动，我判传感器 / 误差 / 输出方向。", ["检查极性"]],
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
    const d = add(`<div class="hd"><span class="dotk tune"></span><span class="t">阶跃分析</span><wa-tag size="small" appearance="filled" variant="neutral">来自规则引擎</wa-tag></div>
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
    const mode = ask("dz.search.mode", "策略：pso / staged，加 ,wide 为宽范围（默认窄范围：初值 0–2 倍）", "pso"); if (!mode) return;
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
    d.innerHTML = `<div class="hd"><span class="dotk file"></span><span class="t">${esc(c.title)}</span><span class="lbl">${esc(({ app: "应用代码", fw: "固件", firmware: "固件", docs: "文档", config: "配置" } as Record<string, string>)[c.layer] ?? "")}${c.source === "agent" ? " · Agent 提议" : ""}</span></div>
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
        ${c.summary ? `<div class="as">${esc(c.summary)}</div>` : ""}</div>${sourceLabel(a) ? `<wa-tag size="small" variant="neutral">${sourceLabel(a)}</wa-tag>` : ""}<span class="where ${a.sim ? "sim" : "hw"}">${where}</span></header>
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
  $("ag-relay").onclick = (e) => {
    const b = e.currentTarget as HTMLButtonElement; b.disabled = true; b.textContent = "继电起步中…";
    call<any>("tune_relay").then(r => add(r?.ok
      ? `<span class="lbl">继电起步：Ku=${n(r.ku, 3, "")} Pu=${n(r.pu, 3, " s")}（${r.cycles} 个周期）→ ${esc(r.gains.rule.toUpperCase())} 初值已发提议卡</span>`
      : `<span class="lbl">继电起步没成功：${esc(r?.why ?? "")}</span>`, "msg bot"), () => {})
      .finally(() => { b.disabled = false; b.textContent = "自整定"; });
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
  let turnUsage: Usage | null = null, timeEl: HTMLElement | null = null;
  // 示例问题：点击直接提问（第一次打开时最省事的入口）
  feed.addEventListener("click", e => {
    const q = (e.target as HTMLElement).closest<HTMLElement>(".chip")?.dataset.q;
    if (q) { $<HTMLInputElement>("ag-in").value = q; $<HTMLFormElement>("ag-form").requestSubmit(); }
  });
  // 等待看门狗：发出即计时；任何 agent_* 事件都算“有响应”；60 s 无事件 → 超时卡
  const watch = new Watch(); const gate = new TurnGate(); let lastText = "", thinkEl: HTMLElement | null = null;
  setInterval(() => {
    if (!watch.on) return;
    const t = watch.tick(performance.now());
    if (thinkEl?.isConnected) thinkEl.textContent = t.label;
    if (t.timeout) showCard(timeoutCard());
  }, 1000);
  function showCard(k: Card, estopBlk = false) {
    const c = add(`<div class="down"><span class="dot"></span><div><b>${esc(k.title)}</b><p>原因：${esc(k.why)}</p><p class="fix">处理：${esc(k.fix)}</p>
      <details class="ag-detail"><summary>查看详情</summary><pre class="mono">${esc(k.detail)}</pre></details></div></div>
      <div class="act">${k.other ? `<button class="btn" data-r="fix" ${k.other.kind === "run" ? "" : "disabled"} title="${esc(k.other.note ?? "")}">${esc(k.other.label)}</button>${k.other.note ? `<span class="nb-note">${esc(k.other.note)}</span>` : ""}` : ""}${k.settings ? `<button class="btn" data-r="cfg">大模型设置</button>` : ""}${k.retry ? `<button class="btn pri" data-r="retry">重试</button>` : ""}</div>`, "card down-card ag-err");
    if (estopBlk) c.dataset.estopBlocker = "1";
    c.querySelector<HTMLElement>("[data-r=cfg]")?.addEventListener("click", () => openCfg());
    if (k.other?.kind === "run") c.querySelector<HTMLElement>("[data-r=fix]")?.addEventListener("click", () => runAction(k.otherId!, s => window.dispatchEvent(new CustomEvent("dz-goto", { detail: s }))));
    c.querySelector<HTMLElement>("[data-r=retry]")?.addEventListener("click", () => {
      c.remove(); watch.stop(); $<HTMLInputElement>("ag-in").value = lastText; $<HTMLButtonElement>("ag-send").disabled = false; $<HTMLFormElement>("ag-form").requestSubmit();
    });
  }
  // 回执：每条消息一个 msg_id；回合进行中也能继续发（不再禁用发送键，以前第 2、3 条因此被静默吞掉）
  type Turn = { id: string; text: string; me: HTMLElement; tag: HTMLElement; w: HTMLElement | null; t0: number };
  const turns: Turn[] = [];
  const R = new Receipts((id, st, ack) => {
    const t = turns.find(x => x.id === id) ?? lostTurns.get(id); if (!t) return;
    t.tag.dataset.state = st; t.tag.textContent = RECEIPT_LABEL[st];
    t.me.classList.toggle("undelivered", st === "lost");
    const nx = t.tag.nextElementSibling;
    if (st !== "lost" && nx?.classList.contains("undel")) nx.remove();
    if (st === "lost") {
      const f = document.createElement("div"); f.className = "undel";
      f.innerHTML = `<button class="btn sm">重发</button>`;
      f.querySelector("button")!.onclick = () => { f.remove(); t.me.remove(); t.tag.remove(); $<HTMLInputElement>("ag-in").value = t.text; $<HTMLFormElement>("ag-form").requestSubmit(); };
      t.tag.after(f);
    }
    if (st === "blocked" && ack) {   // 本地服务暂停了这条：停掉等待计时，不出 60 s 超时卡；解除后本地服务回 running 再计时
      showCard(blockedCard(ack), ack.reason === "estop" || ack.fix_action === "estop_clear");
      if (t.w === live) { watch.stop(); if (thinkEl?.isConnected) thinkEl.textContent = "已暂停：等待解除急停"; }
    }
    if (st === "running" && t.w === live && !watch.on) watch.start(performance.now());
  });
  const lostTurns = new Map<string, Turn>();
  function startLive(t: Turn) {
    const w = add(`<span class="lbl">思考中… 0 s</span><div class="tools"></div><div class="lbl mode"></div>`, "msg bot");
    t.w = w; t.t0 = performance.now(); turnUsage = null; timeEl = null;
    lastText = t.text; gate.begin(); watch.start(performance.now());
    thinkEl = w.firstElementChild as HTMLElement;
    tools = w.querySelector(".tools"); mode = w.querySelector(".mode"); planEl = null; live = w; streamed = "";
  }
  function endTurn(t: Turn) {
    const i = turns.indexOf(t); if (i >= 0) turns.splice(i, 1);
    if (live === t.w) { watch.stop(); live = null; }
    if (turns[0] && !turns[0].w) startLive(turns[0]);   // 下一条排队的消息接着显示「思考中」
  }
  $("ag-form").onsubmit = async e => {
    e.preventDefault();
    const inp = $<HTMLInputElement>("ag-in"), text = inp.value.trim();
    if (!text) return;
    inp.value = "";
    const id = newMsgId();
    const me = add(esc(text), "msg me");
    const tag = document.createElement("div"); tag.className = "lbl rcpt"; me.after(tag);
    const t: Turn = { id, text, me, tag, w: null, t0: performance.now() };
    turns.push(t); lostTurns.set(id, t);
    R.sent(id);
    if (turns[0] === t) startLive(t);
    try {
      const r = await call<any>("agent_ask", { text, msg_id: id });
      R.replied(id);
      if (!t.w) startLive(t);
      const w = t.w!;
      const txt = typeof r === "string" ? r : r?.text ?? "";
      if (txt.startsWith("（Agent 暂时用不了")) w.remove();   // 说明已在“重试 / 设置”卡里
      else w.firstElementChild!.outerHTML = `<div>${esc(txt).replace(/\n/g, "<br>")}</div>`;
      const u = parseUsage(r); if (u) { usageLog.push(u); turnUsage = u; }
      if (w.isConnected) { const d = document.createElement("div"); d.className = "lbl ag-time"; timeEl = d; d.textContent = fmtElapsed(elapsedOf(turnUsage, performance.now() - t.t0)); w.append(d); }
      // 步数用完：给「继续执行」。本地服务返回 continue 操作时用它，否则发一条「继续」
      if (/步数用完/.test(txt) || r?.continue) {
        const c = add(`<div class="act"><button class="btn pri">继续执行</button></div>`, "card cont-card");
        c.querySelector("button")!.onclick = () => {
          c.remove();
          if (r?.continue?.op) void call(r.continue.op, r.continue.args ?? {});
          else { $<HTMLInputElement>("ag-in").value = "继续"; $<HTMLFormElement>("ag-form").requestSubmit(); }
        };
      }
    }
    catch {   // 不静默丢：标「未送达」并给「重发」
      t.w?.remove(); R.failed(id);
    }
    // 不清 tools/mode：工具事件会比回答晚到（本地服务线程 → 事件循环），留给这条消息直到下一问
    finally { endTurn(t); }
  };
  // 进度推送带来新 blocker（如急停打断自整定）：Agent 面板立即发一条消息，修复按钮走统一 fix_action
  // 进度推送带来新 blocker：Agent 面板发一条消息（本地服务发 agent_notice 时以它为准，替换前端这条）；同一 code 未清除前去重
  const seenBlk = new Set<string>(), gateN = new NoticeGate(); let primed = false;
  const notes = new Map<string, HTMLElement>();
  function noteEl(code: string, body: string, fa: string | null | undefined, tag = "") {
    const other = resolveFix(fa);
    const html = `${body}${other ? `<div class="act"><button class="btn pri" ${other.kind === "run" ? "" : "disabled"} title="${esc(other.note ?? "")}">${esc(other.label)}</button>${tag ? `<span class="nb-note">${esc(tag)}</span>` : ""}</div>` : ""}`;
    let c = notes.get(code);
    if (c?.isConnected) c.innerHTML = html; else { c = add(html, "msg bot blk-note"); notes.set(code, c); }
    c.dataset.code = code;
    if (other?.kind === "run") c.querySelector("button")!.onclick = () => runAction(fa!, s => window.dispatchEvent(new CustomEvent("dz-goto", { detail: s })));
  }
  function onBlockers(bs: { code: string; message: string; fix_action?: string | null }[] = []) {
    bs = dropFlashBlockers(bs); const fresh = newBlockers(seenBlk, bs);
    gateN.sync(bs.map(b => b.code)); for (const k of [...notes.keys()]) if (!seenBlk.has(k)) notes.delete(k);
    if (!primed) { primed = true; bs.forEach(b => gateN.offer(b.code)); return; }   // 打开页面时已有的 blocker 不刷屏
    for (const b of fresh) if (b.code !== "params_not_saved" && gateN.offer(b.code)) noteEl(b.code, `<div><b>${esc(b.message)}</b></div>`, b.fix_action);
  }
  function onNotice(n: Notice) {
    if (!n?.blocker_code || isFlashNotice(n)) return;   // #63 未写入 Flash 只在保存参数旁
    if (n.blocker_code === "estop_cleared") return;   // 解除提示由主界面统一一张卡（estopbtn.clearedOnce），这里不重复
    if (n.blocker_code === "params_not_saved") return;   // 设计 v11：未保存只在页头出现一次
    const fallback = notes.get(n.blocker_code)?.dataset.src !== "notice" && notes.has(n.blocker_code);
    if (!gateN.offer(n.blocker_code) && !fallback) return;   // 未清除的同一 blocker 不重复
    seenBlk.add(n.blocker_code);
    const v = noticeView(n);
    noteEl(n.blocker_code, `<div><span class="sys-tag">系统提示</span> <b>${esc(v.head)}</b></div>${v.lines.map(l => `<p>${esc(l)}</p>`).join("")}`, n.fix_action, v.tag);
    notes.get(n.blocker_code)!.dataset.src = "notice";
  }


  // ---------------------------------------------------------------- 设置
  // 首次没配 Key 时自动弹一次；可随时从“大模型设置”再打开。表单没保存前“测试连接”用的是表单里的值。
  type Prov = { base_url: string; model: string; name: string };
  let provs: Record<string, Prov> = {}, prov = "deepseek";
  const fv = (id: string) => $<HTMLInputElement>(id).value.trim();
  const form = () => ({ provider: prov, base_url: fv("cfg-url"), model: fv("cfg-model"), api_key: fv("cfg-key") });
  const extra = () => ({ failover: $<HTMLInputElement>("cfg-fo").checked, local_model: $<HTMLSelectElement>("cfg-local").value,
    tool_mode: $<HTMLSelectElement>("cfg-tm").value, price_in: fv("cfg-pin") || null, price_out: fv("cfg-pout") || null });
  function olSt(cls: string, html: string) { const el = $("cfg-ol-st"); el.className = "cst " + cls; el.innerHTML = html; }
  function cfgSt(cls: string, html: string) { const el = $("cfg-st"); el.className = "cst " + cls; el.innerHTML = html; }
  function pickProv(k: string, fill: boolean) {
    prov = k;
    document.querySelectorAll<HTMLElement>("#cfg-provs .pv").forEach(b => b.setAttribute("aria-checked", String(b.dataset.k === k)));
    if (fill && provs[k]) { $<HTMLInputElement>("cfg-url").value = provs[k].base_url; $<HTMLInputElement>("cfg-model").value = provs[k].model; }
    cfgSt("", "尚未测试连接");
  }
  async function openCfg(first = false) {
    const c = await call("agent_config").catch(() => null);
    if (!c) return;
    provs = c.providers; firstRun = first;
    $("cfg-title").textContent = first ? "配置大模型（首次使用）" : "大模型设置";
    $("cfg-provs").innerHTML = Object.entries(provs).map(([k, p]) =>
      `<button type="button" class="pv" role="radio" data-k="${esc(k)}"><b>${esc(p.name)}</b><span class="mono">${esc(p.model || "手动填写")}</span></button>`).join("");
    document.querySelectorAll<HTMLElement>("#cfg-provs .pv").forEach(b => b.onclick = () => pickProv(b.dataset.k!, true));
    pickProv(c.provider, false);
    $<HTMLInputElement>("cfg-url").value = c.base_url; $<HTMLInputElement>("cfg-model").value = c.model; $<HTMLInputElement>("cfg-repo").value = c.repo ?? "";
    const key = $<HTMLInputElement>("cfg-key"); key.value = ""; key.type = "password";
    key.placeholder = c.has_key ? `已保存（${c.key_hint || "已隐藏"}），留空则不修改` : "sk-…（Ollama 本地可留空）";
    cfgSt(c.configured ? "ok" : "", c.configured ? `已配置 · ${esc(c.model)}` : "尚未测试连接");
    $("cfg-local").innerHTML = c.local_models.map((x: { model: string; size: string; note: string }) =>
      `<option value="${esc(x.model)}" ${x.model === c.local_model ? "selected" : ""}>${esc(x.model)} · ${esc(x.size)}</option>`).join("");
    const note = () => c.local_models.find((x: { model: string }) => x.model === $<HTMLSelectElement>("cfg-local").value)?.note ?? "";
    $("cfg-local").onchange = () => olSt("", esc(note()));
    $<HTMLInputElement>("cfg-fo").checked = c.failover !== false;
    $<HTMLSelectElement>("cfg-tm").value = c.tool_mode || "auto";
    $<HTMLInputElement>("cfg-pin").value = c.price_in ?? ""; $<HTMLInputElement>("cfg-pout").value = c.price_out ?? "";
    olSt("", `${esc(note())}。先点右边检查一次`);
    $<HTMLDialogElement>("cfg").show();   // 非模态：设置开着时急停按钮也必须点得到
  }
  $("ag-cfg").onclick = () => openCfg();
  $("cfg-eye").onclick = () => { const k = $<HTMLInputElement>("cfg-key"); k.type = k.type === "password" ? "text" : "password"; };
  ["cfg-url", "cfg-model", "cfg-key"].forEach(id => $(id).oninput = () => cfgSt("", "配置已修改，请重新测试连接"));
  $("cfg-test").onclick = async () => {
    const b = $<HTMLButtonElement>("cfg-test"); b.disabled = true; cfgSt("busy", `<span class="spin"></span>正在连接 ${esc(fv("cfg-url"))} …`);
    const r = await call("agent_config_test", { form: form() }).catch((e: Error) => ({ ok: false, message: String(e.message || e), fix: "" }));
    b.disabled = false;
    cfgSt(r.ok ? "ok" : "bad", r.ok
      ? `<b>连接成功</b> · ${esc(r.model)} · ${r.ms} ms${r.reply ? ` · 回复“${esc(r.reply)}”` : ""}`
      : `<b>连接失败</b> · ${esc(r.message)}${r.fix ? `<br><span class="fix">→ ${esc(r.fix)}</span>` : ""}`);
  };
  // 模型列表：GET {base_url}/models。首次配置时填好地址和 Key 后自动拉取；失败按 reason / fix_action 回退，预设默认模型只作最后兜底。逻辑见 llmcfg.ts
  let firstRun = false;
  const lister = modelLister({ call: (op, a) => call(op, a), el: id => $(id) as unknown as El, form, preset: () => provs[prov]?.model || "" });
  $("cfg-list").onclick = () => lister.load();
  $("cfg-retry").onclick = () => lister.load();
  ["cfg-url", "cfg-key"].forEach(id => $(id).addEventListener("change", () => { if (firstRun && fv("cfg-url")) lister.auto(); }));
  $("cfg-ol").onclick = async () => {
    const b = $<HTMLButtonElement>("cfg-ol"), want = $<HTMLSelectElement>("cfg-local").value;
    b.disabled = true; olSt("busy", `<span class="spin"></span>检查本机 Ollama…`);
    const r = await call("agent_ollama", { action: "check" }).catch(() => ({ ok: false, message: "本地服务没响应" }));
    if (!r.ok) { b.disabled = false; return olSt("bad", `<b>没找到 Ollama</b> · ${esc(r.message)}${r.fix ? `<br><span class="fix">→ ${esc(r.fix)}</span>` : ""}`); }
    if (!r.models.some((n: string) => n === want || n === want + ":latest")) {
      olSt("busy", `<span class="spin"></span>Ollama 在跑；正在拉 ${esc(want)}（几个 GB，视网速要几分钟）…`);
      const p = await call("agent_ollama", { action: "pull", model: want }).catch(() => ({ ok: false, status: "失败" }));
      if (!p.ok) { b.disabled = false; return olSt("bad", `<b>拉取没成功</b> · ${esc(p.status || p.message || "")}`); }
    }
    b.disabled = false; olSt("ok", `<b>本地就绪</b> · ${esc(want)} · 云端连不上时自动切过去`);
  };
  // 点框外关闭（非模态 dialog 没有 backdrop，所以监听文档点击）
  document.addEventListener("pointerdown", (e) => {
    const d = $<HTMLDialogElement>("cfg");
    if (d.open && !d.contains(e.target as Node) && !(e.target as Element).closest?.("#ag-cfg,[data-r=cfg]")) d.close("cancel");
  });
  $<HTMLDialogElement>("cfg").onclose = () => {
    sessionStorage.setItem("dz-cfg-seen", "1");
    if ($<HTMLDialogElement>("cfg").returnValue !== "save") return;
    const done = add(`<span class="lbl">大模型</span>保存中…`, "msg bot");
    call("agent_config", { set: { ...form(), ...extra(), repo: fv("cfg-repo") } })
      .then(() => { done.innerHTML = `<span class="lbl">大模型</span>已保存：${esc(fv("cfg-model"))}。下一句话起用它回答。`; })
      .catch(() => done.remove());
  };
  // 首启不弹窗（会挡住项目/调参等不依赖 Agent 的功能）：在 Agent 栏放一张空状态卡，用户想用时再点设置
  call("agent_config").then(c => {
    if (c?.configured) badge(/ollama|localhost|127\.0\.0\.1|:11434/i.test(`${c.provider} ${c.base_url}`) ? "local" : "cloud");
    if (!c || c.configured) return;
    showSetup(true);
  }).catch(() => {});

  // 未配置模型：右栏只放这一张（说明 + 去配置）；建议卡自己标来源（来自规则引擎 / 来自模型）
  function showSetup(on: boolean) {
    document.querySelectorAll(".setup-card").forEach(e => e.remove());
    const inp = $<HTMLInputElement>("ag-in");
    inp.dataset.ph ??= inp.placeholder;
    inp.disabled = on; $<HTMLButtonElement>("ag-send").disabled = on; inp.placeholder = on ? "配置模型后可用" : inp.dataset.ph;
    if (!on) return;
    const card = add(`<div class="ag-setup"><b>Agent 还没有大模型</b><p>配置后可以一句话建工程、读题、解释波形。调参、示波、评分、急停和规则引擎建议不依赖它。</p>
      <wa-button size="small" appearance="outlined" data-r="cfg">去配置</wa-button></div>`, "card setup-card");
    card.querySelector<HTMLElement>("[data-r=cfg]")!.onclick = () => openCfg(true);
  }
  let lastAgentState: string | null = null;
  function onAgentState(m: any) {   // status.agent.state 驱动（fix_action=configure_model → 去配置）
    const st = agentState(m); if (!st || st === lastAgentState) return; lastAgentState = st;
    showSetup(st === "unconfigured" || m?.[AGENT_F.obj]?.[AGENT_F.fix] === AGENT_F.cfgFix);
  }

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

  // ---------------------------------------------------------------- 流式 / 用量 / 断线
  let live: HTMLElement | null = null, streamed = "";
  function onDelta(t: string) {      // 流式：边收边显示；工具调用后的新一段从头接
    if (!live) return;
    streamed += t;
    const first = live.firstElementChild as HTMLElement;
    if (first.classList.contains("lbl")) first.outerHTML = `<div class="stream"></div>`;
    (live.firstElementChild as HTMLElement).innerHTML = esc(streamed).replace(/\n/g, "<br>");
  }
  // 云端 / 本地模型标识：断网自动切本地（agent_mode.fallback）或直接配 Ollama 时显示「本地模型」
  function badge(k: "local" | "cloud") {
    const b = document.getElementById("ag-badge"); if (!b) return;
    b.hidden = false; b.dataset.k = k; b.textContent = k === "local" ? "本地模型" : "云端模型";
  }
  window.addEventListener("offline", () => badge("local"));
  function modeLine(m: Msg) {
    if (!mode) return;
    if (m.type === "agent_mode") {
      mode.dataset.base = m.mode === "local" ? `本地 ${m.name}${m.fallback ? " · 云端连不上，已自动切到本地" : ""}` : `大模型 ${m.name}`;
      mode.classList.toggle("local", m.mode === "local");
      badge(m.mode === "local" ? "local" : "cloud");
    }
    if (m.type === "agent_usage") { const u = parseUsage(m); if (u) { usageLog.push(u); turnUsage = u; if (timeEl && u.elapsed_ms != null) timeEl.textContent = fmtElapsed(u.elapsed_ms); } }   // agent_usage 事件（llm-ua e697b86）可能晚于回复到达：到了就用 elapsed_ms 改写本轮耗时   // 只存，不显示 token
    if (m.type === "agent_retry") mode.dataset.use = ` · 服务忙，第 ${m.attempt} 次重试…`;
    if (m.type === "agent_toolmode") mode.dataset.use = ` · ${m.model} 不支持原生工具调用，已改 JSON 兜底`;
    mode.textContent = (mode.dataset.base ?? "") + (mode.dataset.use ?? "");
  }
  function renderDown(m: Msg) {      // 没模型 / 连不上：说清楚、其它功能照常，给“重试 / 设置”
    const c = add(`<div class="down"><span class="dot"></span><div><b>Agent 暂时用不了</b><p>${esc(m.message)}</p>
      ${m.fix ? `<p class="fix">${esc(m.fix)}</p>` : ""}<p class="ok">调参、示波、急停、阶跃测试、评分页都不依赖 Agent，照常能用。</p></div></div>
      <div class="act"><button class="btn" data-r="cfg">大模型设置</button><button class="btn pri" data-r="retry">重试</button></div>`, "card down-card");
    c.querySelector<HTMLElement>("[data-r=cfg]")!.onclick = () => openCfg();
    c.querySelector<HTMLElement>("[data-r=retry]")!.onclick = () => { c.remove(); $<HTMLInputElement>("ag-in").value = m.text; $<HTMLFormElement>("ag-form").requestSubmit(); };
  }

  // llm_retry：同一轮只一条，原地更新
  let retryEl: HTMLElement | null = null;
  function onRetry(m: any) {
    const html = `<span class="lbl">大模型</span>${esc(retryText(toRetry(m)))}<div class="act"><button class="btn sm">${LOCAL_LABEL}</button></div>`;
    if (retryEl?.isConnected) retryEl.innerHTML = html; else retryEl = add(html, "msg bot llm-retry");
    retryEl.querySelector("button")!.onclick = () => {
      const fa = toRetry(m).fix, f = resolveFix(fa);
      if (fa && f?.kind === "run") return runAction(fa, s => window.dispatchEvent(new CustomEvent("dz-goto", { detail: s })));
      document.getElementById("ag-cfg")?.click();   // 本地服务没给可执行的 fix_action：打开模型设置（本地 Ollama 一栏）
      document.getElementById("cfg-ol")?.scrollIntoView({ block: "nearest" });
    };
  }
  return {
    onMsg(m: Msg) {
      if (m.type === "status") onAgentState(m);
      if (isRetry(m)) onRetry(m);
      else if (retryEl && clearsRetry(m.type)) { retryEl.remove(); retryEl = null; }
      if (typeof m.type === "string" && m.type.startsWith("agent_")) watch.touch(performance.now());
      if (m.type === "agent_error") { gate.error(); watch.stop(); live?.remove(); showCard(errorCard(m as any)); }
      if (m.type === "agent_delta") onDelta(m.text);
      if (m.type === "agent_ack") R.ack(m as any);
      if (m.type === "agent_notice") onNotice(m as any);
      if (m.type === "agent_tool") streamed = "";
      if (["agent_mode", "agent_usage", "agent_retry", "agent_toolmode"].includes(m.type)) modeLine(m);
      if (m.type === "agent_unreachable" && gate.allowUnreachable()) renderDown(m);   // 同一轮已出 agent_error 卡：忽略随后的 agent_unreachable
      if (m.type === "agent_plan") renderPlan(m);
      if (m.type === "agent_tune_pending") renderTune(m);
      if (m.type === "agent_journal") renderJournal(m.items);
      if (m.type === "change") renderChange(m);
      if (m.type === "agent_action" && m.tool === "iterate_apply_best") iterPointer();
      if (m.type === "agent_action" && m.tool !== "iterate_apply_best") renderAction(m);   // “采用最好参数”只在调参页结果卡出一次（main.ts #it-card）
      if (m.type === "tune_round") renderRound(m);
      if (m.type === "sweep_result") renderSweep(m);
      if (m.type === "agent_tool" && tools) tools.insertAdjacentHTML("beforeend", `<span class="tool ${m.ok ? "" : "bad"}">${esc(m.name)}</span>`);
    },
    add, onBlockers,
    // #41：急停解除——删掉 estop blocker 消息与 blocked 卡，「等待解除急停」改成中性文案
    resolveEstop() {
      for (const [k, el] of [...notes]) if (k === "estop") { el.remove(); notes.delete(k); seenBlk.delete(k); }
      feed.querySelectorAll("[data-estop-blocker], .blk-note[data-code=estop]").forEach(e => e.remove());
      if (thinkEl?.isConnected && /等待解除急停/.test(thinkEl.textContent || "")) thinkEl.textContent = "急停已解除，等待本地服务继续";
    },
  };
}

// 结果卡只在调参页出一张；Agent 流里只放一行指路（不是第二张卡），不在调参页时能一键过去
function iterPointer(): void {
  const box = document.getElementById("props"); if (!box) return;
  box.querySelector(".it-ptr")?.remove();
  const d = document.createElement("div"); d.className = "msg bot it-ptr";
  d.append("自动迭代已结束，结果卡在调参页。");
  const b = document.createElement("button"); b.type = "button"; b.className = "btn sm"; b.textContent = "去调参页查看";
  b.onclick = () => (document.querySelector('#steps [data-step="调参"]') as HTMLButtonElement | null)?.click();
  d.append(" ", b); box.append(d); d.scrollIntoView({ block: "nearest" });
}
