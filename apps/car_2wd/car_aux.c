#include "car_aux.h"
#include "board_gen.h"
#include "pal.h"
#include "battery.h"
#include "hcsr04.h"

#ifdef RES_ADC_VBAT
static battery_t s_bat;
#endif
#if defined(RES_GPIO_US_TRIG) && defined(RES_GPIO_US_ECHO)
#define CAR_AUX_US 1
static hcsr04_t s_us;
#endif

dz_err_t car_aux_init(void)
{
    dz_err_t e = DZ_OK;
#ifdef RES_ADC_VBAT
    battery_cfg_t bc = battery_cfg_default(RES_ADC_VBAT);   /* 分压比用 board.yaml 的 scale_num/den */
    bc.cells = 2u;
    if ((e = battery_init(&s_bat, &bc)) != DZ_OK) return e;
#endif
#ifdef CAR_AUX_US
    hcsr04_cfg_t uc = hcsr04_cfg_default(RES_GPIO_US_TRIG, RES_GPIO_US_ECHO);
    if ((e = hcsr04_init(&s_us, &uc)) != DZ_OK) return e;
    (void)hcsr04_attach_irq(&s_us);   /* DZ_ENOTSUP 等：留在轮询模式 */
#endif
    return e;
}

bool car_aux_poll(uint32_t now_ms)
{
    bool estop = false;
#ifdef RES_ADC_VBAT
    static uint32_t last_bat;
    if (now_ms - last_bat >= 50u) {
        last_bat = now_ms;
        /* 只有先见过 OK 再掉到 CRIT 才急停：VBAT 脚没接分压（悬空）时读数乱跳，不能一上电就锁死小车 */
        static bool seen_ok;
        if (battery_update(&s_bat, now_ms) == DZ_OK) {
            battery_state_t st = battery_state(&s_bat);
            if (st == BAT_OK) seen_ok = true;
            if (seen_ok && st == BAT_CRIT) estop = true;
        }
    }
#endif
#ifdef CAR_AUX_US
    (void)hcsr04_update(&s_us, now_ms, pal_micros(), true);
#endif
    (void)now_ms;
    return estop;
}

float car_aux_limit_v(float v)
{
#ifdef CAR_AUX_US
    if (v > 0.0f && hcsr04_valid(&s_us) && hcsr04_mm(&s_us) < CAR_AUX_STOP_MM) return 0.0f;
#endif
    return v;
}
