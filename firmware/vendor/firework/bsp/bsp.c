/*
 * BSP 总入口负责按编译配置初始化板级外设，并提供不依赖 RTOS 锁的故障安全关断。
 * 业务层不应绕过这里直接调用 SysConfig 的整机初始化函数。
 */
#include "bsp/bsp.h"

#include "application/app_config.h"

#include "bsp/dac/bsp_dac.h"
#include "bsp/pwm/bsp_pwm.h"
#if APP_ENABLE_TB6612_CONTROL != 0U
#include "bsp/tb6612/bsp_tb6612.h"
#endif
#include "ti_msp_dl_config.h"

#define BSP_AD9833_SAFE_CONTROL_WORD (0x21C0U)
#define BSP_SAFE_SPI_WAIT_ITERATIONS (100000UL)
#define BSP_SPI_FIFO_DEPTH            (4U)
/* 以下派生开关把 Application 功能选择折算为实际需要初始化的板级资源。 */
#define BSP_MATRIX_KEYPAD_ROW_PINS                                      \
    (GPIO_MATRIX_KEYPAD_ROW_0_PIN | GPIO_MATRIX_KEYPAD_ROW_1_PIN |     \
        GPIO_MATRIX_KEYPAD_ROW_2_PIN | GPIO_MATRIX_KEYPAD_ROW_3_PIN)
#define BSP_ENABLE_PWM_OUTPUT                                           \
    ((APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U) ||                     \
        (APP_ENABLE_SERVO_CONTROL != 0U))
#define BSP_ENABLE_ADC_INPUT_0                                          \
    ((APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) &&                        \
        (APP_ENABLE_WAVEFORM_PA27 != 0U))
#define BSP_ENABLE_ADC_INPUT_1                                          \
    ((APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) &&                        \
        (APP_ENABLE_WAVEFORM_PB19 != 0U))
#define BSP_ENABLE_DMA                                                  \
    ((APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U) ||                         \
        (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) ||                     \
        (APP_ENABLE_UART1 != 0U) ||                                    \
        (APP_ENABLE_UART3 != 0U) ||                                    \
        (APP_ENABLE_UART2 != 0U))

typedef enum {
    BSP_INIT_STATE_UNINITIALIZED = 0,
    BSP_INIT_STATE_INITIALIZING,
    BSP_INIT_STATE_READY,
    BSP_INIT_STATE_FAILED
} BSPInitState_e;

/* 初始化状态用于拒绝重入，并保留失败状态以避免部分初始化后再次尝试。 */
static BSPInitState_e bsp_init_state;
static bool bsp_hardware_initialized;
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
static BSPDACInstance *bsp_safe_dac;
#endif
#if BSP_ENABLE_PWM_OUTPUT
static BSPPWMInstance *bsp_safe_pwm;
#endif

static void BSPInitializeConfiguredHardware(void);
static bool BSPTryStopAD9833(void);

void BSPDelayMilliseconds(uint32_t milliseconds)
{
    /* 调度器启动前可用的忙等待；运行期长延时应由上层使用 RTOS 延时。 */
    while (milliseconds > 0U) {
        delay_cycles(CPUCLK_FREQ / 1000UL);
        --milliseconds;
    }
}

bool BSPFlashEraseMainSector(uint32_t address)
{
    uint32_t interrupt_state;
    DL_FLASHCTL_COMMAND_STATUS status;

    /* Flash 命令要求在关中断区间从 RAM 执行，结束后恢复调用前的中断状态。 */
    DL_FlashCTL_unprotectSector(
        FLASHCTL, address, DL_FLASHCTL_REGION_SELECT_MAIN);
    interrupt_state = __get_PRIMASK();
    __disable_irq();
    status = DL_FlashCTL_eraseMemoryFromRAM(
        FLASHCTL, address, DL_FLASHCTL_COMMAND_SIZE_SECTOR);
    if (interrupt_state == 0U) {
        __enable_irq();
    }
    return status == DL_FLASHCTL_COMMAND_STATUS_PASSED;
}

