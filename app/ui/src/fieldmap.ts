// 本地服务事件字段名 → 界面内部形状的唯一映射点（见 docs/dev/events.md）。字段改名只改这里的常量，
// 界面其余代码只用 toRetry / toSsErr / passBasis 的返回值。
export const RETRY_F = { type: "llm_retry", attempt: "attempt", total: "max", wait: "wait_s", fix: "fix_action", msg: "message_zh", localFix: "switch_local_model" } as const;
// “采用最好参数”卡 args.ss_err / preview.ss_err：{measured, unit, band:{limit, unit, item, source}, inside, note_zh}
export const SSERR_F = { obj: "ss_err", measured: "measured", unit: "unit", band: "band", limit: "limit", bUnit: "unit", item: "item", source: "source", inside: "inside", note: "note_zh" } as const;
// 达标口径（可选，后端尚未推）：卡 args/preview 或 iterate.stopped 上的 pass_basis
export const PASS_BASIS_F = "pass_basis";
export type Retry = { attempt: number; total: number; wait?: number; fix?: string; msg?: string };
export type SsErr = { measured: number; unit: string; limit?: number; limitUnit: string; item: string; source: string; inside: boolean | null; note: string };
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const str = (v: unknown) => (typeof v === "string" ? v : "");
export const isRetry = (m: any) => m?.type === RETRY_F.type;
export function toRetry(m: any): Retry {
  return { attempt: num(m?.[RETRY_F.attempt]) ?? 1, total: num(m?.[RETRY_F.total]) ?? 1, wait: num(m?.[RETRY_F.wait]), fix: m?.[RETRY_F.fix] || undefined, msg: str(m?.[RETRY_F.msg]) || undefined };
}
// 从卡（agent_action）或已存的结果里取 ss_err；没有或缺实测值 → null
export function toSsErr(src: any): SsErr | null {
  const o = src?.args?.[SSERR_F.obj] ?? src?.preview?.[SSERR_F.obj] ?? src?.[SSERR_F.obj];
  const v = num(o?.[SSERR_F.measured]); if (v == null) return null;
  const b = o[SSERR_F.band] ?? {};
  const ins = o[SSERR_F.inside];
  return { measured: v, unit: str(o[SSERR_F.unit]), limit: num(b[SSERR_F.limit]), limitUnit: str(b[SSERR_F.bUnit]), item: str(b[SSERR_F.item]), source: str(b[SSERR_F.source]), inside: typeof ins === "boolean" ? ins : null, note: str(o[SSERR_F.note]) };
}
export const passBasis = (src: any): string => str(src?.[PASS_BASIS_F] ?? src?.args?.[PASS_BASIS_F] ?? src?.preview?.[PASS_BASIS_F] ?? src?.args?.ss_err?.[PASS_BASIS_F] ?? src?.preview?.ss_err?.[PASS_BASIS_F] ?? src?.ss_err?.[PASS_BASIS_F] ?? src?.card?.args?.[PASS_BASIS_F]);
// 第 0 轮（初值）指标：后端补字段前从 iterate.round(iter=0) 取；字段名定稿后改这里
export const ROUND0_F = { obj: "round0", metrics: "metrics" } as const;
export const METRIC_F: [key: string, zh: string, unit: string][] = [["ss_err_pct", "稳态误差", "%"], ["overshoot_pct", "超调", "%"], ["settle_ms", "调节时间", "ms"], ["rise_ms", "上升时间", "ms"]];
export const roundMetrics = (m: any): Record<string, number> | null => { const o = m?.[ROUND0_F.metrics] ?? m; return o && METRIC_F.some(([k]) => typeof o[k] === "number") ? o : null; };
// 右栏 Agent 状态：status.agent.state ∈ ready | unconfigured | busy（fix_action configure_model）；后端没给时退回 agent_config.configured
export const AGENT_F = { obj: "agent", state: "state", fix: "fix_action", cfgFix: "configure_model" } as const;
export type AgentState = "ready" | "unconfigured" | "busy";
export function agentState(status: any): AgentState | null { const v = status?.[AGENT_F.obj]?.[AGENT_F.state]; return v === "ready" || v === "unconfigured" || v === "busy" ? v : null; }
// 建议卡来源：rule / rules / 规则 → 规则引擎；llm / model / agent → 模型
export const SOURCE_F = "source";
export function sourceLabel(m: any): string {
  const s = String(m?.[SOURCE_F] ?? m?.preview?.[SOURCE_F] ?? m?.args?.[SOURCE_F] ?? "").toLowerCase();
  const zh = str(m?.source_zh ?? m?.preview?.source_zh ?? m?.args?.source_zh);
  if (s === "rule_engine") return zh && zh !== "规则引擎" ? `来自规则引擎 · ${zh}` : "来自规则引擎";
  if (s === "llm") return "来自模型";
  return /rule|规则/.test(s) ? "来自规则引擎" : /llm|model|agent|模型/.test(s) ? "来自模型" : "";
}
// 卡结论（后端定稿前可选）：verdict ∈ pass|fail|unknown + verdict_zh。结论只显示 verdict_zh；缺 verdict → 中性「未判定」，绝不当作达标
export const VERDICT_F = { v: "verdict", zh: "verdict_zh" } as const;
export type Verdict = { v: "pass" | "fail" | "unknown"; zh: string; warn?: string };
// 降幅测试（阶跃按缩小幅度做，没验题面幅度）：绝不显示「通过」，原文当警告。字段名暂定
export const DOWNSCALE_F = { flag: ["amp_reduced"], zh: ["warning_zh"], partial: "partial" } as const;   // #129 定稿
export const DOWNSCALE_ZH = "未验题面幅度";
export function toVerdict(src: any): Verdict {
  const pick = (k: string) => src?.args?.[k] ?? src?.preview?.[k] ?? src?.[k];
  const v = pick(VERDICT_F.v), zh = str(pick(VERDICT_F.zh));
  const dzh = DOWNSCALE_F.zh.map(k => str(pick(k))).find(Boolean) ?? "", down = v === DOWNSCALE_F.partial || DOWNSCALE_F.flag.some(k => pick(k) === true) || !!dzh || zh.includes(DOWNSCALE_ZH);
  if (down) { const w = dzh || (zh.includes(DOWNSCALE_ZH) ? zh : DOWNSCALE_ZH); return { v: v === "fail" ? "fail" : "unknown", zh: zh && zh !== w ? zh : DOWNSCALE_ZH, warn: w }; }
  if (v === "pass" || v === "fail" || v === "unknown") return { v, zh: zh || VERDICT_ZH[v] };
  return { v: "unknown", zh: "未判定" };
}
// 换示例：op project_switch_example {example}；回 project_forked {example, project, path, message_zh}
export const SWITCH_EX_OP = "project_switch_example";
export const FORKED_F = { type: "project_forked", example: "example", project: "project", msg: "message_zh", alts: "examples" } as const;
// 卡 args.compare / preview.compare（events.md）：{round0:{iter, metrics:[{key,value,unit}]}, best:{…}, unchanged, note_zh}；iterate.stopped 顶层也带 round0
export const COMPARE_F = { obj: "compare", r0: "round0", best: "best", metrics: "metrics", unchanged: "unchanged", note: "note_zh" } as const;
export type MetricV = { key: string; value: number; unit: string };
export type CompareRaw = { round0: MetricV[]; best: MetricV[]; unchanged: boolean; note: string };
export const METRIC_ZH: Record<string, string> = { ss_err_pct: "稳态误差", ss_err: "稳态误差", sse_pct: "稳态误差", settling_s: "调节时间", settle_s: "调节时间", rise_s: "上升时间", sse: "稳态误差", overshoot_pct: "超调", overshoot: "超调", settle_ms: "调节时间", settling: "调节时间", iae: "误差积分 IAE", rise_ms: "上升时间" };
const mlist = (o: any): MetricV[] => (Array.isArray(o?.[COMPARE_F.metrics]) ? o[COMPARE_F.metrics] : []).filter((x: any) => typeof x?.value === "number").map((x: any) => ({ key: str(x.key), value: x.value, unit: str(x.unit) }));
export function toCompare(src: any): CompareRaw | null {
  const c = src?.args?.[COMPARE_F.obj] ?? src?.preview?.[COMPARE_F.obj] ?? src?.[COMPARE_F.obj] ?? (src?.[COMPARE_F.r0] ? { round0: src[COMPARE_F.r0], best: src.best } : null);
  if (!c) return null;
  const r0 = mlist(c[COMPARE_F.r0]), b = mlist(c[COMPARE_F.best]);
  if (!r0.length && !b.length && !c[COMPARE_F.unchanged]) return null;
  return { round0: r0, best: b, unchanged: c[COMPARE_F.unchanged] === true, note: str(c[COMPARE_F.note]) };
}
// r9p6 通用化：指标单位按后缀推断（任何题目都适用，不认识的单位原样显示，不猜换算）
export const unitOfKey = (k: string): string => METRIC_F.find(m => m[0] === k)?.[2] ?? (/_pct$/.test(k) ? "%" : /_ms$/.test(k) ? "ms" : /_s$/.test(k) ? "s" : /_rpm$/.test(k) ? "rpm" : /_deg$/.test(k) ? "°" : "");
export const metricZh = (k: string): string => METRIC_ZH[k] ?? k;
// 环层级（议题 A，app.yaml loop.level / loop.inner，后端经 schema.loops 下发）：任意层数，缺字段退回「—」
export const LOOP_F = { list: "loops", name: "name", level: "level", inner: "inner", locked: "locked" } as const;
export type Loop = { name: string; level: number | null; inner: string; locked: string[] };
export function toLoops(schema: any): Loop[] {
  const a = schema?.[LOOP_F.list]; if (!Array.isArray(a)) return [];
  return a.map((o: any) => ({ name: str(o?.[LOOP_F.name]) || "—", level: num(o?.[LOOP_F.level]) ?? null, inner: str(o?.[LOOP_F.inner]), locked: Array.isArray(o?.[LOOP_F.locked]) ? o[LOOP_F.locked].map(String) : [] }));
}
// 心跳状态位（hb_flags 后端已转中文；reset 可能是 "#12" 这种未知码）
export const HB_F = { flags: "hb_flags", reset: "reset", sat: "sensor_sat" } as const;   // sensor_sat：status 实时布尔（暂定，等 events.md），不锁存
export const SENSOR_SAT_ZH = "传感器饱和";
// r9p6 通用指标卡 metrics_card（后端 #82 草案，字段名未定稿：改名只改这里）
export const MC_F = {
  obj: "metrics_card", kind: "task_kind", kindBasis: "task_kind_basis", items: "items",
  name: "name", clause: "clause", spec: "spec_text", target: "target", cmp: "cmp", thr: "threshold", unit: "unit",
  measured: "measured", value: "value", method: "method", n: "n", unc: "uncertainty",
  verdict: "verdict", verdictZh: "verdict_zh", basis: "pass_basis", source: "source", evidence: "evidence",
  tuning: "tuning", calib: "calibration", coeffs: "coeffs", signal: "signal_source",
  how: "method", manualSteps: "manual_steps", procedure: "procedure", entry: "manual_entry", eValue: "value", eBy: "by", eAt: "at", srcNote: "source_note",
  ampReduced: "amp_reduced", ampSpec: "amp_spec", ampTested: "amp_tested", ampUnit: "amp_unit", warning: "warning_zh", partial: "partial",   // #129 降幅测试
  model: "model",   // 每项 model:{estimate, basis}，后端从 app.yaml plant 抄来；子字段名同 PLANT_F
} as const;
// 指标卡导出：CSV / xlsx 由后端生成，前端只调这个 op（op 名未定稿，改名只改这里）
export const MC_EXPORT_OP = "metrics_export";
export type TaskKind = "control" | "measure" | "power" | "other";
export type McItem = {
  name: string; clause: string; spec: string;
  target: { cmp: string; thr: number | null; unit: string } | null;
  measured: { value: number | null; unit: string; method: string; n: number | null } | null;
  unc: number | null; verdict: "pass" | "fail" | "partial" | "unknown"; verdictZh: string; basis: string;
  source: "sim" | "real" | "calibrated" | "manual" | ""; srcNote: string; evidence: string; tuning: any | null;
  how: "auto" | "manual" | ""; manualSteps: string[]; procedure: string[]; entry: { value: number | null; by: string; at: string } | null;
  calib: { coeffs: number[]; signal: string } | null;
  model: { estimate: string; basis: string } | null;
  amp: { reduced: boolean; spec: string; tested: string } | null; warningZh: string;
};
export type MetricsCard = { kind: TaskKind; kindBasis: string; items: McItem[] };
const strList = (v: unknown): string[] => Array.isArray(v) ? v.map(y => typeof y === "string" ? y : "").filter(Boolean) : typeof v === "string" && v ? [v] : [];
// 幅度：数 / {value, unit} / 字符串；数没带单位时借 target / measured 的单位
export function ampText(a: unknown, x: any): string {
  const un = str(a && typeof a === "object" ? (a as any)[MC_F.unit] : "") || str(x?.[MC_F.ampUnit]);   // #140 只认 amp_unit（暂定名）或幅度自带单位，不猜
  const v = a && typeof a === "object" ? (a as any)[MC_F.value] : a;
  if (typeof v === "number" && Number.isFinite(v)) return `${+v.toPrecision(5)}${un ? " " + un : ""}`;
  return typeof v === "string" && v.trim() ? v.trim() : MISSING_ZH;
}
// #134 「题面幅度 X，实测幅度 Y」：两个都没给 → ""
export function ampLine(x: any): string {
  if (x?.[MC_F.ampSpec] == null && x?.[MC_F.ampTested] == null) return "";
  return `题面幅度 ${ampText(x[MC_F.ampSpec], x)}，实测幅度 ${ampText(x[MC_F.ampTested], x)}`;
}
export function toMetricsCard(src: any): MetricsCard | null {
  const o = src?.[MC_F.obj] ?? src?.args?.[MC_F.obj] ?? src?.preview?.[MC_F.obj];
  if (!o || !Array.isArray(o[MC_F.items])) return null;
  const k = str(o[MC_F.kind]), kind: TaskKind = k === "control" || k === "measure" || k === "power" ? k : "other";
  const items: McItem[] = o[MC_F.items].filter((x: any) => x && typeof x === "object").map((x: any) => {
    const t = x[MC_F.target], m = x[MC_F.measured], v = x[MC_F.verdict], src0 = str(x[MC_F.source]), c = x[MC_F.calib];
    return {
      name: str(x[MC_F.name]), clause: str(x[MC_F.clause]), spec: str(x[MC_F.spec]),
      target: t && typeof t === "object" ? { cmp: str(t[MC_F.cmp]), thr: num(t[MC_F.thr]) ?? null, unit: str(t[MC_F.unit]) } : null,
      measured: m && typeof m === "object" ? { value: num(m[MC_F.value]) ?? null, unit: str(m[MC_F.unit]), method: str(m[MC_F.method]), n: num(m[MC_F.n]) ?? null } : null,
      unc: num(x[MC_F.unc]) ?? null,
      verdict: x[MC_F.ampReduced] === true && v !== "fail" ? "partial" : v === "pass" || v === "fail" || v === MC_F.partial ? v : "unknown",   // 降幅测试绝不算达标
      amp: x[MC_F.ampReduced] != null || x[MC_F.ampSpec] != null || x[MC_F.ampTested] != null ? { reduced: x[MC_F.ampReduced] === true, spec: ampText(x[MC_F.ampSpec], x), tested: ampText(x[MC_F.ampTested], x) } : null, warningZh: str(x[MC_F.warning]), verdictZh: str(x[MC_F.verdictZh]), basis: str(x[MC_F.basis]),
      source: src0 === "sim" || src0 === "real" || src0 === "calibrated" || src0 === "manual" ? src0 : "", srcNote: str(x[MC_F.srcNote]), evidence: str(x[MC_F.evidence]),
      how: x[MC_F.how] === "auto" || x[MC_F.how] === "manual" ? x[MC_F.how] : "",
      manualSteps: strList(x[MC_F.manualSteps]), procedure: strList(x[MC_F.procedure]),
      entry: x[MC_F.entry] && typeof x[MC_F.entry] === "object" ? { value: num(x[MC_F.entry][MC_F.eValue]) ?? null, by: str(x[MC_F.entry][MC_F.eBy]), at: str(x[MC_F.entry][MC_F.eAt]) } : null,
      tuning: x[MC_F.tuning] && typeof x[MC_F.tuning] === "object" ? x[MC_F.tuning] : null,
      model: x[MC_F.model] && typeof x[MC_F.model] === "object" && str(x[MC_F.model][PLANT_F.estimate]) ? { estimate: str(x[MC_F.model][PLANT_F.estimate]), basis: str(x[MC_F.model][PLANT_F.basis]) } : null,
      calib: c && typeof c === "object" ? { coeffs: Array.isArray(c[MC_F.coeffs]) ? c[MC_F.coeffs].filter((y: unknown) => num(y) != null) : [], signal: str(c[MC_F.signal]) } : null,
    };
  });
  return { kind, kindBasis: str(o[MC_F.kindBasis]), items };
}
// #91 报错字段：正文 message_zh，原因 reason_zh / cause_zh / why，修复按钮 fix_action（部分回复里叫 l，草案未定）
export const ERR_F = { msg: "message_zh", why: ["reason_zh", "cause_zh", "why"], fix: ["fix_action", "l"] } as const;
export const NO_REASON_ZH = "后端未给原因";
export const errFixAction = (e: any): string => { for (const k of ERR_F.fix) { const v = e?.[k]; if (typeof v === "string" && v) return v; } return ""; };
export const errWhy = (e: any): string => { for (const k of ERR_F.why) { const v = e?.[k]; if (typeof v === "string" && v && !/^[\x00-\x7f]*$/.test(v)) return v; } return ""; };
// #88 提交确认卡（后端另出 git commit 确认，字段草案）
export const COMMIT_F = { id: "request_id", state: "status", branch: "branch", files: "files", msg: "message", msgZh: "message_zh", path: "path", status: "status" } as const;
// #88 定稿（后端 docs/dev/events.md）：事件 commit_confirm_request → 回 op commit_confirm；拒绝 / 超时 → commit_declined
export const COMMIT_EV = { request: "commit_confirm_request", declined: "commit_declined" } as const;
export const COMMIT_OP = { name: "commit_confirm", id: "request_id", approve: "approve" } as const;
export const COMMIT_DECL_F = { reason: "reason_zh", fix: "fix_action", code: "reason", ok: "ok", commit: "commit", declined: "commit_declined", failed: "commit_failed" } as const;
// 写文件确认卡：scope = "write_only" 表示只授权写文件
export const WRITE_F = { scope: "scope", writeOnly: "write_only" } as const;
export const WRITE_ONLY_ZH = "只授权写入文件，不会存进工程版本（「保存到工程版本」另有确认卡）";
// 工程声明的板子名：schema 里的 title / name（后端给了就用），否则当前项目名
export const BOARD_F = { schema: ["title", "name"], project: "name", path: "path" } as const;
export const writeScopeNote = (card: any): string => card?.[WRITE_F.scope] === WRITE_F.writeOnly ? WRITE_ONLY_ZH : "";
// fw-plant a4161a3 schema/plant.schema.json：plant.estimate ∈ coarse|identified，plant.basis 一句话依据；单位原样显示
export const PLANT_F = { obj: "plant", estimate: "estimate", basis: "basis", unit: "unit", uUnit: "u_unit" } as const;
export const PLANT_EST_ZH: Record<string, string> = { coarse: "粗估", identified: "已辨识" };
// 粗估判定值：调参页标签读工程的 plant.estimate；结果 / 指标卡读每项 model.estimate（同一 schema 枚举）
export const PLANT_COARSE = "coarse";
export const COARSE_ZH = "仅仿真粗估";
// #101 后端将推「清掉结果卡」事件（名字未定稿，暂定）；本地兜底：开始迭代 / 重连 / 换板也清
export const RESULT_CLEAR_EV = ["result_reset"] as const;   // 定稿：result_reset {run_id, reason: iterate_start|reconnect|board_change}
// 结果卡所属板卡（暂定）：重连后 iterate_status 回的结果只有板卡对得上才恢复
export const RESULT_PORT_F = ["port", "board"] as const;
// #104 list_ports 每个仿真项的应用名（暂定，按顺序取第一个非空）；没有就用目录名
export const PORT_APP_F = ["app_name"] as const;   // 定稿：list_ports 仿真项带 app_name / app_dir
export const PORT_DIR_F = ["app_dir"] as const;
export const pickStr = (o: any, keys: readonly string[]): string => { for (const k of keys) { const v = o?.[k]; if (typeof v === "string" && v.trim()) return v.trim(); } return ""; };

