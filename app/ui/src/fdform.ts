// 自定义帧格式表单（替代 window.prompt 填 JSON）。字段与侧车 framedef.py 一致：header/footer/checksum/check_from/endian/fields[{name,type,scale}]
export const FD_TYPES = ["u8", "i8", "u16", "i16", "u32", "i32", "f16", "f32", "f64"] as const;
export type FdField = { name: string; type: string; scale: number };
export type FdForm = { header: string; footer: string; checksum: string; check_from: number; endian: string; fields: FdField[] };
const HEX = /^([0-9a-fA-F]{2})*$/;
export function buildFramedef(f: FdForm): { ok: true; def: any } | { ok: false; error: string } {
  const h = f.header.replace(/\s+/g, ""), t = f.footer.replace(/\s+/g, "");
  if (!HEX.test(h) || !HEX.test(t)) return { ok: false, error: "帧头 / 帧尾要写成偶数位十六进制，例如 AA55" };
  if (!h && !t) return { ok: false, error: "帧头和帧尾至少填一个，不然分不出一帧从哪开始" };
  if (!f.fields.length) return { ok: false, error: "至少添加一个字段" };
  const names = new Set<string>();
  for (const [i, x] of f.fields.entries()) {
    const n = x.name.trim() || `ch${i}`;
    if (names.has(n)) return { ok: false, error: `字段名「${n}」重复了` };
    names.add(n);
    if (!(FD_TYPES as readonly string[]).includes(x.type)) return { ok: false, error: `字段「${n}」的类型不认识` };
    if (!Number.isFinite(x.scale) || x.scale === 0) return { ok: false, error: `字段「${n}」的缩放要是非零数字` };
  }
  if (!Number.isInteger(f.check_from) || f.check_from < 0) return { ok: false, error: "校验起始字节要是 0 或正整数" };
  return { ok: true, def: { kind: "hex", header: h || undefined, footer: t || undefined, checksum: f.checksum || "none", check_from: f.check_from, endian: f.endian === "big" ? "big" : "little",
    fields: f.fields.map((x, i) => ({ name: x.name.trim() || `ch${i}`, type: x.type, scale: x.scale })) } };
}
const v = (id: string) => String((document.getElementById(id) as any)?.value ?? "");
export function initFramedefForm(saved: string | null) {
  const box = document.getElementById("fd-fields")!;
  let init: any = null; try { init = saved ? JSON.parse(saved) : null; } catch { init = null; }
  const row = (x: FdField) => {
    const r = document.createElement("div"); r.className = "fd-f";
    r.innerHTML = `<wa-input size="small" class="fd-n" placeholder="字段名" value=""></wa-input><wa-select size="small" class="fd-t" value="${x.type}">${FD_TYPES.map(t => `<wa-option value="${t}">${t}</wa-option>`).join("")}</wa-select><wa-input size="small" class="fd-s" type="number" value="${x.scale}" title="缩放"></wa-input><wa-button size="small" appearance="plain" class="fd-x" title="删除这个字段">删除</wa-button>`;
    (r.querySelector(".fd-n") as any).value = x.name;
    r.querySelector(".fd-x")!.addEventListener("click", () => r.remove());
    box.append(r);
  };
  if (init && !init.preset) {
    for (const [k, id] of [["header", "fd-header"], ["footer", "fd-tail"], ["checksum", "fd-checksum"], ["check_from", "fd-from"], ["endian", "fd-endian"]]) if (init[k] != null) (document.getElementById(id) as any).value = String(init[k]);
    (init.fields ?? []).forEach((f: any) => row({ name: String(f.name ?? ""), type: String(f.type ?? "f32"), scale: Number(f.scale ?? 1) }));
  }
  if (!box.children.length) row({ name: "", type: "f32", scale: 1 });
  document.getElementById("fd-add")!.addEventListener("click", () => row({ name: "", type: "f32", scale: 1 }));
  return {
    read: () => buildFramedef({ header: v("fd-header"), footer: v("fd-tail"), checksum: v("fd-checksum"), check_from: Number(v("fd-from") || 0), endian: v("fd-endian"),
      fields: [...box.querySelectorAll<HTMLElement>(".fd-f")].map(r => ({ name: String((r.querySelector(".fd-n") as any).value ?? ""), type: String((r.querySelector(".fd-t") as any).value ?? "f32"), scale: Number((r.querySelector(".fd-s") as any).value) })) }),
  };
}
