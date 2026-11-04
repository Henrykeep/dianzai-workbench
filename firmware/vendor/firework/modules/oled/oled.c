/*
 * SSD1306 OLED 驱动：维护页式本地帧缓冲，提供像素/ASCII 绘制并通过 I2C 刷新。
 * 绘图操作只改内存，只有 OLEDUpdate 或 OLEDUpdatePages 才访问显示硬件。
 */
#include "modules/oled/oled.h"

#include <stddef.h>
#include <string.h>

#include "modules/i2c/i2c.h"

/* SSD1306 每页包含 8 行像素，完整帧缓冲按“页优先、页内按列”排列。 */
#define OLED_PAGE_COUNT            (OLED_HEIGHT / 8U)
#define OLED_FRAME_BUFFER_SIZE     (OLED_WIDTH * OLED_PAGE_COUNT)
/* I2C 控制字节用于区分后续负载是命令还是显示数据。 */
#define OLED_CONTROL_COMMAND       (0x00U)
#define OLED_CONTROL_DATA          (0x40U)
/* 固定分块限制栈上临时包大小；数据块恰好覆盖一整页。 */
#define OLED_COMMAND_CHUNK_SIZE    (16U)
#define OLED_DATA_CHUNK_SIZE       (OLED_WIDTH)
/* 内置字体覆盖 ASCII 0x20～0x7F，字形宽 5 列并保留 1 列间距。 */
#define OLED_FONT_FIRST_CHARACTER  (32U)
#define OLED_FONT_LAST_CHARACTER   (127U)
#define OLED_FONT_WIDTH            (5U)
#define OLED_FONT_HEIGHT           (7U)
#define OLED_CHARACTER_ADVANCE     (6U)
#define OLED_LINE_ADVANCE          (8U)

struct OLEDInstance {
    /* OLED 所在的线程安全 I2C 总线。 */
    I2CInstance *i2c;
    /* SSD1306 使用的 7 位 I2C 地址，常见值为 0x3C 或 0x3D。 */
    uint8_t i2c_address;
    /* 128×64 单色图像的本地页式帧缓冲区。 */
    uint8_t frame_buffer[OLED_FRAME_BUFFER_SIZE];
    /* 注册和初始化状态。 */
    bool registered;
    bool initialized;
};

/* 本项目只使用一块 OLED，采用静态实例避免动态内存分配。 */
static OLEDInstance oled_instance;

