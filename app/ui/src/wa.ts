// Web Awesome（MIT，本地打包，不走 CDN）：按需注册用到的组件；主题全部从 tokens.css 映射（wa-theme.css）
import "@awesome.me/webawesome/dist/styles/themes/default.css";
import "./wa-theme.css";
import "@awesome.me/webawesome/dist/components/button/button.js";
import "@awesome.me/webawesome/dist/components/slider/slider.js";
import "@awesome.me/webawesome/dist/components/tag/tag.js";
import "@awesome.me/webawesome/dist/components/card/card.js";
import "@awesome.me/webawesome/dist/components/skeleton/skeleton.js";
// 离线：默认图标库不走 Font Awesome CDN（我们的图标用本地 lucide；组件内部的 system 图标是内联 SVG）
import { registerIconLibrary } from "@awesome.me/webawesome/dist/webawesome.js";
registerIconLibrary("default", { resolver: () => "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E" });
