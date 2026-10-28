/*
 * 【合成样例】按 TI SysConfig 生成的 ti_msp_dl_config.c 的结构手写（只调用 DriverLib），
 * **不是 SysConfig 的真实输出，未上板测试**。用你的 .syscfg 重新生成后整体替换。
 */
#include "ti_msp_dl_config.h"

SYSCONFIG_WEAK void SYSCFG_DL_init(void)
{
    SYSCFG_DL_initPower();
    SYSCFG_DL_GPIO_init();
    SYSCFG_DL_SYSCTL_init();
    SYSCFG_DL_PWM_TIMG0_init();
    SYSCFG_DL_ENC_MOTOR_A_init();
    SYSCFG_DL_TIMER_CTRL_init();
    SYSCFG_DL_UART_LINK_init();
}

SYSCONFIG_WEAK void SYSCFG_DL_initPower(void)
{
    DL_GPIO_reset(GPIOA);
    DL_GPIO_reset(GPIOB);
    DL_TimerG_reset(PWM_TIMG0_INST);
    DL_TimerG_reset(ENC_MOTOR_A_INST);
    DL_TimerG_reset(TIMER_CTRL_INST);
    DL_UART_Main_reset(UART_LINK_INST);

    DL_GPIO_enablePower(GPIOA);
    DL_GPIO_enablePower(GPIOB);
    DL_TimerG_enablePower(PWM_TIMG0_INST);
    DL_TimerG_enablePower(ENC_MOTOR_A_INST);
    DL_TimerG_enablePower(TIMER_CTRL_INST);
    DL_UART_Main_enablePower(UART_LINK_INST);
    delay_cycles(POWER_STARTUP_DELAY);
}

SYSCONFIG_WEAK void SYSCFG_DL_GPIO_init(void)
{
    DL_GPIO_initPeripheralOutputFunction(GPIO_PWM_TIMG0_C0_IOMUX, GPIO_PWM_TIMG0_C0_IOMUX_FUNC);
    DL_GPIO_enableOutput(GPIO_PWM_TIMG0_C0_PORT, GPIO_PWM_TIMG0_C0_PIN);
    DL_GPIO_initPeripheralOutputFunction(GPIO_PWM_TIMG0_C1_IOMUX, GPIO_PWM_TIMG0_C1_IOMUX_FUNC);
    DL_GPIO_enableOutput(GPIO_PWM_TIMG0_C1_PORT, GPIO_PWM_TIMG0_C1_PIN);

    DL_GPIO_initPeripheralInputFunction(GPIO_ENC_MOTOR_A_PHA_IOMUX, GPIO_ENC_MOTOR_A_PHA_IOMUX_FUNC);
    DL_GPIO_initPeripheralInputFunction(GPIO_ENC_MOTOR_A_PHB_IOMUX, GPIO_ENC_MOTOR_A_PHB_IOMUX_FUNC);

    DL_GPIO_initPeripheralOutputFunction(GPIO_UART_LINK_IOMUX_TX, GPIO_UART_LINK_IOMUX_TX_FUNC);
    DL_GPIO_initPeripheralInputFunction(GPIO_UART_LINK_IOMUX_RX, GPIO_UART_LINK_IOMUX_RX_FUNC);

    DL_GPIO_initDigitalOutput(GPIO_MOTOR_A_IN1_PIN_IOMUX);
    DL_GPIO_initDigitalOutput(GPIO_MOTOR_A_IN2_PIN_IOMUX);
    DL_GPIO_initDigitalOutput(GPIO_MOTOR_B_IN1_PIN_IOMUX);
    DL_GPIO_initDigitalOutput(GPIO_MOTOR_B_IN2_PIN_IOMUX);
    DL_GPIO_clearPins(GPIOB, GPIO_MOTOR_A_IN1_PIN_PIN | GPIO_MOTOR_A_IN2_PIN_PIN |
                             GPIO_MOTOR_B_IN1_PIN_PIN | GPIO_MOTOR_B_IN2_PIN_PIN);
    DL_GPIO_enableOutput(GPIOB, GPIO_MOTOR_A_IN1_PIN_PIN | GPIO_MOTOR_A_IN2_PIN_PIN |
                                GPIO_MOTOR_B_IN1_PIN_PIN | GPIO_MOTOR_B_IN2_PIN_PIN);

    DL_GPIO_initDigitalInputFeatures(ENC_MOTOR_B_A_IOMUX, DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_PULL_UP,
                                     DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);
    DL_GPIO_initDigitalInputFeatures(ENC_MOTOR_B_B_IOMUX, DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_PULL_UP,
                                     DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);
    DL_GPIO_setLowerPinsPolarity(ENC_MOTOR_B_PORT, DL_GPIO_PIN_6_EDGE_RISE_FALL | DL_GPIO_PIN_7_EDGE_RISE_FALL);
    DL_GPIO_clearInterruptStatus(ENC_MOTOR_B_PORT, ENC_MOTOR_B_A_PIN | ENC_MOTOR_B_B_PIN);
    DL_GPIO_enableInterrupt(ENC_MOTOR_B_PORT, ENC_MOTOR_B_A_PIN | ENC_MOTOR_B_B_PIN);
}

