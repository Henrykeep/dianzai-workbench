# freertos_firework 项目协作规则

## 项目身份与默认范围

- 这是运行在 TI MSPM0G3507 上的 FreeRTOS 下位机固件，不是上位机项目。
- 默认修改目标仅限当前仓库。Downloads 中的 `porting_code`、`porting_code (1)`、
  `1.md`、`key2.md` 等只可作为协议参考；除非用户明确改变目标，否则不要编辑它们。
- 不修改全局 Pi 配置、本地 Qwen/llama-server 配置、模型文件或训练数据。
- 工作区经常带有用户尚未提交的改动。先运行 `git status --short`，保留并绕开无关改动；
  禁止用 reset、checkout 或批量格式化清除它们。

## 先取证再回答

- 代码是当前行为的首要事实来源，仓库文档次之，外部旧版上位机代码最后。
- 不要仅根据命令清单或旧协议文档断言“已实现”；必须定位发送入口、接收状态机、
  数据发布和显示路径。
- 回答“如何处理”时给出完整调用链，并区分已由源码确认的事实与推断。
- 当前 CCS 环境设置了一个特殊的 `RIPGREP_CONFIG_PATH`，会把 SDK 文件混入普通搜索。
  在本仓库执行 ripgrep 时使用：

  ```bash
  env RIPGREP_CONFIG_PATH=/dev/null rg ...
  ```

- 搜索时排除 `Debug/`、`Release/` 和生成物；不要扫描或修改 TI SDK 源码。

## 分层和关键入口

- `main.c`：只进入框架、启动调度器以及处理致命故障。
- `application/application.c`：按依赖顺序完成总装配与安全关断。
- `application/app_config.h`：Application 功能开关和产品参数的唯一入口。
- `application/task/task_manager.*`：Application 静态 TCB、任务栈、优先级和创建状态。
- `application/menu/display_menu/display_menu.c`：菜单、按键交互、页面状态和异步结果显示。
- `application/communication/serial_communication/serial_communication.*`：UART 注册、收发、
  UART3 文本/数值解析、事务、错误和超时。
- `application/waveform/`：测量、映射、触发保存与输出等业务编排。
- `modules/`：可复用功能和算法，不直接使用 TI DriverLib。
- `bsp/`：唯一允许直接使用 DriverLib、SysConfig 宏和芯片寄存器的层。
- `blink_led.syscfg`：外设资源配置源；不要手改 CCS/SysConfig 生成文件。

典型 UART3 页面链路：

```text
菜单/按键 -> display_menu 页面状态 -> UART3 请求/准备命令
         -> serial_communication 接收任务与超时状态机
         -> 128 点波形订阅或 FFTAnalysis 外部频谱发布
         -> display_menu 轮询状态并刷新 LCD
```

## 嵌入式约束

- 延续静态资源设计；不要引入 `malloc`、无界数组、递归或大块任务栈局部变量。
- ISR 只做最少工作。串口回调、订阅回调和菜单任务不能执行不可控的长时间阻塞。
- Application 新任务必须登记到 `ApplicationTask_e` 并由 `ApplicationTaskCreate()` 创建；
  不在业务文件中直接创建未登记任务。
- 跨任务共享状态要沿用现有临界区、快照或订阅机制，并检查取消、迟到响应、超时和重入。
- 修改功能前检查对应 `APP_ENABLE_*` 条件编译分支；关闭功能时也必须能编译。
- 保持现有 C 风格、定宽整数、单位后缀和公开头文件注释。除非任务要求，不做无关重构。

## UART3 专项约束

- 当前新协议命令以 `\r\n` 结束；`tools/uart3_host_simulator/UART3上位机通信协议.md`
  文末的 `wave1\0/components\0/spectrum\0` 只属于历史兼容附录，不能覆盖当前源码事实。
- 数据请求分为 `start + 128 个数字 + end` 帧和固定长度裸数字流；不要混用解析规则。
- 成功必须在完整点数和结束条件满足后一次性发布；`error`、格式错误、本地超时、取消和
  迟到响应都必须有确定状态，不能让页面永久停在 WAIT。
- 文本命令可能返回多行。处理 `measure*`、`comp*`、`data`、`adcdiag`、`sweep*`、
  `infer` 时不能只保留第一行。
- 改 UART3 时同时检查串口层、菜单层、`app_config.h` 和上位机模拟器；需要详细映射时
  加载项目技能 `freertos-firework` 的 UART3 参考资料。

## 验证与交付

- 仅分析/解释时不改代码；用户要求修改时才实施。
- 修改后至少运行：

  ```bash
  git diff --check
  tools/pi_project_check.sh --quick
  make -C Debug -j2 all
  ```

- 若改动不涉及可编译源，可说明为何跳过构建。涉及 UART3 时还应使用
  `tools/uart3_host_simulator/` 做对应命令、成功、错误、超时和迟到响应测试；硬件行为
  仍需实板确认。
- 默认用中文交付，先说结论，再列修改文件、验证结果和仍需实板验证的部分。
