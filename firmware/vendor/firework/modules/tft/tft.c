/*
 * TFT Module 驱动 ST7735S，并把 128×64 单色逻辑帧缓冲缩放到 128×160 彩色面板。
 */
#include "modules/tft/tft.h"

#include <stddef.h>
#include <string.h>

#include "bsp/bsp.h"
#include "bsp/gpio/bsp_gpio.h"
#include "modules/spi/spi.h"

#define TFT_PAGE_COUNT              (DISPLAY_HEIGHT / 8U)
#define TFT_FRAME_BUFFER_SIZE       (DISPLAY_WIDTH * TFT_PAGE_COUNT)
#define TFT_SCANLINE_BUFFER_SIZE    (TFT_PHYSICAL_WIDTH * 2U)
#define TFT_VERTICAL_SCALE          (2U)
#define TFT_LOGICAL_TOP             ((TFT_PHYSICAL_HEIGHT - \
                                         (DISPLAY_HEIGHT * TFT_VERTICAL_SCALE)) / \
                                    2U)
#define TFT_FONT_FIRST_CHARACTER    (32U)
#define TFT_FONT_LAST_CHARACTER     (127U)
#define TFT_FONT_WIDTH              (5U)
#define TFT_FONT_HEIGHT             (7U)
#define TFT_CHARACTER_ADVANCE       (6U)
#define TFT_LINE_ADVANCE            (8U)

/* ST7735S command set used by common 1.8-inch 128×160 modules. */
#define TFT_COMMAND_SWRESET (0x01U)
#define TFT_COMMAND_SLPIN   (0x10U)
#define TFT_COMMAND_SLPOUT  (0x11U)
#define TFT_COMMAND_NORON   (0x13U)
#define TFT_COMMAND_INVOFF  (0x20U)
#define TFT_COMMAND_INVON   (0x21U)
#define TFT_COMMAND_DISPOFF (0x28U)
#define TFT_COMMAND_DISPON  (0x29U)
#define TFT_COMMAND_CASET   (0x2AU)
#define TFT_COMMAND_RASET   (0x2BU)
#define TFT_COMMAND_RAMWR   (0x2CU)
#define TFT_COMMAND_MADCTL  (0x36U)
#define TFT_COMMAND_COLMOD  (0x3AU)
#define TFT_COMMAND_FRMCTR1 (0xB1U)
#define TFT_COMMAND_FRMCTR2 (0xB2U)
#define TFT_COMMAND_FRMCTR3 (0xB3U)
#define TFT_COMMAND_INVCTR  (0xB4U)
#define TFT_COMMAND_PWCTR1  (0xC0U)
#define TFT_COMMAND_PWCTR2  (0xC1U)
#define TFT_COMMAND_PWCTR3  (0xC2U)
#define TFT_COMMAND_PWCTR4  (0xC3U)
#define TFT_COMMAND_PWCTR5  (0xC4U)
#define TFT_COMMAND_VMCTR1  (0xC5U)
#define TFT_COMMAND_GMCTRP1 (0xE0U)
#define TFT_COMMAND_GMCTRN1 (0xE1U)

struct TFTInstance {
    SPIInstance *spi;
    BSPGPIOInstance *data_command;
    BSPGPIOInstance *reset;
    /* 与 OLED 相同的 128×64、1 bit/pixel 页式画布。 */
    uint8_t frame_buffer[TFT_FRAME_BUFFER_SIZE];
    /* 一行 RGB565 转换缓冲，避免申请 128×160×2 整屏显存。 */
    uint8_t scanline_buffer[TFT_SCANLINE_BUFFER_SIZE];
    uint16_t foreground_color;
    bool registered;
    bool initialized;
};

static TFTInstance tft_instance;

