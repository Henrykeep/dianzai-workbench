/*
 * Waveform Module 保存最多 128 点的线程安全环形快照，并绘制量程映射后的连续曲线。
 */
#include "modules/waveform/waveform.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "task.h"

#define WAVEFORM_SAMPLE_CAPACITY (DISPLAY_WIDTH)
#define WAVEFORM_GRID_X_STEP     (16U)
#define WAVEFORM_GRID_DOT_STEP   (4U)

struct WaveformInstance {
    /* 显示和配置在注册后固定；samples 可由生产任务持续写入。 */
    DisplayInstance *display;
    WaveformConfig config;
    int16_t samples[WAVEFORM_SAMPLE_CAPACITY];
    int16_t render_samples[WAVEFORM_SAMPLE_CAPACITY];
    size_t sample_count;
    size_t write_index;
    bool registered;
};

static WaveformInstance waveform_instance;

static bool WaveformIsValid(const WaveformInstance *instance);
static bool WaveformConfigIsValid(const WaveformConfig *config);
static uint8_t WaveformMapSampleToY(
    const WaveformInstance *instance, int16_t sample);
static void WaveformDrawGrid(WaveformInstance *instance);
static void WaveformDrawVerticalLine(
    DisplayInstance *display,
    uint8_t x, uint8_t first_y, uint8_t second_y);

/* 注册波形绘制器并保存绘图区、量程和网格配置。 */
WaveformInstance *WaveformRegister(
    DisplayInstance *display, const WaveformConfig *config)
{
    if ((display == NULL) || !WaveformConfigIsValid(config)) {
        return NULL;
    }

    if (waveform_instance.registered) {
        return (waveform_instance.display == display)
                   ? &waveform_instance
                   : NULL;
    }

    waveform_instance.display     = display;
    waveform_instance.config      = *config;
    waveform_instance.sample_count = 0U;
    waveform_instance.write_index  = 0U;
    waveform_instance.registered   = true;
    return &waveform_instance;
}

/* 清空环形采样缓冲区。 */
bool WaveformReset(WaveformInstance *instance)
{
    if (!WaveformIsValid(instance)) {
        return false;
    }

    taskENTER_CRITICAL();
    instance->sample_count = 0U;
    instance->write_index  = 0U;
    taskEXIT_CRITICAL();
    return true;
}

/* 修改输入量程，绘制时会对超出量程的采样执行饱和。 */
bool WaveformSetRange(
    WaveformInstance *instance, int16_t minimum, int16_t maximum)
{
    if (!WaveformIsValid(instance) || (minimum >= maximum)) {
        return false;
    }

    taskENTER_CRITICAL();
    instance->config.minimum = minimum;
    instance->config.maximum = maximum;
    taskEXIT_CRITICAL();
    return true;
}

/* 将采样写入固定容量环形缓冲区，满后覆盖最早的数据。 */
bool WaveformPushSample(WaveformInstance *instance, int16_t sample)
{
    if (!WaveformIsValid(instance)) {
        return false;
    }

    taskENTER_CRITICAL();
    instance->samples[instance->write_index] = sample;
    instance->write_index =
        (instance->write_index + 1U) % WAVEFORM_SAMPLE_CAPACITY;
    if (instance->sample_count < WAVEFORM_SAMPLE_CAPACITY) {
        ++instance->sample_count;
    }
    taskEXIT_CRITICAL();
    return true;
}

/* 返回环形缓冲区中最新的采样值。 */
bool WaveformGetLatestSample(
    WaveformInstance *instance, int16_t *sample)
{
    size_t latest_index;

    if (!WaveformIsValid(instance) || (sample == NULL)) {
        return false;
    }

    taskENTER_CRITICAL();
    if (instance->sample_count == 0U) {
        taskEXIT_CRITICAL();
        return false;
    }
    latest_index = (instance->write_index == 0U)
                       ? WAVEFORM_SAMPLE_CAPACITY - 1U
                       : instance->write_index - 1U;
    *sample = instance->samples[latest_index];
    taskEXIT_CRITICAL();
    return true;
}

