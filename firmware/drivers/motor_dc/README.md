# 直流有刷电机驱动（H 桥 PWM + 方向）  `v1.0.0`

支持 IN1/IN2 + PWM（TB6612 类）与单方向脚两种接法，死区、反向、刹车/滑行停止。只依赖 pal.h。

- 接口：`motor_dc_init/motor_dc_set(-1..1)/motor_dc_stop`
- 自检：`motor_dc_selftest()`（上板：短时正反转）；tests/host/test_drivers.c
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：host-sim 上的方向/占空比单测
- **未验证**：真实 TB6612 + 电机**未实测**

## 参考来源
- TB6612FNG 数据手册真值表（东芝）
