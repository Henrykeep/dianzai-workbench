# BSP GPIO 使用指南

## 1. 板级通道映射

| 逻辑通道 | 引脚 | 方向 | 电气含义 |
| --- | --- | --- | --- |
| `BSP_GPIO_CHANNEL_USER_LED_1` | PA0 | 输出 | 独立用户 LED1 |
| `BSP_GPIO_CHANNEL_RGB_LED_BLUE` | PB22 | 输出 | RGB LED 蓝色 |
| `BSP_GPIO_CHANNEL_RGB_LED_RED` | PB26 | 输出 | RGB LED 红色 |
| `BSP_GPIO_CHANNEL_RGB_LED_GREEN` | PB27 | 输出 | RGB LED 绿色 |
| `BSP_GPIO_CHANNEL_USER_BUTTON_NEXT` | PA18 | 输入 | S1，按下为高电平 |
| `BSP_GPIO_CHANNEL_USER_BUTTON_PREVIOUS` | PB21 | 输入 | S2，按下为低电平 |
| `BSP_GPIO_CHANNEL_TFT_DC` | PB1 | 输出 | ST7735S 命令/数据选择 |
| `BSP_GPIO_CHANNEL_TFT_RESET` | PB4 | 输出 | ST7735S 硬件复位 |
| `BSP_GPIO_CHANNEL_AD9850_RESET` | PA1 | 输出 | AD9850 复位，高电平无输出 |
| `BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_0..3` | PB0/PB7/PB12/PB13 | 输出 | 4×4 矩阵键盘行扫描 |
| `BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_0..3` | PA13/PA12/PA29/PA30 | 输入上拉 | 4×4 矩阵键盘列读取 |

BSP 返回的是引脚原始逻辑电平，不负责把高低电平转换成“LED 亮灭”或“按键按下松开”。这些有效电平差异由 `modules/led` 和 `modules/button` 处理。

## 2. 公开接口

```c
BSPGPIOInstance *BSPGPIORegister(BSP_GPIO_Channel_e channel);
bool BSPGPIOWrite(BSPGPIOInstance *instance, bool high);
bool BSPGPIOToggle(BSPGPIOInstance *instance);
bool BSPGPIORead(BSPGPIOInstance *instance, bool *high);
bool BSPGPIOSetOutputEnabled(BSPGPIOInstance *instance, bool enabled);
```

## 3. 控制输出

```c
BSPGPIOInstance *led =
    BSPGPIORegister(BSP_GPIO_CHANNEL_USER_LED_1);

if (led != NULL) {
    (void)BSPGPIOWrite(led, true);
    (void)BSPGPIOToggle(led);
}
```

LED、TFT/AD9850 控制和矩阵键盘行通道可以调用 `BSPGPIOWrite()` 与
`BSPGPIOToggle()`。对板载按键或矩阵键盘列输入实例调用会返回 `false`。

`BSPGPIOSetOutputEnabled()` 只用于矩阵键盘行。驱动扫描时让未选中的行处于高阻
状态，防止多键按下时两个推挽输出通过按键相连；其他通道调用会返回 `false`。

## 4. 读取输入

```c
BSPGPIOInstance *button =
    BSPGPIORegister(BSP_GPIO_CHANNEL_USER_BUTTON_NEXT);
bool pin_high;

if ((button != NULL) && BSPGPIORead(button, &pin_high)) {
    if (pin_high) {
        /* PA18 的原始电平为高，S1 当前按下。 */
    }
}
```

PB21 的有效电平相反：读取为低电平时表示 S2 按下。

`BSPGPIORead()` 也可以读取输出通道当前的引脚电平。

## 5. 按键处理注意事项

BSP 只读取瞬时电平，不实现：

- 按键消抖
- 短按和长按判断
- 自动重复触发
- 按下/释放事件回调

板载按键的这些功能由 `modules/button` 处理；4×4 矩阵键盘由
`modules/matrix_keypad` 逐行扫描并独立防抖。任务中直接轮询时，需要设置合理的
扫描周期和消抖时间。

## 6. GPIO 初始状态

引脚方向、上下拉和启动电平由 `blink_led.syscfg` 生成，并在 `BSPInit()` 中应用。`BSPGPIORegister()` 只返回与逻辑通道对应的静态实例，不会重新配置整个引脚复用。

修改引脚或有效电平时，应同时检查：

- SysConfig 中的 GPIO 引脚和上下拉配置
- `BSP_GPIO_Channel_e` 的逻辑映射
- `bsp_gpio.c` 中的端口、引脚掩码和输入/输出属性
- `modules/led` 或 `modules/button` 中的有效电平配置

## 7. 并发注意事项

BSP GPIO 接口不使用 FreeRTOS 互斥锁。多个任务同时控制同一输出时，最终状态取决于实际调用顺序。建议由一个模块或任务统一拥有一个输出通道。
