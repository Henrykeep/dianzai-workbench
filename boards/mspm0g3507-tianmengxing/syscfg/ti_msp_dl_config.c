/*
 * Copyright (c) 2023, Texas Instruments Incorporated
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * *  Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *
 * *  Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * *  Neither the name of Texas Instruments Incorporated nor the names of
 *    its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
 * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
 * OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
 * WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
 * OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
 * EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*
 *  ============ ti_msp_dl_config.c =============
 *  Configured MSPM0 DriverLib module definitions
 *
 *  DO NOT EDIT - This file is generated for the MSPM0G350X
 *  by the SysConfig tool.
 */

#include "ti_msp_dl_config.h"

DL_TimerG_backupConfig gENC_MOTOR_ABackup;
DL_TimerG_backupConfig gTIMER_CTRLBackup;
DL_SPI_backupConfig gSPI_BUS1Backup;

/*
 *  ======== SYSCFG_DL_init ========
 *  Perform any initialization needed before using any board APIs
 */
SYSCONFIG_WEAK void SYSCFG_DL_init(void)
{
    SYSCFG_DL_initPower();
    SYSCFG_DL_GPIO_init();
    /* Module-Specific Initializations*/
    SYSCFG_DL_SYSCTL_init();
    SYSCFG_DL_PWM_TIMG0_init();
    SYSCFG_DL_ENC_MOTOR_A_init();
    SYSCFG_DL_TIMER_CTRL_init();
    SYSCFG_DL_I2C_IMU_init();
    SYSCFG_DL_UART_LINK_init();
    SYSCFG_DL_UART_IMU_init();
    SYSCFG_DL_SPI_BUS1_init();
    SYSCFG_DL_ADC12_0_init();
    /* Ensure backup structures have no valid state */

	gENC_MOTOR_ABackup.backupRdy 	= false;
	gTIMER_CTRLBackup.backupRdy 	= false;

	gSPI_BUS1Backup.backupRdy 	= false;

}
/*
 * User should take care to save and restore register configuration in application.
 * See Retention Configuration section for more details.
 */
SYSCONFIG_WEAK bool SYSCFG_DL_saveConfiguration(void)
{
    bool retStatus = true;

	retStatus &= DL_TimerG_saveConfiguration(ENC_MOTOR_A_INST, &gENC_MOTOR_ABackup);
	retStatus &= DL_TimerG_saveConfiguration(TIMER_CTRL_INST, &gTIMER_CTRLBackup);
	retStatus &= DL_SPI_saveConfiguration(SPI_BUS1_INST, &gSPI_BUS1Backup);

    return retStatus;
}


SYSCONFIG_WEAK bool SYSCFG_DL_restoreConfiguration(void)
{
    bool retStatus = true;

	retStatus &= DL_TimerG_restoreConfiguration(ENC_MOTOR_A_INST, &gENC_MOTOR_ABackup, false);
	retStatus &= DL_TimerG_restoreConfiguration(TIMER_CTRL_INST, &gTIMER_CTRLBackup, false);
	retStatus &= DL_SPI_restoreConfiguration(SPI_BUS1_INST, &gSPI_BUS1Backup);

    return retStatus;
}

SYSCONFIG_WEAK void SYSCFG_DL_initPower(void)
{
    DL_GPIO_reset(GPIOA);
    DL_GPIO_reset(GPIOB);
    DL_TimerG_reset(PWM_TIMG0_INST);
    DL_TimerG_reset(ENC_MOTOR_A_INST);
    DL_TimerG_reset(TIMER_CTRL_INST);
    DL_I2C_reset(I2C_IMU_INST);
    DL_UART_Main_reset(UART_LINK_INST);
    DL_UART_Main_reset(UART_IMU_INST);
    DL_SPI_reset(SPI_BUS1_INST);
    DL_ADC12_reset(ADC12_0_INST);

    DL_GPIO_enablePower(GPIOA);
    DL_GPIO_enablePower(GPIOB);
    DL_TimerG_enablePower(PWM_TIMG0_INST);
    DL_TimerG_enablePower(ENC_MOTOR_A_INST);
    DL_TimerG_enablePower(TIMER_CTRL_INST);
    DL_I2C_enablePower(I2C_IMU_INST);
    DL_UART_Main_enablePower(UART_LINK_INST);
    DL_UART_Main_enablePower(UART_IMU_INST);
    DL_SPI_enablePower(SPI_BUS1_INST);
    DL_ADC12_enablePower(ADC12_0_INST);
    delay_cycles(POWER_STARTUP_DELAY);
}

