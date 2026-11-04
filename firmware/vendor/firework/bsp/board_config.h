/**
 * @file board_config.h
 * @brief 板级时钟、采样周期和捕获定时器常量的人工维护入口。
 */
#ifndef BSP_BOARD_CONFIG_H
#define BSP_BOARD_CONFIG_H

/*
 * SysConfig 尚未为定时器输入时钟和外部 DDS 晶振生成统一宏，集中在此处
 * 保存板级真实参数。修改 blink_led.syscfg 或更换 DDS 模块时同步更新。
 */
#define BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ    (4000000UL)
#define BSP_BOARD_ADC_SAMPLE_TIMER_PERIOD_US   (1UL)
#define BSP_BOARD_ADC_MAXIMUM_SAMPLE_RATE_HZ   (4000000UL)
#define BSP_BOARD_ADC_DEFAULT_SAMPLE_TIME_CLOCKS (8U)
#define BSP_BOARD_ADC_HIGH_SPEED_SAMPLE_TIME_CLOCKS (2U)
#define BSP_BOARD_CAPTURE_PA27_TIMER_CLOCK_HZ (4000000UL)
#define BSP_BOARD_CAPTURE_PA21_TIMER_CLOCK_HZ (62500UL)
#define BSP_BOARD_DDS_REFERENCE_CLOCK_HZ       (25000000UL)
/* 常见 AD9850 模块搭载 125 MHz 有源晶振；更换模块时同步修改。 */
#define BSP_BOARD_AD9850_REFERENCE_CLOCK_HZ    (125000000UL)

/* 当前捕获定时器分别配置为 100 s 和 1 s 满量程，用于启动时一致性检查。 */
#define BSP_BOARD_CAPTURE_PA27_TIMER_PERIOD_SECONDS (100UL)
#define BSP_BOARD_CAPTURE_PA21_TIMER_PERIOD_SECONDS (1UL)

#endif
