# 交接摘要（2026-10-29 14:30 UTC+8，接手自“嵌入式开发”会话，已通读 1071 条记录 + docs/ + user-projects/）

## 目标（初衷，t0u/t1u/t152u）
用户大三、电控方向，要准备电赛又要考研。要做的是一个**体系**：可复用的固件框架（CubeMX+HAL / SysConfig+DriverLib，换板只改引脚），加一个 **exe 桌面工作台**（Tauri + Python 侧车 + 内置 Agent）。工作台接串口/DMA 遥测，用来看曲线、调 PID、做阶跃和扫频，Agent 当“得力助手”。**不针对某一道题**：26H 钢珠平衡只是举例，要能应万变。

## 宗旨（用户反复强调，每个里程碑都要在 SELFCHECK.md 里逐条自检）
1. 顾全大局：通用、schema 驱动，界面不写题目字段名，各板卡都要考虑（c8t6 / 天空星 407 VET6·VGT6 / 天猛星 MSPM0G3507，以后还有其他板和 FPGA）。
2. 不堆屎山：分层、文件要小、只用变量，一次性规则要并进组件。
3. 带着脑子：自己按做题的完整过程去想，不要用户说一句才做一句；每个取舍写进文档。
4. 站在巨人的肩膀上：善用搜索，克隆仓库学透（SerialWeb、llm-pid-tuner、PID_Helper、deepseek-harness、codex、gemini-cli……）。
5. 实验是检验真理的唯一标准：截图、测试，没上板的标 [未测]。
6. 客观分析，客观对待：如实写弱点。
7. 创新：能创新时才创新，不为创新而创新。
8. 站在用户的角度：走查真实使用流程。
外加：做好版本管理（语义化版本、CHANGELOG 四级标注、一个逻辑改动一个提交、推送前 `make check`、`make test` 和 `make preflight`）。

## 用户偏好
- 不要停下：没让停就继续做，问题攒着第二天一起问（写进 QUESTIONS.md / MORNING.md）。
- UI：要“好看、高级、有工作台的样子”。参照 Saleae Logic 2、Linear、Grafana 这类仪器软件：中性深灰，停靠面板用分隔线分开，数字等宽对齐，蓝色点缀要克制。**不要紫色**，不要网页仪表盘那种卡片风。学参考要学到精髓，不要半吊子；要自己拿主意（“你不要我说什么就是什么”“自己看”）。
- 写代码用 Keil5 / CCS，也接受 VSCode 等。STM32 一律 HAL，不写寄存器。调试器用 ST-Link（队友用 DAP-Link）。
- CI 一失败用户就会收到邮件，所以 CI 必须保持全绿（app-windows 以前失败过）。

## 现状
- 仓库 Henrykeep/dianzai-workbench，v0.11.0 已打 tag。之后的提交：89e4a3c、704baf3（docs/26 v4 原则）。
- UI 改版：v4 设计稿（shots/redesign/v4/，17 条原则见 docs/26 和 refs/design-study.md）已获用户放行（“自己看”）。本次接手开始把它落进 app/ui。
- 实机几乎全部是 [未测]，见 MORNING.md：电池分压比、编码器、QD4310 CRC、天猛星原理图等。

## 待办 / 待确认
- v4 里还没在代码中实现的（见 docs/26 §5）：以阶跃为锚点的时间轴、A/B 区间测量、上一轮余辉、实验历史表、1280×800 下的布局、高对比主题、CJK 字体调优。
- SIM_APPS 已改成扫描（v0.11）。docs/19 排期里还有跟随小车、起摆、风力摆。
- QUESTIONS.md 里的 [待你确认] 9–12 项，以及 MORNING.md 的硬件清单。
- 对用户的承诺：每一步都截图核对再报告；截图要在最后一次改动之后重拍；只报告能在截图里指出来的结论。

