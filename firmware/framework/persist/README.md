# persist — 掉电保存（参数键值 + 黑匣子冻结区）

不含硬件代码；硬件由 `persist_flash_t`（擦/写/读 + 擦除单位）描述，板上用 `drivers/nvm_pal`（走 `pal_nvm_*`，pal 1.5.0）。

```c
static persist_flash_t kvf, bbf; static persist_kv_t kv; static bb_store_t st;
if (nvm_pal_layout(&kvf, &bbf, 1) == DZ_OK) {          /* 第 1 个擦除单位给黑匣子，其余给参数 */
    (void)persist_kv_init(&kv, &kvf);                  /* 只读不写 */
    (void)persist_kv_get(&kv, KEY_PARAMS, &p, sizeof p, &n);   /* 没有 / 长度不对 → 用默认 */
    (void)persist_bb_store(&st, &bbf);                 /* bb_init(&bb, ring, N, &st) */
}
/* 人点“保存”时（停车状态）：persist_kv_put(&kv, KEY_PARAMS, &p, sizeof p); */
```

| 保证 | 怎么做到 |
|---|---|
| 写失败不挡启动 | init 只读；连续 3 次失败后停用（返回 DZ_ENOTSUP），应用继续用 RAM |
| 写到一半掉电不坏旧值 | 追加写，每条带 CRC；坏的那条读时跳过，用上一条 |
| 磨损均衡 | 两个 bank 轮流，满了才擦另一个并搬最新值；同值不写 |

结构体参数存进去时带上版本号/长度，读回长度不对就用默认（固件改了参数表后不会读进错位的值）。
擦除会阻塞（片内 flash 几十 ms），只在停车/空闲时保存，别在控制中断里调。

移植层：host-sim 有 8 KB 模拟 flash（`DZ_SIM_NVM=文件` 可跨进程保留）；MSPM0 / STM32F4 / CubeMX 目前返回 DZ_ENOTSUP
（片内 flash 要先在链接脚本里留扇区，[未做]）。[仿真]

## 1.1.0

- `persist_kv_bb_store`：黑匣子冻进键值区的一个 key（≤15 条），F4 16 KB 扇区也只要 2 个（不用给黑匣子单独留擦除单位）。
- `persist_blob_load/save`：整块参数带结构哈希（例如 `LINK_SCHEMA_HASH`），app.yaml 参数表改了 → 不加载，用默认值。
- 真板：stm32-cubemx（F1/F4）、mspm0-driverlib 按 board.yaml `mcu.nvm_kb` 开（见 ports/*/README）。示例：apps/car_2wd。