bool BSPFlashProgramMain64WithECC(
    uint32_t address, const uint32_t words[2])
{
    uint32_t interrupt_state;
    DL_FLASHCTL_COMMAND_STATUS status;

    if ((words == NULL) || ((address & 7U) != 0U)) {
        return false;
    }
    /* 64 位 ECC 写入要求地址按 8 字节对齐。 */
    DL_FlashCTL_unprotectSector(
        FLASHCTL, address, DL_FLASHCTL_REGION_SELECT_MAIN);
    interrupt_state = __get_PRIMASK();
    __disable_irq();
    status = DL_FlashCTL_programMemoryFromRAM64WithECCGenerated(
        FLASHCTL, address, words);
    if (interrupt_state == 0U) {
        __enable_irq();
    }
    return status == DL_FLASHCTL_COMMAND_STATUS_PASSED;
}

bool BSPInit(void)
{
    if (bsp_init_state == BSP_INIT_STATE_READY) {
        return true;
    }
    if (bsp_init_state != BSP_INIT_STATE_UNINITIALIZED) {
        return false;
    }
    bsp_init_state = BSP_INIT_STATE_INITIALIZING;

    /* 只初始化当前编译配置实际使用的外设，关闭功能不再占用初始化代码。 */
    BSPInitializeConfiguredHardware();
    bsp_hardware_initialized = true;

#if APP_ENABLE_TB6612_CONTROL != 0U
    /* 电机功率级必须在其他初始化和任务启动前首先进入待机。 */
    BSPTB6612EnterSafeState();
#endif

    /* SysConfig 会启用 DAC 并把 PWM CCP 设为输出，立即恢复为安全态。 */
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    DL_TimerG_stopCounter(ADC_SAMPLE_TIMER_INST);
#endif
#if BSP_ENABLE_ADC_INPUT_0
    DL_ADC12_disableConversions(ADC_INPUT_0_INST);
    DL_ADC12_disableDMA(ADC_INPUT_0_INST);
    DL_COMP_disable(ANALOG_CAPTURE_COMP_0_INST);
#endif
#if BSP_ENABLE_ADC_INPUT_1
    DL_ADC12_disableConversions(ADC_INPUT_1_INST);
    DL_ADC12_disableDMA(ADC_INPUT_1_INST);
    DL_COMP_disable(ANALOG_CAPTURE_COMP_1_INST);
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    DL_DAC12_disableSampleTimeGenerator(DAC0);
    DL_DAC12_disableDMATrigger(DAC0);
    DL_DMA_disableChannel(DMA, DMA_DAC_OUTPUT_CHAN_ID);
    DL_DAC12_disableFIFO(DAC0);
#endif
    /* MCU 单独复位时外部 AD9833 仍可能保留旧输出，必须主动休眠。 */
    if (!BSPTryStopAD9833()) {
        bsp_init_state = BSP_INIT_STATE_FAILED;
        return false;
    }
    DL_GPIO_setPins(GPIO_DDS_PORT, GPIO_DDS_AD9833_FSYNC_PIN);
    DL_SPI_disable(SPI_DDS_INST);
#if APP_ENABLE_TFT_MENU != 0U
    /* TFT 注册前保持片选无效并关闭 SPI0。 */
    DL_GPIO_setPins(GPIO_TFT_PORT, GPIO_TFT_TFT_CS_PIN);
    DL_GPIO_setPins(GPIO_TFT_PORT, GPIO_TFT_TFT_RESET_PIN);
    DL_SPI_disable(SPI_TFT_INST);
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    bsp_safe_dac = BSPDACRegister(BSP_DAC_CHANNEL_OUTPUT_0);
#endif
#if BSP_ENABLE_PWM_OUTPUT
    bsp_safe_pwm = BSPPWMRegister(BSP_PWM_CHANNEL_OUTPUT_0);
#endif
    if (
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
        (bsp_safe_dac == NULL) ||
#endif
#if BSP_ENABLE_PWM_OUTPUT
        (bsp_safe_pwm == NULL) ||
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
        !BSPDACSetEnabled(bsp_safe_dac, false) ||
#endif
#if BSP_ENABLE_PWM_OUTPUT
        !BSPPWMSetEnabled(bsp_safe_pwm, false) ||
#endif
        false) {
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
        if (bsp_safe_dac != NULL) {
            (void)BSPDACSetEnabled(bsp_safe_dac, false);
        }
#endif
#if BSP_ENABLE_PWM_OUTPUT
        if (bsp_safe_pwm != NULL) {
            (void)BSPPWMSetEnabled(bsp_safe_pwm, false);
        }
#endif
        bsp_init_state = BSP_INIT_STATE_FAILED;
        return false;
    }

    bsp_init_state = BSP_INIT_STATE_READY;
    return true;
}

