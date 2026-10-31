// 例题 / 仿真板专用文字的唯一存放处（tools/check_ui_generic.py 只放过这个文件）。界面其余代码不得写死某道题、某块板。
// 仿真板 id → 中文名：只是“认识的就翻译”，不认识的板子一律退回通用名，不影响功能。
export const SIM_ZH: Record<string, string> = { motor_pos: "电机位置环", motor_speed: "电机速度环", motor_vel: "电机速度环", ball: "小球", ball_beam: "球杆", "2026H_ball": "小球平衡", pan_tilt: "云台", balance: "平衡车", line: "循迹小车", car: "小车", servo: "舵机", heater: "温控", thermal: "温控" };
// 「从示例开始」的默认例题：后端还没有列例题的 op；有了之后改成取列表第一项
export const DEFAULT_EXAMPLE = "2026H_ball";
