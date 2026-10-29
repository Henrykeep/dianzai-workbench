#include <ti/driverlib/dl_timer.h>
void f(void) {
    DL_Timer_setCaptureCompareValue(TIMG0, 100u, DL_TIMER_CC_0_INDEX);
    DL_TimerA_setCaptureCompareValue(TIMA0, DL_TIMER_CC_1_INDEX, 100u);
}
