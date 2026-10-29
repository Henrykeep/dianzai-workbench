#include "tt.h"
int tt_fail, tt_pass;
void suite_lpf(void); void suite_pid(void); void suite_drivers(void); void suite_sim(void); void suite_dzrtt(void);
void suite_framework(void);
void suite_ctrlparts(void); void suite_dzframe(void); void suite_modules(void); void suite_vision(void); void suite_imu(void); void suite_modlib(void); void suite_signal(void);
int main(void)
{
    suite_lpf(); suite_dzrtt(); suite_pid(); suite_drivers(); suite_sim(); suite_framework();
    suite_dzframe(); suite_modules(); suite_vision(); suite_imu(); suite_modlib(); suite_ctrlparts(); suite_signal();
    printf("\n通过 %d，失败 %d\n", tt_pass, tt_fail);
    return tt_fail ? 1 : 0;
}