## 2026-10-29 晚（UTC+8）：核对清单后的第一批
依据：全盘核对清单 Page（设计文档逐条对照仓库）。按优先级先做了三件，每件一个提交：
1. **偏离修复**：加速度前馈 → `firmware/algo/accel_ff` 1.0.0（通用、无板卡依赖）；2026H ball.c 只保留来源选择（编码器/IMU + 超时）。主机单测与提取前公式逐点比对，example 35/35。
2. **第 1 步 读题拆解**：`tools/req.py` + `schema/requirements.schema.json` + `docs/templates/requirements.yaml`；实例 `examples/2026H_ball/requirements.yaml`、第二例题 `examples/2026X_follow/requirements.yaml`（双车跟车）。见 docs/31。
3. **第 2 步 方案选型**：`tools/scheme.py` + `tools/catalog/parts.yaml`；读第 1 步的 needs/constraints；实例 `examples/2026H_ball/scheme.yaml`、`examples/2026X_follow/scheme.yaml`。见 docs/31。
4. **第 3 步 资源分配**：`tools/alloc.py`（器件库 `res` 字段 → stm32f4 贪心分配 → board.yaml 草稿 + cubemx.md + alloc.md，交 boardlib 同一检查；`--fixed` 沿用已有板接线）。实例 `examples/2026H_ball/alloc/`、`examples/2026X_follow/alloc/`（app requires 的 timer 自动补分配；make check 校验输出未漂移）。mspm0 只出需求清单（stm32f1 见第 6 项）。器件库加可选 price_cny(+price_note)/power_w，目前一件都没填（不编数）。
   顺手修：boardlib mspm0 定时器为 TODO 时误报“不存在”。
5. **第 4 步 机械**：`mechanical/calc/mech.py`（通用惯量/扭矩/电机核对 + 三种机构）、`mechanical/templates/`（差速底盘/云台/球杆平板）、`mechanical/parts/`（CadQuery 可选，电机座/编码器支架/传感器支架 → STEP+STL）。CI 不装 CadQuery，test_parts 在 CI 是跳过；本机 /workspace/cqenv 装了 2.8.0 实测通过。
6. **alloc 支持 STM32F1（C8T6 LQFP48）**：`tools/families/stm32f1.py`，整组重映射；boardlib 的 STM32 检查改为表驱动共用。
7. **验证证据与计分**（参考 DS 合规差距/计分矩阵、MICU 五元组）：requirements.yaml 评分项可选 `why` / `forbidden_claims` / `evidence[{path,layer,date,result}]`；`req.py check` 核对证据目录存在、目录名（`docs/verify/<题号>/logs/<YYYYMMDD-HHMM>_task<编号>_<层>/`）与层/日期/编号一致；`req.py evidence` 出五元组表 + 状态 + 禁止表述（非现场通过自动禁说“已得分”）；`req.py newlog` 建目录；`report.py --req-file --item` 把证据行带进报告并建议 evidence 条目。规范 docs/verify/README.md；2026H B3 有一条真实单元层 partial 证据。
8. **参数回读 / 固件版本 / 黑匣子**：dzctl 0.4.0 心跳带 fw_rev；侧车 export_readback → params.txt；tools/params_diff.py（last-good）；firmware/framework/blackbox（存储失败不挡启动，有测试）。片内 flash 回调未写。
9. **极性自检 / 堵转 / 安全对照**：侧车 agent/polarity.py（op polarity_check）；firmware/algo/stall；docs/32 对照表——缺口：IWDG 没开没喂（最该先补）、stall 未接进应用。
仍未做（按清单优先级）：实板验证、第二道例题（建议跟随小车）、参数预设/掉电保存、界面上的回读/对比按钮、赛前准备清单。
### 第 10 项：直接使用外部代码的规矩（2026-10-29，UTC+8）
- `third_party/vendored/<来源>/`：搬来的代码 + 原样 LICENSE + SOURCE.md；文件头 `Source: <repo>@<commit> <path>`。`.gitignore` 改为 `third_party/*` + `!third_party/vendored/`。
- `tools/check_vendored.py` 在 make check 里强制。GPL 代码（PID_Helper 辨识，第 13 项）放这里；侧车通过 `dzbench/tuning/` 薄层调用，PyInstaller 需加 `--paths third_party/vendored`。
- 已有的“参考 …”文件都是思路借鉴、代码自写，不加 Source: 头。
- 顺带修：第 8 项 params_readback 没有界面入口导致 test_wiring 失败 → 参数面板加“回读”按钮。

### 第 13 项：PID_Helper 辨识直接移植（2026-10-29，UTC+8）
- 本体 `third_party/vendored/pid_helper/pid_helper_ident.py`（GPL-3.0，逐函数移植，改动列在 SOURCE.md）；适配层 `app/sidecar/dzbench/tuning/identify.py`：`steady_state`、`open_loop_pid`、分阶段打分。
- experiment.py 的自写稳态判定已删除（不留两份）；StagedSearch / 四段阶跃 / 相对打分仍是自写。
- 待做：`open_loop_test` 只有门禁（require_open_loop）没有执行入口，接上时直接调 `identify.open_loop_pid`。

