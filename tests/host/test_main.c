#include "tt.h"
int tt_fail, tt_pass;
void suite_lpf(void); void suite_pid(void); void suite_drivers(void); void suite_sim(void);
void suite_framework(void);
void suite_dzframe(void);
int main(void)
{
    suite_lpf(); suite_pid(); suite_drivers(); suite_sim(); suite_framework();
    suite_dzframe();
    printf("\n通过 %d，失败 %d\n", tt_pass, tt_fail);
    return tt_fail ? 1 : 0;
}
