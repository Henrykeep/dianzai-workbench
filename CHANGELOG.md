# 更新日志

格式参照 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。
每条末尾标注验证程度：**[上板]** 真实硬件实测；**[仿真]** host-sim / 单元测试通过；**[编译]** 仅交叉编译通过；**[未测]** 未编译或未运行。
时间为 Asia/Shanghai。仓库整体版本见 git 附注标签；各模块另有自己的 VERSION（见 docs/03、docs/13）。

## [未发布]
- [仿真] 外部代码改为“可直接使用、注明来源”：新目录 `third_party/vendored/`（提交进仓库，其余 third_party 仍是下载的官方 SDK），GPL/AGPL 代码一律隔离在此、经薄适配层调用；`tools/check_vendored.py` 进 make check：每个来源须有 LICENSE、SOURCE.md（Source: repo@commit path），每个代码文件头 15 行内有 Source:，且已在 docs/参考来源.md 登记。参考来源.md 开头改写两种借鉴方式。
- [仿真] 参数面板加“回读”按钮（op params_readback 不带 path 时写 ~/.dzbench/readback/params-<时间>.txt）；polarity_check 暂登记为脚本专用（向导界面未做）。修第 8 项 preflight 的 test_wiring 失败。
- [仿真] 极性自检 + 堵转检测 + 控制安全对照（参考 MICU-auto-embedded 的 control-loop-sign-debug / control-safety-limits）：侧车 `agent/polarity.py` + op `polarity_check`：手推（观察模式）判传感器轴、误差极性、控制器符号，点动判执行器方向，合成负/正反馈结论并指出哪一处反（只读遥测，不发指令）；8 项测试覆盖五种接法与死区/弱数据。新模块 `algo/stall` 1.0.0：高负载 + 近零速 + 持续、起步豁免、锁存/定时重试、NaN 不误报；主机测试用一阶电机模型（正常起步不误报，卡轴后 150+200 ms 报出）。docs/32 逐项对照 8 个安全检查项：发现**没有开 IWDG/喂狗**（只读复位原因）、无热折返、无通用软限位、无 WARN 档——列为建议，未改。[未测] 实物；stall 未接进应用；向导界面未做。
- [仿真] 参数回读 / 固件版本 / 黑匣子（参考 DS-land-and-air 的 P/F/H 命令与 ESP32 NVS 写满卡启动的教训）：dzctl 0.4.0 心跳第 3 个 u32 = 固件版本（git 短哈希，bit31 = 编译时有未提交改动；make 只给 dzctl.c 注入 `DZ_FW_REV`，换提交不全量重编；Keil/CCS 未传时为 0 = 未知），侧车 status 显示 `fw_rev`；`Session.export_readback()` / op `params_readback` 逐个问板子写 params.txt（带 schema/fw_rev/board_uid）；`tools/params_diff.py` 对比两次回读或快照 json（last-good 对比，有差异退出 1）。新模块 `framework/blackbox` 1.0.0：RAM 环形事件日志 + 可选掉电冻结（存储是回调，先擦后写、头最后写、CRC32 校验、放不下只存最新）；**存储失败不挡启动**：init 零存储操作、每次 freeze/load 操作次数有上限、连续 3 次失败自动停用——主机测试模拟读写擦全坏仍进控制循环、启动只碰存储 1 次、停用后不再碰。e2e（host-sim）：心跳版本与 git HEAD 一致、回读→改 kp→diff 报出 0.08 → 0.3。[未测] 片内 flash 回调、上板、界面按钮。
- [仿真] 验证证据与计分（参考 DS-land-and-air 合规差距清单/联调计分矩阵、MICU-auto-embedded 评分五元组）：requirements.yaml 评分项新增可选 `why`（设计依据）、`forbidden_claims`（禁止表述）、`evidence`（路径/层 unit·sim·bench·field/日期/pass·fail·partial）。`tools/req.py check` 核对证据（路径不存在、空目录、目录名与层/日期/编号不符为错误；台架/现场缺 flash.txt·params.txt、缺 why 为提醒）；`req.py evidence` 出合规与计分证据表（操作→验证位置→期望→设计依据→分值 + 状态 + 证据 + 禁止表述，非“现场通过”自动禁说“已得分”，末尾按状态汇总分值）；`req.py newlog` 按 `docs/verify/<题号>/logs/<YYYYMMDD-HHMM>_task<编号>_<层>/` 建目录。`tools/report.py --req-file --item` 把该项证据行带进报告并按满足率建议 evidence 条目（只建议 sim/bench，现场由人写）。规范 docs/verify/README.md；2026H B3 一条真实单元层证据（35/35，标 partial：没测指标）。test_req +1、test_report +2。[未测] 台架/现场证据（还没有实物录像）。
- [仿真] alloc.py / validate_board 支持 STM32F103（C8T6/CBT6，LQFP48）：新表 `tools/families/stm32f1.py`（DS5319 引脚表 + RM0008 AFIO 重映射组 + DMA1 固定通道），stm32f4 的检查改为表驱动 `stm32_check(F)` 两个系列共用，F1 另加整组重映射检查（定时器/串口/I²C/SPI 混用组报错）、48 脚不存在的引脚报错、JTAG 脚（PA15/PB3/PB4）与 PC13 坑脚警告。分配器同一份代码按表跑 F4/F1；F1 循迹车需求 20/20 分配、0 错误，20 kHz PWM 算出 PSC=0/ARR=3599（与用户真实 .ioc 的 3600-1 一致）。`--fixed` 用户真实小车板时如实报出视觉串口和 I²C 已无可用资源（USART3 脚被当 GPIO 用）。test_alloc 9 项。顺手：boardlib 对串口/I²C/SPI 实例为 TODO 不再误报。F4 例子输出不变。[未测] CubeMX 实际按清单配 F1。
- [仿真] 第 4 步机械：`mechanical/calc/mech.py` 取代“预留”占位——通用的转动惯量（圆柱/圆环/杆/板/长方体/球 + 平行轴）、T=Jα+重力矩+摩擦、bang-bang α=4θ/t²、电机线性机械特性核对（安全系数、额定扭矩、折算惯量比），机构 diff_chassis / gimbal / beam(ball_plate) 只把几何换成 J、α、重力矩；输出 `sim:` 块给 host-sim。mechanical/calc/test_mech.py 7 个手算算例（如 1 kg、r=50 mm、2 m/s² → 每轮 0.05 N·m、191 rpm、1 W；500 mm/0.2 kg 杆 + 30 g 球@200 mm、0.2 s 摆 10° → 0.1525 N·m）。模板 mechanical/templates/{diff_chassis,gimbal,ball_plate}.yaml（电机数值标为示例）。CadQuery 参数化零件 mechanical/parts/parts.py（motor_mount / encoder_bracket / sensor_bracket → STEP + STL + 参数表），CadQuery 可选：没装时脚本与测试打印跳过；本机 CadQuery 2.8.0 实测编码器板体积与手算 3378.15 mm³ 一致、STEP 读回体积一致。[未测] 打印、实际装配、电机实测曲线、SolidWorks 打开 STEP。
- [仿真] 第 3 步资源分配 `tools/alloc.py`：scheme.yaml + 器件库新增的 `res`（每件占的 GPIO/PWM/编码器/串口/I²C/SPI/ADC、逻辑名、频率/波特率、建议优先级）→ 按 `families/stm32f4.py` 复用表贪心分配（编码器独占定时器、同件 PWM 同定时器同频、避开 SWD/晶振脚、`--fixed` 沿用现有 board.yaml 接线）→ board.yaml 草稿（交 boardlib.check_board + check_requires，与 validate_board 同一检查）、cubemx.md（User Label、PSC/ARR、编码器模式、RX DMA 数据流、NVIC 表，FreeRTOS 时 ≥5）、alloc.md。2026H：21/21 项分配、0 错误、满足 app.yaml requires；`--fixed` bldc 板时沿用的资源逐项一致。tools/test_alloc.py 5 项（含 50 Hz 舵机 PSC=51/ARR=64614 手算、资源耗尽如实报出、mspm0 无表时全 TODO）。器件库 schema 加可选 price_cny/price_note/power_w/mcu/res。修 boardlib：mspm0 定时器写 TODO 时误报。[未测] stm32f1/mspm0 自动分配（无表）、电流估算、真实 CubeMX 按清单走一遍。
- [仿真] 第 2 步方案选型 `tools/scheme.py` + 器件库 `tools/catalog/parts.yaml`（schema/parts.schema.json，26 件：c8t6/F407 VET6·VGT6/MSPM0G3507，Jetson Nano/MaixCAM2/K230/树莓派/RDK，传感器、执行器、人机件，每件带优缺点/风险/替代件/本仓库支持程度和 repo 证据路径）。读第 1 步 requirements.yaml：按能力标签出候选（按牵涉分值排、规则 forbid 自动排除并写原因）、起稿和核对 scheme.yaml（不提供/被禁用/备选重复/串口超限）、出系统框图（mermaid）。2026H 实例 scheme.yaml；make check 跑 test_scheme（5 项）和例题核对。不叫 select.py（会遮住标准库 select）。[未测] 价格/货源/功耗未入库。
- [仿真] 第 1 步读题拆解 `tools/req.py`（init / check / checklist）+ `schema/requirements.schema.json` + `docs/templates/requirements.yaml` + docs/31：题目 PDF 起稿评分项（分值、≤/≥ 阈值）和候选规则约束 → 人工核对、三人签字的 requirements.yaml → 测试清单 md/csv（规则确认框、评分项→指标/测法/次数/子系统/工作台验收、子系统×评分项耦合矩阵、量级估算）；check 对照 project.yaml 核对子系统 / accept / tests。实例 examples/2026H_ball/requirements.yaml（make check 校验）。2026 年 A–H 八道真题都能起稿，H 题 8 项分值与原文一致、复盘漏看的 4 条规则全部抓到。局限：嵌套小问无归属、表格内要求抓不到。
- [仿真] 新模块 `algo/accel_ff` 1.0.0：加速度前馈（θ≈a/g × 增益，死区边沿连续，无效/NaN/超限 → 0，限幅）从 examples/2026H_ball/subsys/ball/ball.c 提出（核对清单唯一“偏离”项）；来源选择与 IMU 超时仍在例题里，只传 valid。行为不变：主机单测把新模块和提取前原公式在 ±12 m/s²×4 档增益上逐点比对（误差 <1e-6），2026H example 35/35。[未测] 实车。
- [仿真] 验收 / 单位标定 / 串级分层（docs/30），全部写在 yaml `link:`（gen_link 带进 link_schema.json，不进哈希），代码里没有题目字段名：字段 `cal`（多点直线或分段）把曲线/读数换成物理单位；`accept`（误差带、可选速度门限、保持时间、限时、多目标分段、最近 N 轮按最差）让读数条和台账显示 通过/未过（原因）· 到位时间 · 到位后误差；`loops` 给台账加“层”下拉，每层一本台账、参数只列这层增益。TS（accept.ts）与 Python（dzbench/accept.py）同一定义，共用手算期望值的测试向量；make check 改为跑全部 UI 单测（measure.test 以前没跑）。验证：2026H（cm、±1 cm/300 ms/5 s/3 轮）、car_2wd（rps→cm/s、示例阈值）、line_car（轮速/循线两层）。[未测] 真机标定、Windows。
- [仿真] F11/F12 修复：仿真板编译、端口列表、schema 查找优先用 DZBENCH_REPO（以前固定用侧车自己的仓库，写回的默认值到不了仿真板）；自检默认查侧车在用的仓库（以前说没有 dzbench.json）。F7（全新克隆缺 third_party/ 时 check_ai_docs 报错不直观）只诊断，tools/ 归另一位。
- [仿真] 全流程走查（docs/29，2026H 仿真）：流程条“定稿”接通写回→门禁→git 提交；写回卡片摘出 旧→新、只数真正改动；参数筛选；原始默认 HEX；频谱默认被控量；2026H 声明 ref_for。[未测] 真板、Windows。
[仿真] tools/report.py（G11）：录像（.dzlog/CSV）一键出参数表 + 阶跃指标表（每次/平均/最差/满足率，按 --req 判是否满足）+ 叠加阶跃曲线 SVG（无依赖）；指标与工作台同一算法；--source 必填，仿真录像不能标实测；参数只取快照，不猜。tools/test_report.py 用二阶系统解析解核对（超调 16.6% vs 理论 16.3%，含噪声）。docs/templates/report.md 报告骨架。真实录像：15 次仿真摆臂录像 7 次可算。
- [编译] check_deps F1 扩展：apps/examples 里 dt 写成数字字面量（`ec.dt_s = 0.001f`）也拦（夹具 deps_F1_dt_literal）。2026H io_main 的编码器 dt 改为与主循环门控共用 `IO_TICK_MS`（取 1 时行为不变，example 35/35）。[未测] 上板。
- [仿真] G7 `algo/vision` 1.1.0 新增 `vis_plane`：平面五点标定（四角求透视变换 + 中心点验收 check_err，像素↔平面双向）。主机单测：已知透视下 169 点误差 0.0002 mm；同一透视按两角线性插值中心点错 48.6 mm；中心点错 8 px 时 check_err 22.9 mm。[未测] 实机相机、镜头畸变。
- [仿真] G7 新模块 `algo/mtspeed` 1.0.0：变周期 M/T 法测速（PAL 边沿中断时间戳），低线数编码器 + 1 kHz 环时代替窗口差分。主机仿真 1.9 rps、52 边沿/转：标准差 M 法 1 ms 窗口 5.74、20 ms 窗口 0.147、M/T 0.0003 rps（理想等间隔边沿，实物会更大）。[未测] 真实编码器、中断并发双读。
- [仿真] G7 新模块 `algo/slew` 1.0.0：不对称变化率限制（按方向 / 按远离-靠近 0，跨零先减后加），速率按"每秒"写，与控制周期无关（p2 的 Beam_RampStep 按"每拍度数"写，改周期就变速）。主机单测含一阶电机模型：起步 0.5 s、刹车 0.1 s 按配置。[未测] 实车。
- [编译] G5 `docs/28-30分钟换板清单.md`：6 步清单 + 各板最小例程表（port_selftest / motor_speed_demo / car_2wd 按板实测编译结果），9 个组合加进 `make cross`。否决"每板复制一份 minimal 例程"（重复即屎山）。发现缺口：bldc-freertos 板无 LINK 串口与 LED，自检固件跑不了。[未测] 真人计时、上板、Keil。
- [编译] G4 STM32 只保留 CubeMX 主线：`ports/stm32f4-hal` 冻结，只服务天空星 HAL 版与 RM C 型；第三块板用它 validate_board 报错（`tools/test_port_policy.py` 进 make check）。没有删除：天空星 CubeMX 版缺电机 B、RM C 型 HSE 未确认，迁移步骤见 docs/notes/implemented/2026-10-29-cubemx-only.md。
- [仿真] G3 2026H io 胶水拆分：`io_link.c`（上位机链路，无 LINK 板给空实现）、`io_imu.c`（UART 姿态模块 / MPU6050 / 无）、内部接口 `io_parts.h`；io_main.c 296→145 行，条件编译 15→1 处。行为不变：example 单测 35/35、侧车 142 passed、make cross 全过；MPU6050 路径仅 -fsyntax-only。[未测] 上板、Keil。
- [编译] G3 Makefile 按芯片系列拆成 `mk/<BOARD_FAMILY>.mk`（host / stm32f4 / stm32-cubemx / mspm0-driverlib），顶层 327→228 行。拆分前后 11 个 板×应用（含 LINK=rtt）的 .bin 与 `make vars` md5 全部相同。
- [未测] G2 `skills/dz-firmware/SKILL.md`（5 个决策、换板 5 步、加题 6 步、踩过的坑）+ 文件级改法纪律表（改什么只动哪里、哪条检查会拦）。纪律唯一来源 `skills/dz-firmware/edit-rules.md`，`check_ai_docs.py --sync` 写进 AGENTS.md 与 SKILL.md，`--check` 在 make check 里校验一致（思路学 SerialWeb，代码自写）。工作台内置 Agent 提示词尚未接入同一来源（app 线在改界面，未动）。
- [编译] check_deps 新规则 F1：禁止手写控制频率常量（examples 的 subsys/io 只能用 period_ms 生成的 PERIOD_MS_*；apps 的周期宏必须同时交给调度），例外 `DZ-FREQ-OK:`。夹具复刻用户 p1 的 `CONTROL_FREQUENCY 300` 被拦；现有仓库 0 违规。
- [编译] G1 生成物一致性检查 `tools/check_gen_consistency.py`（进 make check / CI）：CubeMX `MX_GPIO_Init` 引脚与 .ioc 的 GPIO 双向对比（改 .ioc 没重新 GENERATE、残留旧引脚即报错），链接脚本必须有 `__flash_kb` ASSERT。复现换板实测：LED PA8→PC13 只改 .ioc 时报出两条。复核更正 docs/27：flash 超限早已由 ASSERT 拦住（`BOARD_FLASH_KB=8` 实测链接报错），初稿误判。新增 docs/notes/。[未测] 真 CubeMX 生成的 gpio.c 分文件布局、Keil。
- [仿真] 界面 v6 落地：三栏工作台、参数刻度尺 + 改动单、阶跃读数条（与侧车 step_metrics 同定义，单测）、台账、流程条、自带 OFL 字体子集；合入 wip/v4-gaps（A/B 光标、t0、余辉、历史、高对比、ref_for）。[未测] Windows 实机、上板。
- [未测] docs/26 §5：v5「调参台」视觉方向（原则出处 + 原创落地 + 自评），示意稿在工作区，代码未动。
- [仿真] 界面按 v4 示意稿落地：灰阶 tokens、分 lane 示波、停靠参数表（含默认列）、侧栏页签；新增 docs/HANDOVER.md。[未测] 实机、Windows 字体、1280 窄屏。
- [未测] docs/26：改为 17 条设计原则、v3 审计和 v4 原则→决定映射（只改文档，应用代码未动）

