# 设计决策表（v9）

只取大厂设计规范和桌面工具的公开资料；每行给出处和我们采用的值。代码一律不搬，只学写法。
GPL 项目（betaflight-configurator）只参考思路和布局，不看样式文件、不复制代码。

## 1. 设计规范

| 主题 | 出处 | 对方做法 | 我们采用的值 |
|---|---|---|---|
| 字号阶梯 | [Primer Typography](https://primer.style/product/primitives/typography) | 12/14/16/20/24/32/40，正文 14 | 5 级 12/14/16/20/32，正文 14，行高 1.5 |
| 间距 | [Fluent 2 Layout](https://fluent2.microsoft.design/layout/) | 4px 基准，2–56 阶梯 | 4/8/12/16/24/32（`--sp1..6`） |
| 设计变量分层 | [microsoft/fluentui tokens](https://github.com/microsoft/fluentui/tree/master/packages/tokens) | 全局值 → 语义别名 | `tokens.css` 唯一来源；组件只用语义变量，`check_ui_layout` 守 |
| 侧栏宽度 | [Fluent 2 Nav](https://fluent2.microsoft.design/components/web/react/core/nav/usage/) | 默认 260，窄屏成浮层 | 200 / 收起 56；≤1500px 自动收起 |
| 按钮主次 | [primer/react Button](https://primer.style/product/components/button) | 每区一个 primary，其余 default/invisible | 每区最多 1 个主按钮；区域按钮数上限见 `check_ui_layout.py` |
| 密度 | [Geist](https://vercel.com/geist/introduction) / [Atlassian spacing](https://atlassian.design/foundations/spacing) | 中性灰底、细分隔线、少阴影 | 卡片 1px 发丝线 `--hair`，阴影只给浮层 |
| 圆角 | [Fluent 2 Shapes](https://fluent2.microsoft.design/shapes) | 2/4/8 小圆角 | 4/6/8，大浮层 14 |
| 空状态 | [Ant Design Empty](https://ant.design/components/empty) / [Arco Empty](https://arco.design/react/components/empty) | 图标 + 一句说明 + 一个动作 | 空状态卡：说明为什么空 + 唯一下一步按钮 |
| 报错 | [Ant Design Result/Alert](https://ant.design/components/alert) | 原因 + 处理办法同句 | 告警条「原因 · 怎么恢复」，指向已有按钮不新增入口 |
| 对话框关闭 | [Apple HIG Modality](https://developer.apple.com/design/human-interface-guidelines/modality) / [Fluent Dialog](https://fluent2.microsoft.design/components/web/react/core/dialog/usage) | 明确关闭控件 | 右上角 × + 点框外；**Esc 永远急停**，不关窗 |
| 色彩 | [Feishu 设计](https://design.feishu.cn/) / [Arco 色彩](https://arco.design/docs/designlab/color) | 单主色 + 语义色 | 单主色琥珀 + ok/warn/err；全站不用紫 |

## 2. 桌面工具

| 主题 | 出处 | 对方做法 | 我们采用的值 |
|---|---|---|---|
| 活动栏/侧栏 | [VS Code UX Guidelines](https://code.visualstudio.com/api/ux-guidelines/overview)，源码 `microsoft/vscode` `src/vs/workbench/browser/parts/` | 左侧图标栏 + 可收起侧栏，当前项左色条 | 左导航当前项 `inset 2px` 主色条，收起只剩图标 |
| 面板分割 | VS Code `sash`、[JetBrains Tool windows](https://www.jetbrains.com/help/idea/tool-windows.html) | 可拖分割、记忆尺寸 | 三栏 `--w-left/--w-side`，后续加拖拽（不引依赖） |
| 状态栏 | [VS Code Status Bar](https://code.visualstudio.com/api/ux-guidelines/status-bar) | 只读状态，左全局右上下文 | 状态栏只读：左链路心跳，右记录回放 |
| 命令面板 | [VS Code Command Palette](https://code.visualstudio.com/api/ux-guidelines/command-palette)、[pacocoursey/cmdk](https://github.com/pacocoursey/cmdk) | 一个快捷键搜全部动作 | 工具箱即命令入口；动作清单来自 `entrypoints.yaml`，不另开入口 |
| 侧栏层级 | [Linear](https://linear.app/docs) / [Figma UI3](https://help.figma.com/hc/en-us/articles/23954856027159) | 低对比侧栏、分组小标题 | 导航底色 `--s0`，分组标签 12px `--dim` |
| 飞书客户端 | [飞书帮助中心](https://www.feishu.cn/hc/zh-CN/) | 窄导航 + 顶部只留搜索和全局 | 顶栏只留连接胶囊、排障、工具箱、急停 |
| 调参上位机 | [betaflight-configurator](https://github.com/betaflight/betaflight-configurator)（GPL，仅看布局） | 左侧按功能分页、顶部连接、PID 表格 + 实时曲线 | 同思路：左步骤导航 / 顶部连接胶囊 / 参数列 + 曲线；不复用任何代码样式 |
| 多曲线对比 | [PlotJuggler](https://github.com/facontidavide/PlotJuggler)（MPL-2.0） | 拖拽分屏、多曲线叠加、时间轴联动 | 示波器多通道共享时间轴；拖拽分屏列入后续 |
| Tauri 桌面布局 | [mountain-loop/yaak](https://github.com/mountain-loop/yaak)（MIT） | Tauri 应用：侧栏 + 分割面板 + 命令面板 | 同为 Tauri，学分割面板与 ⌘K 写法；未借代码 |
| 图标侧栏 + 状态栏 | [podman-desktop](https://github.com/podman-desktop/podman-desktop)（Apache-2.0） | 可收起图标侧栏、底部状态栏 | 对应左侧导航收起态 56px 与只读状态栏 |
| 实时时序面板 | [rerun-io/rerun](https://github.com/rerun-io/rerun)（Apache-2.0） | 时序面板拼接、共享时间游标 | 波形多通道共享时间轴，后续做面板拼接 |
| 请求/响应双栏 | [usebruno/bruno](https://github.com/usebruno/bruno)（MIT）、[Kong/insomnia](https://github.com/Kong/insomnia)（Apache-2.0） | 左列表、中编辑、右结果 | 调参页「参数列 → 曲线 → Agent」三栏 |
| 嵌入式 IDE | Eclipse Theia（EPL）、Arduino IDE 2（AGPL） | 板卡/端口选择在顶栏 | 只看思路：连接胶囊放顶栏；不搬代码 |

## 3. 待拍板（未引入）
- 本轮未借用任何外部代码片段；以上均为学习布局思路。
- 不引新依赖。uPlot 已在仓库（MIT）；如要拖拽分屏或命令面板库（cmdk 为 MIT、React 依赖）需先过许可证确认。

## 4. 文案规范

依据：[Ant Design 文案规范](https://ant.design/docs/spec/copywriting-cn)、[Fluent 2 Content design](https://fluent2.microsoft.design/content-design)、[Microsoft Writing Style Guide](https://learn.microsoft.com/style-guide/welcome/)。

| 规则 | 写法 | 例 |
|---|---|---|
| 按钮 | 动词开头，2–4 个字；带对象时为「动词 + 对象」 | 新建工程、写入 Flash、配置模型、解除、处理 |
| 状态 | 用术语，不用口语 | 未连接、进行中、已完成、已阻塞、已锁定 |
| 语气 | 不用语气词、感叹号、emoji；不寒暄 | ✗「还没接上哦！」 ✓「未连接」 |
| 提示与报错 | 三段：发生了什么 · 原因 · 怎么处理 | 「已急停 · 原因：1.6 s 未收到心跳 · 处理：排除原因后点击右上角「解除」」 |
| Agent 回复 | 结论放第一句；可执行操作做成按钮；不复述问题、不寒暄 | 「建议 kp 降到 0.8。」+［采纳］ |
| 空状态 | 说明这一页做什么 + 一个开始按钮 | 「Agent 未配置。原因…处理：点击「配置模型」」 |
| 快捷键 | 写进 title，不写在正文按钮里 | 急停 Space / Esc |

### 术语表（全产品一种叫法）

| 术语 | 含义 | 不再使用 |
|---|---|---|
| 烧录 | 把固件写入目标板 | 下载、刷机、烧写 |
| 急停 | 立即停止输出并锁定，需「解除」恢复 | 紧急停止、停车、刹车 |
| 解除 | 解除急停锁定 | 恢复、复位 |
| 自整定 | 继电器法测临界增益并给出初始 PID | 一键起步、自动调参、无初值起步 |
| 下发 | 把参数写到板上 RAM（掉电丢失） | 发送、应用、写入 |
| 参数持久化 | 把 RAM 参数写入 Flash（掉电保留），按钮「写入 Flash」 | 存 flash、固化、保存到板子 |
| 评分 | 按评分项逐项实测并留证据 | 打分、验收、测评 |
| 项目 | 一套需求对应的工程与记录 | 赛题（仅作为项目类型时使用） |
| 目标板 | 被调试的硬件；仿真也算 | 板子、下位机 |
| 大模型 | Agent 使用的 LLM 服务 | AI、模型服务 |

## 5. 层级与分辨率
| 规则 | 出处 | 我们采用的值 |
|---|---|---|
| 层级靠间距与分隔线 | [Atlassian spacing](https://atlassian.design/foundations/spacing)、[Primer Divider/Box](https://primer.style/product/primitives/) | 组内 `--sp2`，组间 `--sp5`，区块之间 1px `--hair` |
| 表面层级 | [Fluent 2 Elevation](https://fluent2.microsoft.design/elevation) | `--s0` 导航 / `--s1` 页面 / `--s2` 卡片 / `--s3` 选中，阴影只给浮层 |
| 正文字号与对比 | [Primer](https://primer.style/product/primitives/typography)、[WCAG 2.2 1.4.3](https://www.w3.org/TR/WCAG22/#contrast-minimum) | 正文 14px；次要文字对比度 ≥ 4.5:1 |
| 等宽字体 | [Geist Mono 用法](https://vercel.com/font) | 只用于数值、代码、路径 |
| 最低分辨率 | [Fluent 2 Layout breakpoints](https://fluent2.microsoft.design/layout/) | 1366×768 起；≤1500px 导航收起 |
