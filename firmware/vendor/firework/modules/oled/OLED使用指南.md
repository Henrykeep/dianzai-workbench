# OLED Module 使用指南

`modules/oled/` 提供 SSD1306 128×64 OLED 的默认实例、注册初始化、本地帧缓冲、
像素、ASCII 文字和局部页面刷新接口。OLED 的硬件能力全部位于 Module 层，
`application/menu/oled_menu/` 只负责选择 OLED 后端，页面和按键业务位于
`application/menu/display_menu/`。

## 1. 当前硬件连接

| 信号 | 引脚 |
|---|---|
| SCL | PA31 / I2C0 SCL |
| SDA | PA28 / I2C0 SDA |
| 电源 | 3.3V |
| 地 | GND |

I2C速度为400kHz。常见7位地址是 `0x3C`，部分模块使用 `0x3D`。

## 2. 默认实例初始化

当前项目默认 7 位 I2C 地址是 `0x3C`：

```c
#define OLED_DISPLAY_I2C_ADDRESS (0x3CU)
```

当前默认显示后端是 TFT（`APP_ENABLE_TFT_MENU=1U`、
`APP_ENABLE_OLED_MENU=0U`）。改为 OLED 后，OLED Menu Application 会在
`OLEDMenuInit()` 内部调用：

```c
#include "modules/oled/oled_display.h"

if (!OLEDDisplayInit()) {
    return false;
}

OLEDInstance *oled = OLEDDisplayGetInstance();
DisplayInstance *menu_display = OLEDDisplayGetMenuDisplay();
```

`OLEDDisplayInit()` 只负责注册和初始化显示硬件及通用显示适配器，不绘制启动页、
不创建任务、也不依赖 UART Application。`OLEDDisplayGetInstance()` 返回 OLED
底层实例；`OLEDDisplayGetMenuDisplay()` 返回给 Menu/Waveform 使用的通用适配器。

## 3. 自定义地址注册

```c
#include "modules/oled/oled.h"

static OLEDInstance *oled;

bool ExampleOLEDInit(void)
{
    oled = OLEDRegister(0x3CU);
    return (oled != NULL) && OLEDInitialize(oled);
}
```

当前只提供一个静态OLED实例。重复注册相同地址返回已有实例；注册不同地址返回NULL。

## 4. 帧缓冲工作方式

OLED拥有 `128 × 64 / 8 = 1024` 字节本地帧缓冲。绘图接口只修改RAM，不会立即在
物理屏幕显示：

```c
(void)OLEDClear(oled, false);
(void)OLEDSetPixel(oled, 10U, 10U, true);
(void)OLEDDrawString(oled, 0U, 16U, "HELLO");
(void)OLEDUpdate(oled);
```

必须调用 `OLEDUpdate()` 或 `OLEDUpdatePages()` 才会通过I2C刷新硬件。

## 5. 文字绘制

```c
(void)OLEDDrawCharacter(oled, 0U, 0U, 'A');
(void)OLEDDrawString(oled, 0U, 8U, "LINE1\nLINE2");
```

- 内置字体为5×7，字符水平步进6像素，行步进8像素。
- 支持ASCII编码32～127，其他字符会显示为 `?`。
- 字符串到达右边缘时自动换行，到达底部后停止绘制。
- 当前不包含中文字库。

## 6. 局部页面刷新

SSD1306每页高度为8像素，共8页。只更新第2和第3页：

```c
(void)OLEDUpdatePages(oled, 2U, 2U);
```

局部刷新适合波形页面，可减少I2C传输量。`first_page + page_count` 不能超过8。

## 7. 显示控制

```c
(void)OLEDSetDisplayEnabled(oled, false); /* 面板熄灭，RAM不清除。 */
(void)OLEDSetDisplayEnabled(oled, true);
(void)OLEDSetInverted(oled, true);
(void)OLEDSetContrast(oled, 0x80U);
```

对比度范围为 `0x00～0xFF`，实际亮度变化还取决于OLED模块硬件。

## 8. 使用注意事项

- I2C发送由底层互斥锁保护，但帧缓冲绘制本身没有完整事务锁，建议同一时间只由一个
  任务绘制和刷新。
- 绘图、I2C传输和互斥锁等待都不适合在ISR中执行。
- `OLEDClear()` 只清帧缓冲，不调用 `OLEDUpdate()` 就不会改变屏幕。
- 屏幕不亮时检查供电、共地、地址、SCL/SDA接线和上拉电阻。
- PA15 已经用于 DAC，当前 OLED 时钟使用 PA31，不要再接回 PA15。
- OLED 与 TFT 后端必须二选一；切换 `app_config.h` 后重新完整构建固件。
