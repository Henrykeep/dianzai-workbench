// 内置 Agent 面板（docs/18）：离线阶跃分析、对话、文件改动卡片（diff → 确认 → 门禁 → git 提交 / 回滚）、大模型设置
import { Msg } from "./ws";

type Call = <T = any>(op: string, args?: Record<string, unknown>) => Promise<T>;
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const n = (v: number | null | undefined, d = 2, u = "") => v == null ? "—" : `${(+v).toFixed(d)}${u}`;

export const AGENT_IDLE = `<div class="hint">
  <b>分析阶跃</b>：给一个设定值阶跃后点它，离线算超调 / 上升 / 调节时间 / 振荡，并给调参建议。<br>
  <b>问 Agent</b>：没填 Key 也能问，由<b>离线规则助手</b>回答（只认常见问题）；在 ⚙ 里填大模型（DeepSeek、通义千问、本地 Ollama）对话更灵活。<br>
  Agent 只能<b>提议</b>：参数改动要你点“采纳”才下发；文件改动先给 diff，确认后跑 <code>make check</code> 通过才 git 提交，随时可回滚。它碰不到急停。
  <div class="chips">${["超调好大，怎么办", "帮我把速度环调好", "为什么左轮比右轮慢", "仿真里调好了，可以上车了吗"]
    .map(q => `<button type="button" class="chip" data-q="${q}">${q}</button>`).join("")}</div></div>`;

export function initAgent(call: Call) {
  const feed = $("props");
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
      e.querySelector("button")?.addEventListener("click", ev => { (ev.target as HTMLButtonElement).disabled = true; call("tune_propose", { changes: h.changes, reason: h.text }); });
      hs.append(e);
    });
    d.querySelectorAll<HTMLSelectElement>("select").forEach(s => s.onchange = () => {
      const v = (k: string) => d.querySelector<HTMLSelectElement>(`select[data-k=${k}]`)!.value;
      d.remove(); tune(v("y"), v("sp"));
    });
  }
  $("ag-tune").onclick = () => tune();

  // ---------------------------------------------------------------- 文件改动卡片
  const cards = new Map<number, HTMLElement>();
  function renderChange(c: Msg) {
    let d = cards.get(c.id);
    if (!d) { d = add(""); cards.set(c.id, d); }
    const diff = esc(c.diff).split("\n").map(l => `<span class="${l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : ""}">${l}</span>`).join("\n");
    const st: Record<string, string> = { pending: "待确认", applying: "门禁运行中…", committed: "已提交", failed: "未通过，已还原", rejected: "已拒绝", reverted: "已回滚" };
    d.className = "card change " + c.status;
    d.innerHTML = `<div class="hd"><span class="dotk file"></span><span class="t">${esc(c.title)}</span><span class="lbl">${esc(c.layer)} · ${esc(c.source)}</span></div>
      <p>${esc(c.reason)}</p><pre class="diff">${diff}</pre>
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
  const TOOL_CN: Record<string, string> = { flash: "烧录固件", erase: "擦除", mem_write: "写内存", run_step_test: "实机阶跃实验", rollback_best: "回滚到最好参数" };
  function renderAction(a: Msg) {
    const pv = a.preview ? `<pre class="log">${esc(JSON.stringify(a.preview, null, 1))}</pre>` : "";
    const d = add(`<div class="hd"><span class="dotk file"></span><span class="t">需要你确认：${esc(TOOL_CN[a.tool] ?? a.tool)}</span><span class="lbl">风险 human${a.sim ? " · 仿真" : " · 实机"}</span></div>
      ${pv}<div class="act"><button class="btn pri" data-a="1">执行</button><button class="btn" data-a="0">拒绝</button></div>`, "card change pending");
    d.querySelectorAll<HTMLButtonElement>("button[data-a]").forEach(b => b.onclick = () => {
      d.querySelectorAll("button").forEach(x => (x as HTMLButtonElement).disabled = true);
      call("agent_action_decide", { id: a.id, accept: b.dataset.a === "1" })
        .then(r => { d.querySelector(".act")!.innerHTML = `<span class="lbl ok-t">${r.status === "done" ? "已执行" : "已拒绝"}</span>`; },
              () => { d.querySelector(".act")!.innerHTML = `<span class="lbl">执行失败（见提示）</span>`; });
    });
  }
  const VERDICT: Record<string, string> = { continue: "继续", done: "达标，结束", rollback: "变差，建议回滚到最好一轮", stop: "停止" };
  function renderRound(m: Msg) {
    const v = m.verdict, k = m.metrics;
    add(`<div class="hd"><span class="dotk"></span><span class="t">第 ${v.round} 轮阶跃：${esc(VERDICT[v.action] ?? v.action)}</span><span class="lbl">程序判定</span></div>
      <p>超调 ${n(k.overshoot_pct, 1, "%")} · 调节 ${n(k.settling_s, 3, " s")} · 稳态误差 ${n(k.sse_pct, 1, "%")} · 振荡 ${k.oscillations} · 评分 ${v.score}</p>
      ${v.best ? `<div class="lbl">最好：第 ${v.best.round} 轮 ${esc(JSON.stringify(v.best.gains))}${v.rolled_back ? "（仿真已自动回滚）" : ""}</div>` : ""}
      ${v.reason ? `<div class="lbl">${esc(v.reason)}</div>` : ""}`);
  }
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
    tools = w.querySelector(".tools"); mode = w.querySelector(".mode");
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

  return {
    onMsg(m: Msg) {
      if (m.type === "change") renderChange(m);
      if (m.type === "agent_action") renderAction(m);
      if (m.type === "tune_round") renderRound(m);
      if (m.type === "agent_mode" && mode) mode.textContent = m.mode === "offline" ? `${m.name} · 无需联网${m.fallback ? "（大模型连不上，已自动切换）" : ""}` : `大模型 ${m.name}`;
      if (m.type === "agent_tool" && tools) tools.insertAdjacentHTML("beforeend", `<span class="tool ${m.ok ? "" : "bad"}">${esc(m.name)}</span>`);
    },
    add,
  };
}
