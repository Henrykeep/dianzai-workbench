// 产品名唯一来源：界面上只醒目显示中文名；英文名 XinTai 只在需要 ASCII 的地方用。
export const BRAND = { nameZh: "芯台", nameEn: "XinTai" } as const;
export function applyBrand(): void {
  document.title = BRAND.nameZh;
  document.querySelectorAll<HTMLElement>("[data-brand]").forEach(e => (e.textContent = BRAND.nameZh));
}
