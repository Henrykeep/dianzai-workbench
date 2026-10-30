# 文档索引

**板子名字别搞混**（两块都是立创开发板，名字只差一个字）：

| 叫法 | 芯片 | 仓库里的板卡目录 | IDE |
|---|---|---|---|
| **天空星** | STM32F407（VET6 / VGT6） | `boards/stm32f407-skystar`、`boards/stm32f407-skystar-cubemx` | Keil / CubeMX |
| **天猛星** | TI MSPM0G3507 | `boards/mspm0g3507-tianmengxing` | CCS / SysConfig |

`tools/check_ai_docs.py` 会检查：同一行里“天空星”不能和 MSPM0、“天猛星”不能和 F407/STM32 写在一起。<!-- board-names-ok -->

| 文档 | 内容 |
|---|---|
| 00-快速上手.md | **第一次用先看**：装 exe、CubeMX、Keil 加模块、ST-Link/DAPLink 烧录、连接、Agent 调参、急停（带截图） |
| 01-接口规范.md | PAL 接口、逻辑 ID、错误码、ISR 规则 |
| 02-分层与依赖.md | 分层图、check_deps 规则 |
| 03-模块三件套与版本.md | README/VERSION/selftest、语义化版本、iface_hash |
| 04-入库检查清单.md | 自写模块与第三方移植入库清单（配合 audit_port） |
| 05-CubeMX工作流.md | STM32 推荐流程、HAL-only、DZ-REG-OK、引脚标签、ioc-check |
| 06-新增板卡.md | 新增一块板子的步骤 |
| 07-应用框架.md | project.yaml、子系统、协调器、示例与子系统库入库规则 |
| 08-协处理板与软核.md | Jetson Nano 等 Linux 视觉、K230 视觉脚本库（复用参考仓库）、FPGA/软核、dzframe/1、dzlink |
| 09-机械结构.md | SolidWorks/STEP/STL/3MF、拓竹打印参数、约束清单、估算工具（mechanical/calc）、机构模板（mechanical/templates）、CadQuery 零件（mechanical/parts）、结构版本 |
| 10-SysConfig工作流.md | TI MSPM0 + SysConfig |
| 11-中断与实时.md | ISR 准则 |
| 12-参考工程与参数来源.md | P1/P2 角色、收编原则、counts_per_rev 与“转 10 圈”标定 |
| 13-版本管理.md | 仓库/模块两层版本、CHANGELOG、分支与提交约定 |
| 14-Keil工作流.md | AC6/AC5 要求、keil_inject.py 注入模块、掉电保存区 .sct |
| 15-CCS工作流.md | 天猛星导入 CCS（projectspec + .syscfg，tiarmclang） |
| 16-VSCode工作流.md | tasks/launch（Cortex-Debug，OpenOCD/pyOCD）、EIDE 可选 |
| 17-桌面工作台.md | dzbench：曲线/参数/急停/回放、自定义帧结构（JustFloat/FireWater/HEX 表），侧车 WebSocket 协议，Agent 接缝；仿真 PSO/分阶段 PID 搜索（tuning/search.py，实机只验 top-k；Agent 栏“仿真搜索”按钮，可选宽范围） |
| 18-内置Agent.md | 分层写权限网关、diff 确认 + make check + git 提交/回滚、可插拔大模型、离线阶跃整定 |
| agent-knowledge/ | 内置 Agent 按触发词加载的知识（堵转/极性/阶跃辨识/视觉：K230、颜色识别、视觉调参）与人工接受后写入的项目记忆 |
| 19-赛题覆盖矩阵.md | 历年控制题 × 所需能力 × 仓库现状（有/部分/缺），用于排模块 |
| 20-MSPM0速查.md | MSPM0 坑位速查（宏名、QEI、时钟、版本锁），给 AI 和赶时间的人 |
| 21-结构与3D打印.md | SolidWorks → Bambu Studio 检查清单、材料、电机/编码器/摄像头/PCB 安装座要点（给控制方向同学） |
| 22-协处理器发送库.md | Jetson / 树莓派 / RDK / MaixCAM / K230 用 dzlink 发 dzframe：串口自动探测、Sender、K230 单文件 |
| 23-质量审计.md | v0.7.0 全仓审计：发现的问题、改了什么、为什么有些不改 |
| 24-Agent框架研读.md | 读 Codex / Gemini CLI / Aider / Cline / OpenHands 等源码：采纳什么、不采纳什么、许可证 |
| 25-v0.9计划.md | v0.9 合并计划（P0 优先） |
| 26-UI规范.md | 界面规范：网格、字阶、配色、组件、信息层级 |
| 27-复用性审计.md | 复用性审计：换板实测、可读性、题目覆盖率、参考仓库对照、缺口排序 |
| 28-30分钟换板清单.md | 新人换板清单（准备→选起点→改引脚→检查→自检→单电机闭环）与各板最小例程表 |
| 29-全流程走查.md | 用 2026H 在仿真里从读题走到定稿：摩擦清单、已修项、下一步优先级 |
| 30-验收标定与串级分层.md | yaml 里写 cal / accept / loops：物理单位、评委口径的到位判定与最差 N 轮、串级逐层调法 |
| 31-读题拆解与方案选型.md | 第 1、2 步：题目 PDF → requirements.yaml → 测试清单（tools/req.py）；按能力标签出候选/替代/禁用（tools/scheme.py） |
| ../examples/2026X_follow/README.md | 第二道参考例题：D 题式双车循线跟车（line_obs + peerlink + follow，9 步全套 + 双车安全回归） |
| verify/README.md | 验证证据目录规范：`logs/<时间>_task<编号>_<层>/`、必备文件、req.py evidence 合规与计分表 |
| 32-控制安全对照.md | 8 项控制安全（限流、堵转、软限位、急停、看门狗、无扰切换…）对照本仓库的有/缺；极性自检（标定第 0 步）；通用安全件 framework/safety + 黑匣子 |
| SELFCHECK.md | 里程碑自检（按宗旨逐条） |
| HANDOVER.md | 交接：宗旨、用户偏好、现状、未完成项 |
| MORNING.md | 给你的一页清单：要带什么、要量什么、要拍板什么 |
| QUESTIONS.md | 待你确认的问题 |
| 硬件路线图.md | 各板卡/协处理器状态 |
| 参考来源.md | 借鉴的开源项目与资料汇总 |
| templates/report.md | 设计报告骨架；测试结果一节用 `tools/report.py` 从录像生成 |

> 标注约定：**【已实测】** = 本仓库在 PC 上用测试/编译实际跑过（2026-10-28，Asia/Shanghai）；**【未验证】** = 设计意图或推断，尚未在真实硬件上做实验。实验是检验真理的唯一标准——【未验证】的内容上板前不要当结论。

