# hcsr04 — 超声波测距

10 us 触发 + 回波脉宽计时，非阻塞；气温补偿声速 c = 331.3 + 0.606·T m/s；量程外/无回波报无效。

## board.yaml
```yaml
gpio:
  - { name: US_TRIG, pin: PA0, dir: out }
  - { name: US_ECHO, pin: PA1, dir: in }   # 5 V 模块：ECHO 经 1k/2k 分压到 3.3 V（或选 5 V 容忍脚）
```

## 用法
```c
hcsr04_init(&us, &(hcsr04_cfg_t){ RES_GPIO_US_TRIG, RES_GPIO_US_ECHO, 60, 25000, 20, 4000 });
/* 轮询（简单，精度=轮询周期）：100 us 定时任务里 */
if (hcsr04_update(&us, pal_millis(), pal_micros(), true) && hcsr04_valid(&us)) d = hcsr04_mm(&us);
/* 中断（精度 ~1 us，PAL 1.2.0）：init 后挂一次，主循环照常 update（引脚不再轮询，只管触发与超时） */
if (hcsr04_attach_irq(&us) != DZ_OK) { /* 端口不支持：继续轮询 */ }
```
- 中断模式用 PAL 1.2.0 `pal_gpio_irq_attach`：STM32 CubeMX 工程里把 ECHO 脚设成 GPIO_EXTIx（Both edges）并在 NVIC 勾上对应 EXTI；
  STM32F4 裸 HAL 端口和 MSPM0 运行时自己配（MSPM0 的 .syscfg 只需把 ECHO 设成输入）。
- 对着斜面、软物体（衣服）、窄物体会测不到或跳变，应用层加中值滤波。
- 多个超声波不要同时触发（串扰），轮流测。

## 测试状态
- 【已实测】主机单测：假模块（触发后 450 us 起回波），轮询 100 us 下 500 mm 误差 < 20 mm；边沿模式 300 mm 误差 < 1 mm；host-sim 的 PAL 边沿中断模式（hcsr04_attach_irq）；超时；太近；非法配置。
- 【未验证】上板；温补系数为干燥空气近似。
- 【编译】STM32/MSPM0 的 pal_gpio_irq_attach 只交叉编译，未上板。