SYSCONFIG_WEAK void SYSCFG_DL_GPIO_init(void)
{

    DL_GPIO_initPeripheralOutputFunction(GPIO_PWM_TIMG0_C0_IOMUX,GPIO_PWM_TIMG0_C0_IOMUX_FUNC);
    DL_GPIO_enableOutput(GPIO_PWM_TIMG0_C0_PORT, GPIO_PWM_TIMG0_C0_PIN);
    DL_GPIO_initPeripheralOutputFunction(GPIO_PWM_TIMG0_C1_IOMUX,GPIO_PWM_TIMG0_C1_IOMUX_FUNC);
    DL_GPIO_enableOutput(GPIO_PWM_TIMG0_C1_PORT, GPIO_PWM_TIMG0_C1_PIN);

    DL_GPIO_initPeripheralInputFunction(GPIO_ENC_MOTOR_A_PHA_IOMUX,GPIO_ENC_MOTOR_A_PHA_IOMUX_FUNC);
    DL_GPIO_initPeripheralInputFunction(GPIO_ENC_MOTOR_A_PHB_IOMUX,GPIO_ENC_MOTOR_A_PHB_IOMUX_FUNC);

    DL_GPIO_initPeripheralInputFunctionFeatures(GPIO_I2C_IMU_IOMUX_SDA,
        GPIO_I2C_IMU_IOMUX_SDA_FUNC, DL_GPIO_INVERSION_DISABLE,
        DL_GPIO_RESISTOR_NONE, DL_GPIO_HYSTERESIS_DISABLE,
        DL_GPIO_WAKEUP_DISABLE);
    DL_GPIO_initPeripheralInputFunctionFeatures(GPIO_I2C_IMU_IOMUX_SCL,
        GPIO_I2C_IMU_IOMUX_SCL_FUNC, DL_GPIO_INVERSION_DISABLE,
        DL_GPIO_RESISTOR_NONE, DL_GPIO_HYSTERESIS_DISABLE,
        DL_GPIO_WAKEUP_DISABLE);
    DL_GPIO_enableHiZ(GPIO_I2C_IMU_IOMUX_SDA);
    DL_GPIO_enableHiZ(GPIO_I2C_IMU_IOMUX_SCL);

    DL_GPIO_initPeripheralOutputFunction(
        GPIO_UART_LINK_IOMUX_TX, GPIO_UART_LINK_IOMUX_TX_FUNC);
    DL_GPIO_initPeripheralInputFunction(
        GPIO_UART_LINK_IOMUX_RX, GPIO_UART_LINK_IOMUX_RX_FUNC);
    DL_GPIO_initPeripheralOutputFunction(
        GPIO_UART_IMU_IOMUX_TX, GPIO_UART_IMU_IOMUX_TX_FUNC);
    DL_GPIO_initPeripheralInputFunction(
        GPIO_UART_IMU_IOMUX_RX, GPIO_UART_IMU_IOMUX_RX_FUNC);

    DL_GPIO_initPeripheralOutputFunction(
        GPIO_SPI_BUS1_IOMUX_SCLK, GPIO_SPI_BUS1_IOMUX_SCLK_FUNC);
    DL_GPIO_initPeripheralOutputFunction(
        GPIO_SPI_BUS1_IOMUX_PICO, GPIO_SPI_BUS1_IOMUX_PICO_FUNC);
    DL_GPIO_initPeripheralInputFunction(
        GPIO_SPI_BUS1_IOMUX_POCI, GPIO_SPI_BUS1_IOMUX_POCI_FUNC);

    DL_GPIO_initDigitalOutput(GPIO_MOTOR_A_IN1_MOTOR_A_IN1_IOMUX);

    DL_GPIO_initDigitalOutput(GPIO_MOTOR_A_IN2_MOTOR_A_IN2_IOMUX);

    DL_GPIO_initDigitalOutput(GPIO_MOTOR_B_IN1_MOTOR_B_IN1_IOMUX);

    DL_GPIO_initDigitalOutput(GPIO_MOTOR_B_IN2_MOTOR_B_IN2_IOMUX);

    DL_GPIO_initDigitalOutput(GPIO_CS_SPI1_DEV_CS_IOMUX);

    DL_GPIO_initDigitalOutput(GPIO_US_TRIG_US_TRIG_IOMUX);

    DL_GPIO_initDigitalInputFeatures(GPIO_US_ECHO_US_ECHO_IOMUX,
		 DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
		 DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);

    DL_GPIO_initDigitalInputFeatures(ENC_MOTOR_B_A_IOMUX,
		 DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
		 DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);

    DL_GPIO_initDigitalInputFeatures(ENC_MOTOR_B_B_IOMUX,
		 DL_GPIO_INVERSION_DISABLE, DL_GPIO_RESISTOR_NONE,
		 DL_GPIO_HYSTERESIS_DISABLE, DL_GPIO_WAKEUP_DISABLE);

    DL_GPIO_clearPins(GPIOB, GPIO_MOTOR_A_IN1_MOTOR_A_IN1_PIN |
		GPIO_MOTOR_A_IN2_MOTOR_A_IN2_PIN |
		GPIO_MOTOR_B_IN1_MOTOR_B_IN1_PIN |
		GPIO_MOTOR_B_IN2_MOTOR_B_IN2_PIN |
		GPIO_US_TRIG_US_TRIG_PIN);
    DL_GPIO_setPins(GPIOB, GPIO_CS_SPI1_DEV_CS_PIN);
    DL_GPIO_enableOutput(GPIOB, GPIO_MOTOR_A_IN1_MOTOR_A_IN1_PIN |
		GPIO_MOTOR_A_IN2_MOTOR_A_IN2_PIN |
		GPIO_MOTOR_B_IN1_MOTOR_B_IN1_PIN |
		GPIO_MOTOR_B_IN2_MOTOR_B_IN2_PIN |
		GPIO_CS_SPI1_DEV_CS_PIN |
		GPIO_US_TRIG_US_TRIG_PIN);
    DL_GPIO_setLowerPinsPolarity(GPIOB, DL_GPIO_PIN_6_EDGE_RISE_FALL |
		DL_GPIO_PIN_7_EDGE_RISE_FALL);
    DL_GPIO_clearInterruptStatus(GPIOB, ENC_MOTOR_B_A_PIN |
		ENC_MOTOR_B_B_PIN);
    DL_GPIO_enableInterrupt(GPIOB, ENC_MOTOR_B_A_PIN |
		ENC_MOTOR_B_B_PIN);

}