/* 5×7 ASCII 字体，每个字节表示一列，最低位是该列顶部像素。 */
static const uint8_t oled_font_5x7[96][OLED_FONT_WIDTH] = {
    {0x00, 0x00, 0x00, 0x00, 0x00}, /* space */
    {0x00, 0x00, 0x5F, 0x00, 0x00}, /* ! */
    {0x00, 0x07, 0x00, 0x07, 0x00}, /* " */
    {0x14, 0x7F, 0x14, 0x7F, 0x14}, /* # */
    {0x24, 0x2A, 0x7F, 0x2A, 0x12}, /* $ */
    {0x23, 0x13, 0x08, 0x64, 0x62}, /* % */
    {0x36, 0x49, 0x55, 0x22, 0x50}, /* & */
    {0x00, 0x05, 0x03, 0x00, 0x00}, /* ' */
    {0x00, 0x1C, 0x22, 0x41, 0x00}, /* ( */
    {0x00, 0x41, 0x22, 0x1C, 0x00}, /* ) */
    {0x14, 0x08, 0x3E, 0x08, 0x14}, /* * */
    {0x08, 0x08, 0x3E, 0x08, 0x08}, /* + */
    {0x00, 0x50, 0x30, 0x00, 0x00}, /* , */
    {0x08, 0x08, 0x08, 0x08, 0x08}, /* - */
    {0x00, 0x60, 0x60, 0x00, 0x00}, /* . */
    {0x20, 0x10, 0x08, 0x04, 0x02}, /* / */
    {0x3E, 0x51, 0x49, 0x45, 0x3E}, /* 0 */
    {0x00, 0x42, 0x7F, 0x40, 0x00}, /* 1 */
    {0x42, 0x61, 0x51, 0x49, 0x46}, /* 2 */
    {0x21, 0x41, 0x45, 0x4B, 0x31}, /* 3 */
    {0x18, 0x14, 0x12, 0x7F, 0x10}, /* 4 */
    {0x27, 0x45, 0x45, 0x45, 0x39}, /* 5 */
    {0x3C, 0x4A, 0x49, 0x49, 0x30}, /* 6 */
    {0x01, 0x71, 0x09, 0x05, 0x03}, /* 7 */
    {0x36, 0x49, 0x49, 0x49, 0x36}, /* 8 */
    {0x06, 0x49, 0x49, 0x29, 0x1E}, /* 9 */
    {0x00, 0x36, 0x36, 0x00, 0x00}, /* : */
    {0x00, 0x56, 0x36, 0x00, 0x00}, /* ; */
    {0x08, 0x14, 0x22, 0x41, 0x00}, /* < */
    {0x14, 0x14, 0x14, 0x14, 0x14}, /* = */
    {0x00, 0x41, 0x22, 0x14, 0x08}, /* > */
    {0x02, 0x01, 0x51, 0x09, 0x06}, /* ? */
    {0x32, 0x49, 0x79, 0x41, 0x3E}, /* @ */
    {0x7E, 0x11, 0x11, 0x11, 0x7E}, /* A */
    {0x7F, 0x49, 0x49, 0x49, 0x36}, /* B */
    {0x3E, 0x41, 0x41, 0x41, 0x22}, /* C */
    {0x7F, 0x41, 0x41, 0x22, 0x1C}, /* D */
    {0x7F, 0x49, 0x49, 0x49, 0x41}, /* E */
    {0x7F, 0x09, 0x09, 0x09, 0x01}, /* F */
    {0x3E, 0x41, 0x49, 0x49, 0x7A}, /* G */
    {0x7F, 0x08, 0x08, 0x08, 0x7F}, /* H */
    {0x00, 0x41, 0x7F, 0x41, 0x00}, /* I */
    {0x20, 0x40, 0x41, 0x3F, 0x01}, /* J */
    {0x7F, 0x08, 0x14, 0x22, 0x41}, /* K */
    {0x7F, 0x40, 0x40, 0x40, 0x40}, /* L */
    {0x7F, 0x02, 0x0C, 0x02, 0x7F}, /* M */
    {0x7F, 0x04, 0x08, 0x10, 0x7F}, /* N */
    {0x3E, 0x41, 0x41, 0x41, 0x3E}, /* O */
    {0x7F, 0x09, 0x09, 0x09, 0x06}, /* P */
    {0x3E, 0x41, 0x51, 0x21, 0x5E}, /* Q */
    {0x7F, 0x09, 0x19, 0x29, 0x46}, /* R */
    {0x46, 0x49, 0x49, 0x49, 0x31}, /* S */
    {0x01, 0x01, 0x7F, 0x01, 0x01}, /* T */
    {0x3F, 0x40, 0x40, 0x40, 0x3F}, /* U */
    {0x1F, 0x20, 0x40, 0x20, 0x1F}, /* V */
    {0x3F, 0x40, 0x38, 0x40, 0x3F}, /* W */
    {0x63, 0x14, 0x08, 0x14, 0x63}, /* X */
    {0x07, 0x08, 0x70, 0x08, 0x07}, /* Y */
    {0x61, 0x51, 0x49, 0x45, 0x43}, /* Z */
    {0x00, 0x7F, 0x41, 0x41, 0x00}, /* [ */
    {0x02, 0x04, 0x08, 0x10, 0x20}, /* backslash */
    {0x00, 0x41, 0x41, 0x7F, 0x00}, /* ] */
    {0x04, 0x02, 0x01, 0x02, 0x04}, /* ^ */
    {0x40, 0x40, 0x40, 0x40, 0x40}, /* _ */
    {0x00, 0x01, 0x02, 0x04, 0x00}, /* ` */
    {0x20, 0x54, 0x54, 0x54, 0x78}, /* a */
    {0x7F, 0x48, 0x44, 0x44, 0x38}, /* b */
    {0x38, 0x44, 0x44, 0x44, 0x20}, /* c */
    {0x38, 0x44, 0x44, 0x48, 0x7F}, /* d */
    {0x38, 0x54, 0x54, 0x54, 0x18}, /* e */
    {0x08, 0x7E, 0x09, 0x01, 0x02}, /* f */
    {0x0C, 0x52, 0x52, 0x52, 0x3E}, /* g */
    {0x7F, 0x08, 0x04, 0x04, 0x78}, /* h */
    {0x00, 0x44, 0x7D, 0x40, 0x00}, /* i */
    {0x20, 0x40, 0x44, 0x3D, 0x00}, /* j */
    {0x7F, 0x10, 0x28, 0x44, 0x00}, /* k */
    {0x00, 0x41, 0x7F, 0x40, 0x00}, /* l */
    {0x7C, 0x04, 0x18, 0x04, 0x78}, /* m */
    {0x7C, 0x08, 0x04, 0x04, 0x78}, /* n */
    {0x38, 0x44, 0x44, 0x44, 0x38}, /* o */
    {0x7C, 0x14, 0x14, 0x14, 0x08}, /* p */
    {0x08, 0x14, 0x14, 0x18, 0x7C}, /* q */
    {0x7C, 0x08, 0x04, 0x04, 0x08}, /* r */
    {0x48, 0x54, 0x54, 0x54, 0x20}, /* s */
    {0x04, 0x3F, 0x44, 0x40, 0x20}, /* t */
    {0x3C, 0x40, 0x40, 0x20, 0x7C}, /* u */
    {0x1C, 0x20, 0x40, 0x20, 0x1C}, /* v */
    {0x3C, 0x40, 0x30, 0x40, 0x3C}, /* w */
    {0x44, 0x28, 0x10, 0x28, 0x44}, /* x */
    {0x0C, 0x50, 0x50, 0x50, 0x3C}, /* y */
    {0x44, 0x64, 0x54, 0x4C, 0x44}, /* z */
    {0x00, 0x08, 0x36, 0x41, 0x00}, /* { */
    {0x00, 0x00, 0x7F, 0x00, 0x00}, /* | */
    {0x00, 0x41, 0x36, 0x08, 0x00}, /* } */
    {0x08, 0x04, 0x08, 0x10, 0x08}, /* ~ */
    {0x00, 0x06, 0x09, 0x09, 0x06}  /* DEL placeholder */
};

