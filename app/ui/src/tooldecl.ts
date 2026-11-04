// 工具箱本地声明表：后端 tool_list 上线前的数据源（清单来自 /workspace/refs/USAGE_MATRIX.md「工具箱工具清单」+ 原工具箱已有入口）。
// 只写工具本身的事实（用途、依赖、出处、许可），不写题目或板子。阶段 id 用 stages.ts 的 id（唯一一张阶段表）。
// needs: sidecar = 要本地服务；board = 还要连着板子。built: false = 尚未接入（只占卡位，不假装能用）。
// ui: 工具页里复用的原有控件 id（入口登记在 docs/dev/entrypoints.yaml，控件仍在 #toolbox-m 里）；run: 主操作点哪个控件 / 打开哪个嵌入页。
export type ToolDecl = { id: string; stage: string; icon: string; name_zh: string; summary_zh: string; applies_to: string[]; agent_callable: boolean;
  needs: "none" | "sidecar" | "board"; real_port?: boolean; built: boolean; advanced?: boolean; source: string; license: string; owner?: string;
  ui?: string[]; run?: { click?: string; hook?: string; mount?: string; label: string; writes?: boolean; touches_board?: boolean; changes_zh?: string }; detail?: string };
export const TOOL_DECLS: ToolDecl[] = [
  { id: "serial_term", stage: "debug", icon: "terminal", name_zh: "串口调试", summary_zh: "收发文本 / HEX、时间戳、发送框，按帧描述把通道画成曲线",
    applies_to: ["任意串口设备"], agent_callable: false, needs: "sidecar", built: true, source: "工作台自有（交互参考 SerialWeb；原版待 vendor-tools 合入后挂载）", license: "本仓库",
    run: { mount: "serial", label: "开始监视" }, detail: "串口经本地服务（ws.ts → connect / send_raw / raw_monitor / serial_lines_set），不走浏览器 Web Serial；工具本体由 vendor-tools 分支提供，挂载路径见 serialslot.ts" },
  { id: "wave_meas", stage: "debug", icon: "ruler", name_zh: "波形测量", summary_zh: "对采到的波形看频谱、频率、幅值、占空比、相位",
    applies_to: ["已连接的板子或仿真板"], agent_callable: true, needs: "board", built: true, source: "工作台自有 spectrum.py / wavemeas.py", license: "本仓库",
    ui: ["tb-meas"], run: { click: "tb-meas", label: "打开频谱视图" } },
  { id: "framedef", stage: "debug", icon: "binary", name_zh: "帧格式", summary_zh: "别家固件发的数据怎么解析成通道",
    applies_to: ["key=value 文本", "JustFloat", "FireWater", "自定义帧"], agent_callable: false, needs: "sidecar", built: true, source: "工作台自有 framedef.py", license: "本仓库",
    ui: ["framedef", "framedef-n", "fd-custom"], run: { hook: "framedef", label: "应用帧格式", touches_board: false } },
  { id: "serial_ln", stage: "flash", icon: "cable", name_zh: "串口线控", summary_zh: "串口线控制：复位、进下载模式（DTR / RTS）",
    applies_to: ["ESP32 / STM32 一键下载电路"], agent_callable: false, needs: "board", real_port: true, built: true, advanced: true, source: "工作台自有 session.py", license: "本仓库",
    ui: ["lines-btn"], run: { click: "lines-btn", label: "打开线控", touches_board: true, changes_zh: "会改变 DTR / RTS 电平，板子可能复位或进入 BOOT" } },
  { id: "log_replay", stage: "report", icon: "history", name_zh: "日志回放", summary_zh: "打开录下的记录，回放、导出 CSV / VOFA+，或导入别的工具的曲线",
    applies_to: [".dzlog", "CSV", "VOFA+ 文本"], agent_callable: false, needs: "sidecar", built: true, source: "工作台自有 replay.py / logio.py", license: "本仓库",
    ui: ["logs", "exp-fmt", "export", "imp-path", "import"], run: { click: "replay", label: "回放这份记录" } },
  { id: "flash", stage: "flash", icon: "zap", name_zh: "烧录", summary_zh: "一键把固件烧进板子并校验",
    applies_to: ["pyOCD 支持的探针"], agent_callable: true, needs: "board", built: false, source: "工作台自有 flash.py（pyOCD）", license: "Apache-2.0（pyOCD）", owner: "前端（烧录页已有，工具卡待接）" },
  { id: "cubemx", stage: "project", icon: "cpu", name_zh: "STM32 工程生成", summary_zh: "从 .ioc 无头生成并构建 CubeMX 工程",
    applies_to: ["STM32 + 本机 CubeMX"], agent_callable: false, needs: "sidecar", built: false, source: "mcp-stm32cubeide-server", license: "MIT", owner: "后端（项目页分步生成已接，工具卡待接）" },
  { id: "dashboard", stage: "debug", icon: "gauge", name_zh: "数据看板", summary_zh: "按帧描述把通道自动摆成曲线、仪表、数值",
    applies_to: ["任意帧描述"], agent_callable: false, needs: "board", built: true, source: "工作台自有（Serial-Studio 只参考思路）", license: "本仓库",
    run: { mount: "dashboard", label: "开始显示" } },
  { id: "fft_psd", stage: "debug", icon: "activity", name_zh: "FFT / 噪声谱", summary_zh: "Welch 功率谱和峰值插值，看噪声和干扰频率",
    applies_to: ["采到的任意波形"], agent_callable: true, needs: "sidecar", built: false, source: "mcp-hardware-tools analysis/spectrum.py", license: "Apache-2.0", owner: "后端，分支未开" },
  { id: "dds", stage: "debug", icon: "audio-waveform", name_zh: "DDS 信号源", summary_zh: "让板子或信号源输出指定波形",
    applies_to: ["带 DDS 固件模块的板子", "JDS6600 信号源"], agent_callable: false, needs: "board", built: false, source: "LP-MSPM0G3507_freertos_firework / mcp-hardware-tools", license: "MIT / Apache-2.0", owner: "嵌入式开发-2，分支未开" },
  { id: "visa", stage: "report", icon: "scan-line", name_zh: "仪器读数（VISA）", summary_zh: "读示波器测量值和波形，存成评分证据",
    applies_to: ["USB / LAN 示波器"], agent_callable: true, needs: "sidecar", built: false, source: "mcp-hardware-tools transport/visa.py", license: "Apache-2.0", owner: "后端，分支未开" },
  { id: "hardfault", stage: "debug", icon: "bug", name_zh: "故障诊断（HardFault）", summary_zh: "板子死机后读寄存器，说明原因",
    applies_to: ["Cortex-M"], agent_callable: true, needs: "board", built: false, source: "工作台自有 hardfault.py", license: "本仓库", owner: "嵌入式开发-2，分支未开" },
  { id: "coproc", stage: "flash", icon: "server", name_zh: "协处理器部署", summary_zh: "给 MaixCAM / K230 / 树莓派等推脚本、启停、看日志",
    applies_to: ["SSH 密钥登录的协处理器"], agent_callable: false, needs: "sidecar", built: true, advanced: true, source: "工作台自有 deploy.py", license: "本仓库",
    ui: ["fw-coproc"], run: { click: "fw-coproc", label: "打开部署", writes: true, changes_zh: "会通过 SSH 把脚本写到协处理器并启动" } },
  { id: "rc_calc", stage: "plan", icon: "activity", name_zh: "滤波 / RC 计算", summary_zh: "给截止频率算 RC 取值，或反过来", applies_to: ["一阶 RC、二阶 Sallen-Key"], agent_callable: true,
    needs: "none", built: false, source: "资料去向表（scipy.signal 思路）", license: "BSD-3（scipy）", owner: "前端，分支未开" },
  { id: "pid_disc", stage: "tune", icon: "binary", name_zh: "PID 离散化", summary_zh: "把连续 PID 参数按采样周期换成离散形式，导出 C 头", applies_to: ["位置式 / 增量式 PID"], agent_callable: true,
    needs: "none", built: false, source: "资料去向表（python-control 思路）", license: "BSD-3（python-control）", owner: "前端，分支未开" },
];