SYSCONFIG_WEAK void SYSCFG_DL_SYSCTL_init(void)
{
    DL_SYSCTL_setBORThreshold(DL_SYSCTL_BOR_THRESHOLD_LEVEL_0);
    DL_SYSCTL_setSYSOSCFreq(DL_SYSCTL_SYSOSC_FREQ_BASE);
    DL_SYSCTL_disableHFXT();
    DL_SYSCTL_disableSYSPLL();
    DL_SYSCTL_setMCLKDivider(DL_SYSCTL_MCLK_DIVIDER_DISABLE);
}

static const DL_TimerG_ClockConfig gPWM_TIMG0ClockConfig = {
    .clockSel = DL_TIMER_CLOCK_BUSCLK, .divideRatio = DL_TIMER_CLOCK_DIVIDE_1, .prescale = 0U };
static const DL_TimerG_PWMConfig gPWM_TIMG0Config = {
    .pwmMode = DL_TIMER_PWM_MODE_EDGE_ALIGN, .period = 1600, .startTimer = DL_TIMER_START };

SYSCONFIG_WEAK void SYSCFG_DL_PWM_TIMG0_init(void)
{
    DL_TimerG_setClockConfig(PWM_TIMG0_INST, (DL_TimerG_ClockConfig *)&gPWM_TIMG0ClockConfig);
    DL_TimerG_initPWMMode(PWM_TIMG0_INST, (DL_TimerG_PWMConfig *)&gPWM_TIMG0Config);
    DL_TimerG_setCaptureCompareOutCtl(PWM_TIMG0_INST, DL_TIMER_CC_OCTL_INIT_VAL_LOW, DL_TIMER_CC_OCTL_INV_OUT_DISABLED,
                                      DL_TIMER_CC_OCTL_SRC_FUNCVAL, DL_TIMERG_CAPTURE_COMPARE_0_INDEX);
    DL_TimerG_setCaptCompUpdateMethod(PWM_TIMG0_INST, DL_TIMER_CC_UPDATE_METHOD_IMMEDIATE, DL_TIMERG_CAPTURE_COMPARE_0_INDEX);
    DL_TimerG_setCaptureCompareValue(PWM_TIMG0_INST, 1600, DL_TIMER_CC_0_INDEX);
    DL_TimerG_setCaptureCompareOutCtl(PWM_TIMG0_INST, DL_TIMER_CC_OCTL_INIT_VAL_LOW, DL_TIMER_CC_OCTL_INV_OUT_DISABLED,
                                      DL_TIMER_CC_OCTL_SRC_FUNCVAL, DL_TIMERG_CAPTURE_COMPARE_1_INDEX);
    DL_TimerG_setCaptCompUpdateMethod(PWM_TIMG0_INST, DL_TIMER_CC_UPDATE_METHOD_IMMEDIATE, DL_TIMERG_CAPTURE_COMPARE_1_INDEX);
    DL_TimerG_setCaptureCompareValue(PWM_TIMG0_INST, 1600, DL_TIMER_CC_1_INDEX);
    DL_TimerG_enableClock(PWM_TIMG0_INST);
    DL_TimerG_setCCPDirection(PWM_TIMG0_INST, DL_TIMER_CC0_OUTPUT | DL_TIMER_CC1_OUTPUT);
}