static bool OLEDIsValid(const OLEDInstance *instance);
static bool OLEDWriteCommands(
    OLEDInstance *instance, const uint8_t *commands, size_t size);
static bool OLEDWriteData(
    OLEDInstance *instance, const uint8_t *data, size_t size);

/* 注册 SSD1306 OLED 并保存其 I2C 地址。 */
OLEDInstance *OLEDRegister(uint8_t i2c_address)
{
    if (i2c_address > 0x7FU) {
        return NULL;
    }

    if (oled_instance.registered) {
        return (oled_instance.i2c_address == i2c_address)
                   ? &oled_instance
                   : NULL;
    }

    oled_instance.i2c = I2CRegister(I2C_DEVICE_OLED);
    if (oled_instance.i2c == NULL) {
        return NULL;
    }

    oled_instance.i2c_address = i2c_address;
    oled_instance.registered  = true;
    oled_instance.initialized = false;
    return &oled_instance;
}

/* 配置 128×64 SSD1306，清空显存并打开面板显示。 */
bool OLEDInitialize(OLEDInstance *instance)
{
    static const uint8_t initialization_commands[] = {
        0xAEU,       /* 关闭显示。 */
        0xD5U, 0x80U, /* 设置显示时钟分频。 */
        0xA8U, 0x3FU, /* 设置 64 行复用比。 */
        0xD3U, 0x00U, /* 显示偏移为 0。 */
        0x40U,       /* 显示起始行为 0。 */
        0x8DU, 0x14U, /* 启用内部电荷泵。 */
        0x20U, 0x00U, /* 使用水平寻址模式。 */
        0xA1U,       /* 重映射段地址。 */
        0xC8U,       /* 反向映射 COM 扫描方向。 */
        0xDAU, 0x12U, /* 使用 128×64 面板的 COM 引脚配置。 */
        0x81U, 0xCFU, /* 设置对比度。 */
        0xD9U, 0xF1U, /* 设置预充电周期。 */
        0xDBU, 0x40U, /* 设置 VCOMH 取消选择电平。 */
        0xA4U,       /* 按显示 RAM 内容输出。 */
        0xA6U,       /* 使用正常显示模式，不反色。 */
        0x2EU        /* 禁用滚动。 */
    };
    static const uint8_t display_on_command[] = {0xAFU};

    if (!OLEDIsValid(instance)) {
        return false;
    }

    instance->initialized = false;
    if (!OLEDWriteCommands(instance, initialization_commands,
            sizeof(initialization_commands))) {
        return false;
    }

    memset(instance->frame_buffer, 0, sizeof(instance->frame_buffer));
    instance->initialized = true;

    if (!OLEDUpdate(instance) ||
        !OLEDWriteCommands(
            instance, display_on_command, sizeof(display_on_command))) {
        instance->initialized = false;
        return false;
    }

    return true;
}