SYSCONFIG_WEAK void SYSCFG_DL_SYSCTL_init(void)
{

	//Low Power Mode is configured to be SLEEP0
    DL_SYSCTL_setBORThreshold(DL_SYSCTL_BOR_THRESHOLD_LEVEL_0);

    DL_SYSCTL_setSYSOSCFreq(DL_SYSCTL_SYSOSC_FREQ_BASE);
    /* Set default configuration */
    DL_SYSCTL_disableHFXT();
    DL_SYSCTL_disableSYSPLL();
    DL_SYSCTL_setULPCLKDivider(DL_SYSCTL_ULPCLK_DIV_1);
    DL_SYSCTL_setMCLKDivider(DL_SYSCTL_MCLK_DIVIDER_DISABLE);

}


/*
 * Timer clock configuration to be sourced by  / 1 (32000000 Hz)
 * timerClkFreq = (timerClkSrc / (timerClkDivRatio * (timerClkPrescale + 1)))
 *   32000000 Hz = 32000000 Hz / (1 * (0 + 1))
 */
static const DL_TimerG_ClockConfig gPWM_TIMG0ClockConfig = {
    .clockSel = DL_TIMER_CLOCK_BUSCLK,
    .divideRatio = DL_TIMER_CLOCK_DIVIDE_1,
    .prescale = 0U
};

static const DL_TimerG_PWMConfig gPWM_TIMG0Config = {
    .pwmMode = DL_TIMER_PWM_MODE_EDGE_ALIGN,
    .period = 1600,
    .isTimerWithFourCC = false,
    .startTimer = DL_TIMER_STOP,
};

