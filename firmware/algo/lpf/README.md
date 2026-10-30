# 低通 / 陷波滤波  `v1.2.0`

指数平滑 y += α(x−y)，可按截止频率+采样周期或直接给 α 初始化。用于速度、前馈加速度等噪声信号。

- 接口：`lpf1_init/lpf1_init_alpha/lpf1_update/lpf1_reset`
- 自检：`lpf1_selftest()`；tests/host/test_lpf.c
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 二阶低通 lpf2p + 陷波 notch（biquad.h）
- `lpf2p_init(f, fc, fs)` Butterworth 二阶；`notch_init(f, fc, bw, att_db, fs)` 去电机/螺旋桨固定频率振动；都用 `biquad_update/reset/clear`。
- 什么时候用：要压高频噪声又不想拖慢环路时。fs=1 kHz、100 Hz 处都衰减 20 dB 的对照（tests/host/test_lpf.c 实测）：

| 滤波器 | 截止 | 2 Hz 滞后 | 5 Hz 滞后 | 50 Hz 衰减 |
|---|---|---|---|---|
| lpf1 | 9.9 Hz | 11.1° | 25.9° | −14.2 dB |
| lpf2p | 32.7 Hz | 4.9° | 12.5° | −8.2 dB |

  同样滤噪，lpf2p 相位滞后约减半；代价是每样本 5 乘 4 加、50 Hz 附近压得少。只要平滑、不在环里的量继续用 lpf1。

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：阶跃响应/时间常数主机单测
- **未验证**：—

## 参考来源
- lpf2p/notch：净室推导——模拟 Butterworth / 有限深度陷波原型 + 预畸变双线性变换（Oppenheim & Schafer《Discrete-Time Signal Processing》§7.1；R. Bristow-Johnson《Audio EQ Cookbook》），推导写在 biquad.c 文件头；未参照任何 GPL 实现
- 标准一阶 RC 离散化（α = dt/(RC+dt)），见任一数字信号处理教材
