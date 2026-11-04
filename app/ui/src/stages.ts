// 唯一阶段表：首页流程总览和工具箱分组共用。通用于任何项目或比赛题目（「需求」与「题目」并列，不写比赛专用说法）。
// journey = progress.ts 的 7 步旅程 id（后端 progress.get），用来推当前阶段；page = 这一步在工作台里打开哪个内部页。
export type Stage = { id: string; title: string; hint: string; action: string; page: string; journey: string[] };
export const STAGES: Stage[] = [
  { id: "req", title: "读题 / 需求", hint: "把题目或需求写成一句话，工作台据此拆出要做的事", action: "写下需求", page: "项目", journey: ["req"] },
  { id: "plan", title: "出方案", hint: "选主控、模块和控制方法，看每个选择的理由", action: "生成方案", page: "项目", journey: [] },
  { id: "wiring", title: "接线和 BOM", hint: "按方案得到接线表和器件清单，照着接线", action: "查看接线表", page: "模块", journey: [] },
  { id: "project", title: "生成工程", hint: "生成可编译的工程和驱动代码", action: "生成工程", page: "项目", journey: ["project"] },
  { id: "flash", title: "烧录和自检", hint: "把固件烧进板子，上电自检确认接线和外设", action: "去烧录", page: "烧录", journey: [] },
  { id: "debug", title: "调试", hint: "看实时曲线和串口数据，确认每个模块工作正常", action: "开始调试", page: "联调", journey: ["sim", "bringup"] },
  { id: "tune", title: "调参", hint: "让工作台辅助调参，结果卡说明改善了没有", action: "开始调参", page: "调参", journey: ["tune"] },
  { id: "report", title: "测试和报告", hint: "按指标逐项测试打分，导出报告", action: "去测试", page: "评分", journey: ["score", "seal"] },
];
export const stageOfJourney = (j: string | undefined | null) => STAGES.find(s => s.journey.includes(String(j)))?.id ?? STAGES[0].id;
