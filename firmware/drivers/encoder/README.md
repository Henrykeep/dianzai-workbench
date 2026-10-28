# 编码器测速/测位置  `v1.0.0`

读 PAL 编码器计数（已在移植层扩展为 32 位），差分得速度并经 LPF 滤波；64 位累计位置。

- 接口：`encoder_init/encoder_update/encoder_speed_rps/encoder_position_rev`
- 自检：`encoder_selftest_still()`（上板：静止抖动检查）；tests/host/test_drivers.c
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：host-sim 仿真电机下的测速单测
- **未验证**：真实编码器、counts_per_rev **未实测**

## 参考来源
- M 法测速（定时计数差分）；低速改 T 法留待后续
