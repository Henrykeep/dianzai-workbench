#!/usr/bin/env bash
# 前端（app/ui）npm 依赖许可证检查：发现 GPL / AGPL 即失败（LGPL 不算）。
# 工具：license-checker-rseidelsohn（BSD-3，app/ui devDependencies 里锁定版本），只读本地 node_modules，离线/CI 都能跑。
# 用法：tools/check_npm_licenses.sh            # 退出码 0 = 通过，1 = 有禁用许可证，2 = 环境不全
# 接入：由 Makefile 的 licenses 目标调用（本脚本不改 Makefile）。
set -euo pipefail
UI="$(cd "$(dirname "$0")/../app/ui" && pwd)"
BIN="$UI/node_modules/.bin/license-checker-rseidelsohn"
cd "$UI"
if [ ! -x "$BIN" ]; then
  echo "✗ npm 许可证检查没跑成 · 原因：app/ui/node_modules 里没有 license-checker-rseidelsohn · 处理：在 app/ui 下运行 npm ci（CI 用缓存的 node_modules 即可离线）" >&2
  exit 2
fi
FAIL='GPL;AGPL;GPL-2.0;GPL-3.0;AGPL-3.0;GPL-2.0-only;GPL-2.0-or-later;GPL-3.0-only;GPL-3.0-or-later;AGPL-3.0-only;AGPL-3.0-or-later'
JSON="$(mktemp)"; trap 'rm -f "$JSON"' EXIT
# 1) 工具自带判定（--failOn 是精确匹配许可证名，所以把常见 SPDX 写法都列上）
if ! "$BIN" --excludePrivatePackages --failOn "$FAIL" >/dev/null 2>"$JSON.err"; then tool_fail=1; else tool_fail=0; fi
# 2) 再按 JSON 逐包核对，报出是哪个包、什么许可证、怎么处理（也兜住 "GPL-3.0+"、"(MIT OR GPL-2.0)" 这类写法）
"$BIN" --excludePrivatePackages --json --out "$JSON" 2>/dev/null
node - "$JSON" "$tool_fail" <<'JS'
const [, , f, toolFail] = process.argv;
const d = JSON.parse(require("fs").readFileSync(f, "utf8"));
const bad = [], unk = [];
for (const [pkg, v] of Object.entries(d)) {
  const lic = Array.isArray(v.licenses) ? v.licenses.join(" / ") : String(v.licenses ?? "");
  // OR 组合里有非 GPL 选项可以选那个，不算违规；AND / 单一 GPL、AGPL 算
  const alts = lic.replace(/[()]/g, "").split(/\s+OR\s+/i);
  if (alts.every(a => /(^|[^L])GPL/i.test(a))) bad.push([pkg, lic, v.path]);
  else if (/UNKNOWN|UNLICENSED|Custom/i.test(lic)) unk.push([pkg, lic]);
}
for (const [p, l] of unk) console.log(`! 许可证不明：${p}（${l}）· 原因：包里没写或写法不规范 · 处理：去它的仓库确认许可证，确认后在评审里记一笔`);
for (const [p, l, path] of bad) console.error(`✗ 禁用许可证：${p} 用的是 ${l} · 原因：GPL/AGPL 会把传染义务带进整个工作台的发行包 · 处理：npm ls ${p.replace(/@[^@]*$/, "")} 看是谁引入的，换成 MIT/BSD/Apache 的同类包，或去掉该依赖（位置 ${path}）`);
if (bad.length || toolFail === "1") {
  if (!bad.length) console.error("✗ license-checker 报告了禁用许可证（--failOn），但逐包核对没定位到 · 处理：在 app/ui 运行 node_modules/.bin/license-checker-rseidelsohn --excludePrivatePackages --summary 查看");
  process.exit(1);
}
console.log(`✓ npm 许可证：${Object.keys(d).length} 个包，没有 GPL / AGPL${unk.length ? `（${unk.length} 个许可证不明，见上）` : ""}`);
JS