static const DL_TimerG_ClockConfig gENC_MOTOR_AClockConfig = {
    .clockSel = DL_TIMER_CLOCK_BUSCLK, .divideRatio = DL_TIMER_CLOCK_DIVIDE_1, .prescale = 0U };

SYSCONFIG_WEAK void SYSCFG_DL_ENC_MOTOR_A_init(void)
{
    DL_TimerG_setClockConfig(ENC_MOTOR_A_INST, (DL_TimerG_ClockConfig *)&gENC_MOTOR_AClockConfig);
    DL_TimerG_configQEI(ENC_MOTOR_A_INST, DL_TIMER_QEI_MODE_2_INPUT, DL_TIMER_CC_INPUT_INV_NOINVERT, DL_TIMER_CC_0_INDEX);
    DL_TimerG_configQEI(ENC_MOTOR_A_INST, DL_TIMER_QEI_MODE_2_INPUT, DL_TIMER_CC_INPUT_INV_NOINVERT, DL_TIMER_CC_1_INDEX);
    DL_TimerG_setLoadValue(ENC_MOTOR_A_INST, 65535);
    DL_TimerG_enableClock(ENC_MOTOR_A_INST);
}

static const DL_TimerG_ClockConfig gTIMER_CTRLClockConfig = {
    .clockSel = DL_TIMER_CLOCK_BUSCLK, .divideRatio = DL_TIMER_CLOCK_DIVIDE_1, .prescale = 31U };
static const DL_TimerG_TimerConfig gTIMER_CTRLTimerConfig = {
    .period = TIMER_CTRL_INST_LOAD_VALUE, .timerMode = DL_TIMER_TIMER_MODE_PERIODIC, .startTimer = DL_TIMER_STOP };

SYSCONFIG_WEAK void SYSCFG_DL_TIMER_CTRL_init(void)
{
    DL_TimerG_setClockConfig(TIMER_CTRL_INST, (DL_TimerG_ClockConfig *)&gTIMER_CTRLClockConfig);
    DL_TimerG_initTimerMode(TIMER_CTRL_INST, (DL_TimerG_TimerConfig *)&gTIMER_CTRLTimerConfig);
    DL_TimerG_enableInterrupt(TIMER_CTRL_INST, DL_TIMERG_INTERRUPT_ZERO_EVENT);
    DL_TimerG_enableClock(TIMER_CTRL_INST);
}

static const DL_UART_Main_ClockConfig gUART_LINKClockConfig = {
    .clockSel = DL_UART_MAIN_CLOCK_BUSCLK, .divideRatio = DL_UART_MAIN_CLOCK_DIVIDE_RATIO_1 };
static const DL_UART_Main_Config gUART_LINKConfig = {
    .mode = DL_UART_MAIN_MODE_NORMAL, .direction = DL_UART_MAIN_DIRECTION_TX_RX,
    .flowControl = DL_UART_MAIN_FLOW_CONTROL_NONE, .parity = DL_UART_MAIN_PARITY_NONE,
    .wordLength = DL_UART_MAIN_WORD_LENGTH_8_BITS, .stopBits = DL_UART_MAIN_STOP_BITS_ONE };

SYSCONFIG_WEAK void SYSCFG_DL_UART_LINK_init(void)
{
    DL_UART_Main_setClockConfig(UART_LINK_INST, (DL_UART_Main_ClockConfig *)&gUART_LINKClockConfig);
    DL_UART_Main_init(UART_LINK_INST, (DL_UART_Main_Config *)&gUART_LINKConfig);
    DL_UART_Main_setOversampling(UART_LINK_INST, DL_UART_OVERSAMPLING_RATE_16X);
    DL_UART_Main_setBaudRateDivisor(UART_LINK_INST, UART_LINK_IBRD_32_MHZ_115200_BAUD, UART_LINK_FBRD_32_MHZ_115200_BAUD);
    DL_UART_Main_enableInterrupt(UART_LINK_INST, DL_UART_MAIN_INTERRUPT_RX);
    DL_UART_Main_enable(UART_LINK_INST);
}
