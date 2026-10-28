# 更新日志

格式参照 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。
每条末尾标注验证程度：**[上板]** 真实硬件实测；**[仿真]** host-sim / 单元测试通过；**[编译]** 仅交叉编译通过；**[未测]** 未编译或未运行。
时间为 Asia/Shanghai。仓库整体版本见 git 附注标签；各模块另有自己的 VERSION（见 docs/03、docs/13）。

## [未发布]

### Agent 评测扩展到 2026H 球杆仿真
- `dzbench.json` 改为按对象的 `step_tests`（car_2wd / 2026H_ball），按遥测字段自动选；可带 start 命令与 gains 映射。**[仿真]**
- 2026H 仿真加入假 QD4310 + 球物理，固件新增 DATA id=1 下发球设定值（px，±400 限幅，急停清零）。**[仿真]** 实机 **[未测]**。
- 离线助手：建议里正确写出参数名（以前会显示 None）；要改的文件参数表和当前板子对不上时拒绝改。**[仿真]**
- 修复：超长工具结果被直接截成非法 JSON，导致 12 KB 的 project.yaml 读不出来；现在只截断文本并标 truncated，上限 16 000 字符。**[仿真]**
- 评测集在 car_2wd、2026H_ball 两块仿真板上都是 8/8，已加入 make test。**[仿真]**

## [0.4.0] - 2026-10-29 IMU 数据源 + Agent 端到端 + 版本号统一

### 版本号统一
- 从 0.4.0 起，仓库只用一个版本号：安装包、侧车 `__version__`、tauri / Cargo / package.json 和仓库标签 `vX.Y.Z` 都相同。`make check` 新增 `tools/check_version.py` 做一致性检查。
- 历史说明：`v0.3.0` 是固件和仓库的里程碑标签，当时的安装包按 `app-v*` 标签走到了 0.3.2，两套版本号并存。v0.3.0 已推送，保留不动。从这一版起，app-windows CI 也会在 `v*` 标签上出安装包。

### Agent：从用户视角走通“打开 → 连板 → 问调参”
- 没填 Key 时问 Agent 不再报“没有 API Key”，改由**离线规则助手**回答（`agent/offline.py`）。它走同一套工具、护栏和确认流程。配置了大模型但连不上时，会自动退回离线助手。**[仿真]**
- 评测集可以在仿真板上真跑：`python -m dzbench.agent.evals`。离线助手在 car_2wd 上 8/8 通过，已加入端到端测试。**真实大模型没跑过 [未测]**。
- tune_context 带上一轮实验的 `last_verdict`（是否稳定、是否不对称、建议），LLM 和离线助手都据此决定先 observe 还是改参数。
- 界面改动：
  - 空闲面板加了 4 个示例问题，点一下直接问；
  - 每条回答标出是谁在答（离线 / 大模型名）；
  - 修复：工具事件比回答晚到时，工具标签会丢失。
  - 截图：`app-first-run.png`、`app-agent-offline.png`。

### IMU：给加速度前馈接上真实数据源
- PAL 1.1.0 新增阻塞式 `pal_i2c_mem_read/mem_write` 和 `pal_spi_xfer`（一个 SPI id 对应一颗芯片，片选由移植层软件控制）。board.yaml 新增 `i2c` 和 `spi` 资源类型，引脚和复用检查都在 boardlib 里。
- 各移植层：
  - host-sim 2.0.0：可以挂假芯片回调，能注入 I2C/SPI 故障。故障枚举改了，所以升了主版本。
  - stm32f4-hal 1.1.0：用 HAL I2C/SPI 实现，生成器加了 I2C1-3、SPI1-3 的复用表。共用总线的两个条目 mode 或速率不同时，会重新初始化 SPI。**[编译]**
  - stm32-cubemx 1.2.0：用 CubeMX 的 hi2cN/hspiN 句柄实现；CubeMX 没启用对应模块时返回 ENOTSUP。**[编译]**
  - mspm0-driverlib 0.2.0：I2C/SPI 返回 ENOTSUP，board check 会给出警告。MSPM0 主控要用 IMU，请走 UART 姿态模块。
- 新驱动和算法：
  - `drivers/mpu6050` 1.0.0：I2C，写寄存器后读回校验，带零偏标定。
  - `drivers/bmi088` 1.0.0：SPI，处理了加速度计上电后的哑读切换 SPI 和哑字节，带温度读取。
  - `algo/attitude` 1.0.0：互补滤波求 roll/pitch，加速度门限在晃动时停止修正。
  - `proto/dzimu` 1.0.0：姿态模块到主控的数据帧，DATA 通道 0x20，37 字节。
  - 以上全部 **[仿真]**：tests/host/test_imu.c 用假芯片测寄存器序列、换算、无应答、片选接反、读回不一致、标定失败不改零偏。**真芯片未测**。
