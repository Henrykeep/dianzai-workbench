# dds — 相位累加器波形发生  `v1.0.0`

正弦 / 方波 / 三角 / 锯齿，32 位相位累加器 + 256 点波表，频率分辨率 fs/2³²，输出码范围自定（DAC 12 位就是 0..4095）。
方波可选 `square_exact`：每半周期样本数固定，边沿不抖（频率被量化为 fs/(2·整数)）。

- 用法：定时器以 fs 触发 DAC + DMA 双缓冲；DMA 半满/全满中断里 `dds_fill(&d, 那一半, n/2)`。`dds_actual_mhz()` 显示实际频率。
- 不管硬件：外置 AD9833/AD9850 类 DDS 芯片是另一回事（频率字直接写芯片），本仓库暂无驱动。
- 主机测试 tests/host/test_signal.c：把 dds 输出送进 algo/spectrum，频率/幅度/方波 THD 与理论一致。

## 验证状态
- **已实测（PC 主机）**：频率误差、相位、方波整数半周期、超奈奎斯特拒绝。
- **【未测】上板**（DAC/DMA 接法、输出滤波都没做）。

## 参考来源
LP-MSPM0G3507_freertos_firework@ede35a2 `modules/dac/dac_output.c`（MIT，阡陌）：取整公式与方波整数半周期直接移植。
