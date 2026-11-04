# 1.8 寸 TFT 菜单与接线指南

当前后端按常见的 `ST7735S`、`128×160`、SPI 接口屏幕编写。TFT 与
SSD1306 OLED 共用同一套菜单、波形页面和 PA18/PB21 按键操作，
同一份固件只启用其中一种屏幕。

## 1. 接线

| TFT 模块标识 | LP-MSPM0G3507 | 说明 |
| --- | --- | --- |
| `VCC` | `3V3` | 屏幕逻辑和供电电压 |
| `GND` | `GND` | 必须共地 |
| `SCL` / `SCK` | `PB18` | SPI0 时钟，8 MHz |
| `SDA` / `MOSI` | `PB17` | SPI0 MCU 输出数据 |
| `RES` / `RST` | `PB4` | 硬件复位 |
| `DC` / `A0` | `PB1` | 命令/数据选择 |
| `CS` | `PB20` | 片选，低电平有效 |
| `BLK` / `LED` | `3V3` | 背光常亮；本版本不用 MCU 调光 |

最少需要 `VCC、GND、SCK、MOSI、RST、DC、CS` 共 7 条信号/供电线。
如果模块的背光没有在板上默认接通，还要把 `BLK` 接到 `3V3`，即共 8 条。
`MISO`/`SDO` 不使用，可不接。

> 不要把只允许 3.3 V 逻辑的屏幕信号线直接 5 V。如果模块标注支持
> 5 V，也建议先按模块原理图确认是否自带稳压和电平转换。

## 2. 在 OLED 和 TFT 之间切换

修改 [`application/app_config.h`](../../app_config.h) 中的两个开关。

使用 TFT：

```c
#define APP_ENABLE_OLED_MENU (0U)
#define APP_ENABLE_TFT_MENU  (1U)
```

切回 OLED：

```c
#define APP_ENABLE_OLED_MENU (1U)
#define APP_ENABLE_TFT_MENU  (0U)
```

两个开关必须且只能有一个为 `1U`。同时开启或同时关闭都会在编译期
报错，防止两个后端同时抢占显示菜单。修改后执行 Project Clean 和完整
Build，再烧录新固件。

## 3. 菜单与按键

TFT 直接复用 [`display_menu.c`](../display_menu/display_menu.c) 中的页面和业务动作：

- S1 / PA18 短按：下一项；长按：确认、进入或执行。
- S2 / PB21 短按：上一项；长按：返回上一层。
- 与 OLED 相同的波形、FFT、DAC、DDS、映射和显示设置页面会按
  `app_config.h` 的功能开关自动裁剪。
- 当前默认从主菜单启动；也可改为上电直接进入电赛自定义界面，配置和修改方法见
  [电赛自定义页面使用指南](../custom_page/电赛自定义页面使用指南.md)。

为保留现有 128×64 菜单布局，TFT 后端使用 128×64 单色逻辑画布，
在 128×160 面板中部按纵向 2 倍显示。这样不需要维护两套菜单，也避免
申请约 40 KB 的 RGB565 整屏显存。
刷新时会把待更新逻辑页合并为一个连续 GRAM 地址窗口，只发送一次 `RAMWR`，
减少逐扫描线重复发送命令造成的刷新延迟。

## 4. 代码位置

- 菜单页面和按键任务：[`display_menu.c`](../display_menu/display_menu.c)
- 电赛自定义界面：[`custom_page.c`](../custom_page/custom_page.c)
- TFT Application 入口：[`tft_menu.c`](tft_menu.c)
- TFT 显示适配：[`tft_display.c`](../../../modules/tft/tft_display.c)
- ST7735S 寄存器、字体和刷新驱动：[`tft.c`](../../../modules/tft/tft.c)
- SPI0 逻辑设备：[`spi.c`](../../../modules/spi/spi.c)
- SPI0/GPIO 引脚映射：[`blink_led.syscfg`](../../../blink_led.syscfg)

## 5. 排查

- 背光不亮：先检查 `BLK` 与 `VCC` 供电，以及 GND 是否共地。
- 背光亮但全黑：检查是否已切换到 TFT 配置，然后检查 `CS/DC/RST`。
- 有杂色或屏幕不刷新：检查 `PB18 SCK` 和 `PB17 MOSI` 是否接反。
- 一侧文字被截断、另一侧有彩色边：当前实物已经按 `X=2、Y=1` 补偿；
  其他批次可覆盖 `TFT_RAM_COLUMN_OFFSET`、`TFT_RAM_ROW_OFFSET`。
- 颜色或方向异常：不同批次的 `MADCTL` 和初始化序列可能不同，需要在
  `modules/tft/tft.c` 中调整。
- 按键无反应：显示屏不改变板载按键接线，仍检查 PA18/PB21 和原有跳线。
