# spectrum — 频谱分析（FFT）  `v1.0.0`

实数采样 → 去直流 / Hann 窗 → 基 2 FFT → 单边幅值谱 → 主峰（三点插值，频率精度远小于一个 bin）、
最多 16 个局部峰分量（按频率排序，小屏分页用）、32 段显示频带、THD；两路**同批同步采样**的主峰复数相减得相位差。

- 接口：`spec_analyze / spec_phase_diff_deg / spec_thd / spec_fft`；自检 `spectrum_selftest()`；主机测试 tests/host/test_signal.c
- 幅值是“单边峰值幅度”：0.8 V 幅度的正弦 → `peak_mag ≈ 0.8`（Hann 已补相干增益；非整周期时 Hann 的扇贝损失最多约 −15%，要准用整周期采样或平顶窗）。
- 采样数据从哪来不管：ADC + 定时器触发 + DMA 填一块，填满后交给它（双通道同步采样 → 各算一次 → `spec_phase_diff_deg`）。

## 资源（实验是检验真理的唯一标准）
- 工作区 `spec_work_t` 是 2×N 个 float：1024 点 8 KB，MSPM0G3507（32 KB RAM、无 FPU）建议 ≤512 点。
- **【未测】板上耗时**：M0+ 软浮点下 float FFT 会比原版 CMSIS-DSP q15 慢很多；要快就把 `spec_fft` 换成 `arm_cfft_q15`/`arm_cfft_f32`，其余不变。

## 验证状态
- **已实测（PC 主机）**：整周期/非整周期正弦频率误差、幅值、多频分量排序、相位差 ±1°、THD（方波理论 48.3%）、非法参数。
- **【未测】上板**。

## 参考来源
LP-MSPM0G3507_freertos_firework@ede35a2 `modules/fft/fft.c`（MIT，阡陌）：分析流程直接移植（见文件头）。docs/参考来源.md。
