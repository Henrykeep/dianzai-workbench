// 入口规则表（docs/dev/entrypoints.yaml）里的 ready: false = 入口已登记、功能未就绪 → 按钮置灰「等待固件支持」。
// 不在前端写死哪些未就绪：构建时把 yaml 原文打进来（entry-data.ts），这里只做解析。
export type Entry = { id: string; label: string; ready: boolean };
export function parseEntrypoints(text: string): Map<string, Entry> {
  const out = new Map<string, Entry>();
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*-\s*\{\s*id:\s*([A-Za-z0-9_.]+)\s*,(.*)\}/); if (!m) continue;
    const label = m[2].match(/label:\s*([^,}]+)/)?.[1].trim() ?? m[1];
    out.set(m[1], { id: m[1], label, ready: !/\bready:\s*false\b/.test(m[2]) });
  }
  return out;
}
let table = new Map<string, Entry>();
export const setEntrypoints = (text: string) => { table = parseEntrypoints(text); };
export const entry = (id: string) => table.get(id);