/* 5×7 ASCII 字体；字节表示一列，最低位对应字符顶部像素。 */
static const uint8_t tft_font_5x7[96][TFT_FONT_WIDTH] = {
    {0x00,0x00,0x00,0x00,0x00},{0x00,0x00,0x5F,0x00,0x00},
    {0x00,0x07,0x00,0x07,0x00},{0x14,0x7F,0x14,0x7F,0x14},
    {0x24,0x2A,0x7F,0x2A,0x12},{0x23,0x13,0x08,0x64,0x62},
    {0x36,0x49,0x55,0x22,0x50},{0x00,0x05,0x03,0x00,0x00},
    {0x00,0x1C,0x22,0x41,0x00},{0x00,0x41,0x22,0x1C,0x00},
    {0x14,0x08,0x3E,0x08,0x14},{0x08,0x08,0x3E,0x08,0x08},
    {0x00,0x50,0x30,0x00,0x00},{0x08,0x08,0x08,0x08,0x08},
    {0x00,0x60,0x60,0x00,0x00},{0x20,0x10,0x08,0x04,0x02},
    {0x3E,0x51,0x49,0x45,0x3E},{0x00,0x42,0x7F,0x40,0x00},
    {0x42,0x61,0x51,0x49,0x46},{0x21,0x41,0x45,0x4B,0x31},
    {0x18,0x14,0x12,0x7F,0x10},{0x27,0x45,0x45,0x45,0x39},
    {0x3C,0x4A,0x49,0x49,0x30},{0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36},{0x06,0x49,0x49,0x29,0x1E},
    {0x00,0x36,0x36,0x00,0x00},{0x00,0x56,0x36,0x00,0x00},
    {0x08,0x14,0x22,0x41,0x00},{0x14,0x14,0x14,0x14,0x14},
    {0x00,0x41,0x22,0x14,0x08},{0x02,0x01,0x51,0x09,0x06},
    {0x32,0x49,0x79,0x41,0x3E},{0x7E,0x11,0x11,0x11,0x7E},
    {0x7F,0x49,0x49,0x49,0x36},{0x3E,0x41,0x41,0x41,0x22},
    {0x7F,0x41,0x41,0x22,0x1C},{0x7F,0x49,0x49,0x49,0x41},
    {0x7F,0x09,0x09,0x09,0x01},{0x3E,0x41,0x49,0x49,0x7A},
    {0x7F,0x08,0x08,0x08,0x7F},{0x00,0x41,0x7F,0x41,0x00},
    {0x20,0x40,0x41,0x3F,0x01},{0x7F,0x08,0x14,0x22,0x41},
    {0x7F,0x40,0x40,0x40,0x40},{0x7F,0x02,0x0C,0x02,0x7F},
    {0x7F,0x04,0x08,0x10,0x7F},{0x3E,0x41,0x41,0x41,0x3E},
    {0x7F,0x09,0x09,0x09,0x06},{0x3E,0x41,0x51,0x21,0x5E},
    {0x7F,0x09,0x19,0x29,0x46},{0x46,0x49,0x49,0x49,0x31},
    {0x01,0x01,0x7F,0x01,0x01},{0x3F,0x40,0x40,0x40,0x3F},
    {0x1F,0x20,0x40,0x20,0x1F},{0x3F,0x40,0x38,0x40,0x3F},
    {0x63,0x14,0x08,0x14,0x63},{0x07,0x08,0x70,0x08,0x07},
    {0x61,0x51,0x49,0x45,0x43},{0x00,0x7F,0x41,0x41,0x00},
    {0x02,0x04,0x08,0x10,0x20},{0x00,0x41,0x41,0x7F,0x00},
    {0x04,0x02,0x01,0x02,0x04},{0x40,0x40,0x40,0x40,0x40},
    {0x00,0x01,0x02,0x04,0x00},{0x20,0x54,0x54,0x54,0x78},
    {0x7F,0x48,0x44,0x44,0x38},{0x38,0x44,0x44,0x44,0x20},
    {0x38,0x44,0x44,0x48,0x7F},{0x38,0x54,0x54,0x54,0x18},
    {0x08,0x7E,0x09,0x01,0x02},{0x0C,0x52,0x52,0x52,0x3E},
    {0x7F,0x08,0x04,0x04,0x78},{0x00,0x44,0x7D,0x40,0x00},
    {0x20,0x40,0x44,0x3D,0x00},{0x7F,0x10,0x28,0x44,0x00},
    {0x00,0x41,0x7F,0x40,0x00},{0x7C,0x04,0x18,0x04,0x78},
    {0x7C,0x08,0x04,0x04,0x78},{0x38,0x44,0x44,0x44,0x38},
    {0x7C,0x14,0x14,0x14,0x08},{0x08,0x14,0x14,0x18,0x7C},
    {0x7C,0x08,0x04,0x04,0x08},{0x48,0x54,0x54,0x54,0x20},
    {0x04,0x3F,0x44,0x40,0x20},{0x3C,0x40,0x40,0x20,0x7C},
    {0x1C,0x20,0x40,0x20,0x1C},{0x3C,0x40,0x30,0x40,0x3C},
    {0x44,0x28,0x10,0x28,0x44},{0x0C,0x50,0x50,0x50,0x3C},
    {0x44,0x64,0x54,0x4C,0x44},{0x00,0x08,0x36,0x41,0x00},
    {0x00,0x00,0x7F,0x00,0x00},{0x00,0x41,0x36,0x08,0x00},
    {0x08,0x04,0x08,0x10,0x08},{0x00,0x06,0x09,0x09,0x06}
};