// #101 r9f：台账一轮（iterate.round 事件 / 阶跃实验收尾）——暂定字段名，后端定稿改这里
export const LEDGER_ROUND_F = { iter: "iter", valid: "valid", params: "params", overshoot: "overshoot_pct", settle: "settle_ms", runId: "run_id", kind: "kind", manual: "manual_step", diverged: "diverged", sat: "sensor_sat", aborted: "aborted", status: "status", why: "reason_zh" } as const;
// #131 结果卡停止原因：无效轮数用后端 invalid_streak（暂定名），没有就数台账；发散只认 diverged / sensor_sat / 后端 reason；中止带后端原因
export const STOP_F = { invalidN: "invalid_streak", diverged: "diverged", sat: "sensor_sat", why: ["reason_zh", "message_zh"], abortCodes: ["aborted", "stopped", "abort"], invalidCodes: ["invalid", "invalid_streak"], divCodes: ["diverged", "unstable"] } as const;
export const ABORT_ZH = "中止", NO_ROUND_ZH = "没有可用的一轮";

// #110 r9f：拒绝 / 失败原因按序找：reason_zh → message_zh → detail（顶层、data、error 里都找）——暂定，后端定稿改这里
export const COMMIT_REASON_KEYS = ["reason_zh", "message_zh", "detail"] as const;
export const COMMIT_REASON_HOSTS = ["", "data", "error"] as const;
export const COMMIT_USER_F = "user_declined";   // 界面自己标：这次拒绝是用户点的「取消」
export const USER_DECLINED_ZH = "你已取消写入";
export const COMMIT_STORE_KEY = "dz.commitPending";   // #111 sessionStorage：刷新后恢复待确认的提交卡

