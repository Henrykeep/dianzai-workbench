// 标定向导（产品逻辑重组 4）：极性 → 循迹黑白 → 视觉像素表 → FOC 对齐 → IMU 零偏。
// 每一步 = 准备清单 + 录几段遥测（只读，侧车 wave_measure / polarity_check）+ 算出建议值；
// 建议值不直接写板子：点“提议写入”走 propose{source:"标定"}，在本页的提议卡上确认后才下发（同一张提议卡、同一个 proposal_decide）。
// 清单内容整理自 MICU-auto-embedded templates/auto-embedded/refs/（control-loop-sign-debug.md、foc-calibration-checklist.md、
// attitude-init-single-frame.md）；“先过准备清单再开录”的形态参考 PID_Helper IdentificationPrepPanel.tsx。代码自写。
type Call = <T = any>(op: string, a?: Record<string, unknown>) => Promise<T>;
type P = { name: string; desc?: string };
type Slot = { key: string; label: string };          // 一段录制：录哪个状态（白底 / 黑线 / 静止…）
type Out = { key: string; label: string; calc: (m: Record<string, number>) => number; hint: string };
export type WizStep = { id: string; title: string; check: string[]; chans: string[]; slots: Slot[]; outs: Out[]; secs: number; note?: string };

const avg = (m: Record<string, number>, k: string) => m[k];
export const WIZ: WizStep[] = [
  { id: "line", title: "循迹黑白", secs: 2, chans: ["循迹通道"],
    check: ["传感器离地高度与比赛时一致（高度变，读数全变）", "场地灯光与比赛时一致，避免阳光直射", "先放白底，再放黑线正中，各录一段"],
    slots: [{ key: "w", label: "白底" }, { key: "b", label: "黑线" }],
    outs: [{ key: "thr", label: "阈值", calc: m => (avg(m, "w|0") + avg(m, "b|0")) / 2, hint: "黑白读数的中点；固件 line_sensor 用归一化 on_thr 时填 0.5，用原始阈值时填这个" }] },
  { id: "foc", title: "FOC 对齐", secs: 2, chans: ["编码器原始角"],
    check: ["电流采样零偏：电机不通电时标（ia+ib+ic≈0 自检）", "相序：正 iq 时电机朝约定正方向转、编码器读数同向增大；不符只在最底层翻一次符号", "极对数：开环慢转一机械圈数电周期，或查手册", "强制对齐：施加电角度 0 的电压矢量（id>0、iq=0），转子停稳后录一段编码器原始角"],
    slots: [{ key: "a", label: "对齐后静止" }],
    outs: [{ key: "zero", label: "零电角度", calc: m => avg(m, "a|0"), hint: "固件 foc_set_calibration 的零点；方向和极对数看上电对齐结果（foc_align）" }],
    note: "固件 foc 模块上电时自己做对齐；这里是没跑自动对齐、或要核对它时用。" },
  { id: "imu", title: "IMU 零偏", secs: 3, chans: ["gx", "gy", "gz"],
    check: ["板子静止放平，不碰桌子（录的时候波动大会提示）", "上电预热 1 分钟后再录，温漂大的芯片要周期重标", "零偏只管陀螺；yaw 没有磁力计时不可观测，这一步定不了"],
    slots: [{ key: "s", label: "静止" }],
    outs: [0, 1, 2].map(i => ({ key: `b${i}`, label: `零偏 ${"xyz"[i]}`, calc: (m: Record<string, number>) => avg(m, `s|${i}`), hint: "静止平均值，固件里 读数 − 零偏" })) },
];