## [0.11.0] - 2026-10-29 通用仿真对象、界面改版、评测 13 例、MSPM0 走查
- [编译] MSPM0 走查：干净克隆里 `make BOARD=mspm0g3507-* gen` 因缺 SDK 退出、没生成 link_gen.c，CCS 导入 projectspec 会缺文件 → gen / vars 不再要求 SDK。DFP 包能被 pyOCD 识别出 mspm0g3507【离线】；CCS 导入 / 真烧【未测】。走查表见 docs/15。
- [仿真] pendulum_rot 默认 k_al 0.8 → 1.2：0.8 太接近稳定边界，静止时有极限环（摆杆 ±0.9°、摆臂 pp 3.5°）；现在摆杆 pp 0.3°（±1 个编码器计数），摆臂 pp 约 1.2°。曲线台阶是编码器量化（摆臂 0.23°/计数、摆杆 0.15°/计数），不是绘图问题。加静止测试。
- [仿真] 界面：断开后清掉顶栏状态块；Agent 引导问题按 schema 生成（不再写死“速度环”“左轮比右轮慢”）。
- [仿真] 通用仿真被控对象 4 个：motor_pos（位置环）、pendulum_rot（旋转倒立摆，状态反馈平衡）、pan_tilt（视觉云台，30 fps / 50 ms 延迟 / 可丢帧）、line_car（8 路灰度循线，串级）。同一套侧车 / 阶跃 / 扫频 / Agent，不改代码就能跑；侧车自动发现 apps/ 与 examples/ 下可仿真的工程。共用收发头 apps/include/link_app.h（设定值约定 DATA id=1）。tests/test_e2e_plants.py 每个对象跑一轮阶跃。全部【未上板】。
- [仿真] 修：多个对象都有 sp_a/spd_a 时阶跃配置按 dzbench.json 顺序选，line_car 拿到 car_2wd 的配置（报“阶跃后数据不足”）。现在 step_test > 当前仿真工程名 > gains 参数都在板上 > 顺序。加单测。
- [编译] 修：gen/ 按板共享，换 APP 时 requires 检查可能被跳过，缺资源变成 `RES_xxx undeclared` 编译错误。现在每个 板×应用 单独检查，报 `[缺资源]`。cross 矩阵加入新对象（host-sim ×4、天空星 motor_pos/pan_tilt、天猛星 pendulum_rot）。
- [仿真] 评测集 10 → 13 例：传感器丢失不调参、实机阶跃必须走确认卡（`as_hw` + `expect_action`）、带宽用扫频；`user_generic` 让点名参数不存在的对象也能跑；`evalrun --ports all`。修离线助手只读前 12 个 yaml（对象多了当前工程被截掉）。离线对照组 6 个对象 × 13 例全过；真模型【未测】。
- [仿真] docs/19 覆盖矩阵刷新：云台 / 循迹 / 串级 / 位置环更新，下一步排期为跟随小车（双车）、起摆、风力摆。
- [仿真] 界面复查：Y 轴随数据自适应（有最小跨度）；参数表独立滚动、操作栏固定；回放列表只列当前端口的记录；Agent 引导缩成两行；通道 / 参数空状态加图标。