// r9f 急停横幅：事件 / status 里的字段——暂定名，后端定稿改这里；缺了显示 MISSING_ZH，不编
export const ESTOP_F = { at: ["latched_at"], reason: ["reason_zh"], code: "reason", measured: ["measured_ms"], threshold: ["threshold_ms"], restored: "restored", fix: "fix_action", source: "source", restoredSrc: "latch_restored" } as const;   // 定稿（threshold_ms 来自握手 wd_timeout_ms，可能为 null）
export const MISSING_ZH = "后端未给";
export const LATCH_AT_MISSING_ZH = "锁存时间后端未给";

// r9g 急停横幅按原因显示字段（唯一一张表）：cause 取事件 source / kind / status.estop_cause.cause（去掉 firmware: 前缀）
// fields = 这种原因天然带的数值；label = 固定文案（有就不读 reason_zh）。表里没有的原因：只显示原因文字
// #132 缺值文案：缺时间 / 缺原因 / 缺数值都不写「后端未给」；缺原因 → 「急停」，心跳类缺实测间隔 → 一句「（间隔未知）」
export const ESTOP_GENERIC_ZH = "急停", ESTOP_GAP_UNKNOWN_ZH = "（间隔未知）", ESTOP_HB_ZH = "心跳超时";
export const ESTOP_CAUSES: Record<string, { label?: string; fields: readonly ("measured" | "threshold")[] }> = {
  ui: { label: "手动急停", fields: [] }, button: { label: "手动急停", fields: [] }, key: { label: "手动急停", fields: [] }, manual: { label: "手动急停", fields: [] },
  heartbeat: { fields: ["measured", "threshold"] }, heartbeat_lost: { fields: ["measured", "threshold"] }, hb_lost: { fields: ["measured", "threshold"] },
  hb_timeout: { fields: ["measured", "threshold"] }, watchdog: { fields: ["measured", "threshold"] }, "2": { fields: ["measured", "threshold"] },
};

