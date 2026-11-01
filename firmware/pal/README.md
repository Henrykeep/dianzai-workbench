# PAL 硬件抽象层接口  `v1.8.0`

上层代码访问硬件的唯一入口：GPIO/PWM/编码器/串口/定时器/ADC/DAC/I2C/SPI/掉电存储/时间。资源用逻辑 ID（`RES_*`，由 board.yaml 生成），不出现引脚号。所有函数返回 `dz_err_t`；标 `[ISR-safe]` 的可在中断里调用。

- 接口：`pal.h`（接口）；实现位于 `ports/<port>/`
- 自检：—（接口无逻辑；各移植层的自检固件 `apps/port_selftest`）
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## ADC 块采样与 DAC（1.6.0，缺口清单第 8 项）
| 接口 | host-sim | stm32f4-hal | stm32-cubemx | mspm0-driverlib |
|---|---|---|---|---|
| `pal_adc_block_read(id, buf, n, rate_hz)` 软件定时块采样（≤ 20 kHz，周期须整数 µs，迟到报 DZ_ETIMEOUT） | 有（主机测试） | 有（同一份 `pal_adc_block.inc`，交叉编译） | 有（同上） | 有（同上） |
| `pal_dac_write / pal_dac_info` | 有（board.yaml `dac:`，`host_sim_dac_get` 观测） | DZ_ENOTSUP（冻结端口） | 有（1.7.0，HAL_DAC，交叉编译；F103C8 等无 DAC 的型号 DZ_ENOTSUP） | 有（1.7.0，DAC12 DATA0 直写，交叉编译） |
- 哪些芯片能写 `dac:`：tools/boardlib.py `DAC_PARTS`（F1 大容量/互联型、F405/407/410/413/415/417/423/427/429/437/439/446/469/479、H7/G4/L4/F7、MSPM0G350x/G150x）；F103C8/CB、F401/F411/F412、MSPM0G310x 没有 DAC，validate_board 直接拒绝并说明原因，pal_dac_write 返回 DZ_ENOTSUP。没登记的型号按“没有”处理，补表即可。
- CubeMX：DAC 外设、输出缓冲、引脚在 .ioc 里配（标签 DAC_<名>，ioc_import 会认出来）；MSPM0：SysConfig 加 DAC12 模块（输出 PA15）。
- 定时器触发 + DMA 高速块采样：board.yaml `adc[].block` 打开。stm32-cubemx 1.10.0（F1/F4，TRGO + DMA，≤200 kHz）、mspm0-driverlib 0.10.0（TIMG 零点事件 + DMA，≤500 kHz）【编译】未上板；不满足条件（无 block、不能整数分频、其他系列、f4-hal）退回软件定时。
- 思路参考 LP-MSPM0G3507_freertos_firework@ede35a2 `bsp/adc`、`bsp/dac`（块采样 + 完成通知、DAC 码与 mV 换算），代码自写。

## 三相 PWM（1.8.0，FOC / BLDC）
| 接口 | host-sim | stm32f4-hal | stm32-cubemx | mspm0-driverlib |
|---|---|---|---|---|
| `pal_pwm3_set(id, u, v, w)` 三路同周期生效 | 有（主机测试，`host_sim_pwm3_updates`） | DZ_ENOTSUP（冻结） | 有（UDIS 包住三路 CCR 写，靠预装载，交叉编译） | 有（关中断连写三路 CC，交叉编译） |
| `pal_pwm3_check(id)` 中心对齐核对 | 有（`host_sim_pwm3_edge_aligned` 模拟配错） | DZ_ENOTSUP | 读 CR1.CMS | `DL_Timer_getCounterMode == UP_DOWN` |
```yaml
pwm:
  - { name: PWM_U, timer: TIM1, channel: 1, pin: PA8,  freq_hz: 20000 }
  - { name: PWM_V, timer: TIM1, channel: 2, pin: PA9,  freq_hz: 20000 }
  - { name: PWM_W, timer: TIM1, channel: 3, pin: PA10, freq_hz: 20000 }
pwm3:
  - { name: FOC, phases: [PWM_U, PWM_V, PWM_W] }     # → RES_PWM3_FOC
```
- validate_board（boardlib.check_pwm3）：三相须同一定时器、不同通道、同频率；STM32 只认 TIM1~5/8/20（TIM9~17 不能中心对齐）；MSPM0G 只认 TIMA0 通道 0~3（TIMA1 / TIMG 只有 2 个 CC）；f4-hal 拒绝；<16 kHz 警告。自测 tools/test_pwm3_caps.py。
- CubeMX：TIM1 Counter Mode 选 Center Aligned 1/2/3，三路 PWM Mode 1、Output compare preload Enable；周期 = 2×ARR 个计数，所以 20 kHz 时 ARR = f_tim / 40000。互补输出 / 死区由 CubeMX 配（本层不碰）。MSPM0：SysConfig TIMA0 Center-aligned（Up/Down），CC 更新方式选“计数到零”。
- 上层：`firmware/algo/foc` 出 0..1 占空比 → `foc_duty_to_pal` → `pal_pwm3_set`。【编译】真板没跑过。

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：host-sim 实现跑通全部主机测试
- **未验证**：stm32f4-hal / stm32-cubemx 实现只做过交叉编译，**未上板**

## 参考来源
- Zephyr 设备驱动模型、Arduino HAL 的“逻辑名 + 移植层”思想（只借鉴思想，未拷代码）
