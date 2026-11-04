import { readFileSync } from "node:fs";
import { statusOf, buildList, groups, search, loadRecent, pushRecent } from "../src/toolmodel.ts";
import { TOOL_DECLS } from "../src/tooldecl.ts";
import { STAGES, stageOfJourney } from "../src/stages.ts";
import { flowModel } from "../src/flow.ts";
import { buildFramedef } from "../src/fdform.ts";
import { BoundedLog, parseHexInput, DISPLAY_CAP } from "../src/serialterm.ts";
import { injectBridge } from "../src/serialslot.ts";
import { logLabel } from "../src/fieldmap.ts";
const eq = (a: any, b: any, m: string) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${m}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`); };
const ok = (c: any, m: string) => { if (!c) throw new Error(m); };
// 状态
eq(statusOf({ built: false, needs: "none" }, { sidecar: true, board: true }), "not_integrated", "未接入");
eq(statusOf({ built: true, needs: "board" }, { sidecar: true, board: false }), "needs_board", "需连板");
eq(statusOf({ built: true, needs: "sidecar" }, { sidecar: false, board: false }), "no_sidecar", "侧车没开");
// 唯一阶段表：工具的 stage 都在表里，首页 8 步
eq(STAGES.length, 8, "8 步"); for (const d of TOOL_DECLS) ok(STAGES.some(s => s.id === d.stage), `工具 ${d.id} 阶段 ${d.stage} 不在 stages.ts`);
eq(stageOfJourney("bringup"), "debug", "旅程映射"); eq(stageOfJourney("zzz"), "req", "未知回第一步");
// 分组：当前阶段没有工具时展开后面第一个有工具的阶段，且排第一
const l = buildList(null, { sidecar: true, board: true }, "req", []);
const g = groups(l); ok(g[0].open && g.filter(x => x.open).length === 1, "只展开一组且排第一"); eq(g[g.length - 1].title, "更多", "更多在最后");
ok(search(l, "串口").some(t => t.id === "serial_term"), "搜索"); eq(search(l, "  ").length, 0, "空搜索");
const mem: Record<string, string> = {}; const st = { getItem: (k: string) => mem[k] ?? null, setItem: (k: string, v: string) => { mem[k] = v; } };
for (let i = 0; i < 8; i++) pushRecent(st, "t" + i); pushRecent(st, "t3"); eq(loadRecent(st)[0], "t3", "最近使用置顶"); eq(loadRecent(st).length, 6, "最多 6 个");
// 首页流程
const f0 = flowModel({ hasProject: false, connected: false, tuned: false }); eq(f0.find(x => x.state === "cur")?.id, "req", "新用户从读题开始");
const f1 = flowModel({ hasProject: true, connected: false, tuned: false }); eq(f1.find(x => x.state === "cur")?.id, "wiring", "有工程先接线");
const f2 = flowModel({ hasProject: true, connected: true, tuned: false }); eq(f2.find(x => x.state === "cur")?.id, "debug", "连上板进调试");
ok(f0.every(x => x.state !== "blocked"), "新用户不显示卡住");
// 帧格式表单
ok(!buildFramedef({ header: "A", footer: "", checksum: "none", check_from: 0, endian: "little", fields: [{ name: "a", type: "u8", scale: 1 }] } as any).ok, "奇数位 hex 拒绝");
ok(!buildFramedef({ header: "", footer: "", checksum: "none", check_from: 0, endian: "little", fields: [{ name: "a", type: "u8", scale: 1 }] } as any).ok, "头尾都空拒绝");
ok(buildFramedef({ header: "AA 55", footer: "", checksum: "sum8", check_from: 0, endian: "little", fields: [{ name: "a", type: "u16", scale: 1 }] } as any).ok, "合法定义");
// 串口显示上限 8 KB + 丢弃计数
const bl = new BoundedLog(); bl.push({ t: 0, dir: "rx", bytes: new Uint8Array(DISPLAY_CAP + 100) } as any); bl.push({ t: 1, dir: "rx", bytes: new Uint8Array(50) } as any);
ok(bl.size <= DISPLAY_CAP, "不超上限"); eq(bl.dropped, 150, "丢弃计数");
ok(parseHexInput("AA 5").ok === false && parseHexInput("aa 55").ok, "hex 输入校验");
ok(injectBridge("<html><head></head><body></body></html>").indexOf("navigator") < injectBridge("<html><head></head><body></body></html>").indexOf("</head>") + 10, "适配层注入在最前");
ok(!/\.log|\/|AD5791/.test(logLabel({ path: "/x/y/2026-11-04_120102_sim_car.log", size: 2048, header: { port: "sim:car", start: 1762229000, schema_hash: "AD5791CF" } })), "日志名不露路径/哈希");
// 工具箱相关文件不得直接用 Tauri 专有 API（网页版要同样能用）
for (const f of ["toolbox", "toolmodel", "tooldecl", "serialslot", "serialterm", "dashboard", "fdform", "flow", "stages"]) {
  const s = readFileSync(`src/${f}.ts`, "utf8"); ok(!/@tauri-apps|__TAURI__|navigator\.serial\.requestPort\(\)/.test(s.replace(/BRIDGE_JS[\s\S]*?`;/, "")), `${f}.ts 用了 Tauri/Web Serial 专有 API`);
}
console.log("ok");
