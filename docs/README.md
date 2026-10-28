# 文档索引

| 文档 | 内容 |
|---|---|
| 01-接口规范.md | PAL 接口、逻辑 ID、错误码、ISR 规则 |
| 02-分层与依赖.md | 分层图、check_deps 规则 |
| 03-模块三件套与版本.md | README/VERSION/selftest、语义化版本、iface_hash |
| 04-入库检查清单.md | 自写模块与第三方移植入库清单（配合 audit_port） |
| 05-CubeMX工作流.md | STM32 推荐流程、HAL-only、DZ-REG-OK、引脚标签、ioc-check |
| 06-新增板卡.md | 新增一块板子的步骤 |
| 07-应用框架.md | project.yaml、子系统、协调器、示例与子系统库入库规则 |
| 08-协处理板与软核.md | Jetson Nano 等 Linux 视觉、FPGA/软核、dzframe/1、dzlink |
| 09-机械结构.md | SolidWorks/STEP/STL/3MF、拓竹打印参数、约束清单、估算工具、结构版本 |
| 10-SysConfig工作流.md | TI MSPM0 + SysConfig |
| 11-中断与实时.md | ISR 准则 |
| 12-参考工程与参数来源.md | P1/P2 角色、收编原则、counts_per_rev 与“转 10 圈”标定 |
| 13-版本管理.md | 仓库/模块两层版本、CHANGELOG、分支与提交约定 |
| 14-Keil工作流.md | AC6/AC5 要求、keil_inject.py 注入模块 |
| 15-CCS工作流.md | 天猛星导入 CCS（projectspec + .syscfg，tiarmclang） |
| 硬件路线图.md | 各板卡/协处理器状态 |
| 参考来源.md | 借鉴的开源项目与资料汇总 |

> 标注约定：**【已实测】** = 本仓库在 PC 上用测试/编译实际跑过（2026-10-28，Asia/Shanghai）；**【未验证】** = 设计意图或推断，尚未在真实硬件上做实验。实验是检验真理的唯一标准——【未验证】的内容上板前不要当结论。

