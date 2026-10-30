# wavemeas — 波形参数测量  `v1.0.0`

一块 ADC 原始码（`uint16_t[]`，定时器触发 + DMA 填满后交给它）→ 最小/最大/峰峰/均值/交流有效值、频率/周期、占空比、
波形类型（直流/正弦/方波/三角/锯齿/谐波）；两路同批同步采样 → 相位差。

- 接口：`wm_measure(x, n, fs, lsb_v, spec, &r)`（lsb_v = 每码伏数，含分压；spec 传同一块的 `spec_analyze` 结果可让分类更准，可 NULL）、
  `wm_phase_deg(a, b, n, fs, freq)`（正 = b 超前）、底层 `wm_features / wm_classify`；自检 `wavemeas_selftest()`。
- 频率：中点 ±10% 峰峰的施密特过零，上升沿线性插值，取首末上升沿之间的平均周期；窗口里不足 2 个上升沿时不给频率（低频用 capfreq 硬件捕获）。
- 占空比：首末上升沿之间（整周期）高于中点的样本比例；不足一周期回退原版全窗统计。
- 分类：原版定点阈值原样；峰值因数按均值算，占空比远离 50% 的方波不会判成 SQUARE（原版同样如此）（峰值因数²、贴轨比例、步长均匀度、曲率、三次谐波、主峰占比）。原版说明：“业务初筛，不替代示波器”。
- 采样来源：ADC + 定时器触发 + DMA 填一块（PAL 的块采样接口见 firmware/pal/pal.h）。上位机同算法：app/sidecar/dzbench/wavemeas.py（频谱视图下方的参数行）。

## 验证状态
- **已实测（PC 主机）**：tests/host/test_signal.c 的 wavemeas_*：正弦/方波/三角/锯齿/直流分类、频率误差 < 0.5%、25% 占空比、相位差 ±1°、非法参数。
- **【未测】上板**（M0+ 软浮点下耗时未测）。

## 参考来源
LP-MSPM0G3507_freertos_firework@ede35a2 `application/waveform/waveform_measurement/waveform_measurement.c`（MIT，阡陌）：时域特征 + 分类直接移植（见文件头）。docs/参考来源.md。
