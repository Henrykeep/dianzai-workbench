import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { DataTable, tablesSrc } from "../src/datatables";
import { currentMetrics, resultCardHtml, type Stopped } from "../src/iterui";
import { ampLine, ampLineHtml, UNIT_UNDECL_ZH, AMP_UNIT_DECL_KEY } from "../src/fieldmap";
import { fromRoundEvent } from "../src/ledgerbus";
import { distinctName } from "../src/boardid";
import type { LedgerRound } from "../src/ledgerbus";
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

// #143 data_tables 在 hello 顶层；schema 里没有 → 用 hello 的，sha 一致 → ok，不提示「未提供」
{
  const raw = JSON.stringify({ schema_version: 1, roles: [{ code: "P", zh: "比例" }] });
  const sha = createHash("sha256").update(raw).digest("hex");
  const hello = { schema: { fields: [] }, data_tables: { roles: { sha256: sha, content: JSON.parse(raw) } } };
  const t = new DataTable<any>("roles", "角色表", (c: any) => (c && Array.isArray(c.roles) ? c.roles : null), []);
  t.setBundled(JSON.parse(raw), sha);
  t.onHandshake(hello.schema); assert.equal(t.hs, "absent", "旧写法：读 schema 下 → absent（复现 #143）");
  t.onHandshake(tablesSrc(hello.schema, hello)); assert.equal(t.hs, "ok", "读顶层 → 哈希比对通过");
  assert.doesNotMatch(t.notice(false) ?? "", /未提供/);
  assert.equal(tablesSrc({ data_tables: { roles: null } }, hello).data_tables.roles, null, "schema 自带时优先");
  assert.equal(tablesSrc(null, {}), null);
}

// #147 best 指向第 1 轮且没带指标：卡上指标取第 1 轮，不拿第 0 轮
{
  const rs: LedgerRound[] = [
    { n: 0, params: { kp: 1 }, metrics: { overshoot_pct: 30, settling_s: 0.9 }, valid: true, runId: "Q" },
    { n: 1, params: { kp: 4 }, metrics: { overshoot_pct: 3, settling_s: 0.3 }, valid: true, runId: "Q" },
  ];
  const r = { reason: "pass", run_id: "Q", best: { iter: 1, params: { kp: 4 } }, base: { overshoot_pct: 30, settling_s: 0.9 } } as unknown as Stopped;
  const m = currentMetrics(r, rs);
  assert.match(m, /超调 3%/); assert.doesNotMatch(m, /30%/); assert.match(m, /调节 0\.3 s/);
  const r0 = { reason: "pass", run_id: "Q", best: { iter: 0, params: { kp: 1 } }, base: { overshoot_pct: 30 } } as unknown as Stopped;
  assert.match(currentMetrics(r0, rs), /超调 30%/, "best 就是第 0 轮时照用");
}

// #148 amp_unit 为 null：数值照显示，只是不带单位；卡片有内容
{
  const x = { amp_spec: 1, amp_tested: 0.5, amp_unit: null };
  assert.equal(ampLine(x), "题面幅度 1，实测幅度 0.5");
  const r = { reason: "pass", best: { iter: 0, params: { kp: 1 }, metrics: { overshoot_pct: 3 } }, verdict: { v: "pass", warn: "按降幅测试，未验题面幅度" }, amp_reduced: true, ...x } as unknown as Stopped;
  const h = resultCardHtml(r, esc, { canApply: true, applyReady: true });
  assert.match(h, /题面幅度 1，实测幅度 0\.5/); assert.doesNotMatch(h, /null|undefined/);
  assert.ok(h.includes(UNIT_UNDECL_ZH) && h.includes(`data-decl-unit="${AMP_UNIT_DECL_KEY}"`), "无单位：挂「单位未声明」链接到声明");
  assert.match(ampLineHtml({ ...x, amp_unit_decl: "link.step[0].unit" }, esc), /data-decl-unit="link\.step\[0\]\.unit"/);
  const withU = ampLineHtml({ amp_spec: 200, amp_tested: 50, amp_unit: "mm" }, esc);
  assert.equal(withU, "题面幅度 200 mm，实测幅度 50 mm"); assert.ok(!withU.includes(UNIT_UNDECL_ZH));
  assert.equal(ampLineHtml({}, esc), "");
}

// #147 round_id：有就按 round_id 对轮（轮号相同也不串）
{
  const a = fromRoundEvent({ iter: 1, run_id: "Q", round_id: "r-a", params: { kp: 2 }, overshoot_pct: 25, settle_ms: 800 })!;
  const b = fromRoundEvent({ iter: 1, run_id: "Q", round_id: "r-b", params: { kp: 4 }, overshoot_pct: 3, settle_ms: 300 })!;
  assert.equal(b.roundId, "r-b");
  const r = { reason: "pass", run_id: "Q", best: { iter: 1, round_id: "r-b", params: { kp: 4 } }, base: { overshoot_pct: 30 } } as unknown as Stopped;
  assert.match(currentMetrics(r, [a, b]), /超调 3%/);
  const r0 = { reason: "pass", run_id: "Q", best: { iter: 0, round_id: "zz", params: { kp: 4 } }, base: { overshoot_pct: 30 } } as unknown as Stopped;
  assert.doesNotMatch(currentMetrics(r0, [a, b]), /30%/, "round_id 对不上：不拿 base 凑，显示 —");
}

// 结构冲突两份同名文件：带上目录才分得开
assert.deepEqual(["/a/x/link_schema.json", "/b/linkgen/link_schema.json"].map((f, _, a) => distinctName(f, a)), ["…/x/link_schema.json", "…/linkgen/link_schema.json"]);
assert.equal(distinctName("/a/s_A.json", ["/a/s_A.json", "/a/s_B.json"]), "s_A.json");
console.log("r10v ok");
