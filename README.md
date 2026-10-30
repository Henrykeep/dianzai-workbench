# 电赛工作台

可移植、可复用的电赛嵌入式工作台：**换板只改 `BOARD=`，换题只写 `project.yaml` + 子系统**。

> **第一次用？** 看 [docs/00-快速上手.md](docs/00-快速上手.md)：装 exe → CubeMX → Keil 加模块 → 烧录 → 连接 → Agent 调参 → 急停。

```
make test                                   # 主机单测 + 仿真闭环
make check                                  # 板卡校验、依赖规则、接口版本、ioc/syscfg/audit 自检
make BOARD=stm32f407-skystar-cubemx APP=motor_speed_demo   # 交叉编译（需 arm-none-eabi-gcc，HAL 见 tools/fetch_stm32f4.sh）
make selftest BOARD=<板>                    # 移植层自检固件
```

| 目录 | 内容 |
|---|---|
| firmware/ | 与芯片无关：pal 接口、algo（pid/lpf）、proto（dzframe）、drivers、framework（subsys/coord） |
| ports/ | 移植层：host-sim、stm32-cubemx（STM32 唯一主线）、stm32f4-hal（冻结，仅存量两块板） |
| boards/ | 每板一个 board.yaml（天空星、RoboMaster C 型、天猛星、Jetson Nano 协处理…） |
| apps/ examples/ | 通用仿真被控对象（速度环 car_2wd、位置环 motor_pos、旋转倒立摆 pendulum_rot、视觉云台 pan_tilt、循线 line_car），题目实例（examples/2026H_ball 只是其中一个） |
| host/python/dzlink | 协处理板/PC 端协议库 |
| mechanical/ | SolidWorks + STEP/STL + Bambu Studio 3MF 模型库与结构约束（预留） |
| tools/ | 生成器与检查器 |
| docs/ | 设计文档，从 docs/README.md 开始 |

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 上）**：`make preflight`（干净克隆 + 空 HOME：make check、make test〔主机单测 + 仿真闭环 + 侧车 pytest〕、make compat、交叉编译）推送前要求在要推的那个提交上跑通；界面类型检查与单测（app/ui/tests）另跑；新界面在无头 Chrome 里对着 host-sim 走过。
- **未验证**：**硬件行为**——CHANGELOG 里还没有一条 [上板]，真板、真电机、真传感器都要你带板子验（清单见 docs/dev/MORNING.md）。合成的 .ioc/.syscfg 没用官方工具打开过；Tauri 桌面壳里大部分新界面没点过。

远端：GitHub `Henrykeep/dianzai-workbench`（main）；版本见 git 附注标签（当前 v0.10.0）和 CHANGELOG。