- [仿真] 界面改版（docs/26-UI规范.md）：设计变量（4/8 间距、5 级字阶、一个靛蓝强调色、状态色只表状态）+ 统一组件；深 / 浅两套主题（顶栏切换，记住选择）；Lucide 图标；少用功能收进菜单（串口细节、板子命令、Agent “…”），功能未删。截图 shots/ui2/before_* / after_*。
- [仿真] 顶栏状态块改为 schema 驱动：遥测字段写 `pin: 标签`、`pin_with: [字段]` 就上顶栏，界面不再认具体字段名（原来写死 vis_state）。
- [编译] check_deps 新规则 I1（restudy M4）：传给 pal_gpio_irq_attach 的中断回调里出现 printf / pal_delay / 串口或链路发送 / malloc / OLED / 浮点数学函数 / while·for 循环 → 拦截。违规样例自测；现有代码 0 处违规。
- [仿真] dt 异常重置（restudy P4）：pid 1.1.0 加 `pid_check_gap`（间隔 > 5×dt 或 > 0.5 s：清微分历史 / 微分滤波，保留积分），lpf 1.1.0 加 `lpf1_check_gap`（下个样本直通）；car_2wd 控制中断按 pal_micros 实测间隔调用。自测通过；断点恢复场景真板【未测】。iface_hash 自测改为按模块当前版本算（原来写死 1.0.0）。
- [仿真] doctor 自检（restudy A7）：`python -m dzbench --doctor [--repo 工程]` 或 UI 顶栏“自检”，查 Python 依赖、arm-gcc / make、dzbench.json、Keil 路径、flash.target、MSPM0 器件包、探针、串口、大模型 Key、数据目录，每项 ✓/!/✗ 加中文修复提示，只读。多探针不猜（A3）：没配 flash.probe 又插了多个探针 → 报 multi_probe 并列出序列号；配置的探针没插 → probe_missing。假 pyOCD 单测；真探针【未测】。

