# 更新日志

格式参照 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。
每条末尾标注验证程度：**[上板]** 真实硬件实测；**[仿真]** host-sim / 单元测试通过；**[编译]** 仅交叉编译通过；**[未测]** 未编译或未运行。
时间为 Asia/Shanghai。仓库整体版本见 git 附注标签；各模块另有自己的 VERSION（见 docs/03、docs/13）。

## [未发布]

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