SYSCONFIG_WEAK void SYSCFG_DL_PWM_TIMG0_init(void) {

    DL_TimerG_setClockConfig(
        PWM_TIMG0_INST, (DL_TimerG_ClockConfig *) &gPWM_TIMG0ClockConfig);

    DL_TimerG_initPWMMode(
        PWM_TIMG0_INST, (DL_TimerG_PWMConfig *) &gPWM_TIMG0Config);

    // Set Counter control to the smallest CC index being used
    DL_TimerG_setCounterControl(PWM_TIMG0_INST,DL_TIMER_CZC_CCCTL0_ZCOND,DL_TIMER_CAC_CCCTL0_ACOND,DL_TIMER_CLC_CCCTL0_LCOND);

    DL_TimerG_setCaptureCompareOutCtl(PWM_TIMG0_INST, DL_TIMER_CC_OCTL_INIT_VAL_LOW,
		DL_TIMER_CC_OCTL_INV_OUT_DISABLED, DL_TIMER_CC_OCTL_SRC_FUNCVAL,
		DL_TIMERG_CAPTURE_COMPARE_0_INDEX);

    DL_TimerG_setCaptCompUpdateMethod(PWM_TIMG0_INST, DL_TIMER_CC_UPDATE_METHOD_IMMEDIATE, DL_TIMERG_CAPTURE_COMPARE_0_INDEX);
    DL_TimerG_setCaptureCompareValue(PWM_TIMG0_INST, 1600, DL_TIMER_CC_0_INDEX);

    DL_TimerG_setCaptureCompareOutCtl(PWM_TIMG0_INST, DL_TIMER_CC_OCTL_INIT_VAL_LOW,
		DL_TIMER_CC_OCTL_INV_OUT_DISABLED, DL_TIMER_CC_OCTL_SRC_FUNCVAL,
		DL_TIMERG_CAPTURE_COMPARE_1_INDEX);

    DL_TimerG_setCaptCompUpdateMethod(PWM_TIMG0_INST, DL_TIMER_CC_UPDATE_METHOD_IMMEDIATE, DL_TIMERG_CAPTURE_COMPARE_1_INDEX);
    DL_TimerG_setCaptureCompareValue(PWM_TIMG0_INST, 1600, DL_TIMER_CC_1_INDEX);

    DL_TimerG_enableClock(PWM_TIMG0_INST);


    
    DL_TimerG_setCCPDirection(PWM_TIMG0_INST , DL_TIMER_CC0_OUTPUT | DL_TIMER_CC1_OUTPUT );


}


static const DL_TimerG_ClockConfig gENC_MOTOR_AClockConfig = {
    .clockSel = DL_TIMER_CLOCK_BUSCLK,
    .divideRatio = DL_TIMER_CLOCK_DIVIDE_1,
    .prescale = 0U
};


SYSCONFIG_WEAK void SYSCFG_DL_ENC_MOTOR_A_init(void) {

    DL_TimerG_setClockConfig(
        ENC_MOTOR_A_INST, (DL_TimerG_ClockConfig *) &gENC_MOTOR_AClockConfig);

    DL_TimerG_configQEI(ENC_MOTOR_A_INST, DL_TIMER_QEI_MODE_2_INPUT,
        DL_TIMER_CC_INPUT_INV_NOINVERT, DL_TIMER_CC_0_INDEX);
    DL_TimerG_configQEI(ENC_MOTOR_A_INST, DL_TIMER_QEI_MODE_2_INPUT,
        DL_TIMER_CC_INPUT_INV_NOINVERT, DL_TIMER_CC_1_INDEX);
    DL_TimerG_setLoadValue(ENC_MOTOR_A_INST, 65535);
    DL_TimerG_enableClock(ENC_MOTOR_A_INST);
}



/*
 * Timer clock configuration to be sourced by BUSCLK /  (32000000 Hz)
 * timerClkFreq = (timerClkSrc / (timerClkDivRatio * (timerClkPrescale + 1)))
 *   1000000 Hz = 32000000 Hz / (1 * (31 + 1))
 */
static const DL_TimerG_ClockConfig gTIMER_CTRLClockConfig = {
    .clockSel    = DL_TIMER_CLOCK_BUSCLK,
    .divideRatio = DL_TIMER_CLOCK_DIVIDE_1,
    .prescale    = 31U,
};

/*
 * Timer load value (where the counter starts from) is calculated as (timerPeriod * timerClockFreq) - 1
 * TIMER_CTRL_INST_LOAD_VALUE = (1 ms * 1000000 Hz) - 1
 */
static const DL_TimerG_TimerConfig gTIMER_CTRLTimerConfig = {
    .period     = TIMER_CTRL_INST_LOAD_VALUE,
    .timerMode  = DL_TIMER_TIMER_MODE_PERIODIC,
    .startTimer = DL_TIMER_STOP,
};

