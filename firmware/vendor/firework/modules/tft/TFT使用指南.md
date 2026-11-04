# TFT Module 使用指南

`modules/tft/` 提供 ST7735S 128×160 SPI 屏的注册、初始化和绘图后端。
Application 通常不直接调用底层 TFT API，而是通过 `TFTDisplayInit()` 把它
绑定到 `modules/display/` 的通用 128×64 逻辑画布。

当前 `app_config.h` 默认启用 TFT、关闭 OLED；两个显示后端必须且只能选择一个。

## 初始化

```c
#include "modules/tft/tft_display.h"

if (!TFTDisplayInit()) {
    /* 检查 ST7735S 供电和 SPI/CS/DC/RESET 接线。 */
}

DisplayInstance *display = TFTDisplayGetMenuDisplay();
```

`TFTDisplayInit()` 内部依次注册 SPI0、DC/RESET GPIO，复位面板，发送 ST7735S
初始化序列，清黑整屏，再注册通用显示适配器。

当前蓝色 PCB 实物屏的控制器 GRAM 可视区偏移为 `X=2、Y=1`，驱动已经在
`TFT_RAM_COLUMN_OFFSET` 和 `TFT_RAM_ROW_OFFSET` 中补偿。若更换其他批次后
出现一侧文字被截断、另一侧有彩色边，可在编译选项中覆盖这两个宏。

## 显存和刷新

- 逻辑帧缓冲：128×64÷8 = 1024 字节。
- RGB565 行缓冲：128×2 = 256 字节。
- 没有申请 128×160×2 的整屏彩色显存。
- `TFTUpdatePages()` 对所选页只设置一次连续地址窗口和一次 `RAMWR`，再逐行转换
  RGB565 并流式写入，在面板中部纵向 2 倍显示。一次全画布刷新由原来的约 768 次
  小 SPI 传输降为约 133 次。
- 通用对比度值在 TFT 上映射为前景 RGB565 亮度。

完整接线和 Application 配置见
[`TFT菜单与接线指南`](../../application/menu/tft_menu/TFT菜单与接线指南.md)。