static bool TFTIsRegistered(const TFTInstance *instance);
static bool TFTIsReady(const TFTInstance *instance);
static bool TFTWriteCommand(TFTInstance *instance, uint8_t command);
static bool TFTWriteData(
    TFTInstance *instance, const uint8_t *data, size_t size);
static bool TFTWriteCommandData(TFTInstance *instance,
    uint8_t command, const uint8_t *data, size_t size);
static bool TFTSetAddressWindow(TFTInstance *instance,
    uint16_t x_start, uint16_t y_start,
    uint16_t x_end, uint16_t y_end);
static bool TFTFillPhysicalScreen(TFTInstance *instance, uint16_t color);
static void TFTBuildLogicalScanline(TFTInstance *instance, uint8_t y);

TFTInstance *TFTRegister(void)
{
    if (tft_instance.registered) {
        return &tft_instance;
    }

    tft_instance.spi = SPIRegister(SPI_DEVICE_TFT_0);
    tft_instance.data_command =
        BSPGPIORegister(BSP_GPIO_CHANNEL_TFT_DC);
    tft_instance.reset =
        BSPGPIORegister(BSP_GPIO_CHANNEL_TFT_RESET);
    if ((tft_instance.spi == NULL) ||
        (tft_instance.data_command == NULL) ||
        (tft_instance.reset == NULL)) {
        return NULL;
    }

    tft_instance.foreground_color = 0xFFFFU;
    tft_instance.registered       = true;
    return &tft_instance;
}

