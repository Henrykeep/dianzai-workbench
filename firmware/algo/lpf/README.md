# 一阶低通滤波  `v1.0.0`

指数平滑 y += α(x−y)，可按截止频率+采样周期或直接给 α 初始化。用于速度、前馈加速度等噪声信号。

- 接口：`lpf1_init/lpf1_init_alpha/lpf1_update/lpf1_reset`
- 自检：`lpf1_selftest()`；tests/host/test_lpf.c
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：阶跃响应/时间常数主机单测
- **未验证**：—

## 参考来源
- 标准一阶 RC 离散化（α = dt/(RC+dt)），见任一数字信号处理教材
