// 生产包必须带非空的原因表 / 角色表（import.meta.glob 跨出 vite root 时取空，之前生产包里是空表 → 连板前一律「未知原因」）
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import assert from "node:assert/strict";
const out = mkdtempSync(join(tmpdir(), "dz-prodtables-"));
try {
  execFileSync("node_modules/.bin/vite", ["build", "--outDir", out, "--emptyOutDir", "--logLevel", "error"], { stdio: "pipe" });
  const js = readdirSync(join(out, "assets")).filter(f => f.endsWith(".js")).map(f => readFileSync(join(out, "assets", f), "utf8")).join("\n");
  const reasons = JSON.parse(readFileSync("../../docs/dev/reason_codes.json", "utf8"));
  const ks = Object.keys(reasons); assert.ok(ks.length > 0, "reason_codes.json 非空");
  // 表本体以对象字面量打进包：每个原因码后紧跟 {…zh:"中文名"…}（只出现在零散代码里的字符串不算）
  const ent = (k: string) => new RegExp(`["']?${k}["']?:\\{[^{}]*zh:`).test(js);
  for (const k of ks) { assert.ok(ent(k), `原因表条目 ${k} 不在生产包`); assert.ok(js.includes(reasons[k].zh), `原因 ${k} 的中文名不在生产包`); }
  const roles = JSON.parse(readFileSync("../../docs/dev/roles.json", "utf8"));
  const rk: { code: string; zh: string }[] = roles.roles ?? []; assert.ok(rk.length > 0, "roles.json 非空");
  const esc = (x: string) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  for (const r of rk) assert.ok(new RegExp(`code:["']${esc(r.code)}["'],zh:["']${esc(r.zh)}["']`).test(js), `角色表条目 ${r.code} 不在生产包`);
  console.log(`prodtables ok (${ks.length} reasons, ${rk.length} roles)`);
} finally { rmSync(out, { recursive: true, force: true }); }
