# 任意波形 Flash 槽位

`arbitrary_waveform.c` 提供 1～3 个可配置 Flash 槽位，当前默认 2 个。每个槽位最多保存 1024 个
12 位 DAC 采样值、采样率和周期数；播放时只把当前槽位复制到 DAC 模块的共享
缓冲区，因此不会为每个槽位占用额外 SRAM。

## 配置

在 `application/app_config.h` 中修改：

```c
#define APP_ENABLE_ARBITRARY_WAVEFORM       (1U)
#define APP_ARBITRARY_WAVEFORM_SLOT_COUNT   (2U)
#define APP_ARBITRARY_WAVEFORM_MAX_SAMPLES  (1024U)
```

该功能依赖 `APP_ENABLE_WAVEFORM_OUTPUT_DAC`。关闭 DAC 时会自动关闭任意波形
服务。只有启用任意波形功能时，链接脚本才把 Flash 末尾
`0x1DC00～0x1FFFF` 的 9 KiB 区域从普通程序区中预留；默认关闭时程序可以使用
完整 Flash。预留区大小固定为 3 个最大槽位，实际启用 1 或 2 个槽位也不会缩小。

## API 示例

```c
static const uint16_t table[] = { 0U, 2048U, 4095U, 2048U };

/* 上电后 ApplicationInit 已自动调用 ArbitraryWaveformInit。 */
ArbitraryWaveformSave(0U, table, 4U, 1000000UL, 1U);
ArbitraryWaveformStart(0U);
/* 不需要输出时： */
ArbitraryWaveformStop();
```

实际输出频率为：

`sample_rate_hz × cycle_count ÷ sample_count`。

播放时 DAC 的物理更新率固定为 `APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ`（默认
1 MSPS）。模块会把槽位数据归一化到相位表，并根据上述公式设置相位步进，所以
槽位中的 `sample_rate_hz` 用于保持原播放速度，不再直接配置 DAC Sample Timer。

为避免表内周期数超过奈奎斯特上限，`cycle_count` 必须不大于
`sample_count / 2`。

当前 DAC Sample Timer 只接受 500、1k、2k、4k、8k、16k、100k、200k、500k
和 1M Hz 这些离散采样率；API 会拒绝其他值。保存新槽位或擦除槽位前会先
停止 DAC，避免 DMA 正在读取时修改播放数据。