## [0.10.0] - 2026-10-29 仿真当实板、RTT 链路、走查修复
- [仿真] 修偶发：阶跃响应良好但窗口内没算出调节时间时，调参提示格式化 None 抛错，离线助手回答“还没法分析”（评测 look_before_conclude 时过时不过）。加单测。
- [编译] 修 CI：keil_inject --board 调 `make vars` 时 CubeMX 板没 HAL 会报错（本地有 third_party 没暴露）→ vars / gen 不再要求 HAL；check 里这条测试固定在无 HAL 条件下跑。
- [仿真] 上电自描述（restudy S3）：car_2wd / 2026H 复位后第一拍就发心跳（带 schema 哈希），不用等 500 ms；host-sim 两个应用编译、make check 通过，真板【未上板】。
- [仿真] 记录 / 回放：记录文件名带端口或仿真应用（run_…_sim-2026H_ball.dzlog，COM 口同理），回放列表认得出是哪次；新开的记录马上进列表并标“记录中”（原来要断开才刷新，且刚建的空文件会让整个列表变“还没有记录”）；列表只读文件头，不再整份读 30 个记录。
- [仿真] 2026H 视觉状态：顶栏加“视觉”块（VALID 绿 / HELD 黄 / LOST 红 · vis_age_ms · 丢帧数）；字段可在 project.yaml 写 `na:`，等于它时显示“—”（cpu_pm / stk_min_w 仿真里没数据，原来显示 65535）；仿真专用命令 `V n`（命令框发 V 40 = 假相机停 4 s，n=0 为 3 s），实测 VALID→HELD→LOST→VALID。真板上 io_sim_cmd 是空的弱函数。
- [编译] keil_inject `--board <板> --app <应用>`：先 make gen，再按头文件依赖闭包只挑用到的模块、应用源文件、board_gen / link_gen、DZ_ 宏，不用手列 --module（F103 car_2wd 挑 10 个，只用这些目标文件 arm-gcc 链接通过；Keil 里【未测】）。docs/14 改为推荐这个写法。
- [编译] ioc_import：文档里写的 `-o` 实际不认（只有 --out）→ 加 `-o`；新板没 --base 时 openocd_target 按系列填（stm32f1 → target/stm32f1x.cfg），name 用 .ioc 文件名代替 TODO。链接步骤依赖链接脚本（改 .ld 会重链）。
- [编译] 固件 LINK 可走 RTT：`make LINK=rtt BOARD=… APP=…`（新模块 firmware/proto/dzrtt 0.1.0，SEGGER RTT 兼容控制块、非阻塞整段丢；应用经 apps/include/link_io.h 收发，默认仍是串口）。输出到 build/<板>-rtt/。主机单测模拟探针读写已过；MSPM0 / F407 交叉编译通过（MSPM0 car_2wd 多 1.3 KB RAM）；真探针【未上板】。
- [仿真] 端口 `sim:<应用>+hw`（端口列表“仿真板当实板”）：同一个仿真程序，风险分级按实板走，阶跃/扫频实验要点确认卡，可端到端测 pre-arm 检查。确认卡把解锁前检查画成 ✓/✗ 清单、标出 120 s 有效期、执行被拦时直接显示原因。
- [仿真] 走查 v0.9.0 修的别扭处：启动瞬间弹假“侧车未连接”；Agent 工具栏溢出（重置护栏/模式被裁掉）；扫频只能靠问 Agent、结果界面不显示 → 加“扫频”按钮和结果卡；离线助手在阶跃实验后几秒才问时说“没阶跃”→ 改为引用上一轮判定并指向“规则建议”；浮点 1e-45 级噪声显示为 0。实机确认卡（arm 卡）仿真里是自动级不出卡，未在实板上走查。
- [仿真] RTT 传输：端口 `rtt:<目标>[@探针]`，经 pyOCD 读写 SEGGER RTT 通道 0（API 按 pyOCD 主干源码 pyocd/debug/rtt.py 核对：RTTControlBlock.from_target → start → up/down_channels；连上后 resume），装了 pyOCD 且配置了 flash.target 时出现在端口列表。假 pyocd 测过；真探针未测；本仓库固件还没有 RTT 版 LINK 输出。
- [编译] CI：新增 ci.yml，每次推送（任何分支）跑 make check（含 check_version）/ test / compat；firmware 工作流改为每次推 main / release/* / v* tag 都跑，不再按路径过滤。
- [编译] `make preflight`：从 HEAD 干净克隆到临时目录、空 HOME、不带 TI 器件包、清 DZBENCH_*/PYOCD_* 环境变量，跑 check/test/compat/cross。推送前必跑。
- [仿真] 测试与本机状态解耦：DZBENCH_HOME 每个测试指到空目录（不读本机 machine.json / LLM Key / 快照）；仿真程序与 gen 按需编译（干净克隆里 test_e2e_flash 原来找不到 build/）；器件包本机目录改走 DZBENCH_HOME；pytest 打印跳过原因，CI 装 arm-gcc 和 MSPM0 SDK 免得 ELF/板卡测试静默跳过。

