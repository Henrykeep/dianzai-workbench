/*
 * TFT 适配层只连接 TFTDisplay 和通用 DisplayMenu；分辨率差异由显示实例处理。
 */
#include "application/menu/tft_menu/tft_menu.h"

#include "application/menu/display_menu/display_menu.h"
#include "modules/tft/tft_display.h"

/* TFT 后端只负责初始化屏幕，页面和按键逻辑复用通用菜单。 */
bool TFTMenuInit(void)
{
    if (!TFTDisplayInit()) {
        return false;
    }
    return DisplayMenuInit(TFTDisplayGetMenuDisplay());
}

bool TFTMenuSubmitADCWaveformSample(int16_t sample)
{
    return DisplayMenuSubmitADCWaveformSample(sample);
}

bool TFTMenuSubmitUART2WaveformSample(int16_t sample)
{
    return DisplayMenuSubmitUART2WaveformSample(sample);
}