### 第 11 项：Agent 护栏（2026-10-29，UTC+8）
- `agent/stuck.py`（OpenHands 移植）、`agent/untrusted.py`（工具结果包 `<工具数据>`）、`AgentLoop._trim_middle`（头尾裁剪）、`gateway.similar_lines`（aider 移植）。说明在 docs/18 末节。
- 解析工具消息的地方要先 `untrusted.unwrap()`（offline.py、stuck.py、测试已改）。

### 第 14 项：信号类模块 + 板上菜单（2026-10-29，UTC+8）
- 新模块 algo/spectrum、sigfilt、dds、capfreq，framework/menu，drivers/keypad4x4；测试 tests/host/test_signal.c。来自 firework 的 MIT 代码放在 firmware 树里（逐文件 Source 头），不进 third_party/vendored（那里留给需要隔离的 GPL）。
- 没做：ADC 定时器触发 + DMA 块采集（pal 要新增接口，各 port 都得实现，单列一项）、AD9833/AD9850 驱动、菜单接进 app 的例子。firework 的 4429 行 display_menu.c 和 2409 行 waveform_measurement.c 没搬（业务耦合太重）。

### 第 12 项：Agent 上下文（2026-10-29，UTC+8）
- `agent/codemap.py`（仓库地图，git 状态缓存）、`agent/knowledge.py`（触发词知识 + 项目记忆）、`docs/agent-knowledge/`。新增工具 repo_map（AUTO）、remember（LOG，走网关 diff 卡片，人接受才写）。
- 新知识文件：加 `triggers:` 头即可，不用改代码；README.md 无触发词不会被加载。

### 看门狗（2026-10-29，UTC+8）
- pal 1.3.0 `pal_wdg_start/kick`；实现只在 stm32-cubemx（寄存器直写），MSPM0 WWDT 待做。复位原因进心跳、被咬后进安全态还没做。

### 保护表 / 告警条 / 赛前检查（2026-10-29，UTC+8）
- 保护表：app.yaml 参数加 `protect:` 分类、`protect_fixed:` 列编译期常量（都不进 schema 哈希）；界面 `protect.ts`，撤销栈 UndoLog 只记“保护”页下发。堵转电流行没有——algo/stall 还没接进任何 app。
- 告警条：`alerts.ts`；确认位置存侧车 `Timeline.acked`（op alert_ack，广播同步多窗口）。
- 赛前检查：`precontest.py`；判定项加在 board_items，人工项改 MANUAL 列表；“哪些路径算固件”改 FW_PATHS（tools/ 只算 gen_* / boardlib / families / syscfg_gen.sh 这些生成代码的）。
- 心跳 status 字（dzctl 0.5.0）：应用在 app_init 里 `dzctl_set_reset_cause(pal_reset_cause())`，安全态/堵转/急停用 `dzctl_set_flags`；car_2wd 是范例。侧车 `hb_status_event` 决定哪些进时间线。
- 掉电保存：`framework/persist` 1.1.0 + `drivers/nvm_pal`；stm32-cubemx（F1/F4）与 mspm0 已有真实现（board.yaml `mcu.nvm_kb`），**全部 [编译] 未上板**——第一次上板先跑 car_2wd：改个参数 → 存参数 → 断电 → 读黑匣子看 `上电读参数：用了 flash 里存的`。MSPM0 ECC：写到一半掉电的 64 位字读出来可能触发 ECC 错（NMI），没实测。Keil / CCS：`tools/gen_ide_nvm.py` 生成 `boards/<板>/keil/dz_nvm.sct` 与 `ccs/dz_nvm_linker.cmd`，keil_inject `--board` / projectspec 自动用上（[未测] 没在 Keil/CCS 里编译过——第一次在 Keil 里编译请看 map 里 ER_DZ_NVM 地址）。stm32f4-hal 端口仍 ENOTSUP。car_2wd 1.3.0 已接存参数（'W'）+ 急停冻结黑匣子。
- 跟车：`proto/peerlink`（帧）+ `algo/follow`（控制），还没有应用接（D 类例题接）。
- 丢线恢复 `algo/line_obs`：已接进 line_car 1.1.0（找线 + 黑匣子）；找线速度/扫幅只在仿真里调过，真车 [未测]。
- 安全通用件 `framework/safety`：新应用照 car_2wd 或 2026H_ball/io/io_safety.c 接（init/boot/update/clear 四个调用 + 心跳标志 + 0x7D 导出）。黑匣子只有 RAM 环。
- MSPM0 看门狗：WWDT0，`wwdt_calc.h` 档位粗；复位原因映射【编译】未上板核实。