bool TFTInitialize(TFTInstance *instance)
{
    static const uint8_t frame_rate[] = {0x01U, 0x2CU, 0x2DU};
    static const uint8_t frame_rate_3[] = {
        0x01U, 0x2CU, 0x2DU, 0x01U, 0x2CU, 0x2DU
    };
    static const uint8_t power_1[] = {0xA2U, 0x02U, 0x84U};
    static const uint8_t power_3[] = {0x0AU, 0x00U};
    static const uint8_t power_4[] = {0x8AU, 0x2AU};
    static const uint8_t power_5[] = {0x8AU, 0xEEU};
    static const uint8_t gamma_positive[] = {
        0x02U,0x1CU,0x07U,0x12U,0x37U,0x32U,0x29U,0x2DU,
        0x29U,0x25U,0x2BU,0x39U,0x00U,0x01U,0x03U,0x10U
    };
    static const uint8_t gamma_negative[] = {
        0x03U,0x1DU,0x07U,0x06U,0x2EU,0x2CU,0x29U,0x2DU,
        0x2EU,0x2EU,0x37U,0x3FU,0x00U,0x00U,0x02U,0x10U
    };
    static const uint8_t inversion_control[] = {0x07U};
    static const uint8_t power_2[] = {0xC5U};
    static const uint8_t vcom[] = {0x0EU};
    static const uint8_t memory_access[] = {0xC8U};
    static const uint8_t pixel_format[] = {0x05U};

    if (!TFTIsRegistered(instance)) {
        return false;
    }
    instance->initialized = false;

    (void)BSPGPIOWrite(instance->data_command, false);
    (void)BSPGPIOWrite(instance->reset, true);
    BSPDelayMilliseconds(5U);
    (void)BSPGPIOWrite(instance->reset, false);
    BSPDelayMilliseconds(20U);
    (void)BSPGPIOWrite(instance->reset, true);
    BSPDelayMilliseconds(150U);

    if (!TFTWriteCommand(instance, TFT_COMMAND_SWRESET)) {
        return false;
    }
    BSPDelayMilliseconds(150U);
    if (!TFTWriteCommand(instance, TFT_COMMAND_SLPOUT)) {
        return false;
    }
    BSPDelayMilliseconds(120U);

    if (!TFTWriteCommandData(instance, TFT_COMMAND_FRMCTR1,
            frame_rate, sizeof(frame_rate)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_FRMCTR2,
            frame_rate, sizeof(frame_rate)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_FRMCTR3,
            frame_rate_3, sizeof(frame_rate_3)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_INVCTR,
            inversion_control, sizeof(inversion_control)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_PWCTR1,
            power_1, sizeof(power_1)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_PWCTR2,
            power_2, sizeof(power_2)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_PWCTR3,
            power_3, sizeof(power_3)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_PWCTR4,
            power_4, sizeof(power_4)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_PWCTR5,
            power_5, sizeof(power_5)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_VMCTR1,
            vcom, sizeof(vcom)) ||
        !TFTWriteCommand(instance, TFT_COMMAND_INVOFF) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_MADCTL,
            memory_access, sizeof(memory_access)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_COLMOD,
            pixel_format, sizeof(pixel_format)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_GMCTRP1,
            gamma_positive, sizeof(gamma_positive)) ||
        !TFTWriteCommandData(instance, TFT_COMMAND_GMCTRN1,
            gamma_negative, sizeof(gamma_negative)) ||
        !TFTWriteCommand(instance, TFT_COMMAND_NORON)) {
        return false;
    }
    BSPDelayMilliseconds(10U);

    instance->initialized = true;
    memset(instance->frame_buffer, 0, sizeof(instance->frame_buffer));
    if (!TFTFillPhysicalScreen(instance, 0x0000U) ||
        !TFTWriteCommand(instance, TFT_COMMAND_DISPON)) {
        instance->initialized = false;
        return false;
    }
    BSPDelayMilliseconds(100U);
    return true;
}

bool TFTClear(TFTInstance *instance, bool pixels_on)
{
    if (!TFTIsReady(instance)) {
        return false;
    }
    memset(instance->frame_buffer,
        pixels_on ? 0xFF : 0x00, sizeof(instance->frame_buffer));
    return true;
}

bool TFTSetPixel(TFTInstance *instance,
    uint8_t x, uint8_t y, bool pixel_on)
{
    size_t index;
    uint8_t mask;

    if (!TFTIsReady(instance) ||
        (x >= DISPLAY_WIDTH) || (y >= DISPLAY_HEIGHT)) {
        return false;
    }
    index = (size_t)x + ((size_t)(y / 8U) * DISPLAY_WIDTH);
    mask  = (uint8_t)(1U << (y & 0x07U));
    if (pixel_on) {
        instance->frame_buffer[index] |= mask;
    } else {
        instance->frame_buffer[index] &= (uint8_t)~mask;
    }
    return true;
}

bool TFTDrawCharacter(TFTInstance *instance,
    uint8_t x, uint8_t y, char character)
{
    uint8_t column;
    uint8_t row;
    uint8_t character_index;

    if (!TFTIsReady(instance) ||
        (x >= DISPLAY_WIDTH) || (y >= DISPLAY_HEIGHT)) {
        return false;
    }
    if (((uint8_t)character < TFT_FONT_FIRST_CHARACTER) ||
        ((uint8_t)character > TFT_FONT_LAST_CHARACTER)) {
        character = '?';
    }
    character_index = (uint8_t)character - TFT_FONT_FIRST_CHARACTER;

    for (column = 0U; column < TFT_CHARACTER_ADVANCE; ++column) {
        uint8_t column_bits = (column < TFT_FONT_WIDTH)
                                  ? tft_font_5x7[character_index][column]
                                  : 0U;
        for (row = 0U; row < TFT_FONT_HEIGHT; ++row) {
            uint16_t pixel_x = (uint16_t)x + column;
            uint16_t pixel_y = (uint16_t)y + row;

            if ((pixel_x < DISPLAY_WIDTH) &&
                (pixel_y < DISPLAY_HEIGHT)) {
                (void)TFTSetPixel(instance, (uint8_t)pixel_x,
                    (uint8_t)pixel_y,
                    (column_bits & (uint8_t)(1U << row)) != 0U);
            }
        }
    }
    return true;
}

