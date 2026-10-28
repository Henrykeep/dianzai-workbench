# 更新日志

格式参照 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。
每条末尾标注验证程度：**[上板]** 真实硬件实测；**[仿真]** host-sim / 单元测试通过；**[编译]** 仅交叉编译通过；**[未测]** 未编译或未运行。
时间为 Asia/Shanghai。仓库整体版本见 git 附注标签；各模块另有自己的 VERSION（见 docs/03、docs/13）。

## [未发布]
### 新增
- 工作台：预设“⚡”触发发送 UI（字段 比较符 值，显示已触发次数），预设增删/定时/触发向所有客户端广播 [仿真]（截图 app-send.png）
- 工作台：发送栏 + 预设（文本/HEX/命令/DATA，单发/定时/遥测触发，存本机）；急停即停全部定时与触发，侧车发送锁定到解除急停 R；无心跳设备的 `key=value` 文本自动成虚拟 schema，曲线/频谱/触发可用 [仿真]（假串口测试）；真机 [未测]。思路参考 SerialWeb，代码自写
- 工作台：频谱视图（按固件遥测周期 FFT，去直流 + Hann，周期不符/丢帧警告）、回放时间轴（拖动跳转、暂停、倍速）[仿真]
- 工作台：原始监视器（文本/HEX、收发区分、时间戳，非工作台固件设备也能看）、.dzlog→CSV（UTF-8 BOM）、串口自动重连（指数退避；主动断开不重连；重连后重读参数；重连中急停如实报“未送达”）[仿真]（假串口测试）；真实 USB 拔插 [未测]。思路参考 SerialWeb，代码自写
- 根目录 `AGENTS.md` + `llms.txt`，`tools/check_ai_docs.py` 进 `make check` 校验与 docs 索引同步；内置 Agent 把 AGENTS.md 放进系统提示 [仿真]
- Windows 安装包 CI 打通：`app-v0.3.0-rc4` 产出 NSIS 安装包 [编译]（安装与运行 [未测]）
- 内置 Agent（docs/18）：分层写权限网关（secret/frozen/config/app/docs；diff 确认 → 门禁 make check/test → git 提交，失败自动还原，带尾注才可回滚）、急停不可调用、可插拔 OpenAI 兼容大模型（DeepSeek/通义千问/Ollama 等，Key 只存本机）、离线阶跃分析与整定建议、参数写回 yaml [仿真]（假 LLM + 临时 git 仓库测试，playwright 截图）；真实大模型服务商 [未测]；安装版工程仓库设置 [未测]
- 桌面工作台 `app/`（docs/17）：Python 侧车 dzbench（串口/仿真/回放、自动波特率、按心跳哈希自动识别 schema、参数限幅+ACK 重发、急停 3 连发、原始 .dzlog、快照、Agent 只提议接缝）[仿真]；Vite+TS+uPlot 界面 [仿真]（playwright 截图）；真实串口 [未测]；Tauri 外壳与 Windows CI [未测]
- `firmware/proto/dzctl` 0.1.0：参数表读写（限幅、拒 NaN）、急停锁存、命令、心跳带 schema 哈希 [仿真]
- `tools/gen_link.py`：由 yaml `link:` 生成遥测打包/参数表/link_schema.json [仿真]
- host-sim `--stream`：实时模式，LINK 走 stdin/stdout（仅 POSIX）[仿真]
- `firmware/common/dz_compiler.h`：AC6/AC5/IAR/GCC/clang（含 tiarmclang）编译器抽象；`make compat` 以 C99 `-pedantic-errors` 编译全部模块 [编译]（AC5/AC6/IAR/tiarmclang [未测]）
- `tools/keil_inject.py`：幂等向 .uvprojx 注入工作台模块（组/IncludePath/Define，.bak 备份，--dry-run），用户真实工程**副本**测试 [仿真]；Keil 内编译 [未测]
- 模块：`spsc` 采样队列、`key` 消抖（短按/长按/连发）、`qd4310` 串口协议驱动（CRC-8 初值待确认）、`ssd1306` 帧缓冲（Press Start 2P 字体，OFL）、`ball_beam` 单轴球杆控制器 [仿真]
- MaixCAM2 钢珠帧（dzframe 内 7 字节 payload）：`host/maixcam/ball_sender.py` 与 C 端互通测试 [仿真]；相机实机 [未测]
- syscfg_import：新命名（GPIO_<名>_PIN / PWM_<定时器> / ENC QEI·GPIO / TIMER），用 TI SDK 官方例程 .syscfg 核对 [仿真]
- CCS：天猛星 `ccs/tianmengxing.syscfg` + `gen_ccs_projectspec.py` 生成的 tiarmclang 工程，`make vars` [未测]
- VS Code：tasks、Cortex-Debug launch（OpenOCD/pyOCD）、EIDE 说明 [未测]
- docs/14 Keil、docs/15 CCS、docs/16 VS Code 工作流 [未测]
### 变更
- car_2wd / 2026H_ball 的 LINK 改为 dzframe + dzctl（原文本协议移除）；2026H 参数补 min/max/unit [仿真]
- `examples/2026H_ball` 重构为单轴球杆：QD4310 摆杆 + ball_beam + MaixCAM2 视觉；P1/P2 参数标注“来自非最终版比赛代码，未验证” [仿真]；bldc/skystar 交叉编译 [编译]
- F103 / Bldc 板：PWM 改 20 kHz；F103 PA8=LED、PB1=BUZZER、串口 RX DMA 改 Circular；Bldc UART4=BEAM、USART2=VISION [编译]
- skystar / host-sim 增加 BEAM 串口（同一应用换板只改引脚）[编译]
- pid / motor_dc README 补参考来源（PX4、SparkFun），未使用 P1 代码