- 新应用 `apps/imu_module`：RM C 型板读 BMI088 → 开机静止 1 s 标定零偏 → 1 kHz 互补滤波 → 从 IMU 串口（丝印 UART2 = USART1）以 200 Hz 发 dzimu。dji-rm-c 板做了这些改动：
  - 加了 BMI088 的 SPI1 资源；
  - HSE 填 12 MHz（取自社区 C 板工程的 .ioc，**未对照实物核实**）；
  - 原来没被使用的 `UART2` 改名为 `IMU`。
  - 已加入 `make cross`。**[编译]**，**未上板**。
- 2026H io 层按板上资源在编译期选 IMU 来源：有 uart IMU 就解 dzimu，否则有 i2c IMU 就轮询 MPU6050，都没有时 imu_ok 恒为 false。
  - 新参数 `imu_axis` 选哪根轴朝车头。
  - 遥测增加 `imu_ax_mps2` / `imu_ok`。
  - 仿真板会以 200 Hz 发假 dzimu 帧，sidecar 端到端测试检查 imu_ok=1 和 imu_axis 的限幅。**[仿真]**
  - 注意：车身俯仰时，重力分量会混进前向加速度。

### ELF 变量观察
- 通道栏的“ELF 变量”：输入变量名时从 ELF 符号表联想；“开始观察”后通过 SWD 直接读内存，样本走虚拟通道画线，不用改固件。sidecar 新增 elf_symbols、watch_start、watch_stop。
- 已对照验证：
  - 真 F407 ELF（2026H_ball）的 222 个符号，地址和大小与 arm-none-eabi-nm 全部一致；
  - 用假探针测过 service 层的 watch，flash dry_run 和 HardFault 分核解码也都有测试。
- **真探针未实测**。

### 波形与导出
- 波形只送时间窗内的数据，并按像素列做 min/max 抽稀：30 s × 1 kHz 不卡，尖峰不会丢。
- 通道栏可以按名字选通道（`bb_* err`，支持 * 通配）。
- Shift+点击“导出 CSV”导出 PlotJuggler 格式（.pj.csv，无 BOM，时间列 time，只含数值列）。PlotJuggler 本身没装过，**未实测**。

## [0.3.0] - 2026-10-29 MSPM0 实生成 + 视觉链路

### 视觉工具
- `host/maixcam/ball_tracker.py`：自写钢珠跟踪器（ROI、多重门限、α-β 外推、丢失后重捕获），已接入 ball_sender。PC 合成测试通过，**实机未测**，LAB 阈值是占位值。
- `python -m dzlink.latency`：stats 模式给出帧率/丢帧/抖动，flash 模式用屏幕闪点法测绝对延迟。计算部分有测试，**实机未测**。

### 视觉链路与钢珠环 A/B 选项
- 新模块 `firmware/algo/vision` 1.0.0：
  - `vis_link` 有 VALID/HELD/LOST 三态，给出数据时效 age_ms、按 8 位 seq 统计的丢帧数、相对延迟抖动；
  - `vis_calib` 做 2..9 点分段线性标定，左右斜率独立，表外外推并提示。
- 新模块 `firmware/algo/abobs` 1.0.0：通用 α-β 观测器，带野值门限，外推超时后速度清零。
- `ball_beam` 1.1.0 增加 A/B 选项（全 0 时就是原行为）：估计器 α-β 或差分+低通；串级或单环；静摩擦补偿；静平衡前馈表。
- 2026H：
  - vision 子系统改用 vis_link/vis_calib（参数 vis_*、cal_*）；
  - io 层记录 dzframe seq 和相机时间戳；
  - 加速度前馈可选编码器或 IMU，带死区和失效保护：无效、过期或异常大的读数都让前馈归 0；
  - 遥测增加 vis_state/vis_age_ms/vis_drops/vis_lat_ms/ff_deg。
- **IMU 没有驱动**，io 层不会填 imu_* 字段，所以 ff_src=1 时前馈恒为 0（这正是失效保护该有的行为）。实板**未测**。
### 修复
- 2026H 在 F407 目标板上编译失败：看门狗变量在没有 LINK 串口的板上未被使用，触发 -Werror。原因是 make check 不做交叉编译。新增 `make cross`（全部 板×应用 组合），并加入 CI `firmware` 工作流。

