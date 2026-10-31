// 参数角色下拉的唯一来源：docs/dev/roles.json {schema_version:1, roles:[{code, zh}]}（构建时打包）；没有文件 / 版本不认识 → 前端兜底表 ROLE_CODES
import { ROLE_CODES, ROLES_FILE_F } from "./fieldmap";
export type RoleCode = readonly [string, string];
let LIST: RoleCode[] = ROLE_CODES.map(x => [x[0], x[1]] as const);
export function setRoleCodes(o: unknown) {
  LIST = ROLE_CODES.map(x => [x[0], x[1]] as const);
  const f: any = o;
  if (!f || f[ROLES_FILE_F.ver] !== 1 || !Array.isArray(f[ROLES_FILE_F.list])) return;
  const l = f[ROLES_FILE_F.list].filter((r: any) => typeof r?.[ROLES_FILE_F.code] === "string" && r[ROLES_FILE_F.code] && typeof r?.[ROLES_FILE_F.zh] === "string" && r[ROLES_FILE_F.zh]).map((r: any) => [r[ROLES_FILE_F.code], r[ROLES_FILE_F.zh]] as const);
  if (l.length) LIST = l;
}
export const roleCodes = (): readonly RoleCode[] => LIST;
try {
  const g: Record<string, any> = typeof (import.meta as any).glob === "function" ? import.meta.glob("../../../docs/dev/roles.json", { eager: true, import: "default" }) : {};
  const f = Object.values(g)[0]; if (f) setRoleCodes(f);
} catch { /* 兜底表 */ }