## [0.9.0] - 2026-10-29 调参安全、扫频、器件包
- [仿真] 实验解锁（ArduPilot 式 pre-arm）：实机阶跃/扫频/开环实验的确认卡预览里先跑检查——急停、链路 1 s 内有数据、实验通道在遥测里、电池/温度门限、板上增益回读与侧车记录一致；点击时再查一次，不通过拒绝执行。确认卡一次性，超过 120 s 过期。仿真测过；实机未测。
- [仿真] 频率响应：新工具 `run_sweep_test`（闭环正弦扫频，复用 step_test 的通道和工作点，配置 `step_test.sweep`；按板子实际收到的 sp 算增益/相位；实机需点击，最长 90 s，频率上限按发送/遥测周期限制），返回闭环带宽（相对最低频点 −3 dB）、谐振峰、相位滞后 90° 频率，残差大的点标为不可信。新计算器 `bode_predict`（FOPDT + PID → 相位/幅值裕度、闭环带宽，模型预测）。与一阶闭环解析解对过；仿真板扫频测过；真板未测。
- [仿真] CI 修复：侧车测试不再依赖本机是否下载了 TI 器件包（conftest 统一给假包）；之前本地有包、CI 没包，test_e2e_flash 在 app-windows 上报 no_pack。
- [仿真] 文本遥测解析：`\r\n`、单独 `\r` 都当行尾；先按 UTF-8、不合法再按 GB18030（GBK）解码，中文通道名可用，GBK 第二字节不再拆出假 ASCII 通道。补任意字节切分 / CRLF 切开 / GBK 双字节切开的测试。
- [仿真] 串口 DTR/RTS 可配：配置 `serial.dtr/rts`（null = 驱动默认）或连接栏“DTR/RTS 不拉高”；在 open() 前设好，防 ESP32/一键下载电路一连就复位。真 CH340/ESP32 未测。
- [仿真] 钢珠跟踪器：搜索期连续 3 帧位置一致才锁定（`confirm`，1 = 旧行为）、门限随速度放宽（`gate_vel_k`）、外推时速度逐帧衰减（`coast_damp`）、速度上限。PC 合成数据测过，实机阈值未调。
- [仿真] 侧车烧录：MSPM0 改走 TI 官方 DFP 包（MSPM0G1X0X_G3X0X_DFP 1.3.1，BSD-3，sha256 校验；`tools/fetch_third_party.sh m0pack`），Windows 安装包内置；缺包时报 `no_pack` 而不是让 pyOCD 猜目标。查找顺序 DZBENCH_PACK → 安装包内 → third_party/packs → ~/.dzbench/packs。真探针未测。
- [仿真] 变量监视按地址合并成块读（相邻间隔 ≤64 B 合一次读），减少 SWD 往返。真探针提速幅度未测。
- [编译] MSPM0 移植层 PWM：按计数模式算周期和占空（向下计数默认 / 向上计数 / 中心对齐 2·LOAD），支持 CCPOINV 反相；依据 SDK dl_timer.c。未上板。
- [编译] check_deps D2：抓 `DL_Timer*_setCaptureCompareValue(实例, 值, 通道)` 参数写反（第 2 个参数是 *_INDEX）。
- [编译] board.yaml 新增 `reserved_pins`；天猛星标 SWD（PA19/PA20）、CH340 串口（PA10/PA11，仅 uart.LINK 可用）为错误，晶振/ROSC（PA2–PA6）为告警。功能名对照 TI SLAU873 和 IOMUX 头文件；CH340 接线和晶体是否焊接未对照原理图。

