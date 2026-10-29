# sigfilt — 三点中值 + 一维卡尔曼  `v1.0.0`

- `med3_*`：去单点毛刺（ADC 偶发尖峰、超声波偶发跳变），保持阶跃边沿，延迟 1 个样本。
- `kf1_*`：一维卡尔曼（状态不变 + 噪声），本质是增益自适应的一阶低通；稳态增益 `kf1_steady_gain()` 就是等价的 lpf alpha，可和 algo/lpf 对照选参数。
- 常见串法：原始值 → med3 去毛刺 → kf1 / lpf1 平滑。
- 接口见 sigfilt.h；自检 `sigfilt_selftest()`；主机测试 tests/host/test_signal.c

## 验证状态
- **已实测（PC 主机）**：中值去毛刺不拖阶跃、卡尔曼噪声方差下降、收敛到稳态增益、NaN 不改状态、非法参数。
- **【未测】上板**。

## 参考来源
LP-MSPM0G3507_freertos_firework@ede35a2 `modules/filter/filter.c`（MIT，阡陌）直接移植（见文件头）。
