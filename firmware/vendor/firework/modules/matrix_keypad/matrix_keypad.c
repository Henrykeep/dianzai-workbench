/*
 * MatrixKeypad Module 逐行驱动 4×4 矩阵，独立防抖 16 个键并生成按下/释放位图。
 */
#include "modules/matrix_keypad/matrix_keypad.h"

#include <stddef.h>

#include "bsp/gpio/bsp_gpio.h"

#define MATRIX_KEYPAD_DEBOUNCE_TIME_MS (30UL)

struct MatrixKeypadInstance {
    /* 四路行输出和四路带上拉的列输入。 */
    BSPGPIOInstance *rows[MATRIX_KEYPAD_ROW_COUNT];
    BSPGPIOInstance *columns[MATRIX_KEYPAD_COLUMN_COUNT];
    /* 每个键独立保存原始状态、防抖状态和累计稳定时间。 */
    uint16_t last_raw_keys;
    uint16_t stable_keys;
    uint32_t debounce_elapsed_ms[MATRIX_KEYPAD_KEY_COUNT];
    bool registered;
};

static MatrixKeypadInstance matrix_keypad_instance;

static const BSP_GPIO_Channel_e matrix_keypad_row_channels[
    MATRIX_KEYPAD_ROW_COUNT] = {
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_0,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_1,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_2,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_ROW_3,
};

static const BSP_GPIO_Channel_e matrix_keypad_column_channels[
    MATRIX_KEYPAD_COLUMN_COUNT] = {
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_0,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_1,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_2,
    BSP_GPIO_CHANNEL_MATRIX_KEYPAD_COLUMN_3,
};

static const char matrix_keypad_characters[MATRIX_KEYPAD_KEY_COUNT] = {
    '1', '2', '3', 'A',
    '4', '5', '6', 'B',
    '7', '8', '9', 'C',
    '*', '0', '#', 'D',
};

static bool MatrixKeypadIsValid(const MatrixKeypadInstance *instance);
static bool MatrixKeypadSetAllRows(
    MatrixKeypadInstance *instance, bool high);
static bool MatrixKeypadSetAllRowOutputs(
    MatrixKeypadInstance *instance, bool enabled);
static void MatrixKeypadRestoreIdleRows(MatrixKeypadInstance *instance);
static uint32_t MatrixKeypadSaturatingAdd(
    uint32_t value, uint32_t increment);

MatrixKeypadInstance *MatrixKeypadRegister(void)
{
    MatrixKeypadInstance *instance = &matrix_keypad_instance;
    uint32_t index;
    uint16_t initial_raw_keys;

    if (instance->registered) {
        return instance;
    }

    for (index = 0U; index < MATRIX_KEYPAD_ROW_COUNT; ++index) {
        instance->rows[index] =
            BSPGPIORegister(matrix_keypad_row_channels[index]);
        if (instance->rows[index] == NULL) {
            return NULL;
        }
    }
    for (index = 0U; index < MATRIX_KEYPAD_COLUMN_COUNT; ++index) {
        instance->columns[index] =
            BSPGPIORegister(matrix_keypad_column_channels[index]);
        if (instance->columns[index] == NULL) {
            return NULL;
        }
    }

    instance->last_raw_keys = 0U;
    instance->stable_keys   = 0U;
    for (index = 0U; index < MATRIX_KEYPAD_KEY_COUNT; ++index) {
        instance->debounce_elapsed_ms[index] = 0U;
    }
    instance->registered = true;

    /* 上电保持全部行无效，随后记录一次原始状态作为防抖起点。 */
    if (!MatrixKeypadSetAllRows(instance, true) ||
        !MatrixKeypadReadRaw(instance, &initial_raw_keys)) {
        instance->registered = false;
        return NULL;
    }
    instance->last_raw_keys = initial_raw_keys;
    return instance;
}

bool MatrixKeypadReadRaw(
    MatrixKeypadInstance *instance, uint16_t *pressed_keys)
{
    uint16_t raw_keys = 0U;
    uint32_t row;
    uint32_t column;

    if (!MatrixKeypadIsValid(instance) || (pressed_keys == NULL)) {
        return false;
    }

    /*
     * 先把四行全部切为高阻，再把输出锁存值设为低。扫描时只启用当前行，
     * 避免多键按下时高低输出行通过按键直接相连。
     */
    if (!MatrixKeypadSetAllRowOutputs(instance, false) ||
        !MatrixKeypadSetAllRows(instance, false)) {
        MatrixKeypadRestoreIdleRows(instance);
        return false;
    }

    for (row = 0U; row < MATRIX_KEYPAD_ROW_COUNT; ++row) {
        if (!BSPGPIOSetOutputEnabled(instance->rows[row], true)) {
            MatrixKeypadRestoreIdleRows(instance);
            return false;
        }

        for (column = 0U; column < MATRIX_KEYPAD_COLUMN_COUNT;
             ++column) {
            bool column_high;
            uint32_t key_index;

            if (!BSPGPIORead(instance->columns[column], &column_high)) {
                MatrixKeypadRestoreIdleRows(instance);
                return false;
            }
            if (!column_high) {
                key_index = row * MATRIX_KEYPAD_COLUMN_COUNT + column;
                raw_keys |= (uint16_t)(1UL << key_index);
            }
        }

        if (!BSPGPIOSetOutputEnabled(instance->rows[row], false)) {
            MatrixKeypadRestoreIdleRows(instance);
            return false;
        }
    }

    MatrixKeypadRestoreIdleRows(instance);
    *pressed_keys = raw_keys;
    return true;
}