### 修复
- 工作台：参数面板聚焦中的格子不跟随其他客户端/Agent 改的值 → 未在编辑的格子一律跟随 [仿真]
- 截图脚本：car_2wd DATA id=1 是 (v m/s, w rad/s)，原先按两轮 r/s 发 2/3 被 max_rps=5 限幅成 sp_a=5；固件无误，只改脚本与注释 [仿真]

## [0.2.0] - 2026-10-29 多板验证
### 新增
- `apps/car_2wd`：2 电机 + 2 编码器 + dzframe 遥测的多板验收应用，含闭环仿真测试 [仿真]
- `ports/stm32-cubemx` 1.1.0：F1 系列、RX Normal DMA 重启 / 无 DMA 逐字节中断、TIM 作 HAL 时基、FreeRTOS（默认任务接缝 + `dz_cubemx_tim_callback`）[编译]
- `boards/stm32f103c8t6-car-cubemx`（基于用户 USART.ioc，合成 Core）[编译]
- `boards/stm32f407-bldc-freertos-cubemx`（基于用户 Bldc.ioc，FreeRTOS + TIM1 时基，合成 Core）[编译]
- `ports/mspm0-driverlib` 0.1.0 与 `boards/mspm0g3507-tianmengxing` car_2wd 配置（合成 SysConfig 输出）[编译]
- board.yaml `encoder.mode: gpio_isr`（软件正交解码）[编译]
- ioc_import：PWM < 5 kHz、无标签引脚警告；TIM 时基 / FreeRTOS 一致性检查 [仿真]
- `tools/fetch_third_party.sh` 统一拉取 F1/F4 HAL、FreeRTOS、MSPM0 SDK
- docs/12 参考工程与参数来源、“转 10 圈”编码器标定步骤 [未测]
### 变更
- ioc_import：Normal DMA / 无 DMA 由错误降为警告
- check_deps：允许 FreeRTOS 默认任务固定写法与 TIM 回调转发；SysConfig 生成文件按厂商代码处理（C2）

## [0.1.0] - 2026-10-28 第 0 阶段
### 新增
- PAL 接口、错误码、PID / 一阶低通、motor_dc / encoder 驱动 [仿真]
- board.yaml schema、校验器、代码生成器；天空星 F407（VET6/VGT6）、host-sim [编译]/[仿真]
- 移植层 stm32f4-hal、host-sim；motor_speed_demo [编译]/[仿真]
- 子系统调度 / 协调器框架、gen_project；2026H_ball 实例 [仿真]
- dzframe/1 协议（C + Python dzlink）、协处理板描述、Jetson Nano 视觉板 [仿真]
- check_deps / iface_hash / ioc_import / syscfg_import 第 0 阶段 [仿真]
- docs 01–11

[未发布]: https://github.com/Henrykeep/dianzai-workbench/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Henrykeep/dianzai-workbench/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Henrykeep/dianzai-workbench/releases/tag/v0.1.0