// #121 结论码 → 中文（后端没给 verdict_zh 时本地兜底）
export const VERDICT_ZH: Record<string, string> = { pass: "通过", fail: "未通过", unknown: "未判定", partial: "未验题面幅度" };
// #122 提交动作统一叫法
export const COMMIT_BTN_ZH = "保存到工程版本";
// #133 两步先后：写入成功后提示 + 把待保存卡带到眼前；提交卡副标题
export const WRITTEN_ZH = "已写入文件，还没保存到工程版本", COMMIT_SUB_ZH = "把刚写入的文件存成一个版本，可回滚";
export const COMMIT_SENT_F = "__sent";   // #117 sessionStorage 里标记：已点确认、等后端结果
export const COMMIT_SENT_ZH = "已发出，等后端结果";
// #116 最好一轮在台账里是无效 / 发散：不显示、不给「采用」
export const NO_STABLE_ZH = "发散，未找到稳定参数";
// 参数角色确认：自动整定回 needs-manual + fix_action confirm_roles，带 missing[参数名] / suggested{名: 角色}；握手参数表可带 role（只读显示）
export const ROLE_F = { fix: "fix_action", confirm: "confirm_roles", missing: "missing", suggested: "suggested", reason: "reason_zh", paramRole: "role" } as const;
export const ROLE_CONFIRM_OP = "confirm_roles";   // 定稿：confirm_roles {roles:{name: code}} → {ok, roles} 或 {message_zh, fix_action}
export const ROLE_REPLY_F = { ok: "ok", roles: "roles", msg: "message_zh", fix: "fix_action" } as const;
export const ROLE_SENDING_ZH = "已发出，等后端结果";
export const ROLE_CODES = [["P", "比例"], ["I", "积分"], ["D", "微分"], ["FF", "前馈"], ["LIM", "限幅"], ["other", "其他"]] as const;
export const ROLE_NO_FLASH_ZH = "改角色不用重新烧录", ROLE_LIM_ZH = "不参与整定";   // 角色来源：握手 / link_schema params[i].role（P|I|D|FF|LIM|other|null）
export const ROLE_SUGGEST_ZH = "建议，待确认", ROLE_BTN_ZH = "确认角色", ROLE_RETRY_ZH = "重试整定";