void BSPEnterSafeState(void)
{
    uint8_t dma_channel;

    /* 该路径不获取锁，可从 fault/栈溢出上下文重复调用。 */
    __disable_irq();
    if (!bsp_hardware_initialized) {
        return;
    }
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    DL_TimerG_stopCounter(ADC_SAMPLE_TIMER_INST);
#endif
#if BSP_ENABLE_ADC_INPUT_0
    DL_TimerG_stopCounter(ANALOG_CAPTURE_TIMER_0_INST);
#endif
#if BSP_ENABLE_ADC_INPUT_1
    DL_TimerG_stopCounter(ANALOG_CAPTURE_TIMER_1_INST);
#endif
#if BSP_ENABLE_PWM_OUTPUT
    BSPPWMEnterSafeState();
#endif
#if APP_ENABLE_TB6612_CONTROL != 0U
    BSPTB6612EnterSafeState();
#endif
#if BSP_ENABLE_ADC_INPUT_0
    DL_ADC12_disableConversions(ADC_INPUT_0_INST);
    DL_ADC12_disableDMA(ADC_INPUT_0_INST);
    DL_COMP_disable(ANALOG_CAPTURE_COMP_0_INST);
#endif
#if BSP_ENABLE_ADC_INPUT_1
    DL_ADC12_disableConversions(ADC_INPUT_1_INST);
    DL_ADC12_disableDMA(ADC_INPUT_1_INST);
    DL_COMP_disable(ANALOG_CAPTURE_COMP_1_INST);
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    DL_DAC12_disableSampleTimeGenerator(DAC0);
    DL_DAC12_disableDMATrigger(DAC0);
    DL_DAC12_disableFIFO(DAC0);
#endif
#if BSP_ENABLE_DMA
    for (dma_channel = DMA_DAC_OUTPUT_CHAN_ID;
         dma_channel <= DMA_ADC_INPUT_1_CHAN_ID; ++dma_channel) {
        DL_DMA_disableChannel(DMA, dma_channel);
    }
#else
    (void)dma_channel;
#endif
    (void)BSPTryStopAD9833();
    DL_GPIO_setPins(GPIO_DDS_PORT, GPIO_DDS_AD9833_FSYNC_PIN);
    DL_SPI_disable(SPI_DDS_INST);
#if APP_ENABLE_TFT_MENU != 0U
    DL_GPIO_setPins(GPIO_TFT_PORT, GPIO_TFT_TFT_CS_PIN);
    DL_GPIO_clearPins(GPIO_TFT_PORT, GPIO_TFT_TFT_RESET_PIN);
    DL_SPI_disable(SPI_TFT_INST);
#endif
    /* 即使故障发生在扫描中，也把四路矩阵行恢复成一致的高电平。 */
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    DL_GPIO_setPins(
        GPIO_MATRIX_KEYPAD_ROW_0_PORT, BSP_MATRIX_KEYPAD_ROW_PINS);
    DL_GPIO_enableOutput(
        GPIO_MATRIX_KEYPAD_ROW_0_PORT, BSP_MATRIX_KEYPAD_ROW_PINS);
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    DL_DAC12_disable(DAC0);
#endif

#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    if (bsp_safe_dac != NULL) {
        (void)BSPDACSetEnabled(bsp_safe_dac, false);
    }
#endif
}

/*
 * SysConfig 的弱 SYSCFG_DL_init() 会无条件初始化工程中声明的全部外设。
 * 这里保留统一的电源、引脚和系统时钟初始化，再按 app_config 功能开关调用
 * 模块初始化函数，使链接器能够移除关闭功能对应的初始化代码。
 */
