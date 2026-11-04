# 显示通用菜单使用指南

菜单页面和按键逻辑位于 `application/menu/display_menu/display_menu.c`，同时供
SSD1306 OLED 和 ST7735S TFT 使用；`oled_menu.c` 与 `tft_menu.c` 只负责选择并
初始化显示后端。当前默认配置是 TFT，OLED 默认关闭，但两者的页面和按键行为相同。

## 基本按键

| 板载按键 | 引脚 | 普通菜单短按 | 普通菜单长按 |
| --- | --- | --- | --- |
| S1 | PA18 | 下一项 | 确认、进入或执行 |
| S2 | PB21 | 上一项 | 返回上一层 |

- 防抖时间 30 ms，持续按住 800 ms 产生一次长按事件；
- S1 高电平有效，需确认 LaunchPad 的 J8 跳线；
- S2 低电平有效，SysConfig 已配置内部上拉；
- `CONTRAST +`、`CONTRAST -` 在长按后可每 80 ms 连续调整；
- 普通动作完成后显示约 700 ms 的 `SUCCESS` 或 `FAILED` 结果页。

波形、频谱和 UART3 文本结果属于专用页面，按键含义与普通菜单不同，见下文。

## 当前主菜单

主菜单项目按 `app_config.h` 编译期裁剪，可能包含：

```text
CUSTOM PAGE     电赛自定义页
WAVEFORM        本地 ADC、UART2、UART3 曲线
FFT SPECTRUM    本地/UART2 FFT 和 UART3 频谱
UART3 REMOTE    上位机模式、测量、输出和扫频命令
PA27 MAPPING    PA27 测量结果自动映射
DAC OUTPUT      PA15 DAC 输出
ARBITRARY DAC   Flash 任意波形槽位
PA27 TRIGGER    PA27 阈值触发保存
PWM OUTPUT      PA23 通用 PWM
DDS OUTPUT      AD9833
AD9850 OUTPUT   AD9850
DISPLAY         显示设置
INFORMATION     当前硬件和按键提示
RESET VIEW      恢复正常显示和默认对比度
```

当前默认可见的核心项是 `CUSTOM PAGE`、`WAVEFORM`、`FFT SPECTRUM`、
`UART3 REMOTE`、`DAC OUTPUT`、`PWM OUTPUT`、`DISPLAY`、`INFORMATION` 和
`RESET VIEW`。舵机默认关闭，所以 PA23 通用 PWM 页面默认开启；启用任一路舵机
后，该页面会自动关闭以避免共用 TIMG7 冲突。

## WAVEFORM 页面

来源列表只保留已启用项：

- `ADC PA27`；
- `ADC PB19`，默认关闭；旧源码枚举中仍可能叫 `PA21`；
- `UART2 PB16`；
- UART3 的 `LWAVE A1/A3`、`LWAVE B1/B3`、`LWAVE 1/3`、`LAFC`、`LPFC`；
- UART3 的 `WAVE A1/A3`、`WAVE B1/B3`、`WAVE 1/3`、`AFC`、`PFC`。

本地 ADC 选择后立即发起一次测量。PA27 当前默认 1024 点、1 MHz；PB19 启用后
默认也为 1024 点、1 MHz。显示使用本次完整窗口的最后 128 点。UART2 收满 1024
点后显示最后 128 点。

进入任一 UART3 曲线项会自动测量一次：模型数据先发 `sep1` 或 `sep2`，等待
READY 后再发所选数据命令；幅相频曲线先发 `sweep1`，等待 `SWEEP DONE` 后再取数。
因此进入 `UART3 LWAVE A1` 就会自动发送 `sep1\r\n`，无需先在
`UART3 REMOTE` 手动执行 SEP1。页面会显示 `PREP`、`SWEEP`、`WAIT`、`TIME` 或
`ERROR`，不会无限等待。

| 按键 | 波形页动作 |
| --- | --- |
| S1 短按 | 向上切换 Y 轴量程 |
| S1 长按 | 重新测量当前来源；UART3 会重新执行准备阶段 |
| S2 短按 | 循环切换所有已编译来源 |
| S2 长按 | 返回 WAVEFORM 来源菜单 |

UART3 波形显示默认保留原始直流量；设
`APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC=1U` 后只对显示副本减去帧平均值。

## FFT SPECTRUM 页面

来源可包括 `FFT PA27`、`FFT PB19`、`FFT UART2`、`UART3 LSPECT A/B`、
`UART3 SPECT A/B` 和 `UART3 SPECTRUM`。本地 ADC 和 UART2 都冻结一帧显示，
不会在后台连续刷新；UART3 在进入页面时执行对应的准备和数据请求。

| 按键 | 频谱页动作 |
| --- | --- |
| S1 短按 | 循环切换所有已编译频谱来源 |
| S1 长按 | 重新测量当前来源；UART3 会重新执行准备阶段 |
| S2 短按 | 进入或翻阅有效频率分量；末页返回柱状图 |
| S2 长按 | 返回 FFT 来源菜单 |

