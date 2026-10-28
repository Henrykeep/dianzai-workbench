# PAL 硬件抽象层接口  `v1.0.0`

上层代码访问硬件的唯一入口：GPIO/PWM/编码器/串口/定时器/ADC/时间。资源用逻辑 ID（`RES_*`，由 board.yaml 生成），不出现引脚号。所有函数返回 `dz_err_t`；标 `[ISR-safe]` 的可在中断里调用。

- 接口：`pal.h`（接口）；实现位于 `ports/<port>/`
- 自检：—（接口无逻辑；各移植层的自检固件 `apps/port_selftest`）
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：host-sim 实现跑通全部主机测试
- **未验证**：stm32f4-hal / stm32-cubemx 实现只做过交叉编译，**未上板**

## 参考来源
- Zephyr 设备驱动模型、Arduino HAL 的“逻辑名 + 移植层”思想（只借鉴思想，未拷代码）
