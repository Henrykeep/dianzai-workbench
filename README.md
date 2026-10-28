# 电赛工作台（第 0 阶段）

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
| ports/ | 移植层：host-sim、stm32-cubemx（推荐）、stm32f4-hal |
| boards/ | 每板一个 board.yaml（天空星、RoboMaster C 型、天猛星、Jetson Nano 协处理…） |
| apps/ examples/ | 演示应用、题目实例（2026H_ball） |
| host/python/dzlink | 协处理板/PC 端协议库 |
| mechanical/ | SolidWorks + STEP/STL + Bambu Studio 3MF 模型库与结构约束（预留） |
| tools/ | 生成器与检查器 |
| docs/ | 设计文档，从 docs/README.md 开始 |

## 验证状态（实验是检验真理的唯一标准）
- **已实测**：PC 上 178 项主机测试、dzlink 回环、各检查器自检；交叉编译（skystar、skystar-cubemx、dji-rm-c 临时 HSE）。
- **未验证**：**所有硬件行为**——本阶段没有任何代码上过真实板子。合成的 .ioc/.syscfg 未经官方工具打开。

远端：本仓库仅本地 git，不推送。