### 板卡与 VS Code
- 新板 `mspm0g3507-launchpad`（TI LP-MSPM0G3507）：LED/KEY/UART 引脚已对照 SDK 官方 LP 例程；syscfg 由 CLI 生成；car_2wd 编译通过；**未上板**。
- `make compdb` 生成 compile_commands.json；新增 `.vscode/c_cpp_properties.json`，含 GCC、CCS(Debug/) 和 STM32 三套配置；docs/16 补充 ArmClang 与 GCC 的取舍、SDK 版本锁、XDS110/DAPLink。**未在 VS Code 里实测**。

### MSPM0 SysConfig CLI
- 【已实测】`tools/syscfg_gen.sh` 用 SysConfig CLI 1.28.0 + SDK 2.11 重新生成天猛星 `ti_msp_dl_config`，入库文件换成真实生成物；car_2wd 用它交叉编译通过。CI `firmware` 工作流负责比对和编译（首次运行已通过）。
- 真 CLI 发现的问题：GPIO 引脚 `$name` 不能都叫 `PIN`，改为逻辑名（宏改为 `GPIO_<名>_<名>_PIN`）；定时器没有 `CLK_FREQ`，board.yaml 的 timer 加 `clk_hz`（schema 已更新）。
- STM32F4 PAL 也改用 `dz_wrap.h`。

### 编码器 1.1.0
- `firmware/common/dz_wrap.h`：16/32 位计数回绕差分，MSPM0 PAL 改用它，有主机测试。
- `encoder_cfg_t.window_n`：滑动窗口测速（M 法加长窗口），适合低 PPR + 高频控制。真 M/T 法需要边沿捕获，**未实现**。实板**未测**。

### 调参实验
- experiment.py：相对基线打分 + 权重模板（balanced/conservative/actuator）、四段正负阶跃 + 不对称提示、稳态原因码、分阶段 P→I→D（无 LLM 默认）、开环 plant_stable 门禁、群体搜索仅仿真 [仿真]
- 护栏：慢但未进调节带不再算不稳定（修 sluggish 调不动）[仿真]
- Agent 规则 8–11（事实/推断、先读再改、看稳态原因码、待实板确认）+ evals.json 评测集与打分器（未在真实 LLM 上跑）
- 参数面板：有草稿时显示"板上"生效值 [编译]
- docs/19 赛题覆盖矩阵（题名待核对）

### 安全
- dzctl 0.2.0：上位机心跳看门狗 `dzctl_wd_*`，car_2wd / 2026H 接入：调参中侧车崩溃或拔线 1 s -> 输出归零并锁存急停；侧车每 250 ms 发心跳（仅对已识别的工作台固件）[仿真]

### MSPM0 校验
- board.yaml 校验 mspm0 系列：复用表从 SDK `mspm0g350x.h` 自动生成；QEI 只许 TIMG8、TIMG8 不能同时做 PWM；PA0/1、PA2–6、PA19/20、PA21/23 坑脚警告；引脚冲突（如 UART0 PA10/11 与 I2C1）；PWM 分频可行性 [编译]
- check_deps D1：DL_xxx() 必须在 SDK 头文件存在；TIMA 实例不得用 DL_TimerG_*（含别名宏）[编译]
### 新增
- Agent 风险分级（auto / log / human / forbid，未登记工具默认禁止，审计日志）与“需要你确认”动作卡 [仿真]；调参护栏（双向+绝对单步限制、0 起步小值、每轮一项、变差方向禁止、程序判定达标/回滚/停止、实机 8 轮、电量/温度门限、实机回滚要人点）、紧凑上下文、严格回复解析、无 LLM 规则模式、固定种子基准 [仿真]。思路参考 llm-pid-tuner（MIT）、embeddedskills（MIT）
- 工具链：pyOCD 烧录（前置条件、默认 dry-run、烧前备份、烧后心跳哈希校验、回滚）、Keil `UV4 -b` 日志解析、分层配置 `dzbench.json` + `~/.dzbench/machine.json`、按内核 HardFault 解码（M0+ 无 CFSR）、ELF 符号 + 按变量名轮询曲线 [仿真]（假探针/日志样本单测）；真实探针、Keil、真实故障 [未测]
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
- Windows：Makefile 导出 PYTHONUTF8=1，侧车调 make 也带上（工具打印 ✓ 在 cp1252 控制台崩溃）；依赖 host-sim 的 toolchain 测试在 Windows 上跳过 [编译]
- 侧车在 Windows 上读写 UTF-8 文件/子进程输出：全部显式 `encoding="utf-8"`（CI app-v0.3.0 在 cp1252 下失败）[编译]；安装包版本号 0.3.1（之前文件名误为 0.1.0）
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
