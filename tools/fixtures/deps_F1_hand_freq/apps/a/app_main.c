#define CTRL_PERIOD_US 1000u
#define PWM_HZ 20000u  /* DZ-FREQ-OK: PWM 载波，不是控制频率 */
#define LOOP_HZ 100
float dt(void) { return CTRL_PERIOD_US * 1e-6f; }
