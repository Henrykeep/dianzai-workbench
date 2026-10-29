# stall — 堵转检测  `v1.0.0`

“负载高（电流/Iq 或指令占空比）+ 速度近零 + 持续 hold_ms”→ STALLED。起步豁免、滞回、锁存（`stall_clear` 或 `retry_ms` 自动重试）。
纯逻辑，不碰硬件；拿到 STALLED 后由应用输出归零 / 进 ESTOP / 记黑匣子（firmware/framework/blackbox）。

- 接口：`stall_init / stall_update / stall_clear`；自检 `stall_selftest()`；主机测试 tests/host/test_ctrlparts.c（含一阶电机模型：堵住轴 → 判堵转的时刻；正常起步不误报；数据 NaN 不误报/不误解除）
- 没有电流采样：load 用 |占空比|，load_on 取“正常运行最大占空比”以上；有编码器即可用。

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：上述测试。
- **【未测】上板**：真实电机的门限要按手册堵转电流 / 实测空载电流标定，没有任何实测数。

## 参考来源
- MICU-auto-embedded（实验室/开源小组工程）`templates/auto-embedded/refs/control-safety-limits.md` 检查项 2（判据、FOC 下 OCP 不触发、起步豁免）。见 docs/参考来源.md。代码自写。