export function initCalWiz(call: Call, fields: () => string[], params: () => P[], toast: (t: string) => void) {
  const root = document.getElementById("calwiz"); if (!root) return;
  const opt = (xs: string[], sel = "") => `<option value="">—</option>` + xs.map(x => `<option${x === sel ? " selected" : ""}>${x}</option>`).join("");
  const box = (h: string) => { const d = document.createElement("div"); d.className = "wz"; d.innerHTML = h; root.append(d); return d; };
  const rec = async (f: string, secs: number) => { await new Promise(r => setTimeout(r, secs * 1000)); return call<any>("wave_measure", { field: f, seconds: secs }); };
  const render = () => {
    root.innerHTML = "";
    const fs = fields(), ps = params().map(p => p.name);
    // 第 0 步：极性（先方向再参数）
    const pol = box(`<h4>0 · 极性<span class="hint">Kp/限幅是放大器，修不了方向错——先验方向再调参数</span></h4>
      <ul><li>手推：执行器不出力，人把被控量往约定 + 方向推，录 3 s</li><li>点动：开环小幅 +u / 0 / −u / 0，录 3 s</li></ul>
      <div class="row">被控量 y<select class="in" data-c="y">${opt(fs)}</select> 误差 e<select class="in" data-c="e">${opt(fs)}</select> 控制量 u<select class="in" data-c="u">${opt(fs)}</select></div>
      <div class="row"><button class="btn" data-p="push">录手推 3 s</button><button class="btn" data-p="jog">录点动 3 s</button><span class="out"></span></div>`);
    const signs: Record<string, number> = {};
    pol.querySelectorAll<HTMLButtonElement>("[data-p]").forEach(b => b.onclick = async () => {
      const g = (k: string) => pol.querySelector<HTMLSelectElement>(`[data-c="${k}"]`)!.value || undefined;
      if (!g("y")) return toast("先选被控量 y");
      b.disabled = true; const o = pol.querySelector(".out")!; o.textContent = "录制中…";
      try {
        await new Promise(r => setTimeout(r, 3000));
        const r = await call<any>("polarity_check", { step: b.dataset.p, y: g("y"), e: g("e"), u: g("u"), seconds: 3, signs: { ...signs } });
        for (const k of ["sensor", "err", "ctrl", "act"]) if (r[k]?.sign) signs[k] = r[k].sign;
        const v = r.verdict;
        o.textContent = Object.entries(r).filter(([k]) => k !== "verdict").map(([k, x]: any) => `${k}: ${x.sign ? (x.sign > 0 ? "+" : "−") : "?"}${x.why ? "（" + x.why + "）" : ""}`).join("  ") + (v ? ` → ${v.msg}` : "");
      } catch { o.textContent = ""; } finally { b.disabled = false; }
    });
    WIZ.forEach((s, i) => {
      const d = box(`<h4>${i + 1} · ${s.title}</h4>${s.note ? `<p class="hint">${s.note}</p>` : ""}
        <ul>${s.check.map(c => `<li><label><input type="checkbox"> ${c}</label></li>`).join("")}</ul>
        <div class="row">${s.chans.map((c, k) => `${c}<select class="in" data-k="${k}">${opt(fs)}</select>`).join(" ")}</div>
        <div class="row">${s.slots.map(sl => `<button class="btn" data-s="${sl.key}">录${sl.label} ${s.secs} s</button>`).join("")}<span class="out mono"></span></div>
        <div class="res"></div>`);
      const got: Record<string, number> = {}, o = d.querySelector(".out")!, res = d.querySelector<HTMLElement>(".res")!;
      d.querySelectorAll<HTMLButtonElement>("[data-s]").forEach(b => b.onclick = async () => {
        const ch = [...d.querySelectorAll<HTMLSelectElement>("[data-k]")].map(x => x.value);
        if (!ch.some(Boolean)) return toast(`先选${s.chans[0]}`);
        if ([...d.querySelectorAll<HTMLInputElement>("ul input")].some(x => !x.checked) && !confirm("准备清单还没全勾，照样录？")) return;
        b.disabled = true; o.textContent = "录制中…";
        try {
          const warn: string[] = [];
          for (let k = 0; k < ch.length; k++) if (ch[k]) {
            const r = await (k ? call<any>("wave_measure", { field: ch[k], seconds: s.secs }) : rec(ch[k], s.secs));
            if (!r.ok) { warn.push(`${ch[k]}：${r.reason}`); continue; }
            got[`${b.dataset.s}|${k}`] = r.avg;
            if (r.pp > 0.2 * Math.max(1e-9, Math.abs(r.avg)) && s.id !== "line") warn.push(`${ch[k]} 波动 ${r.pp.toPrecision(3)}，不像静止`);
          }
          o.textContent = Object.entries(got).map(([k, v]) => `${k}=${v.toPrecision(5)}`).join("  ") + (warn.length ? "  注意：" + warn.join("；") : "");
          showRes();
        } finally { b.disabled = false; }
      });
      const showRes = () => {
        const rows = s.outs.map(x => { let v = NaN; try { v = x.calc(got); } catch { /* 缺段 */ } return { x, v }; }).filter(r => Number.isFinite(r.v));
        res.innerHTML = rows.map(r => `<div class="row"><span>${r.x.label} = <b class="mono">${r.v.toPrecision(5)}</b></span> 写到参数<select class="in" data-o="${r.x.key}">${opt(ps)}</select><span class="hint">${r.x.hint}</span></div>`).join("")
          + (rows.length ? `<div class="row"><button class="btn pri" data-w>提议写入（在下面确认后才下发）</button></div>` : "");
        res.querySelector<HTMLButtonElement>("[data-w]")?.addEventListener("click", async () => {
          const ch: Record<string, number> = {};
          rows.forEach(r => { const p = res.querySelector<HTMLSelectElement>(`[data-o="${r.x.key}"]`)!.value; if (p) ch[p] = r.v; });
          if (!Object.keys(ch).length) return toast("先选择写入哪个参数（没有对应参数就先在 app.yaml 里加）");
          await call("propose", { changes: ch, source: "标定", reason: `标定向导 · ${s.title}` });
        });
      };
    });
    // 视觉：像素 → 物理量分段线性表（固件 vis_calib_init，点写进 app.yaml，不是单个参数）
    const vis = box(`<h4>${WIZ.length + 1} · 视觉像素表<span class="hint">vis_calib：2 个以上 (像素, 物理量) 点，像素严格递增</span></h4>
      <ul><li>相机固定好高度和角度（动了就重标）</li><li>目标放到已知距离 / 位置，录像素值，填对应物理量</li></ul>
      <div class="row">像素通道<select class="in" data-v>${opt(fs)}</select> 物理量<input class="in" type="number" step="any" style="width:6em" data-q><button class="btn" data-a>录 1 s 加一点</button></div>
      <pre class="mono out"></pre>`);
    const pts: [number, number][] = [];
    vis.querySelector<HTMLButtonElement>("[data-a]")!.onclick = async () => {
      const f = vis.querySelector<HTMLSelectElement>("[data-v]")!.value, q = vis.querySelector<HTMLInputElement>("[data-q]")!.value;
      if (!f || q === "") return toast("选像素通道并填物理量");
      const r = await rec(f, 1); if (!r.ok) return toast(r.reason);
      pts.push([r.avg, +q]); pts.sort((a, b) => a[0] - b[0]);
      vis.querySelector(".out")!.textContent = `# 贴进固件 vis_calib_init 的两张表（${pts.length} 点）\nfloat px[]  = {${pts.map(p => p[0].toFixed(1)).join(", ")}};\nfloat val[] = {${pts.map(p => p[1]).join(", ")}};`;
    };
  };
  render();
  return { refresh: render };
}