bool TFTDrawString(TFTInstance *instance,
    uint8_t x, uint8_t y, const char *text)
{
    uint8_t cursor_x = x;
    uint8_t cursor_y = y;

    if (!TFTIsReady(instance) || (text == NULL) ||
        (x >= DISPLAY_WIDTH) || (y >= DISPLAY_HEIGHT)) {
        return false;
    }
    while (*text != '\0') {
        if (*text == '\n') {
            cursor_x = 0U;
            cursor_y = (uint8_t)(cursor_y + TFT_LINE_ADVANCE);
            ++text;
            continue;
        }
        if ((uint16_t)cursor_x + TFT_CHARACTER_ADVANCE > DISPLAY_WIDTH) {
            cursor_x = 0U;
            cursor_y = (uint8_t)(cursor_y + TFT_LINE_ADVANCE);
        }
        if ((uint16_t)cursor_y + TFT_FONT_HEIGHT > DISPLAY_HEIGHT) {
            break;
        }
        (void)TFTDrawCharacter(instance, cursor_x, cursor_y, *text);
        cursor_x = (uint8_t)(cursor_x + TFT_CHARACTER_ADVANCE);
        ++text;
    }
    return true;
}

bool TFTUpdate(TFTInstance *instance)
{
    return TFTUpdatePages(instance, 0U, TFT_PAGE_COUNT);
}

bool TFTUpdatePages(TFTInstance *instance,
    uint8_t first_page, uint8_t page_count)
{
    uint8_t logical_y;
    uint8_t last_y;
    uint16_t physical_first_y;
    uint16_t physical_last_y;

    if (!TFTIsReady(instance) || (page_count == 0U) ||
        (first_page >= TFT_PAGE_COUNT) ||
        ((uint16_t)first_page + page_count > TFT_PAGE_COUNT)) {
        return false;
    }

    logical_y = (uint8_t)(first_page * 8U);
    last_y = (uint8_t)(logical_y + (page_count * 8U));
    physical_first_y = (uint16_t)TFT_LOGICAL_TOP +
                       ((uint16_t)logical_y * TFT_VERTICAL_SCALE);
    physical_last_y = (uint16_t)TFT_LOGICAL_TOP +
                      ((uint16_t)last_y * TFT_VERTICAL_SCALE) - 1U;

    /*
     * 一次设置整段地址窗口并只发送一次 RAMWR。ST7735S 会在后续数据块间
     * 保持 GRAM 写指针，避免每条物理扫描线重复发送 CASET/RASET/RAMWR。
     */
    if (!TFTSetAddressWindow(instance, 0U, physical_first_y,
            TFT_PHYSICAL_WIDTH - 1U, physical_last_y) ||
        !TFTWriteCommand(instance, TFT_COMMAND_RAMWR)) {
        return false;
    }
    for (; logical_y < last_y; ++logical_y) {
        uint8_t repeat;

        TFTBuildLogicalScanline(instance, logical_y);
        for (repeat = 0U; repeat < TFT_VERTICAL_SCALE; ++repeat) {
            if (!TFTWriteData(instance, instance->scanline_buffer,
                    sizeof(instance->scanline_buffer))) {
                return false;
            }
        }
    }
    return true;
}

bool TFTSetDisplayEnabled(TFTInstance *instance, bool enabled)
{
    if (!TFTIsReady(instance)) {
        return false;
    }
    return TFTWriteCommand(instance,
        enabled ? TFT_COMMAND_DISPON : TFT_COMMAND_DISPOFF);
}

bool TFTSetInverted(TFTInstance *instance, bool inverted)
{
    if (!TFTIsReady(instance)) {
        return false;
    }
    return TFTWriteCommand(instance,
        inverted ? TFT_COMMAND_INVON : TFT_COMMAND_INVOFF);
}

bool TFTSetContrast(TFTInstance *instance, uint8_t contrast)
{
    uint16_t red;
    uint16_t green;
    uint16_t blue;

    if (!TFTIsReady(instance)) {
        return false;
    }
    red   = (uint16_t)(contrast >> 3U);
    green = (uint16_t)(contrast >> 2U);
    blue  = (uint16_t)(contrast >> 3U);
    instance->foreground_color =
        (uint16_t)((red << 11U) | (green << 5U) | blue);
    return true;
}