/* 用全灭或全亮数据填充本地帧缓冲区。 */
bool OLEDClear(OLEDInstance *instance, bool pixels_on)
{
    if (!OLEDIsValid(instance) || !instance->initialized) {
        return false;
    }

    memset(instance->frame_buffer, pixels_on ? 0xFF : 0x00,
        sizeof(instance->frame_buffer));
    return true;
}

/* 修改帧缓冲区中的一个像素。 */
bool OLEDSetPixel(
    OLEDInstance *instance, uint8_t x, uint8_t y, bool pixel_on)
{
    size_t index;
    uint8_t mask;

    if (!OLEDIsValid(instance) || !instance->initialized ||
        (x >= OLED_WIDTH) || (y >= OLED_HEIGHT)) {
        return false;
    }

    /* 每个字节表示同一列内连续 8 个纵向像素，低位对应较小的 y。 */
    index = (size_t)x + ((size_t)(y / 8U) * OLED_WIDTH);
    mask  = (uint8_t)(1U << (y & 0x07U));

    if (pixel_on) {
        instance->frame_buffer[index] |= mask;
    } else {
        instance->frame_buffer[index] &= (uint8_t)~mask;
    }

    return true;
}

/* 使用内置列式字体绘制一个字符，并清空字符间隔列。 */
bool OLEDDrawCharacter(
    OLEDInstance *instance, uint8_t x, uint8_t y, char character)
{
    uint8_t column;
    uint8_t row;
    uint8_t character_index;

    if (!OLEDIsValid(instance) || !instance->initialized ||
        (x >= OLED_WIDTH) || (y >= OLED_HEIGHT)) {
        return false;
    }

    if (((uint8_t)character < OLED_FONT_FIRST_CHARACTER) ||
        ((uint8_t)character > OLED_FONT_LAST_CHARACTER)) {
        character = '?';
    }
    character_index = (uint8_t)character - OLED_FONT_FIRST_CHARACTER;

    for (column = 0U; column < OLED_CHARACTER_ADVANCE; ++column) {
        uint8_t column_bits = (column < OLED_FONT_WIDTH)
                                  ? oled_font_5x7[character_index][column]
                                  : 0U;

        for (row = 0U; row < OLED_FONT_HEIGHT; ++row) {
            uint16_t pixel_x = (uint16_t)x + column;
            uint16_t pixel_y = (uint16_t)y + row;

            if ((pixel_x < OLED_WIDTH) && (pixel_y < OLED_HEIGHT)) {
                (void)OLEDSetPixel(instance, (uint8_t)pixel_x,
                    (uint8_t)pixel_y,
                    (column_bits & (uint8_t)(1U << row)) != 0U);
            }
        }
    }

    return true;
}

/* 逐字符绘制字符串，并在到达屏幕右边缘时自动换行。 */
bool OLEDDrawString(
    OLEDInstance *instance, uint8_t x, uint8_t y, const char *text)
{
    uint8_t cursor_x = x;
    uint8_t cursor_y = y;

    if (!OLEDIsValid(instance) || !instance->initialized || (text == NULL) ||
        (x >= OLED_WIDTH) || (y >= OLED_HEIGHT)) {
        return false;
    }

    while (*text != '\0') {
        if (*text == '\n') {
            cursor_x = 0U;
            cursor_y = (uint8_t)(cursor_y + OLED_LINE_ADVANCE);
            ++text;
            continue;
        }

        if ((uint16_t)cursor_x + OLED_CHARACTER_ADVANCE > OLED_WIDTH) {
            cursor_x = 0U;
            cursor_y = (uint8_t)(cursor_y + OLED_LINE_ADVANCE);
        }
        if ((uint16_t)cursor_y + OLED_FONT_HEIGHT > OLED_HEIGHT) {
            break;
        }

        (void)OLEDDrawCharacter(instance, cursor_x, cursor_y, *text);
        cursor_x = (uint8_t)(cursor_x + OLED_CHARACTER_ADVANCE);
        ++text;
    }

    return true;
}

/* 将完整帧缓冲区写入 SSD1306。 */
bool OLEDUpdate(OLEDInstance *instance)
{
    return OLEDUpdatePages(instance, 0U, OLED_PAGE_COUNT);
}