bool MatrixKeypadProcess(MatrixKeypadInstance *instance,
    uint32_t elapsed_ms, MatrixKeypadEvent *event)
{
    uint16_t raw_keys;
    uint32_t key_index;

    if (!MatrixKeypadIsValid(instance) || (elapsed_ms == 0U) ||
        (event == NULL) || !MatrixKeypadReadRaw(instance, &raw_keys)) {
        return false;
    }

    event->pressed_keys  = 0U;
    event->released_keys = 0U;

    for (key_index = 0U; key_index < MATRIX_KEYPAD_KEY_COUNT;
         ++key_index) {
        uint16_t key_mask = (uint16_t)(1UL << key_index);
        bool raw_pressed  = (raw_keys & key_mask) != 0U;
        bool last_pressed = (instance->last_raw_keys & key_mask) != 0U;
        bool stable_pressed = (instance->stable_keys & key_mask) != 0U;

        if (raw_pressed != last_pressed) {
            if (raw_pressed) {
                instance->last_raw_keys |= key_mask;
            } else {
                instance->last_raw_keys &= (uint16_t)~key_mask;
            }
            instance->debounce_elapsed_ms[key_index] = 0U;
            continue;
        }

        if (raw_pressed == stable_pressed) {
            instance->debounce_elapsed_ms[key_index] = 0U;
            continue;
        }

        instance->debounce_elapsed_ms[key_index] =
            MatrixKeypadSaturatingAdd(
                instance->debounce_elapsed_ms[key_index], elapsed_ms);
        if (instance->debounce_elapsed_ms[key_index] <
            MATRIX_KEYPAD_DEBOUNCE_TIME_MS) {
            continue;
        }

        instance->debounce_elapsed_ms[key_index] = 0U;
        if (raw_pressed) {
            instance->stable_keys |= key_mask;
            event->pressed_keys |= key_mask;
        } else {
            instance->stable_keys &= (uint16_t)~key_mask;
            event->released_keys |= key_mask;
        }
    }

    event->held_keys = instance->stable_keys;
    return true;
}

bool MatrixKeypadGetStableKeys(
    const MatrixKeypadInstance *instance, uint16_t *pressed_keys)
{
    if (!MatrixKeypadIsValid(instance) || (pressed_keys == NULL)) {
        return false;
    }

    *pressed_keys = instance->stable_keys;
    return true;
}

uint16_t MatrixKeypadKeyMask(MatrixKeypadKey_e key)
{
    if ((key < MATRIX_KEYPAD_KEY_1) ||
        (key >= (MatrixKeypadKey_e)MATRIX_KEYPAD_KEY_COUNT)) {
        return 0U;
    }

    return (uint16_t)(1UL << (uint32_t)key);
}

char MatrixKeypadKeyToChar(MatrixKeypadKey_e key)
{
    if ((key < MATRIX_KEYPAD_KEY_1) ||
        (key >= (MatrixKeypadKey_e)MATRIX_KEYPAD_KEY_COUNT)) {
        return '\0';
    }

    return matrix_keypad_characters[(uint32_t)key];
}

MatrixKeypadKey_e MatrixKeypadFindFirstKey(uint16_t pressed_keys)
{
    uint32_t key_index;

    for (key_index = 0U; key_index < MATRIX_KEYPAD_KEY_COUNT;
         ++key_index) {
        if ((pressed_keys & (uint16_t)(1UL << key_index)) != 0U) {
            return (MatrixKeypadKey_e)key_index;
        }
    }

    return MATRIX_KEYPAD_KEY_NONE;
}

static bool MatrixKeypadIsValid(const MatrixKeypadInstance *instance)
{
    return (instance != NULL) && instance->registered;
}

static bool MatrixKeypadSetAllRows(
    MatrixKeypadInstance *instance, bool high)
{
    uint32_t row;

    if (instance == NULL) {
        return false;
    }

    for (row = 0U; row < MATRIX_KEYPAD_ROW_COUNT; ++row) {
        if ((instance->rows[row] == NULL) ||
            !BSPGPIOWrite(instance->rows[row], high)) {
            return false;
        }
    }
    return true;
}

static bool MatrixKeypadSetAllRowOutputs(
    MatrixKeypadInstance *instance, bool enabled)
{
    uint32_t row;

    if (instance == NULL) {
        return false;
    }

    for (row = 0U; row < MATRIX_KEYPAD_ROW_COUNT; ++row) {
        if ((instance->rows[row] == NULL) ||
            !BSPGPIOSetOutputEnabled(instance->rows[row], enabled)) {
            return false;
        }
    }
    return true;
}

/* 扫描结束或发生错误时，尽力把所有行恢复为相同的高电平安全态。 */
static void MatrixKeypadRestoreIdleRows(MatrixKeypadInstance *instance)
{
    if (instance == NULL) {
        return;
    }

    (void)MatrixKeypadSetAllRows(instance, true);
    (void)MatrixKeypadSetAllRowOutputs(instance, true);
}

static uint32_t MatrixKeypadSaturatingAdd(
    uint32_t value, uint32_t increment)
{
    return (UINT32_MAX - value < increment) ? UINT32_MAX
                                             : value + increment;
}