### 心跳条（2026-10-29，UTC+8）
- 侧车 `linkhealth.py`（每秒格子，status 里的 `hb` + op `health`），界面 `hbstrip.ts`，曲线 `Plot.jumpTo`（`view` 非空 = 视图钉住，按 P 继续时清掉）。格子同时带 log_t（dzlog 时间）和 plot_t（曲线时间），后面的事件时间线复用同一对时间。
- 事件时间线：`events.py`（from_broadcast / from_reply 分类表 + Timeline），会话内的看门狗/CRC 突增由 `Session.mark` 在 status() 里记；界面 `timeline.ts`，曲线 `Plot.setMarks`。
- 已知：一个 status() 被 hello 先拿走的格子不会再广播，界面连上时用 op health 补齐（按 i 去重）。

## 2026-10-30（UTC+8）：参考仓库 15 项缺口（/workspace/refs/REFS_REVIEW.md“优先级”表，按顺序做）
1. 自定义 HEX/文本帧结构表 → `app/sidecar/dzbench/framedef.py` + 连接设置“非工作台帧”。[仿真]
2. 完整 PSO + 分阶段搜索（仿真跑，实机只验 top-k）→ `app/sidecar/dzbench/tuning/search.py` + vendored `pid_helper_pso.py`。[仿真]；没加侧车 op / 界面，下一步可把 identify 的 FOPDT 直接喂给它。
   - 已接界面：Agent 栏“仿真搜索”→ op `tune_search` → 候选“上板验证”= `tune_propose` 提议卡（确认后才写）。`wide` 可选宽范围。
   - 评测稳定性：`dzbench/agent/evals.py` 等阶跃改按板子时间判定（wait_step_in_window），不再固定 sleep；满载 CPU 下 2026H 评测通过。
   - 上板验证可勾“全部采纳后自动阶跃”：service.propose_hint(verify_step) / verify_after_decide，server 的 proposal_decide 在整组采纳后后台跑 run_step_test，护栏判定走 tune_round。
3. 速度/位置环预设 + 平滑切换 → 快照 `mode` 标签 + `snapshot_restore(ramp_s)`（session.py / snapshots.ramp_plan，界面快照页“—/速度环/位置环”和过渡秒数）。[仿真]；固件参数表没加模式字段（真要切环结构需固件自己有 mode 参数，可作为普通参数放进预设）。
4. 最好一轮自动记录 + 一键回滚 + max_step_ratio → service._save_best_snapshot（快照“自动-最好一轮”）、Agent 菜单“回到最好一轮”（tune_best / tune_rollback_best）、config `tune.max_step_ratio` → TuneGuard.profile（只收紧）。[仿真]
5. K230 视觉脚本库 → `third_party/vendored/k230_edc_skill/`、`k230_mspm0g_contest/`（上游原样 + `DZ_FRAME` 补丁）+ `boards/k230-vision/board.yaml` + `tools/test_k230_vision.py`；说明见 docs/08“K230 视觉脚本库”。[编译]；没在 K230 上跑过；EDC-Skill 无许可证，公开前要作者许可；钢球 kmodel 不在仓库。
6. 视觉知识包 → `docs/agent-knowledge/vision-{k230,color,tuning}.md`（触发词按需加载，knowledge.py 不用改）+ app/sidecar/tests/test_knowledge_vision.py。[仿真]；没做真实对话里的效果评测。
7. 波形测量 → `firmware/algo/wavemeas`（移植 firework 时域特征 + 分类，自写过零测频/占空比/DFT 相位）+ `dzbench/wavemeas.py` + op `wave_measure`（频谱视图参数行、相位参考下拉）。[仿真]；未上板；原版分类对非 50% 占空比方波不判 SQUARE（照原版）。阈值触发、任意波形输出没做。
8. ADC/DAC PAL → PAL 1.6.0：`pal_adc_block_read`（软件定时，四端口共用 `firmware/pal/pal_adc_block.inc`）、`pal_dac_write/info` + board.yaml `dac:`（只 host-sim 实现，真板端口 DZ_ENOTSUP，validate_board 拒绝真板写 dac）。端口版本 host-sim 2.5.0 / cubemx 1.8.0 / f4-hal 1.4.0 / mspm0 0.8.0。[仿真]；没做定时器触发 + DMA、真板 DAC。
