// 参数角色下拉的唯一来源：握手 data_tables.roles（侧车）优先，界面打包的 docs/dev/roles.json 兜底（构建时校验，缺失 / 不合格构建失败）
import { ROLE_CODES } from "./fieldmap";
import { DataTable, validRoles, type RoleList } from "./datatables";
export type RoleCode = readonly [string, string];
export const ROLES_T = new DataTable<RoleList>("roles", "角色表", validRoles, ROLE_CODES.map(x => [x[0], x[1]]));
declare const __DZ_ROLES_SHA__: string | null;
try {
  const g: Record<string, any> = typeof (import.meta as any).glob === "function" ? import.meta.glob("../../../docs/dev/roles.json", { eager: true, import: "default" }) : {};
  ROLES_T.setBundled(Object.values(g)[0] ?? null, typeof __DZ_ROLES_SHA__ === "string" ? __DZ_ROLES_SHA__ : null);
} catch { /* 兜底表 */ }
export const setRoleCodes = (o: unknown, sha: string | null = null) => ROLES_T.setBundled(o, sha);   // 测试 / tsx 用
export const roleCodes = (): readonly RoleCode[] => ROLES_T.value();
const DEV = (() => { try { return !!(import.meta as any).env?.DEV; } catch { return false; } })();
export const roleCodesNotice = (dev = DEV) => ROLES_T.notice(dev);
