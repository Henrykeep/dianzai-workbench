# foc — 电压型 FOC（无刷电机 / 云台电机）

无电流采样的 SimpleFOC 式电压控制：Clarke / Park / 反 Park、SVPWM（中点注入）、开环速度、角度闭环（PID → Uq）、上电对齐（零电角度、传感器方向、极对数检查）。纯 C，不碰硬件：输入机械角，输出三相占空比 0..1。

## 用法
```c
foc_init(&foc, &(foc_cfg_t){ .pole_pairs = 7, .vbus = 12, .v_limit = 6, .kp = 2, .ki = 4, .kd = 0.06f });
/* 对齐（电机会先转一个电周期再转回来，约 4×t_align_s） */
while (foc_align_step(&foc, as5600_angle_multi(&enc), dt, du) == DZ_EBUSY) { pwm3(du); wait(dt); as5600_update(&enc, pal_micros()); }
/* 记下 foc.zero_e / foc.dir 存参数表，下次 foc_set_calibration 跳过对齐 */
foc_angle_step(&foc, target, as5600_angle_multi(&enc), as5600_velocity(&enc), dt, du);  pwm3(du);
```
- 开环 `foc_openloop_step(&foc, vel, uq, dt, du)` 不需要传感器，用来先确认三相接线和极对数（转速 = vel）。
- 对齐返回 DZ_EFAIL：`pp_est` 和配置差太多 → 极对数填错；几乎没转 → 电机没接 / v_align 太小。
- 驱动板（如 QD4310 / DRV8313 / SimpleFOC Mini）三路 PWM 中心对齐、≥20 kHz；电压控制下电流 ≈ Uq/R，v_limit 别超过电机允许电流 × 相电阻。

## 测试状态
- 【仿真】主机单测（tests/host/test_foc.c，简化 PMSM 模型 iq=(vq−ke·ωe)/R）：变换往返、SVPWM 线电压 / 范围 / 超限缩回、开环同步、对齐（传感器正 / 反装）后零点误差 < 0.05 rad、带负载角度闭环、极对数配错和电机不转报错、假 AS5600 端到端（磁铁反装、走超过一圈）。
- 【未测】真电机、真驱动板；模型没有电感、齿槽、死区。
- 参考：SimpleFOC (Arduino-FOC) BLDCMotor::setPhaseVoltage / alignSensor；pid_helper 例程 foc_dev.c（见 docs/参考来源.md）。
