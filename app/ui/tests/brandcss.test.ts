// #59 / #64 守门：界面上不再出现旧名「电赛工作台」；间距是 4 的倍数；圆角只用 0 / 4px / 8px / 999px（胶囊）
import { readFileSync, readdirSync } from "fs";
const OLD = "电赛" + "工作台";
const files = ["index.html", "../src-tauri/tauri.conf.json", ...readdirSync("src").filter(f => /\.(ts|css)$/.test(f)).map(f => "src/" + f)];
const bad: string[] = [];
for (const f of files) readFileSync(f, "utf8").split("\n").forEach((l, i) => { if (l.includes(OLD)) bad.push(`${f}:${i + 1} 旧产品名`); });
const RADII = new Set(["0", "inherit", "4px", "8px", "999px"]);
const css = readdirSync("src").filter(f => f.endsWith(".css")).map(f => "src/" + f);
for (const f of css) {
  const s = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const m of s.matchAll(/(?:^|[;{\s])((?:margin|padding|gap|row-gap|column-gap)(?:-[a-z-]+)?)\s*:\s*([^;}]+)/g))
    for (const n of m[2].matchAll(/(-?[0-9.]+)px/g)) if (+n[1] % 4) bad.push(`${f} ${m[1]}:${m[2].trim()} 不是 4 的倍数`);
  for (const m of s.matchAll(/(?:^|[;{\s])(border(?:-[a-z-]+)?-radius)\s*:\s*([^;}]+)/g))
    for (const t of m[2].trim().split(/\s+/)) if (!RADII.has(t) && !/^var\(--r(-[a-z]+)?\)$/.test(t)) bad.push(`${f} ${m[1]}:${t} 圆角不在 0/4/8/999px`);
  for (const m of s.matchAll(/--(sp\d|r(?:-[a-z]+)?)\s*:\s*([^;]+)/g)) {
    const v = m[2].trim();
    if (m[1].startsWith("sp") ? parseFloat(v) % 4 !== 0 : !RADII.has(v)) bad.push(`${f} --${m[1]}:${v}`);
  }
}
if (bad.length) { console.error(bad.join("\n")); throw new Error(`brand/css 守门：${bad.length} 处`); }
console.log("✓ brandcss（无旧产品名 · 间距 4 的倍数 · 圆角 0/4/8/999px）");
