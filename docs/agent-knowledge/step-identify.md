---
triggers: 辨识, 开环, 阶跃响应, fopdt, 初值, 时间常数, 纯滞后
---
# 开环阶跃辨识（dzbench/tuning/identify.py，净室实现：Smith 两点法 + SIMC，来源见 docs/参考来源.md）
- 做法：先稳住（基线 ≥0.35 s），控制量突增 du，记录到稳态。两点法：10% 和 63.2% 时刻 → τ = (t63 − t10)/0.895，L = t10 − 0.105τ，K = Δy/du。
- 整定：保守 λ（IMC）：λ = max(3.5L, 0.95τ, 150 ms)，Kp = (τ+L/2)/(K(λ+L/2))，Ti ≥ 3 s，Td 很小。初值偏保守，再在闭环里加。
- 只对开环稳定的对象做（速度环可以；倒立摆、球杆不行），门禁 `experiment.require_open_loop`（step_test.plant_stable=true）。
- 稳态判定原因码：warming_up / still_drifting → 先多等（observe），不要据此改参数。