本地 FFT 显示 32 个单边频谱柱。`APP_FFT_REMOVE_DC=1U` 时先减去本帧平均值，
柱状图从 bin 1 开始；关闭时保留 bin 0，但主峰搜索仍跳过直流。当前 PA27 默认
1 MHz/1024 点，原始 bin 间隔约 976.5625 Hz。UART2 默认按 100 samples/s 和
64 点计算。

本地 ADC/UART2 的分量列表最多 16 项，每页 3 项。当前 UART3 新频谱事务只接收
频谱数字，不附带 components 列表，因此在 UART3 频谱页按 S2 不会得到由
`compa`/`compb` 填充的分量；这两条命令的文本结果应从 `UART3 REMOTE →
MEASURE / DIAG` 查看。

## UART3 REMOTE 页面

该页面把上位机的文本命令按功能分组：

| 子页 | 实际命令 |
| --- | --- |
| DDS A FREQUENCY | `key01`，等待 `FREQ(1~1M Hz)` 后发送预设频率 |
| DDS A AMPLITUDE | `key02`，等待 `AMP(0~255)` 后发送预设幅度 |
| DDS B PHASE | `phase0/45/90/180/270`、`phi90` |
| CAPTURE / MODE | `sep1`、`sep2`、`filter`、`normal`、`filteroff`、`phase`、`ddsphase` |
| MEASURE / DIAG | `measurea/b`、`compa/b`、`data`、`adcdiag` |
| MODEL OUTPUT | `outputa/b`、`output`、`sepouta/b`、`outputoff` |
| SWEEP / INFER | `sweep`、`sweep1`、`sweep2`、`infer` |

所有固件发出的文本命令和参数都以 `\r\n` 结束。命令页最多保存 15 个 20 字符
片段，一屏显示 5 个；过长的上位机行会按显示宽度切分。

| 按键 | UART3 文本结果页动作 |
| --- | --- |
| S1 短按 | 翻到下一页文本 |
| S1 长按 | 重新发送当前命令；两阶段参数命令重新从 key 开始 |
| S2 长按 | 取消本地等待并返回 |

文本页本地超时为 5 s。收到 `error` 或明显错误文本会进入失败状态；取消、成功或
失败后的迟到文本会被丢弃，避免污染下一次命令。

完整数据命令、READY 条件和超时见
[UART3 上位机通信协议](../../../tools/uart3_host_simulator/UART3上位机通信协议.md)。

## 输出页面

### DAC OUTPUT

PA15 DAC 支持：关闭输出、0.50/1.00/1.65/2.50/3.00 V 直流、周期波形上下限，
以及正弦、方波、三角波、锯齿波。周期波形常用档位为 1/10/100 Hz、
1/5/10/20/31.25/62.5 kHz；方波额外提供 500 kHz。当前默认上下限为
0.50 V 和 2.80 V，必须保持下限小于上限。

选择输出后只显示操作结果，不会自动跳到 PA27。需要回环时使用
`PA15 → 100 Ω → PA27`，断开 J17，再手动进入 PA27 页面。高频幅值、失真和边沿
应使用示波器确认。

### PWM OUTPUT

PA23/TIMG7 CCP0 支持启停、50/100/500 Hz、1/5/10/20 kHz 和
0/10/25/50/75/90/100% 占空比。初始化参数为 1 kHz、50%，但输出保持停止。

### DDS / AD9850

AD9833 页面支持启停、正弦/三角/方波、1 Hz～1 MHz 预设频率和
0/45/90/180/270° 相位。初始化后保持 RESET/SLEEP。AD9850 页面支持 SIN/SQ
输出脚和 1 Hz～40 MHz 预设，只有对应编译开关开启时才出现。

### 任意波形与阈值触发

任意波形当前默认关闭，槽位数默认 2；启用后可播放槽位并循环到下一个有效槽位。
PA27 阈值触发默认关闭，默认阈值 1000 mV、1 MHz、200 us，依赖 PA27 测量、
任意波形和 DAC。

## 添加普通菜单项

菜单条目和页面必须具有静态生命周期：

```c
static void MyAction(void *context)
{
    (void)context;
    DisplayMenuSetActionFeedback("MY ACTION", RunMyAction());
}

static const MenuItem settings_items[] = {
    {"OPTION A", NULL, MyAction, NULL},
    {"OPTION B", NULL, MyAction, NULL}
};

static const MenuPage settings_page = {
    "SETTINGS",
    settings_items,
    sizeof(settings_items) / sizeof(settings_items[0])
};
```

普通动作在 DisplayMenu 任务中执行，不要长时间阻塞，也不要从 ISR 直接绘图。
状态变化后由菜单任务统一调用 `MenuRender()` 和 `DisplayUpdate()`。

## 常见排查

- S1 无反应：检查 J8 和 PA18 是否在按下时由低变高；
- S2 一直按下：检查 PB21 是否被外部拉低；
- 页面一直 `WAIT`：本地 ADC 检查 DMA/采样配置；UART3 检查 PA26/PA25 是否交叉、
  是否共地、上位机是否使用 CRLF 和正确的响应点数；
- UART3 显示 `TIME`：准备阶段 5 s、帧式数据 2 s、裸流数据 15 s、扫频准备 30 s
  内没有收到完整响应；
- 动作显示 `FAILED`：确认对应 Module 已初始化，且编译开关与实际接线一致。
