# ssd1306 — OLED 帧缓冲驱动

- 传输回调 `ssd1306_write_fn`。1.1.0 起自带两种基于 PAL 的现成传输（`ssd1306_tr.c`），换板只改 board.yaml：
  - `ssd1306_tr_i2c` + `ssd1306_i2c_t{ RES_I2C_OLED, 0x3C }`：控制字节 0x00/0x40 当作 `pal_i2c_mem_write` 的 reg，16 字节分块。
  - `ssd1306_tr_spi` + `ssd1306_spi_t{ RES_SPI_OLED, RES_GPIO_OLED_DC, RES_GPIO_OLED_RST }`：D/C 脚区分命令/数据，64 字节分块；`ssd1306_spi_reset()` 做硬复位。
  - 软件 I2C 等特殊接法仍可自己写回调。

```yaml
i2c:
  - { name: OLED, instance: I2C1, scl: PB6, sda: PB7, speed_hz: 400000 }
# 或 4 线 SPI：
spi:
  - { name: OLED, instance: SPI2, sck: PB13, mosi: PB15, miso: PB14, cs: PB12, mode: 0, hz: 8000000 }
gpio:
  - { name: OLED_DC, pin: PB10, dir: out }
  - { name: OLED_RST, pin: PB11, dir: out, active_low: true }
```
- 【已实测】主机单测（1.1.0）：假 SSD1306 芯片按控制字节/D-C 电平统计，I2C 与 SPI 下 init 含 0xAF、flush 1024/512 字节、分块上限、地址不应答报错。
- 绘图只改 RAM，`ssd1306_flush()` 整屏写入（1 KB；400 kHz I2C 约 25 ms，建议放在 5–10 Hz 的低优先级任务）。
- 字体：8×8 ASCII，由 `tools/gen_font8x8.py` 从 **Press Start 2P**（CodeMan38，SIL Open Font License 1.1）渲染生成，OFL 允许嵌入，字体名与许可见 font8x8.c 文件头。
- 【已实测】主机单测：像素寻址（页/位）、越界裁剪、文本、定点数格式化、flush 字节数、128×32 模式。
- 【未验证】真实屏幕（初始化序列按数据手册推荐流程；对比度/预充电取常见模块值 0xCF/0xF1，外部 VCC 供电的屏需关升压 8D 10）。
- 参考：Solomon Systech SSD1306 Datasheet Rev 1.1；Adafruit_SSD1306（https://github.com/adafruit/Adafruit_SSD1306，BSD）；u8g2（https://github.com/olikraus/u8g2，BSD-2）——只参考结构，未拷贝代码。用户工程里的中景园类 OLED 例程**未使用**（许可不明）。
