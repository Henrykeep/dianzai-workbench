// 默认浅色；只有用户点过主题切换（存 dz.theme）才用别的
export const THEMES = ["light", "dark", "hc"];
export const pickTheme = (saved: string | null | undefined) => THEMES.includes(saved ?? "") ? saved! : "light";
