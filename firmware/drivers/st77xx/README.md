# st77xx — ST7735 / ST7789 彩色 TFT

RGB565，4 线 SPI + D/C + RES + BL；**无帧缓冲**（直接开窗写 GRAM，适配 MSPM0 的 32 KB RAM，见 QUESTIONS 37）。

## board.yaml
```yaml
spi:
  - { name: TFT, instance: SPI1, sck: PA5, mosi: PA7, miso: PA6, cs: PA4, mode: 0, hz: 20000000 }
gpio:
  - { name: TFT_DC, pin: PB0, dir: out }
  - { name: TFT_RST, pin: PB1, dir: out, active_low: true }
  - { name: TFT_BL, pin: PB2, dir: out }          # 可省，直接接 3.3 V
```
没有 CS 脚的 1.3" ST7789（7 针）一般要 SPI **mode 3**。

## 用法
```c
st77xx_cfg_t c = st77xx_cfg_st7789_240x240(RES_SPI_TFT, RES_GPIO_TFT_DC, RES_GPIO_TFT_RST, PAL_ID_NONE);
st77xx_init(&tft, &c);                 /* 阻塞约 300 ms */
st77xx_fill(&tft, ST77XX_BLACK);
st77xx_text(&tft, 0, 0, "KP 0.72", ssd1306_font8x8, ST77XX_WHITE, ST77XX_BLACK, 2);
```
- 字体由调用者传入（列优先、bit0 在上的 8×8 表）；可以直接用 `ssd1306_font8x8`。
- 颜色不对：红蓝反 → `bgr=true`；整体反色 → 切 `invert`。图像错位 → 调 `x_off/y_off`（不同厂家的玻璃偏移不同）。
- 整屏刷新 240×240 在 20 MHz SPI 下约 60 ms；放低优先级任务，只刷变化的区域。

## 测试状态
- 【已实测】主机单测：假 ST77xx 芯片按 D/C 电平解码命令，校验初始化序列（SWRESET/SLPOUT/COLMOD=05/MADCTL/INV/DISPON）、CASET/RASET 偏移、整屏/裁剪填充、像素、放大文字、旋转后尺寸与 MADCTL、非法配置。
- 【未验证】真实屏幕。部分 ST7735 屏需要额外的帧率/电源命令（FRMCTR1/PWCTR1），若花屏请反馈屏的型号。
- 参考：Sitronix ST7735S / ST7789VW 数据手册命令表；Adafruit-ST7735-Library（MIT）的旋转/偏移做法（只参考思路）。
