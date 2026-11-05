// 角色表 / 原因表：校验规则 + 运行时来源（握手 data_tables 优先，界面打包的副本兜底）+ 提示文案。纯逻辑，vite.config 和测试都用。
import { ROLES_FILE_F, DATA_TABLES_F, DATA_FIX_ZH, DATA_FIX_DEV } from "./fieldmap";
// 打开这个开关：reason_codes.json 缺失也让构建失败（后端把文件提交进仓库后改成 true，只改这一处）
export const REQUIRE_REASON_CODES = true;   // 5ce00ab 起 reason_codes.json 已进仓库
export type RoleList = [string, string][];
export type ReasonMap = Record<string, { zh: string; kind?: string; causes?: string[]; stop?: boolean; message_zh?: string; fix_action?: string }>;
const parse = (c: unknown) => { if (typeof c !== "string") return c; try { return JSON.parse(c); } catch { return undefined; } };
export function validRoles(c: unknown): RoleList | null {
  const f: any = parse(c);
  if (!f || typeof f !== "object" || f[ROLES_FILE_F.ver] !== 1 || !Array.isArray(f[ROLES_FILE_F.list]) || !f[ROLES_FILE_F.list].length) return null;
  const ok = (r: any) => typeof r?.[ROLES_FILE_F.code] === "string" && r[ROLES_FILE_F.code] && typeof r?.[ROLES_FILE_F.zh] === "string" && r[ROLES_FILE_F.zh];
  return f[ROLES_FILE_F.list].every(ok) ? f[ROLES_FILE_F.list].map((r: any) => [r[ROLES_FILE_F.code], r[ROLES_FILE_F.zh]]) : null;
}
export function validReasons(c: unknown): ReasonMap | null {
  const o: any = parse(c);
  if (!o || typeof o !== "object" || Array.isArray(o)) return null;
  const es = Object.entries(o);
  if (!es.length || !es.every(([, v]: any) => v && typeof v.zh === "string" && v.zh)) return null;   // 有一条不合格就整表不用
  const m: ReasonMap = {}; for (const [k, v] of es as any) { m[k] = { zh: v.zh, kind: v.kind, ...(typeof v.fix_action === "string" && v.fix_action ? { fix_action: v.fix_action } : {}) }; const cs = Array.isArray(v.causes) ? v.causes.filter((x: unknown) => typeof x === "string" && x) : []; if (cs.length) m[k].causes = cs; if (v.stop === true) m[k].stop = true; if (typeof v.message_zh === "string" && v.message_zh) m[k].message_zh = v.message_zh; } return m;
}
// 构建闸门：返回错误列表（空 = 通过）。roles.json 必须在且合法；reason_codes.json 在就必须合法，缺失只在 REQUIRE_REASON_CODES 时算错
export function buildCheck(rolesRaw: string | null, reasonRaw: string | null, requireReason = REQUIRE_REASON_CODES): string[] {
  const e: string[] = [];
  if (rolesRaw == null) e.push("docs/dev/roles.json 缺失"); else if (!validRoles(rolesRaw)) e.push("docs/dev/roles.json 格式错误");
  if (reasonRaw == null) { if (requireReason) e.push("docs/dev/reason_codes.json 缺失"); } else if (!validReasons(reasonRaw)) e.push("docs/dev/reason_codes.json 格式错误");
  return e;
}
export type HsState = "pending" | "absent" | "srvmissing" | "bad" | "mismatch" | "ok";
export class DataTable<T> {
  bundled: T | null = null; bundledSha: string | null = null; hs: HsState = "pending"; hsVal: T | null = null;
  constructor(readonly key: string, readonly what: string, readonly validate: (c: unknown) => T | null, readonly fallback: T, readonly devMissingNotice = false) {}
  setBundled(c: unknown, sha: string | null = null) { this.bundled = c == null ? null : this.validate(c); this.bundledSha = this.bundled ? sha : null; }
  // 握手：data_tables[key] = {sha256（原始文件字节）, content（解析后的 JSON）} | null；没有 → absent（用打包副本 + 提示）；content 不合格 → bad；sha 和打包副本不同 → mismatch（仍用侧车内容）
  onHandshake(hs: any) {
    const dt = hs?.[DATA_TABLES_F.obj], t = dt?.[this.key];
    if (dt && typeof dt === "object" && this.key in dt && t === null) { this.hs = "srvmissing"; this.hsVal = null; return; }   // 本地服务那边文件缺失 / 损坏（另有 data_file_missing 阻断项）
    if (!t || typeof t !== "object") { this.hs = "absent"; this.hsVal = null; return; }
    const v = this.validate(t[DATA_TABLES_F.content]); this.hsVal = v;
    if (!v) { this.hs = "bad"; return; }
    const sha = typeof t[DATA_TABLES_F.sha] === "string" ? t[DATA_TABLES_F.sha].toLowerCase() : null;
    this.hs = this.bundledSha && sha && sha !== this.bundledSha.toLowerCase() ? "mismatch" : "ok";
  }
  reset() { this.hs = "pending"; this.hsVal = null; }
  value(): T { return (this.hs === "ok" || this.hs === "mismatch") && this.hsVal ? this.hsVal : this.bundled ?? this.fallback; }
  notice(dev = false): string {
    const tail = `${DATA_FIX_ZH}${dev ? DATA_FIX_DEV : ""}`;
    switch (this.hs) {
      case "pending": return "";
      case "absent": return `本地服务未提供${this.what}，已使用内置列表。${tail}`;
      case "srvmissing": return `${this.what}缺失，已使用内置列表。${tail}`;
      case "bad": return `${this.what}格式错误，已使用内置列表。${tail}`;
      case "mismatch": return `界面与本地服务的${this.what}不一致，请重装或更新。${tail}`;
      default: return this.devMissingNotice && dev && !this.bundled ? `界面打包里没有${this.what}（仅开发模式提示）` : "";
    }
  }
}

// #143 data_tables 在 hello 回包顶层（与 schema 平级）。schema 自己带了就用它（兼容），否则用最近一次 hello 顶层的
export function tablesSrc(schema: any, hello: any): any {
  if (schema && typeof schema === "object" && DATA_TABLES_F.obj in schema) return schema;
  return hello && typeof hello === "object" && DATA_TABLES_F.obj in hello ? { [DATA_TABLES_F.obj]: hello[DATA_TABLES_F.obj] } : null;
}