- Agent 评测一键运行 `make agent-eval`：真大模型 × 两块仿真板 × 10 例 × 重复 N 次，出 report.md/json；没 Key 或中途退回离线时退出码 2、报告标“不算成绩”。运行器 [仿真]，真模型结果 [未测]（docs/18 §3.3）
- Agent 计划卡 / 板子记忆 / 一键“撤销 Agent”：计划按 {步骤, 状态} 整表更新（同时只一步进行中，重复/空步骤拒绝）；每块板（schema+UID）记最近 200 条参数与提交；撤销参数改回旧值或 git revert，**那次提交改过的文件有未提交改动时拒绝撤销**，撤销后告诉模型别原样重做。[仿真]（真大模型 [未测]）
- Agent 工作模式：通用 / 诊断（只读）/ 调参 / 改代码 / 审查，按模式收窄工具白名单，审批分级照旧；没有“全自动”档。评测加 2 例（共 10 例），离线基线全过。[仿真]
- Agent 护栏（只对真大模型开）：看了数据却一个数字都没引用 → 退回重写一次；同参数重复调用第 3/5 次提醒；空结果明说“成功但没有数据”。[仿真]（真大模型效果 [未测]）
- 参数写板：Agent 落地参数和恢复快照都**写后回读比对**，不一致报错；提议卡待确认期间该参数被别处改过 → 卡片作废，要求按当前值重提；一张卡只能落地一次。[仿真]（实板 [未测]）
- Agent 调过的参数进入“试用中”：对话里出现“保留（存快照）/ 恢复原值”，恢复时逐个写回并回读；不点保留就一直提示（思路来自 ArduPilot 自整定的“未保存即恢复原增益”）。测试之间的保守增益沿用已有护栏：判定失稳自动回滚到最好一轮。[仿真]（实板 [未测]）
- 继电器自整定算法（Åström–Hägglund，Ku/Pu + Tyreus–Luyben/ZN 增益，峰值按半周期取防噪声，收敛判据）：只有算法和 FOPDT 仿真单测；**固件还没有“输出覆盖”通道，所以没接成 Agent 工具**，门禁沿用 plant_stable。[仿真·仅算法]
- docs/24 Agent 框架源码研读（Codex、Gemini CLI、DeepSeek Harness、Aider、Cline、OpenHands、Goose、OpenCode、Continue、SWE-agent、smolagents、嵌入式 MCP），docs/25 v0.9 计划。

### 修复 / 改进
- app-windows CI：v0.8.0 的 Windows 构建因 test_wiring 里 3 个仿真板测试挂掉（mingw 没有 asan/ubsan、Makefile 用了 find）。所有起仿真板的测试统一标 `needs_sim`，Windows/无 make+cc 跳过；没标却起仿真板的测试本地直接失败（子进程侧车也拦）。Makefile 改纯 make 递归通配、Windows 默认不开 sanitizer（Windows 跑仿真板 [未测]）。app-windows 改为每次推 main 都跑。[编译]（Windows CI 结果见本次 run）
- 外壳代码 main.rs 在本机用 rustc 1.99 对 Windows（x86_64-pc-windows-msvc）`cargo check` 通过（debug + release）[编译]。
- 侧车收到 SIGTERM 先删“上次连接”记录，退得慢也不会下次误报“意外退出” [仿真]。
- **dzctl 0.3.0：心跳带板 ID**（芯片 UID 折成 32 位；F1/F4 端口用 HAL_GetUIDw*，仿真用 DZ_SIM_UID；MSPM0 读 FACTORYREGION TRACEID（0x41C40000，SLASEX6 §8.35）混 USERID，预量产片 TRACEID=0 时报未知 [编译]）。旧上位机只读前 4 字节，兼容 [仿真]。
- 换 USB 口自动跟随改为**按板 ID 认板**：两块同型号 CH340 板同时插着也不会跟错；旧固件（无 ID）+ 无 USB 序列号 + 多个候选时不猜，中文提示手动选 [仿真]。真 CH340 [未测]。

## [0.8.1] - 2026-10-29 Windows 构建修复

### 修复
- app-windows CI：v0.8.0 的 Windows 构建因 test_wiring 里 3 个仿真板测试挂掉（mingw 没有 asan/ubsan、Makefile 用了 find）。所有起仿真板的测试统一标 `needs_sim`，Windows/无 make+cc 跳过；没标却起仿真板的测试本地直接失败（子进程侧车也拦）。Makefile 改纯 make 递归通配（排序，CCS projectspec 稳定）、Windows 默认不开 sanitizer（Windows 跑仿真板 [未测]）。app-windows 改为每次推 main 都跑。[编译]