/* 设置连续页窗口，只刷新帧缓冲区中指定的 8 像素高页面。 */
bool OLEDUpdatePages(
    OLEDInstance *instance, uint8_t first_page, uint8_t page_count)
{
    uint8_t window_commands[] = {
        0x21U, 0x00U, 0x7FU, /* Column address 0～127. */
        0x22U, first_page, 0U /* Page address range. */
    };
    size_t offset;
    size_t size;

    if (!OLEDIsValid(instance) || !instance->initialized ||
        (page_count == 0U) || (first_page >= OLED_PAGE_COUNT) ||
        ((uint16_t)first_page + page_count > OLED_PAGE_COUNT)) {
        return false;
    }

    /* 窗口端点包含在刷新范围内，帧缓冲偏移按整页宽度计算。 */
    window_commands[5] = (uint8_t)(first_page + page_count - 1U);
    offset = (size_t)first_page * OLED_WIDTH;
    size   = (size_t)page_count * OLED_WIDTH;

    return OLEDWriteCommands(
               instance, window_commands, sizeof(window_commands)) &&
           OLEDWriteData(instance, &instance->frame_buffer[offset], size);
}

/* 发送 SSD1306 显示开关命令。 */
bool OLEDSetDisplayEnabled(OLEDInstance *instance, bool enabled)
{
    uint8_t command = enabled ? 0xAFU : 0xAEU;

    if (!OLEDIsValid(instance) || !instance->initialized) {
        return false;
    }

    return OLEDWriteCommands(instance, &command, sizeof(command));
}

/* 发送 SSD1306 正常或反色显示命令。 */
bool OLEDSetInverted(OLEDInstance *instance, bool inverted)
{
    uint8_t command = inverted ? 0xA7U : 0xA6U;

    if (!OLEDIsValid(instance) || !instance->initialized) {
        return false;
    }

    return OLEDWriteCommands(instance, &command, sizeof(command));
}

/* 设置 SSD1306 硬件对比度。 */
bool OLEDSetContrast(OLEDInstance *instance, uint8_t contrast)
{
    uint8_t commands[] = {0x81U, contrast};

    if (!OLEDIsValid(instance) || !instance->initialized) {
        return false;
    }

    return OLEDWriteCommands(instance, commands, sizeof(commands));
}

/* 检查 OLED 实例是否已经成功注册。 */
static bool OLEDIsValid(const OLEDInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->i2c != NULL) && (instance->i2c_address <= 0x7FU);
}

/* 在命令控制字节前添加 0x00，并通过 I2C 发送命令序列。 */
static bool OLEDWriteCommands(
    OLEDInstance *instance, const uint8_t *commands, size_t size)
{
    uint8_t packet[OLED_COMMAND_CHUNK_SIZE + 1U];
    size_t offset = 0U;

    if (!OLEDIsValid(instance) || (commands == NULL) || (size == 0U)) {
        return false;
    }

    while (offset < size) {
        size_t chunk_size = size - offset;
        if (chunk_size > OLED_COMMAND_CHUNK_SIZE) {
            chunk_size = OLED_COMMAND_CHUNK_SIZE;
        }

        packet[0] = OLED_CONTROL_COMMAND;
        memcpy(&packet[1], &commands[offset], chunk_size);

        if (!I2CWrite(instance->i2c, instance->i2c_address, packet,
                chunk_size + 1U)) {
            return false;
        }

        offset += chunk_size;
    }

    return true;
}

/* 在数据控制字节前添加 0x40，并分块发送帧缓冲区。 */
static bool OLEDWriteData(
    OLEDInstance *instance, const uint8_t *data, size_t size)
{
    uint8_t packet[OLED_DATA_CHUNK_SIZE + 1U];
    size_t offset = 0U;

    if (!OLEDIsValid(instance) || (data == NULL) || (size == 0U)) {
        return false;
    }

    while (offset < size) {
        size_t chunk_size = size - offset;
        if (chunk_size > OLED_DATA_CHUNK_SIZE) {
            chunk_size = OLED_DATA_CHUNK_SIZE;
        }

        packet[0] = OLED_CONTROL_DATA;
        memcpy(&packet[1], &data[offset], chunk_size);

        if (!I2CWrite(instance->i2c, instance->i2c_address, packet,
                chunk_size + 1U)) {
            return false;
        }

        offset += chunk_size;
    }

    return true;
}