SYSCONFIG_WEAK void SYSCFG_DL_TIMER_CTRL_init(void) {

    DL_TimerG_setClockConfig(TIMER_CTRL_INST,
        (DL_TimerG_ClockConfig *) &gTIMER_CTRLClockConfig);

    DL_TimerG_initTimerMode(TIMER_CTRL_INST,
        (DL_TimerG_TimerConfig *) &gTIMER_CTRLTimerConfig);
    DL_TimerG_enableInterrupt(TIMER_CTRL_INST , DL_TIMERG_INTERRUPT_ZERO_EVENT);
    DL_TimerG_enableClock(TIMER_CTRL_INST);





}


static const DL_I2C_ClockConfig gI2C_IMUClockConfig = {
    .clockSel = DL_I2C_CLOCK_BUSCLK,
    .divideRatio = DL_I2C_CLOCK_DIVIDE_1,
};

SYSCONFIG_WEAK void SYSCFG_DL_I2C_IMU_init(void) {

    DL_I2C_setClockConfig(I2C_IMU_INST,
        (DL_I2C_ClockConfig *) &gI2C_IMUClockConfig);
    DL_I2C_setAnalogGlitchFilterPulseWidth(I2C_IMU_INST,
        DL_I2C_ANALOG_GLITCH_FILTER_WIDTH_50NS);
    DL_I2C_enableAnalogGlitchFilter(I2C_IMU_INST);

    /* Configure Controller Mode */
    DL_I2C_resetControllerTransfer(I2C_IMU_INST);
    /* Set frequency to 400000 Hz*/
    DL_I2C_setTimerPeriod(I2C_IMU_INST, 7);
    DL_I2C_setControllerTXFIFOThreshold(I2C_IMU_INST, DL_I2C_TX_FIFO_LEVEL_EMPTY);
    DL_I2C_setControllerRXFIFOThreshold(I2C_IMU_INST, DL_I2C_RX_FIFO_LEVEL_BYTES_1);
    DL_I2C_enableControllerClockStretching(I2C_IMU_INST);


    /* Enable module */
    DL_I2C_enableController(I2C_IMU_INST);


}

static const DL_UART_Main_ClockConfig gUART_LINKClockConfig = {
    .clockSel    = DL_UART_MAIN_CLOCK_BUSCLK,
    .divideRatio = DL_UART_MAIN_CLOCK_DIVIDE_RATIO_1
};

static const DL_UART_Main_Config gUART_LINKConfig = {
    .mode        = DL_UART_MAIN_MODE_NORMAL,
    .direction   = DL_UART_MAIN_DIRECTION_TX_RX,
    .flowControl = DL_UART_MAIN_FLOW_CONTROL_NONE,
    .parity      = DL_UART_MAIN_PARITY_NONE,
    .wordLength  = DL_UART_MAIN_WORD_LENGTH_8_BITS,
    .stopBits    = DL_UART_MAIN_STOP_BITS_ONE
};

SYSCONFIG_WEAK void SYSCFG_DL_UART_LINK_init(void)
{
    DL_UART_Main_setClockConfig(UART_LINK_INST, (DL_UART_Main_ClockConfig *) &gUART_LINKClockConfig);

    DL_UART_Main_init(UART_LINK_INST, (DL_UART_Main_Config *) &gUART_LINKConfig);
    /*
     * Configure baud rate by setting oversampling and baud rate divisors.
     *  Target baud rate: 115200
     *  Actual baud rate: 115211.52
     */
    DL_UART_Main_setOversampling(UART_LINK_INST, DL_UART_OVERSAMPLING_RATE_16X);
    DL_UART_Main_setBaudRateDivisor(UART_LINK_INST, UART_LINK_IBRD_32_MHZ_115200_BAUD, UART_LINK_FBRD_32_MHZ_115200_BAUD);


    /* Configure Interrupts */
    DL_UART_Main_enableInterrupt(UART_LINK_INST,
                                 DL_UART_MAIN_INTERRUPT_RX);


    DL_UART_Main_enable(UART_LINK_INST);
}
static const DL_UART_Main_ClockConfig gUART_IMUClockConfig = {
    .clockSel    = DL_UART_MAIN_CLOCK_BUSCLK,
    .divideRatio = DL_UART_MAIN_CLOCK_DIVIDE_RATIO_1
};

static const DL_UART_Main_Config gUART_IMUConfig = {
    .mode        = DL_UART_MAIN_MODE_NORMAL,
    .direction   = DL_UART_MAIN_DIRECTION_TX_RX,
    .flowControl = DL_UART_MAIN_FLOW_CONTROL_NONE,
    .parity      = DL_UART_MAIN_PARITY_NONE,
    .wordLength  = DL_UART_MAIN_WORD_LENGTH_8_BITS,
    .stopBits    = DL_UART_MAIN_STOP_BITS_ONE
};

