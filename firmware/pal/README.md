# PAL 硬件抽象层接口  `v1.7.0`

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
- 定时器触发 + DMA 的高速块采样**没做**（见缺口清单）。
- 思路参考 LP-MSPM0G3507_freertos_firework@ede35a2 `bsp/adc`、`bsp/dac`（块采样 + 完成通知、DAC 码与 mV 换算），代码自写。

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：host-sim 实现跑通全部主机测试
- **未验证**：stm32f4-hal / stm32-cubemx 实现只做过交叉编译，**未上板**

## 参考来源
- Zephyr 设备驱动模型、Arduino HAL 的“逻辑名 + 移植层”思想（只借鉴思想，未拷代码）