/* 快照采样缓冲区，绘制网格和从左向右滚动的连续波形。 */
bool WaveformRender(WaveformInstance *instance)
{
    size_t count;
    size_t oldest_index;
    size_t index;
    uint8_t plot_x;
    uint8_t plot_y;
    uint8_t previous_y = 0U;
    bool has_previous = false;

    if (!WaveformIsValid(instance)) {
        return false;
    }

    for (plot_y = instance->config.y;
         plot_y < (uint8_t)(instance->config.y + instance->config.height);
         ++plot_y) {
        for (plot_x = instance->config.x;
             plot_x < (uint8_t)(instance->config.x + instance->config.width);
             ++plot_x) {
            (void)DisplaySetPixel(
                instance->display, plot_x, plot_y, false);
        }
    }

    if (instance->config.grid_enabled) {
        WaveformDrawGrid(instance);
    }

    /* 临界区内只复制静态数据，实际逐像素绘制在退出临界区后完成。 */
    taskENTER_CRITICAL();
    count = instance->sample_count;
    oldest_index = (count < WAVEFORM_SAMPLE_CAPACITY)
                       ? 0U
                       : instance->write_index;
    for (index = 0U; index < count; ++index) {
        instance->render_samples[index] = instance->samples[
            (oldest_index + index) % WAVEFORM_SAMPLE_CAPACITY];
    }
    taskEXIT_CRITICAL();

    if (count > instance->config.width) {
        size_t skip = count - instance->config.width;
        for (index = 0U; index < instance->config.width; ++index) {
            instance->render_samples[index] =
                instance->render_samples[index + skip];
        }
        count = instance->config.width;
    }

    plot_x = (uint8_t)(instance->config.x + instance->config.width - count);
    for (index = 0U; index < count; ++index, ++plot_x) {
        uint8_t current_y =
            WaveformMapSampleToY(instance, instance->render_samples[index]);

        if (has_previous) {
            WaveformDrawVerticalLine(
                instance->display, plot_x, previous_y, current_y);
        } else {
            (void)DisplaySetPixel(
                instance->display, plot_x, current_y, true);
            has_previous = true;
        }
        previous_y = current_y;
    }

    return true;
}

/* 检查波形实例和显示适配器是否有效。 */
static bool WaveformIsValid(const WaveformInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->display != NULL) &&
           WaveformConfigIsValid(&instance->config);
}

/* 检查绘图区边界和输入量程。 */
static bool WaveformConfigIsValid(const WaveformConfig *config)
{
    return (config != NULL) && (config->width >= 2U) &&
           (config->height >= 2U) &&
           ((uint16_t)config->x + config->width <= DISPLAY_WIDTH) &&
           ((uint16_t)config->y + config->height <= DISPLAY_HEIGHT) &&
           (config->minimum < config->maximum);
}

/* 将输入采样按当前量程映射到绘图区的纵坐标。 */
static uint8_t WaveformMapSampleToY(
    const WaveformInstance *instance, int16_t sample)
{
    int32_t clamped = sample;
    uint32_t range;
    uint32_t offset;
    uint32_t scaled;

    if (clamped < instance->config.minimum) {
        clamped = instance->config.minimum;
    } else if (clamped > instance->config.maximum) {
        clamped = instance->config.maximum;
    }

    range = (uint32_t)((int32_t)instance->config.maximum -
                       instance->config.minimum);
    offset = (uint32_t)(clamped - instance->config.minimum);
    scaled = (offset * (instance->config.height - 1U)) / range;

    return (uint8_t)(instance->config.y + instance->config.height - 1U -
                     scaled);
}

/* 绘制中心水平虚线和固定间距的垂直点阵网格。 */
static void WaveformDrawGrid(WaveformInstance *instance)
{
    uint8_t x;
    uint8_t y;
    uint8_t center_y = (uint8_t)(instance->config.y +
                                 (instance->config.height / 2U));

    for (x = instance->config.x;
         x < (uint8_t)(instance->config.x + instance->config.width);
         x = (uint8_t)(x + WAVEFORM_GRID_DOT_STEP)) {
        (void)DisplaySetPixel(instance->display, x, center_y, true);
    }

    for (x = (uint8_t)(instance->config.x + WAVEFORM_GRID_X_STEP);
         x < (uint8_t)(instance->config.x + instance->config.width);
         x = (uint8_t)(x + WAVEFORM_GRID_X_STEP)) {
        for (y = instance->config.y;
             y < (uint8_t)(instance->config.y + instance->config.height);
             y = (uint8_t)(y + WAVEFORM_GRID_DOT_STEP)) {
            (void)DisplaySetPixel(instance->display, x, y, true);
        }
    }
}

/* 连接相邻采样列，避免快速变化时曲线出现明显断点。 */
static void WaveformDrawVerticalLine(
    DisplayInstance *display,
    uint8_t x, uint8_t first_y, uint8_t second_y)
{
    uint8_t start_y = (first_y < second_y) ? first_y : second_y;
    uint8_t end_y   = (first_y > second_y) ? first_y : second_y;
    uint8_t y;

    for (y = start_y; y <= end_y; ++y) {
        (void)DisplaySetPixel(display, x, y, true);
    }
}