SYSCONFIG_WEAK void SYSCFG_DL_UART_IMU_init(void)
{
    DL_UART_Main_setClockConfig(UART_IMU_INST, (DL_UART_Main_ClockConfig *) &gUART_IMUClockConfig);

    DL_UART_Main_init(UART_IMU_INST, (DL_UART_Main_Config *) &gUART_IMUConfig);
    /*
     * Configure baud rate by setting oversampling and baud rate divisors.
     *  Target baud rate: 460800
     *  Actual baud rate: 460431.65
     */
    DL_UART_Main_setOversampling(UART_IMU_INST, DL_UART_OVERSAMPLING_RATE_16X);
    DL_UART_Main_setBaudRateDivisor(UART_IMU_INST, UART_IMU_IBRD_32_MHZ_460800_BAUD, UART_IMU_FBRD_32_MHZ_460800_BAUD);


    /* Configure Interrupts */
    DL_UART_Main_enableInterrupt(UART_IMU_INST,
                                 DL_UART_MAIN_INTERRUPT_RX);


    DL_UART_Main_enable(UART_IMU_INST);
}

static const DL_SPI_Config gSPI_BUS1_config = {
    .mode        = DL_SPI_MODE_CONTROLLER,
    .frameFormat = DL_SPI_FRAME_FORMAT_MOTO3_POL1_PHA1,
    .parity      = DL_SPI_PARITY_NONE,
    .dataSize    = DL_SPI_DATA_SIZE_8,
    .bitOrder    = DL_SPI_BIT_ORDER_MSB_FIRST,
};

static const DL_SPI_ClockConfig gSPI_BUS1_clockConfig = {
    .clockSel    = DL_SPI_CLOCK_BUSCLK,
    .divideRatio = DL_SPI_CLOCK_DIVIDE_RATIO_1
};

SYSCONFIG_WEAK void SYSCFG_DL_SPI_BUS1_init(void) {
    DL_SPI_setClockConfig(SPI_BUS1_INST, (DL_SPI_ClockConfig *) &gSPI_BUS1_clockConfig);

    DL_SPI_init(SPI_BUS1_INST, (DL_SPI_Config *) &gSPI_BUS1_config);

    /* Configure Controller mode */
    /*
     * Set the bit rate clock divider to generate the serial output clock
     *     outputBitRate = (spiInputClock) / ((1 + SCR) * 2)
     *     1000000 = (32000000)/((1 + 15) * 2)
     */
    DL_SPI_setBitRateSerialClockDivider(SPI_BUS1_INST, 15);
    /* Set RX and TX FIFO threshold levels */
    DL_SPI_setFIFOThreshold(SPI_BUS1_INST, DL_SPI_RX_FIFO_LEVEL_1_2_FULL, DL_SPI_TX_FIFO_LEVEL_1_2_EMPTY);

    /* Enable module */
    DL_SPI_enable(SPI_BUS1_INST);
}

/* ADC12_0 Initialization */
static const DL_ADC12_ClockConfig gADC12_0ClockConfig = {
    .clockSel       = DL_ADC12_CLOCK_SYSOSC,
    .divideRatio    = DL_ADC12_CLOCK_DIVIDE_1,
    .freqRange      = DL_ADC12_CLOCK_FREQ_RANGE_24_TO_32,
};
SYSCONFIG_WEAK void SYSCFG_DL_ADC12_0_init(void)
{
    DL_ADC12_setClockConfig(ADC12_0_INST, (DL_ADC12_ClockConfig *) &gADC12_0ClockConfig);
    DL_ADC12_configConversionMem(ADC12_0_INST, ADC12_0_ADCMEM_0,
        DL_ADC12_INPUT_CHAN_2, DL_ADC12_REFERENCE_VOLTAGE_VDDA, DL_ADC12_SAMPLE_TIMER_SOURCE_SCOMP0, DL_ADC12_AVERAGING_MODE_DISABLED,
        DL_ADC12_BURN_OUT_SOURCE_DISABLED, DL_ADC12_TRIGGER_MODE_AUTO_NEXT, DL_ADC12_WINDOWS_COMP_MODE_DISABLED);
    DL_ADC12_enableConversions(ADC12_0_INST);
}

