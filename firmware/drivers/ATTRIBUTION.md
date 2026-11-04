# 第三方驱动来源与许可（ATTRIBUTION）

芯台整体以 AGPL-3.0-or-later 发布。下列第三方代码原样（逐字节）收录，保留各自的 LICENSE 文件与版权头，按各自许可使用；
唯一例外是 ADS1256 / ST7735 / ILI9488 三个驱动里直接调用的 STM32 HAL 被换成 pal_* 调用（差异见各自的 `PAL-CHANGES.patch`）。
芯台自写的胶水（`glue/`、`ad983x/ad983x_port.*`）为 AGPL-3.0-or-later。

| 目录 | 上游 | 提交 | 许可 | 许可文件 |
|---|---|---|---|---|
| `libdriver/ad7705` | https://github.com/libdriver/ad7705 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ad7705/LICENSE` |
| `libdriver/ad9833` | https://github.com/libdriver/ad9833 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ad9833/LICENSE` |
| `libdriver/ads1115` | https://github.com/libdriver/ads1115 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ads1115/LICENSE` |
| `libdriver/ads1118` | https://github.com/libdriver/ads1118 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ads1118/LICENSE` |
| `libdriver/adxl345` | https://github.com/libdriver/adxl345 | unknown | MIT, Copyright (c) LibDriver | `libdriver/adxl345/LICENSE` |
| `libdriver/aht20` | https://github.com/libdriver/aht20 | unknown | MIT, Copyright (c) LibDriver | `libdriver/aht20/LICENSE` |
| `libdriver/as5600` | https://github.com/libdriver/as5600 | unknown | MIT, Copyright (c) LibDriver | `libdriver/as5600/LICENSE` |
| `libdriver/at24cxx` | https://github.com/libdriver/at24cxx | unknown | MIT, Copyright (c) LibDriver | `libdriver/at24cxx/LICENSE` |
| `libdriver/bh1750fvi` | https://github.com/libdriver/bh1750fvi | unknown | MIT, Copyright (c) LibDriver | `libdriver/bh1750fvi/LICENSE` |
| `libdriver/bmm150` | https://github.com/libdriver/bmm150 | unknown | MIT, Copyright (c) LibDriver | `libdriver/bmm150/LICENSE` |
| `libdriver/bmp280` | https://github.com/libdriver/bmp280 | unknown | MIT, Copyright (c) LibDriver | `libdriver/bmp280/LICENSE` |
| `libdriver/button` | https://github.com/libdriver/button | unknown | MIT, Copyright (c) LibDriver | `libdriver/button/LICENSE` |
| `libdriver/cs1237` | https://github.com/libdriver/cs1237 | unknown | MIT, Copyright (c) LibDriver | `libdriver/cs1237/LICENSE` |
| `libdriver/dht11` | https://github.com/libdriver/dht11 | unknown | MIT, Copyright (c) LibDriver | `libdriver/dht11/LICENSE` |
| `libdriver/ds1302` | https://github.com/libdriver/ds1302 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ds1302/LICENSE` |
| `libdriver/ds18b20` | https://github.com/libdriver/ds18b20 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ds18b20/LICENSE` |
| `libdriver/ds3231` | https://github.com/libdriver/ds3231 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ds3231/LICENSE` |
| `libdriver/hcsr04` | https://github.com/libdriver/hcsr04 | unknown | MIT, Copyright (c) LibDriver | `libdriver/hcsr04/LICENSE` |
| `libdriver/hlw8032` | https://github.com/libdriver/hlw8032 | unknown | MIT, Copyright (c) LibDriver | `libdriver/hlw8032/LICENSE` |
| `libdriver/hmc5883l` | https://github.com/libdriver/hmc5883l | unknown | MIT, Copyright (c) LibDriver | `libdriver/hmc5883l/LICENSE` |
| `libdriver/hx711` | https://github.com/libdriver/hx711 | unknown | MIT, Copyright (c) LibDriver | `libdriver/hx711/LICENSE` |
| `libdriver/ina219` | https://github.com/libdriver/ina219 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ina219/LICENSE` |
| `libdriver/ina226` | https://github.com/libdriver/ina226 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ina226/LICENSE` |
| `libdriver/ir_remote` | https://github.com/libdriver/ir_remote | unknown | MIT, Copyright (c) LibDriver | `libdriver/ir_remote/LICENSE` |
| `libdriver/ld3320` | https://github.com/libdriver/ld3320 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ld3320/LICENSE` |
| `libdriver/llcc68` | https://github.com/libdriver/llcc68 | unknown | MIT, Copyright (c) LibDriver | `libdriver/llcc68/LICENSE` |
| `libdriver/max30102` | https://github.com/libdriver/max30102 | unknown | MIT, Copyright (c) LibDriver | `libdriver/max30102/LICENSE` |
| `libdriver/max31865` | https://github.com/libdriver/max31865 | unknown | MIT, Copyright (c) LibDriver | `libdriver/max31865/LICENSE` |
| `libdriver/max6675` | https://github.com/libdriver/max6675 | unknown | MIT, Copyright (c) LibDriver | `libdriver/max6675/LICENSE` |
| `libdriver/max7219` | https://github.com/libdriver/max7219 | 56db66a | MIT, Copyright (c) LibDriver | `libdriver/max7219/LICENSE` |
| `libdriver/mcp3421` | https://github.com/libdriver/mcp3421 | unknown | MIT, Copyright (c) LibDriver | `libdriver/mcp3421/LICENSE` |
| `libdriver/mcp4725` | https://github.com/libdriver/mcp4725 | unknown | MIT, Copyright (c) LibDriver | `libdriver/mcp4725/LICENSE` |
| `libdriver/mfrc522` | https://github.com/libdriver/mfrc522 | unknown | MIT, Copyright (c) LibDriver | `libdriver/mfrc522/LICENSE` |
| `libdriver/mlx90614` | https://github.com/libdriver/mlx90614 | unknown | MIT, Copyright (c) LibDriver | `libdriver/mlx90614/LICENSE` |
| `libdriver/mpu6050` | https://github.com/libdriver/mpu6050 | unknown | MIT, Copyright (c) LibDriver | `libdriver/mpu6050/LICENSE` |
| `libdriver/mpu6500` | https://github.com/libdriver/mpu6500 | unknown | MIT, Copyright (c) LibDriver | `libdriver/mpu6500/LICENSE` |
| `libdriver/mpu9250` | https://github.com/libdriver/mpu9250 | unknown | MIT, Copyright (c) LibDriver | `libdriver/mpu9250/LICENSE` |
| `libdriver/multi_button` | https://github.com/libdriver/multi_button | unknown | MIT, Copyright (c) LibDriver | `libdriver/multi_button/LICENSE` |
| `libdriver/nrf24l01` | https://github.com/libdriver/nrf24l01 | unknown | MIT, Copyright (c) LibDriver | `libdriver/nrf24l01/LICENSE` |
| `libdriver/ntc` | https://github.com/libdriver/ntc | unknown | MIT, Copyright (c) LibDriver | `libdriver/ntc/LICENSE` |
| `libdriver/pca9685` | https://github.com/libdriver/pca9685 | unknown | MIT, Copyright (c) LibDriver | `libdriver/pca9685/LICENSE` |
| `libdriver/pcf8563` | https://github.com/libdriver/pcf8563 | unknown | MIT, Copyright (c) LibDriver | `libdriver/pcf8563/LICENSE` |
| `libdriver/pcf8574` | https://github.com/libdriver/pcf8574 | unknown | MIT, Copyright (c) LibDriver | `libdriver/pcf8574/LICENSE` |
| `libdriver/pcf8591` | https://github.com/libdriver/pcf8591 | unknown | MIT, Copyright (c) LibDriver | `libdriver/pcf8591/LICENSE` |
| `libdriver/qmc5883l` | https://github.com/libdriver/qmc5883l | unknown | MIT, Copyright (c) LibDriver | `libdriver/qmc5883l/LICENSE` |
| `libdriver/sht30` | https://github.com/libdriver/sht30 | unknown | MIT, Copyright (c) LibDriver | `libdriver/sht30/LICENSE` |
| `libdriver/sht31` | https://github.com/libdriver/sht31 | unknown | MIT, Copyright (c) LibDriver | `libdriver/sht31/LICENSE` |
| `libdriver/sht4x` | https://github.com/libdriver/sht4x | unknown | MIT, Copyright (c) LibDriver | `libdriver/sht4x/LICENSE` |
| `libdriver/ssd1306` | https://github.com/libdriver/ssd1306 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ssd1306/LICENSE` |
| `libdriver/st7789` | https://github.com/libdriver/st7789 | unknown | MIT, Copyright (c) LibDriver | `libdriver/st7789/LICENSE` |
| `libdriver/st7920` | https://github.com/libdriver/st7920 | unknown | MIT, Copyright (c) LibDriver | `libdriver/st7920/LICENSE` |
| `libdriver/sx1262` | https://github.com/libdriver/sx1262 | unknown | MIT, Copyright (c) LibDriver | `libdriver/sx1262/LICENSE` |
| `libdriver/syn6288` | https://github.com/libdriver/syn6288 | unknown | MIT, Copyright (c) LibDriver | `libdriver/syn6288/LICENSE` |
| `libdriver/tcs34725` | https://github.com/libdriver/tcs34725 | unknown | MIT, Copyright (c) LibDriver | `libdriver/tcs34725/LICENSE` |
| `libdriver/tlc5615` | https://github.com/libdriver/tlc5615 | unknown | MIT, Copyright (c) LibDriver | `libdriver/tlc5615/LICENSE` |
| `libdriver/tm1637` | https://github.com/libdriver/tm1637 | a640aae | MIT, Copyright (c) LibDriver | `libdriver/tm1637/LICENSE` |
| `libdriver/tm1638` | https://github.com/libdriver/tm1638 | unknown | MIT, Copyright (c) LibDriver | `libdriver/tm1638/LICENSE` |
| `libdriver/tm1640` | https://github.com/libdriver/tm1640 | unknown | MIT, Copyright (c) LibDriver | `libdriver/tm1640/LICENSE` |
| `libdriver/tsl2561` | https://github.com/libdriver/tsl2561 | unknown | MIT, Copyright (c) LibDriver | `libdriver/tsl2561/LICENSE` |
| `libdriver/ttp229` | https://github.com/libdriver/ttp229 | unknown | MIT, Copyright (c) LibDriver | `libdriver/ttp229/LICENSE` |
| `libdriver/w25qxx` | https://github.com/libdriver/w25qxx | unknown | MIT, Copyright (c) LibDriver | `libdriver/w25qxx/LICENSE` |
| `libdriver/ws2812b` | https://github.com/libdriver/ws2812b | unknown | MIT, Copyright (c) LibDriver | `libdriver/ws2812b/LICENSE` |
| `libdriver/wt588e02b` | https://github.com/libdriver/wt588e02b | unknown | MIT, Copyright (c) LibDriver | `libdriver/wt588e02b/LICENSE` |
| `libdriver/x9cxx` | https://github.com/libdriver/x9cxx | unknown | MIT, Copyright (c) LibDriver | `libdriver/x9cxx/LICENSE` |
| `adi-no-os/`（include、drivers/api、util 与 18 个驱动目录） | https://github.com/analogdevicesinc/no-OS | 3c5f7a7 | BSD-3-Clause, Copyright Analog Devices, Inc. | `adi-no-os/LICENSE_BSD` |
| `other/ads1256` | https://github.com/eta-systems/ADS1255 | 57dc041 | Apache-2.0 | `other/ads1256/LICENSE` |
| `other/st7735` | https://github.com/afiskon/stm32-st7735 | b940810 | MIT | `other/st7735/LICENSE` |
| `other/ili9488` | https://github.com/maudeve-it/ILI9XXX-XPT2046-STM32 | 0e5f1fd | MIT | `other/ili9488/LICENSE` |
| `ad983x/ad9833.*`、`ad983x/ad9850.*` | https://gitee.com/qianmonai/LP-MSPM0G3507_freertos_firework | ede35a2 | MIT, Copyright (c) 2026 阡陌 | `ad983x/LICENSE-firework.txt` |
| `../vendor/firework/`（整个仓库） | https://gitee.com/qianmonai/LP-MSPM0G3507_freertos_firework | ede35a2 | MIT, Copyright (c) 2026 阡陌 | `../vendor/firework/LICENSE` |