## [0.8.0] - 2026-10-29 “真的接上了吗” + 赛场鲁棒性 + 板名

### 修复（接线排查，详见 docs/23 §v0.8.0）
- **界面“烧录”绕过了人工确认**：编译/烧录/回滚统一走风险网关，界面按钮也弹确认卡 [仿真]。
- 烧完核对必须用复位之后的新心跳；回滚后按烧前哈希核对；Agent 新增 `flash_rollback`（human 级）；ELF 备份大小按片上 Flash [仿真]。真探针 [未测]。
- 连不存在的口不再误报“没收到 dzframe”：分“找不到（列出现在能看到的口）/ 被占用 / 没有 dzframe”三类中文提示 [仿真]。
- 删掉没人调的 `hardfault_decode`、`change_list` op。

### 赛场鲁棒性
- 拔线：板子 1 s 没心跳自锁急停；侧车自动重连，插回去不自动解除急停；**插到别的 USB 口 / COM 号变了会按 VID/PID/序列号跟过去**并提示 [仿真]。真 USB 拔插 [未测]。
- 侧车崩溃：外壳 1 s 后重启（1 分钟最多 5 次）；重启后提示“侧车刚才意外退出…”并预选上次的口，**不自动连**；正常关闭不误报 [仿真]（外壳部分 [编译]，仅 Windows CI）。
- 两个窗口：单实例（再双击 = 把已有窗口拉到前面）[编译]；第二个侧车抢端口 → 退出码 3 + 中文说明，外壳不再重启 [仿真]；多个界面连同一个侧车时状态栏提示 [仿真]。
- 串口独占打开（POSIX；Windows 本来独占）：被串口助手等占着时中文报“被占着” [仿真]。
- 线上乱码：CRC 丢坏帧，坏帧多时状态栏提示查干扰/波特率，调参照常 [仿真]。

### 界面
- 固件栏：编译 / 烧录… / 回滚固件；Agent 栏：阶跃实验、规则建议、重置护栏、新对话；连接栏：自动重连开关 [仿真，按钮显示未做浏览器测试]。

### 测试
- 新：test_e2e_flash.py（假 pyOCD 全流程）、test_e2e_robust.py（赛场情况）、test_wiring.py（入口对照 + 新按钮 + Agent 工具 + car_2wd 固件参数）、tools/test_new_subsys.py。工具：pty 仿真板 ptyboard.py、界面替身 wsui.py。

### 文档
- 板名对照表：**天空星 = 立创 STM32F407，天猛星 = 立创 MSPM0G3507**（docs/README.md 顶部）；check_ai_docs 新增“板名和芯片写反”检查。仓库里的电池说明本来就是对的（天空星 VBAT 等你填分压、天猛星要自己焊分压），是 v0.7.0 汇报里写错了。
- QUESTIONS 50–54，MORNING 更新。

## [0.7.0] - 2026-10-29 电池急停仿真跑通 + 全仓质量审计 + FreeRTOS 监测

### 修复（审计发现）
- **烧录链路接通**：编译结果以前从没交给烧录器（`note_build` 只有测试调用），真用时烧录前置条件 `build_ok` 永远不满足。Agent 新增 `build` 工具（Keil `UV4 -b`），`build_log` 也会登记；镜像取 `build.image`（缺省 `build.elf`），核对哈希取 `build.link_schema`；日志与镜像时间差 >120 s 不登记 [仿真]。真机烧录 [未测]。
- **电池 CRIT 急停在仿真里跑通**：host-sim 的 ADC 换算以前写死 1/1，board.yaml 的分压不生效；现在由 gen_board 生成 `g_host_adc_info[]`。test_car 新增用例：8.2 V → 6.0 V 锁急停，电压回升也不解除 [仿真]。
- car_2wd 急停时照常更新编码器，遥测转速不再冻结在急停前的值 [仿真]。
- 天空星 VBAT `scale_num: 1` 时电池保护实际不生效：未改（要看你的分压），写进 QUESTIONS 45 / MORNING。

### FreeRTOS
- rtosmon 1.0.0（firmware/framework）：CPU 负载千分比 + 全部任务最小栈余量与任务名，纯逻辑，含 32 位回绕 [仿真]。
- stm32-cubemx 1.4.0：`dz_freertos.{h,c}` 周期任务 `dz_rtos_periodic`（vTaskDelayUntil、超时计数与重新对齐、最长耗时）、`dz_rtos_monitor_poll`（uxTaskGetSystemState，`dz_cubemx_loop` 自动调用，main.c 不加行）、CubeMX 运行时统计两个函数用 DWT 实现；任务模板 `freertos_task_template.c` [编译]。上板 [未测]。
- 2026H_ball 遥测加 `cpu_pm`、`stk_min_w`（裸机 = 0xFFFF）[编译]。docs/11 加 FreeRTOS 一节。

### 重构 / 清理
- gen_board：四个端口的 ADC 初值格式串合成 `_adc_info()`，生成结果逐字节一致。
- 删 `host/python/dzlink/workbench.py`（全是 NotImplementedError、无人调用）。
- 文档路径漂移 3 处修正。审计全文见 docs/23-质量审计.md。

### 文档
- docs/MORNING.md：给你的一页清单（要带什么、要量什么、要拍板什么）。QUESTIONS 45–49。

## [0.6.0] - 2026-10-29 PAL 边沿中断/MSPM0 ADC + 协处理器发送库 + 快速上手

