---
name: freertos-firework
description: 面向当前 MSPM0G3507 + FreeRTOS 下位机仓库的专项分析、修改和验证流程。处理项目架构、app_config、任务、菜单、UART3 上位机协议、ADC/DMA、FFT、DDS、DAC、波形测量或固件回归审查时使用。
---

# freertos_firework 专项技能

本技能只服务当前仓库。不要修改全局 Pi/Qwen 配置，也不要把 Downloads 中的上位机旧代码
当作默认修改目标。

## 按需加载资料

- 跨层功能、初始化、任务或模块归属：读取 `references/architecture.md`。
- UART3 命令、返回格式、页面处理或上位机兼容：读取
  `references/uart3-protocol.md`。
- 要编辑、审查或交付：读取 `references/verification.md`。

只读与当前任务相关的资料，不要一次性读取整个仓库。

## UART3 不可混淆的硬锚点

- `sep1/sep2/sweep1` 的准备成功行与最终数据帧是两个阶段。`start` 只表示最终 128 点
  数据帧开始，绝不是 `sep1` 的准备成功标志。
- `lwavea1` 的 prepared 链路是：发送 `sep1\r\n`；等待相容的
  `MODEL ... A READY`（A/AB READY 均可）；再发送 `lwavea1\r\n`；接收
  `start`、128 个十进制数字行、`end`。
- `lwavea1` 的准备阶段超时为 5 s，进入最终 128 点收集后的超时为 2 s。回答“超时”时
  必须区分这两个阶段。
- `AA + int16 大端 + 55` 是 UART3 可选通用二进制采样解析格式，不是当前
  `lwave* / lspect* / lafc / lpfc` 事务的响应格式；不得把两者写在同一数据帧定义中。
- 看到协议文末兼容附录的 `wave1\0/components\0/spectrum\0` 时先标为历史资料，再回到当前
  `SerialCommunicationUART3DataType_e`、请求表和状态机核对，不能让旧协议覆盖当前实现。

## 工作流程

1. 识别用户要的是解释、诊断、审查还是修改；前三类默认只读。
2. 从仓库根目录运行 `git status --short`，记录并保留已有改动。
3. 使用 `env RIPGREP_CONFIG_PATH=/dev/null rg` 查找声明、调用者、状态和配置宏。
4. 阅读对应 `.h`、`.c`、`application/app_config.h` 和直接相关文档，建立从入口到输出的
   完整链路。
5. 若需修改，选择拥有该职责的最小层，沿用已有静态资源、异步事务和错误状态设计。
6. 按 `references/verification.md` 验证；不能执行的硬件验证要明确标注。
7. 用中文先给结论，再给证据或修改、验证结果和剩余风险。

## 当前硬件命名

- 第二路物理 ADC 是 PB19/ADC1.6；旧 `PA21` ADC 宏、枚举和路由仅为兼容名。
- PA21 当前仍是 COMP2 IN1- 捕获脚。分析第二路测量时必须分别核对 PB19 ADC 与
  PA21 Capture，不能把全部 `PA21` 文本机械替换成 PB19。

## 判断原则

- 当前源码优先于仓库文档；仓库文档优先于外部旧版上位机代码。
- “存在命令字符串”不等于交互已完成。至少验证发送入口、结束符、准备阶段、接收格式、
  成功/错误/超时状态、数据发布和显示/调用方。
- 回答 UART3 时先明确当前处于准备阶段、数据阶段还是普通文本命令页；禁止跨阶段拼接事实。
- 不用猜测填补硬件行为。没有实板、逻辑分析仪或真实串口证据时，写明这是待验证项。
- 不通过大范围重写掩盖局部问题，不修改自动生成文件或 TI SDK。
