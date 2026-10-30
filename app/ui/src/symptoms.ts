// 按症状排障（产品逻辑重组 5）：症状 → 可能原因 → 快速验证 → 工作台里点哪儿。只做导航，不新增后端能力。
// 症状表整理自 MICU-auto-embedded templates/auto-embedded/refs/troubleshooting.md（按症状诊断各表），
// 分类用同目录 failure-taxonomy.md 的 8 类（environment-missing … realtime-violation）。按本工作台的入口改写。
export type Act = { label: string; click?: string[]; step?: string };
export type Sym = { cat: string; tax: string; sym: string; why: string; check: string; acts: Act[] };
const DOCTOR: Act = { label: "自检", click: ["doctor"] }, BB: Act = { label: "读黑匣子", click: ["pre", "pre-bbtn"] };
const HF: Act = { label: "问 Agent 解 HardFault", step: "调参" };
export const TAX: Record<string, string> = {
  "environment-missing": "缺工具", "project-config-error": "工程配置", "connection-failure": "连不上", "artifact-missing": "缺产物",
  "target-response-abnormal": "板子异常", "permission-problem": "权限", "ambiguous-context": "目标不唯一", "realtime-violation": "实时性",
};
export const SYMPTOMS: Sym[] = [
  { cat: "连接", tax: "connection-failure", sym: "串口列表里没有板子 / 连上又掉", why: "线只供电不带数据、驱动没装、USB 口供电不足", check: "换线换口；自检看串口项", acts: [DOCTOR, { label: "串口线控", click: ["lines-btn"] }] },
  { cat: "连接", tax: "permission-problem", sym: "打开串口被拒绝", why: "Linux 下不在 dialout 组；串口被别的软件占着", check: "自检看权限项；关掉其他串口助手", acts: [DOCTOR] },
  { cat: "连接", tax: "target-response-abnormal", sym: "收到字节但是乱码 / 没识别出协议", why: "波特率、数据位、停止位不一致；固件用的不是工作台帧", check: "状态栏看波特率；原始字节页看是不是可读文本", acts: [{ label: "原始字节", step: "模块" }, { label: "非工作台帧格式", click: ["framedef"] }] },
  { cat: "连接", tax: "target-response-abnormal", sym: "有数据但没心跳 / 状态栏是黄灯", why: "板上固件不是这个工程编出来的、主循环卡死", check: "烧录页核对 HEAD；读黑匣子看复位原因", acts: [{ label: "烧录页", step: "烧录" }, BB] },
  { cat: "烧录与启动", tax: "connection-failure", sym: "烧录失败 / 找不到探针", why: "探针没接好、SWD 线太长、目标没供电、被锁了读保护", check: "烧录页“调试探针”看识别结果", acts: [{ label: "烧录页", step: "烧录" }, DOCTOR] },
  { cat: "烧录与启动", tax: "environment-missing", sym: "编译报缺工具链 / openocd / pyserial", why: "宿主没装或不在 PATH", check: "自检逐项给安装提示", acts: [DOCTOR] },
  { cat: "烧录与启动", tax: "target-response-abnormal", sym: "烧完不运行 / 一直复位", why: "启动模式（BOOT0）不对、时钟或晶振配置错、看门狗、HardFault", check: "读黑匣子看复位原因（看门狗 / 掉电 / 软件复位）", acts: [BB, HF] },
  { cat: "烧录与启动", tax: "target-response-abnormal", sym: "跑一会儿就死机（HardFault）", why: "栈溢出、空指针、未对齐访问、数组越界", check: "让 Agent 用 decode_hardfault 解寄存器；查栈水位", acts: [HF, BB] },
  { cat: "控制", tax: "target-response-abnormal", sym: "方向反 / 越调越歪 / 一上电就打满", why: "传感器轴、误差极性、执行器方向里有一处反了（不是增益问题）", check: "标定页第 0 步极性自检", acts: [{ label: "极性自检", step: "标定" }] },
  { cat: "控制", tax: "target-response-abnormal", sym: "来回振荡 / 啸叫", why: "增益过大、微分噪声、控制周期太长或抖", check: "调参页做扫频看相位裕度；规则建议", acts: [{ label: "调参页", step: "调参" }] },
  { cat: "控制", tax: "target-response-abnormal", sym: "响应慢 / 有静差", why: "增益太小、积分限幅太紧、执行器饱和", check: "做一次阶跃实验看判定", acts: [{ label: "调参页", step: "调参" }] },
  { cat: "控制", tax: "target-response-abnormal", sym: "自己急停 / 报堵转", why: "保护阈值太紧、真的堵了、传感器断线", check: "读黑匣子看是哪条保护；参数栏“保护”页看阈值", acts: [BB, { label: "调参页", step: "调参" }] },
  { cat: "控制", tax: "realtime-violation", sym: "控制周期抖 / 超时", why: "ISR 太长、中断优先级冲突、高频路径用了 float（无 FPU）", check: "联调页事件时间线、心跳条看周期；GPIO 翻转 + 示波器测", acts: [{ label: "联调页", step: "联调" }] },
  { cat: "外设", tax: "target-response-abnormal", sym: "I2C 不应答（传感器读不到）", why: "从机地址错、没上拉（4.7 kΩ）、SDA/SCL 接反", check: "逻辑分析仪抓 SDA/SCL；看驱动的失败计数", acts: [{ label: "模块页", step: "模块" }] },
  { cat: "外设", tax: "target-response-abnormal", sym: "PWM 没输出 / 占空比不对", why: "定时器时钟没开、通道没复用、ARR/CCR 算错", check: "示波器测引脚；占空比 = CCR / (ARR+1)", acts: [{ label: "模块页", step: "模块" }] },
  { cat: "外设", tax: "target-response-abnormal", sym: "ADC 读数跳 / 偏", why: "采样时间不足、输入阻抗大、参考电压不稳", check: "接已知电压对比；加长采样周期", acts: [{ label: "波形测量", click: ["tb-meas"] }] },
  { cat: "参数", tax: "project-config-error", sym: "调好的参数断电就没了", why: "只下发到 RAM，没存 flash / 没写回 yaml", check: "参数页顶部生命周期条看停在哪一站", acts: [{ label: "封箱页", step: "封箱" }] },
  { cat: "参数", tax: "ambiguous-context", sym: "同时接了几块板 / 几个串口", why: "工作台不知道该连哪个", check: "连接下拉里只留一个；拔掉不用的", acts: [DOCTOR] },
];
export function filterSym(q: string): Sym[] {
  const k = q.trim().toLowerCase(); if (!k) return SYMPTOMS;
  return SYMPTOMS.filter(s => (s.sym + s.why + s.check + s.cat + TAX[s.tax]).toLowerCase().includes(k));
}
export function initSymptoms(go: (step: string) => void) {
  const dlg = document.getElementById("sym-dlg") as HTMLDialogElement | null; if (!dlg) return;
  const list = document.getElementById("sym-list")!, q = document.getElementById("sym-q") as HTMLInputElement;
  const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
  const draw = () => {
    const xs = filterSym(q.value);
    list.innerHTML = xs.map((s, i) => `<li><b>${esc(s.sym)}</b> <span class="tag">${esc(s.cat)}</span><span class="tag" title="${s.tax}">${TAX[s.tax]}</span>
      <div class="hint">可能：${esc(s.why)}<br>先验：${esc(s.check)}</div><div class="row">${s.acts.map((a, j) => `<button class="btn sm" type="button" data-i="${i}" data-j="${j}">${esc(a.label)}</button>`).join("")}</div></li>`).join("") || "<li>没有匹配的症状，先跑一次自检</li>";
    list.querySelectorAll<HTMLButtonElement>("button").forEach(b => b.onclick = () => {
      const a = xs[+b.dataset.i!].acts[+b.dataset.j!]; dlg.close();
      if (a.step) go(a.step);
      a.click?.forEach(id => document.getElementById(id)?.click());
    });
  };
  q.oninput = draw;
  document.getElementById("sym-open")!.onclick = () => { draw(); dlg.show(); q.focus(); };
}