### PAL / 移植层
- PAL 1.2.0：GPIO 边沿中断 `pal_gpio_irq_attach/detach`（RISING/FALLING/BOTH，按逻辑电平判断，active_low 自动换算；回调带 t_us）。host-sim 2.1.0 [仿真]；stm32f4-hal 1.2.0（运行时配 IT_RISING_FALLING、NVIC 6、EXTI 各向量）[编译]；stm32-cubemx 1.3.0（提供 HAL_GPIO_EXTI_Callback，G0/C0/L5/U5/H5/MP1 用 Rising/Falling 回调；`DZ_CM_NO_EXTI_CALLBACK` 可让出，自己调 `dz_cm_gpio_exti(pin)`）[编译]；同一引脚号不同端口返回 DZ_EBUSY。
- mspm0-driverlib 0.4.0：ADC12 单次转换（SysConfig 实例名 `ADC12_<n>`，1 ms 超时计入 diag adc_timeout）+ GPIO 边沿中断（GROUP1_IRQHandler 由 gen_board 生成）[编译]。syscfg_import 识别 ADC12_<n> [仿真]。天猛星板加 US_TRIG PB8 / US_ECHO PB9、VBAT ADC0 CH2 PA25（分压 11:1【未验证】）。

### 模块 / 应用
- hcsr04 1.1.0：`hcsr04_attach_irq/detach_irq` 用 PAL 边沿中断计回波 [仿真]。
- attitude 1.1.0：`attitude_linear_acc` 去重力，MPU6050 直连路径也能拿线加速度 [仿真]。
- car_2wd：car_aux（电池：先见过 OK 再掉到 CRIT 才急停，只置不清；超声：<150 mm 前进速度限 0）[仿真]，电池急停在 host-sim 只编译未跑通 [编译]。

### 工具
- tools/test_module_ide.py（进 make check）：28 个模块逐个 keil_inject（含依赖闭包）+ 仅用注入的 include 做 gcc -fsyntax-only；CCS projectspec 含全部 .c 与 -I [仿真]。

### 协处理器
- dzlink 1.1.0：`Sender`（按通道打包、seq、整数截断、限速、心跳；MaixCAM 自动用 maix.uart）、`autodetect`（Jetson/树莓派/RDK/MaixCAM 平台识别 + 监听 MCU 心跳选串口，`DZ_SERIAL` 覆盖）[仿真]；K230 MicroPython 单文件 host/k230/dzsend.py，与 dzlink 逐字节一致 [仿真]。各平台实机串口 [未测]。docs/22。

### 工作台 / 文档
- 修 PytestUnhandledThreadExceptionWarning：识别 schema 后的后台读参线程吞掉断开时的异常并上报 `param_read_aborted`；pytest 把该警告升为错误 [仿真]。
- docs/00 快速上手（装 exe → CubeMX → Keil → ST-Link/DAPLink 烧录 → 连接 → Agent 调参 → 急停），4 张仿真板截图；Windows/Keil/烧录步骤 [未测]。

## [0.5.0] - 2026-10-29 模块库 + MSPM0 I2C/SPI + IMU 去重力 + 2026H 评测

### 模块库（可移植驱动）
每个都有 README（含 board.yaml 片段）、VERSION、selftest，以及 host-sim 上的假芯片单测（tests/host/test_modlib.c）；host-sim 板新增对应测试资源。全部 **[仿真]**（主机单测），**上板 [未测]**。
- servo 1.0.0：角度→脉宽、trim、反向、软件限位、速率限制。
- buzzer 1.0.0：开/关节奏 + 重复 + 优先级，有源（GPIO）/无源（PWM 50%）。
- battery 1.0.0：分压换算、滤波、OK/LOW/CRIT/NONE（滞回 + 保持时间，防电机启动误报）、粗略百分比。MSPM0 端口 ADC 仍 ENOTSUP。
- ssd1306 1.1.0：自带 PAL I2C（控制字节作 reg，16 B 分块）和 4 线 SPI（D/C，64 B 分块）传输 + 硬复位。
- hcsr04 1.0.0：非阻塞触发/回波计时，轮询或 EXTI 边沿两种，温补声速、超时、量程。
- line_sensor 1.0.0：1..8 路数字/模拟灰度，标定、加权位置、丢线记边、路口检测。
- stepper 1.0.0：STEP/DIR 梯形加减速（Q32 相位累加，ISR 内无浮点/除法），运动中不换向、平滑停止、急停、EN。
- st77xx 1.0.0：ST7735/ST7789 RGB565，开窗直写（无帧缓冲）、旋转/偏移/BGR/反色、放大文字。
- bt_serial 1.0.0：HC-05/JDY-31 按行收发、非阻塞 AT 改名/改波特率、STATE/EN 脚。
- motor_2pwm 1.0.0：DRV8833 双 PWM（慢/快衰减、刹车/滑行）；motor_dc 不变（QUESTIONS 36）。
- key 已满足要求（消抖/长按/连发），未改。
- docs/19 覆盖矩阵更新。

### 文档
- 新增 docs/21-结构与3D打印：SolidWorks → Bambu Studio 检查清单（公差、导出、切片、材料）和电机/编码器/摄像头/PCB 安装座要点，只有思路与清单，无 CAD。经验值 **[未测]**。

### MSPM0：I2C / SPI（DriverLib）
- ports/mspm0-driverlib 0.3.0：`pal_i2c_mem_read/write`、`pal_spi_xfer` 用 DriverLib 轮询实现（原来返回 ENOTSUP），带超时与诊断计数。**[编译]**
- 天猛星 `.syscfg` 新增 I2C0（PA0/PA1，400 kHz）、SPI1（PB23/22/21，mode 3，1 MHz）+ 软件片选 PB20、UART1 IMU 口（PA8/PA9，460800），并用 SysConfig CLI 重新生成；board.yaml 同步，`syscfg_import --check` 能识别 I2C/SPI。**[编译]**，引脚未对照原理图。
- apps/imu_module 1.1.0：`requires_any` 支持二选一，板上有 SPI BMI088 就用它，否则用 I2C MPU6050；`mspm0g3507-tianmengxing:imu_module` 加入 make cross。**[编译]**，未上板。

### IMU 前向加速度去重力
- dzimu 1.1.0：新增 `dzimu_linear_acc`，用模块给的 roll/pitch 减掉重力分量。**[仿真]**
- 2026H：新参数 `imu_grav_comp`（默认 1），只作用于 uart 姿态模块路径，姿态未收敛的帧不用；MPU6050 直连路径仍含重力。仿真里的模块装歪 3°，e2e 测试验证去重力后接近 0、关掉后约 −0.51 m/s²。**[仿真]** 实车 **[未测]**。

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
