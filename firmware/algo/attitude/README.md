# 互补滤波求姿态（roll / pitch）  `v1.0.0`

输入 IMU 的加速度（m/s²）和角速度（rad/s），输出横滚角和俯仰角（rad）。不算 yaw。

- `attitude_init(&a, tau_s, acc_gate)`：`tau_s` 一般取 0.3～1 s；`acc_gate` 取 0.15
- 剩余陀螺零偏 b 会造成稳态误差 b·tau，所以开机要静止标定零偏（MPU6050 和 BMI088 驱动都有 `calib_gyro`）
- 急加速或碰撞时 |a| 不等于 1 g，这一拍只积分陀螺（门限 acc_gate）

## 验证状态
- **已实测（PC 主机）**：静止倾斜收敛、零偏稳态误差、加速度门限、俯仰（selftest 和 tests/host/test_imu.c）
- **未验证**：真车振动环境下 tau 的取值

## 参考来源
- 标准互补滤波与欧拉角运动学公式（教科书内容，自写）