static bool TFTIsRegistered(const TFTInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->spi != NULL) &&
           (instance->data_command != NULL) &&
           (instance->reset != NULL);
}

static bool TFTIsReady(const TFTInstance *instance)
{
    return TFTIsRegistered(instance) && instance->initialized;
}

static bool TFTWriteCommand(TFTInstance *instance, uint8_t command)
{
    return TFTIsRegistered(instance) &&
           BSPGPIOWrite(instance->data_command, false) &&
           SPIWrite8(instance->spi, &command, 1U);
}

static bool TFTWriteData(
    TFTInstance *instance, const uint8_t *data, size_t size)
{
    return TFTIsRegistered(instance) && (data != NULL) && (size > 0U) &&
           BSPGPIOWrite(instance->data_command, true) &&
           SPIWrite8(instance->spi, data, size);
}

static bool TFTWriteCommandData(TFTInstance *instance,
    uint8_t command, const uint8_t *data, size_t size)
{
    return TFTWriteCommand(instance, command) &&
           TFTWriteData(instance, data, size);
}

static bool TFTSetAddressWindow(TFTInstance *instance,
    uint16_t x_start, uint16_t y_start,
    uint16_t x_end, uint16_t y_end)
{
    uint8_t columns[4];
    uint8_t rows[4];

    /* 把画布坐标换算为控制器 GRAM 坐标，避开面板外的隐藏行列。 */
    x_start = (uint16_t)(x_start + TFT_RAM_COLUMN_OFFSET);
    x_end   = (uint16_t)(x_end + TFT_RAM_COLUMN_OFFSET);
    y_start = (uint16_t)(y_start + TFT_RAM_ROW_OFFSET);
    y_end   = (uint16_t)(y_end + TFT_RAM_ROW_OFFSET);
    columns[0] = (uint8_t)(x_start >> 8U);
    columns[1] = (uint8_t)x_start;
    columns[2] = (uint8_t)(x_end >> 8U);
    columns[3] = (uint8_t)x_end;
    rows[0] = (uint8_t)(y_start >> 8U);
    rows[1] = (uint8_t)y_start;
    rows[2] = (uint8_t)(y_end >> 8U);
    rows[3] = (uint8_t)y_end;

    return TFTWriteCommandData(
               instance, TFT_COMMAND_CASET, columns, sizeof(columns)) &&
           TFTWriteCommandData(
               instance, TFT_COMMAND_RASET, rows, sizeof(rows));
}

static bool TFTFillPhysicalScreen(TFTInstance *instance, uint16_t color)
{
    uint16_t x;
    uint16_t y;

    for (x = 0U; x < TFT_PHYSICAL_WIDTH; ++x) {
        instance->scanline_buffer[x * 2U] = (uint8_t)(color >> 8U);
        instance->scanline_buffer[x * 2U + 1U] = (uint8_t)color;
    }
    if (!TFTSetAddressWindow(instance, 0U, 0U,
            TFT_PHYSICAL_WIDTH - 1U, TFT_PHYSICAL_HEIGHT - 1U) ||
        !TFTWriteCommand(instance, TFT_COMMAND_RAMWR)) {
        return false;
    }
    for (y = 0U; y < TFT_PHYSICAL_HEIGHT; ++y) {
        if (!TFTWriteData(instance, instance->scanline_buffer,
                sizeof(instance->scanline_buffer))) {
            return false;
        }
    }
    return true;
}

static void TFTBuildLogicalScanline(TFTInstance *instance, uint8_t y)
{
    uint8_t x;
    uint8_t mask = (uint8_t)(1U << (y & 0x07U));
    size_t page_offset = (size_t)(y / 8U) * DISPLAY_WIDTH;

    for (x = 0U; x < DISPLAY_WIDTH; ++x) {
        uint16_t color =
            ((instance->frame_buffer[page_offset + x] & mask) != 0U)
                ? instance->foreground_color
                : 0x0000U;
        instance->scanline_buffer[(size_t)x * 2U] =
            (uint8_t)(color >> 8U);
        instance->scanline_buffer[(size_t)x * 2U + 1U] =
            (uint8_t)color;
    }
}
