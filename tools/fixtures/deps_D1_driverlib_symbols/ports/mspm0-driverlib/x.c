#include "ti_msp_dl_config.h"
#define PWM_MOTOR_INST TIMA1
void f(void) {
    DL_GPIO_setDirection(GPIOA, 1);
    DL_TimerG_setCaptureCompareValue(PWM_MOTOR_INST, 10, 0);
    DL_TimerA_setCaptureCompareValue(PWM_MOTOR_INST, 10, 0);
}
