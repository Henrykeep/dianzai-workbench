# ssd1306 — OLED 帧缓冲驱动

- 传输回调 `ssd1306_write_fn`：PAL 没有 I2C，由应用/板卡提供（HAL_I2C_Master_Transmit、软件 I2C 或 SPI 都可，写在 ports 或应用的 io 层，不进本模块）。
- 绘图只改 RAM，`ssd1306_flush()` 整屏写入（1 KB；400 kHz I2C 约 25 ms，建议放在 5–10 Hz 的低优先级任务）。
- 字体：8×8 ASCII，由 `tools/gen_font8x8.py` 从 **Press Start 2P**（CodeMan38，SIL Open Font License 1.1）渲染生成，OFL 允许嵌入，字体名与许可见 font8x8.c 文件头。
- 【已实测】主机单测：像素寻址（页/位）、越界裁剪、文本、定点数格式化、flush 字节数、128×32 模式。
- 【未验证】真实屏幕（初始化序列按数据手册推荐流程；对比度/预充电取常见模块值 0xCF/0xF1，外部 VCC 供电的屏需关升压 8D 10）。
- 参考：Solomon Systech SSD1306 Datasheet Rev 1.1；Adafruit_SSD1306（https://github.com/adafruit/Adafruit_SSD1306，BSD）；u8g2（https://github.com/olikraus/u8g2，BSD-2）——只参考结构，未拷贝代码。用户工程里的中景园类 OLED 例程**未使用**（许可不明）。
