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
2. **第 1 步 读题拆解**：`tools/req.py` + `schema/requirements.schema.json` + `docs/templates/requirements.yaml`；实例 `examples/2026H_ball/requirements.yaml`。见 docs/31。
3. **第 2 步 方案选型**：`tools/scheme.py` + `tools/catalog/parts.yaml`；读第 1 步的 needs/constraints；实例 `examples/2026H_ball/scheme.yaml`。见 docs/31。
仍未做（按清单优先级）：实板验证、第二道例题（建议跟随小车）、机械/3D 模板与参数化零件库、参数预设/掉电保存、last-good 对比、赛前准备清单。4. **第 3 步 资源分配**：`tools/alloc.py`（器件库 `res` 字段 → stm32f4 贪心分配 → board.yaml 草稿 + cubemx.md + alloc.md，交 boardlib 同一检查；`--fixed` 沿用已有板接线）。实例 `examples/2026H_ball/alloc/`（make check 校验输出未漂移）。stm32f1/mspm0 只出需求清单。器件库加可选 price_cny(+price_note)/power_w，目前一件都没填（不编数）。
   顺手修：boardlib mspm0 定时器为 TODO 时误报“不存在”。
