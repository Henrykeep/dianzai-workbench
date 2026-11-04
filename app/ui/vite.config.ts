import { defineConfig } from "vite";
import { readFileSync, existsSync, mkdirSync, copyFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { buildCheck } from "./src/datatables";
// 角色表 / 原因表：构建时校验（roles.json 缺失或不合格 → 构建失败），并把打包副本的 sha256 注入，运行时与握手 data_tables 比对
const rd = (p: string) => { const f = resolve(__dirname, "../../docs/dev", p); return existsSync(f) ? readFileSync(f, "utf8") : null; };
const roles = rd("roles.json"), reasons = rd("reason_codes.json");
const errs = buildCheck(roles, reasons);
if (errs.length) throw new Error(`数据表校验失败：${errs.join("；")}。修复：运行 python -m dzbench selfcheck-data`);
const sha = (s: string | null) => s == null ? null : createHash("sha256").update(s).digest("hex");
// 串口调试页：第三方原样代码只放 third_party/vendored/serialweb/（vendor-tools 分支提供）；构建时拷到 dist/vendor/serialweb/，没有就退回内置终端
const SW = resolve(__dirname, "../../third_party/vendored/serialweb");
const serialweb = { name: "dz-serialweb",
  configureServer(s: any) { s.middlewares.use("/vendor/serialweb/", (req: any, res: any, next: any) => { const f = resolve(SW, (req.url || "/").replace(/^\/+/, "").split("?")[0] || "index.html"); if (f.startsWith(SW) && existsSync(f)) { res.end(readFileSync(f)); } else next(); }); },
  closeBundle() { if (!existsSync(resolve(SW, "index.html"))) return; const o = resolve(__dirname, "dist/vendor/serialweb"); mkdirSync(o, { recursive: true }); for (const f of ["index.html", "LICENSE", "SOURCE.md"]) if (existsSync(resolve(SW, f))) copyFileSync(resolve(SW, f), resolve(o, f)); } };
// Tauri 要求相对路径 + 固定端口；浏览器模式由侧车 --ui dist 直接托管
export default defineConfig({
  plugins: [serialweb],
  base: "./", server: { port: 1420, strictPort: true }, build: { target: "es2021", outDir: "dist" },
  define: { __DZ_ROLES_SHA__: JSON.stringify(sha(roles)), __DZ_REASON_SHA__: JSON.stringify(sha(reasons)),
    // 打包副本内容直接注入（import.meta.glob 跨出 vite root 时取不到文件，生产包原来是空表）
    __DZ_ROLES_JSON__: roles ?? "null", __DZ_REASON_JSON__: reasons ?? "null" },
});
