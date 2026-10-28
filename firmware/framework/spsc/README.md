# spsc — 单生产者单消费者采样队列

ISR 推、主循环取的定长环形队列，带丢弃计数和 `pop_latest`（只要最新样本）。

- 接口见 `spsc.h`；自检 `spsc_selftest()`。
- 【已实测】主机单测（tests/host/test_modules.c），含 32 位计数回绕。
- 【未验证】上板 ISR 并发（单核下只靠编译器屏障与 32 位对齐读写的原子性，Cortex-M 满足）。
- 参考：P2 工程的时间戳采样队列设计（思路，非代码）；Linux kfifo 的自由计数+掩码。
