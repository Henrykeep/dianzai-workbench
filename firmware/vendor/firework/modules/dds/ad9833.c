/* AD9833 驱动负责控制字、28 位频率字和 12 位相位字的寄存器写入时序。 */
#include "modules/dds/ad9833.h"

#include "application/app_config.h"

#if (APP_ENABLE_WAVEFORM_OUTPUT_DDS != 0U) || \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 != 0U)

#include <stddef.h>

#define AD9833_CONTROL_B28       (0x2000U)
#define AD9833_CONTROL_RESET     (0x0100U)
#define AD9833_CONTROL_SLEEP1    (0x0080U)
#define AD9833_CONTROL_SLEEP12   (0x0040U)
#define AD9833_CONTROL_OPBITEN   (0x0020U)
#define AD9833_CONTROL_DIV2      (0x0008U)
#define AD9833_CONTROL_MODE      (0x0002U)

#define AD9833_FREQUENCY_0       (0x4000U)
#define AD9833_FREQUENCY_1       (0x8000U)
#define AD9833_PHASE_0           (0xC000U)
#define AD9833_PHASE_1           (0xE000U)
#define AD9833_FREQUENCY_MASK    (0x3FFFU)
#define AD9833_PHASE_MASK        (0x0FFFU)
#define AD9833_PHASE_STEPS       (4096UL)
#define AD9833_FULL_CIRCLE_DEGREES (360U)
#define AD9833_TUNING_MODULUS    (268435456ULL)
#define AD9833_MAXIMUM_REFERENCE_CLOCK_HZ (25000000UL)

static bool AD9833BuildFrequencyWords(uint32_t reference_clock_hz,
    uint32_t frequency_hz, uint16_t address, uint16_t words[2]);
static bool AD9833BuildPhaseWord(
    uint16_t phase_degrees, uint16_t address, uint16_t *word);
static bool AD9833BuildControlWord(uint16_t base_control,
    DDSWaveform_e waveform, bool enabled, uint16_t *control_word);
static bool AD9833ContextIsValid(const AD9833Context *context,
    const SPIInstance *spi);

/* 按官方顺序在 RESET 状态下装入两个频率和两个相位寄存器。 */
bool AD9833Initialize(AD9833Context *context, SPIInstance *spi,
    uint32_t reference_clock_hz, uint32_t frequency_hz,
    uint16_t phase_degrees, DDSWaveform_e waveform, bool enabled)
{
    uint16_t words[8];
    uint16_t final_control;

    if ((context == NULL) || (spi == NULL) ||
        !AD9833BuildFrequencyWords(reference_clock_hz,
            frequency_hz, AD9833_FREQUENCY_0, &words[1]) ||
        !AD9833BuildFrequencyWords(reference_clock_hz,
            frequency_hz, AD9833_FREQUENCY_1, &words[3]) ||
        !AD9833BuildPhaseWord(
            phase_degrees, AD9833_PHASE_0, &words[5]) ||
        !AD9833BuildPhaseWord(
            phase_degrees, AD9833_PHASE_1, &words[6]) ||
        !AD9833BuildControlWord(
            AD9833_CONTROL_B28, waveform, enabled, &final_control)) {
        return false;
    }

    words[0] = AD9833_CONTROL_B28 | AD9833_CONTROL_RESET;
    words[7] = final_control;

    if (!SPIWrite16(spi, words, sizeof(words) / sizeof(words[0]))) {
        return false;
    }

    context->control_shadow = final_control;
    context->waveform       = waveform;
    context->enabled        = enabled;
    context->initialized    = true;
    return true;
}

/* 将输出频率换算为 28 位调谐字，并更新当前使用的 FREQ0。 */
bool AD9833SetFrequency(AD9833Context *context, SPIInstance *spi,
    uint32_t reference_clock_hz, uint32_t frequency_hz)
{
    uint16_t words[2];

    if (!AD9833ContextIsValid(context, spi) ||
        !AD9833BuildFrequencyWords(reference_clock_hz,
            frequency_hz, AD9833_FREQUENCY_0, words)) {
        return false;
    }

    return SPIWrite16(spi, words, sizeof(words) / sizeof(words[0]));
}

/* 将角度换算为 12 位相位字，并更新当前使用的 PHASE0。 */
bool AD9833SetPhase(AD9833Context *context, SPIInstance *spi,
    uint16_t phase_degrees)
{
    uint16_t word;

    if (!AD9833ContextIsValid(context, spi) ||
        !AD9833BuildPhaseWord(
            phase_degrees, AD9833_PHASE_0, &word)) {
        return false;
    }

    return SPIWrite16(spi, &word, 1U);
}