static void BSPInitializeConfiguredHardware(void)
{
    SYSCFG_DL_initPower();
    SYSCFG_DL_GPIO_init();
    SYSCFG_DL_SYSCTL_init();

#if BSP_ENABLE_PWM_OUTPUT
    SYSCFG_DL_PWM_OUTPUT_init();
#endif
#if APP_ENABLE_TB6612_CONTROL != 0U
    SYSCFG_DL_TB6612_PWM_init();
#endif
#if BSP_ENABLE_ADC_INPUT_0
    SYSCFG_DL_ANALOG_CAPTURE_TIMER_0_init();
    SYSCFG_DL_ANALOG_CAPTURE_COMP_0_init();
    SYSCFG_DL_ADC_INPUT_0_init();
#endif
#if BSP_ENABLE_ADC_INPUT_1
    SYSCFG_DL_ANALOG_CAPTURE_TIMER_1_init();
    SYSCFG_DL_ANALOG_CAPTURE_COMP_1_init();
    SYSCFG_DL_ADC_INPUT_1_init();
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    SYSCFG_DL_ADC_SAMPLE_TIMER_init();
#endif
#if APP_ENABLE_MPU6050_INPUT != 0U
    SYSCFG_DL_I2C_MPU6050_init();
#endif
#if APP_ENABLE_OLED_MENU != 0U
    SYSCFG_DL_I2C_OLED_init();
#endif
#if APP_ENABLE_UART0_DEBUG != 0U
    SYSCFG_DL_UART_DEBUG_init();
#endif
#if APP_ENABLE_UART1 != 0U
    SYSCFG_DL_UART_PORT1_init();
#endif
#if APP_ENABLE_UART2 != 0U
    SYSCFG_DL_UART_PORT2_init();
#endif
#if APP_ENABLE_UART3 != 0U
    SYSCFG_DL_UART_PORT3_init();
#endif
    /* 即使未启用 AD9833，也要发送休眠控制字确保外部模块处于安全态。 */
    SYSCFG_DL_SPI_DDS_init();
#if APP_ENABLE_TFT_MENU != 0U
    SYSCFG_DL_SPI_TFT_init();
#endif
#if BSP_ENABLE_DMA
    SYSCFG_DL_DMA_init();
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    SYSCFG_DL_DAC12_init();
#endif
}

/*
 * Fault 路径不能获取 DDS/SPI mutex；直接使用已由 SysConfig 配置好的 SPI1，
 * 在有限轮询内写入 B28|RESET|SLEEP1|SLEEP12。即使失败也继续关闭本机外设。
 */
static bool BSPTryStopAD9833(void)
{
    uint8_t drained_words = 0U;
    uint32_t timeout = BSP_SAFE_SPI_WAIT_ITERATIONS;

    if (!DL_SPI_isPowerEnabled(SPI_DDS_INST)) {
        return false;
    }
    if (!DL_SPI_isEnabled(SPI_DDS_INST)) {
        DL_SPI_enable(SPI_DDS_INST);
    }

    DL_GPIO_setPins(GPIO_DDS_PORT, GPIO_DDS_AD9833_FSYNC_PIN);
    while (DL_SPI_isBusy(SPI_DDS_INST) && (timeout > 0U)) {
        --timeout;
    }
    if (timeout == 0U) {
        return false;
    }
    while (!DL_SPI_isRXFIFOEmpty(SPI_DDS_INST) &&
           (drained_words < BSP_SPI_FIFO_DEPTH)) {
        (void)DL_SPI_receiveData16(SPI_DDS_INST);
        ++drained_words;
    }
    DL_GPIO_clearPins(GPIO_DDS_PORT, GPIO_DDS_AD9833_FSYNC_PIN);

    timeout = BSP_SAFE_SPI_WAIT_ITERATIONS;
    while (DL_SPI_isTXFIFOFull(SPI_DDS_INST) && (timeout > 0U)) {
        --timeout;
    }
    if (timeout == 0U) {
        DL_GPIO_setPins(GPIO_DDS_PORT, GPIO_DDS_AD9833_FSYNC_PIN);
        return false;
    }

    DL_SPI_transmitData16(SPI_DDS_INST, BSP_AD9833_SAFE_CONTROL_WORD);
    timeout = BSP_SAFE_SPI_WAIT_ITERATIONS;
    while (DL_SPI_isBusy(SPI_DDS_INST) && (timeout > 0U)) {
        --timeout;
    }
    DL_GPIO_setPins(GPIO_DDS_PORT, GPIO_DDS_AD9833_FSYNC_PIN);
    return timeout > 0U;
}
