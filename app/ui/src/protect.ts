// 保护阈值表：schema 里带 protect 分类的参数（堵转电流 / 倾倒角 / 限幅 / 断线停车…）+ protect_fixed 编译期常量（只读）。
// 不认任何参数名：分类、顺序都来自 app.yaml。改值走参数面板同一套草稿 → 下发（S.edit / sendPending），每次下发记上一次板上值，可一键撤销。
import { Param } from "./params";
export type Fixed = { name: string; value: number | string; unit?: string; where?: string };
export type Row = { cat: string; p?: Param; fixed?: Fixed };
export function protectRows(params: (Param & { protect?: string })[], fixed: Fixed[] = []): Row[] {
  const rows: Row[] = params.filter(p => p.protect).map(p => ({ cat: p.protect!, p }));
  rows.sort((a, b) => a.cat.localeCompare(b.cat, "zh"));        // 同类挨着；同类内保持 yaml 顺序（sort 稳定）
  return rows.concat(fixed.map(f => ({ cat: f.name, fixed: f })));
}
// 撤销栈：每个参数记最近 n 次下发前的板上值
export class UndoLog {
  private h = new Map<string, number[]>();
  constructor(private n = 10) {}
  push(name: string, before: number | undefined) { if (before == null) return; const a = this.h.get(name) ?? []; a.push(before); if (a.length > this.n) a.shift(); this.h.set(name, a); }
  peek(name: string) { const a = this.h.get(name); return a?.length ? a[a.length - 1] : undefined; }
  pop(name: string) { return this.h.get(name)?.pop(); }
  clear() { this.h.clear(); }
}