/* 修改波形控制位，成功写入后才更新软件影子状态。 */
bool AD9833SetWaveform(AD9833Context *context, SPIInstance *spi,
    DDSWaveform_e waveform)
{
    uint16_t control_word;

    if (!AD9833ContextIsValid(context, spi) ||
        !AD9833BuildControlWord(context->control_shadow,
            waveform, context->enabled, &control_word) ||
        !SPIWrite16(spi, &control_word, 1U)) {
        return false;
    }

    context->control_shadow = control_word;
    context->waveform       = waveform;
    return true;
}

/* 启动时恢复波形位，停止时同时置位 RESET、SLEEP1 和 SLEEP12。 */
bool AD9833SetEnabled(AD9833Context *context, SPIInstance *spi,
    bool enabled)
{
    uint16_t control_word;

    if (!AD9833ContextIsValid(context, spi) ||
        !AD9833BuildControlWord(context->control_shadow,
            context->waveform, enabled, &control_word) ||
        !SPIWrite16(spi, &control_word, 1U)) {
        return false;
    }

    context->control_shadow = control_word;
    context->enabled        = enabled;
    return true;
}

/* 使用 64 位四舍五入运算生成低 14 位在前的频率寄存器字。 */
static bool AD9833BuildFrequencyWords(uint32_t reference_clock_hz,
    uint32_t frequency_hz, uint16_t address, uint16_t words[2])
{
    uint64_t scaled_frequency;
    uint32_t tuning_word;

    if ((reference_clock_hz == 0U) ||
        (reference_clock_hz > AD9833_MAXIMUM_REFERENCE_CLOCK_HZ) ||
        (frequency_hz == 0U) ||
        (frequency_hz > (reference_clock_hz / 2U)) ||
        (words == NULL)) {
        return false;
    }

    scaled_frequency = ((uint64_t)frequency_hz *
        AD9833_TUNING_MODULUS) + (reference_clock_hz / 2U);
    tuning_word = (uint32_t)(scaled_frequency / reference_clock_hz);

    words[0] = address |
               (uint16_t)(tuning_word & AD9833_FREQUENCY_MASK);
    words[1] = address |
               (uint16_t)((tuning_word >> 14U) &
                          AD9833_FREQUENCY_MASK);
    return true;
}

/* 将 0～359 度四舍五入到 AD9833 的 4096 个相位步进。 */
static bool AD9833BuildPhaseWord(
    uint16_t phase_degrees, uint16_t address, uint16_t *word)
{
    uint32_t phase_word;

    if ((phase_degrees >= AD9833_FULL_CIRCLE_DEGREES) ||
        (word == NULL)) {
        return false;
    }

    phase_word = (((uint32_t)phase_degrees * AD9833_PHASE_STEPS) +
                     (AD9833_FULL_CIRCLE_DEGREES / 2U)) /
                 AD9833_FULL_CIRCLE_DEGREES;
    *word = address | (uint16_t)(phase_word & AD9833_PHASE_MASK);
    return true;
}

/* 从影子控制字安全地重建波形、复位和休眠相关控制位。 */
static bool AD9833BuildControlWord(uint16_t base_control,
    DDSWaveform_e waveform, bool enabled, uint16_t *control_word)
{
    uint16_t control;

    if ((waveform < DDS_WAVEFORM_SINE) ||
        (waveform >= DDS_WAVEFORM_COUNT) ||
        (control_word == NULL)) {
        return false;
    }

    control = base_control &
              (uint16_t)~(AD9833_CONTROL_RESET |
                          AD9833_CONTROL_SLEEP1 |
                          AD9833_CONTROL_SLEEP12 |
                          AD9833_CONTROL_OPBITEN |
                          AD9833_CONTROL_DIV2 |
                          AD9833_CONTROL_MODE);
    control |= AD9833_CONTROL_B28;

    if (waveform == DDS_WAVEFORM_TRIANGLE) {
        control |= AD9833_CONTROL_MODE;
    } else if (waveform == DDS_WAVEFORM_SQUARE) {
        control |= AD9833_CONTROL_OPBITEN |
                   AD9833_CONTROL_DIV2 |
                   AD9833_CONTROL_SLEEP12;
    }

    if (!enabled) {
        control |= AD9833_CONTROL_RESET |
                   AD9833_CONTROL_SLEEP1 |
                   AD9833_CONTROL_SLEEP12;
    }

    *control_word = control;
    return true;
}

/* AD9833 无读回接口，只能检查软件上下文和 SPI 句柄。 */
static bool AD9833ContextIsValid(const AD9833Context *context,
    const SPIInstance *spi)
{
    return (context != NULL) && context->initialized && (spi != NULL);
}

#endif /* AD9833/AD9850 driver set */
