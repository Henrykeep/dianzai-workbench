/*
 * OLED 适配层只连接 OLEDDisplay 和通用 DisplayMenu，避免为不同屏幕复制页面逻辑。
 */
#include "application/menu/oled_menu/oled_menu.h"

#include "application/menu/display_menu/display_menu.h"
#include "modules/oled/oled_display.h"

/* OLED 后端只负责初始化屏幕，页面和按键逻辑由通用菜单实现。 */
bool OLEDMenuInit(void)
{
    if (!OLEDDisplayInit()) {
        return false;
    }
    return DisplayMenuInit(OLEDDisplayGetMenuDisplay());
}

bool OLEDMenuSubmitADCWaveformSample(int16_t sample)
{
    return DisplayMenuSubmitADCWaveformSample(sample);
}

bool OLEDMenuSubmitUART2WaveformSample(int16_t sample)
{
    return DisplayMenuSubmitUART2WaveformSample(sample);
}
