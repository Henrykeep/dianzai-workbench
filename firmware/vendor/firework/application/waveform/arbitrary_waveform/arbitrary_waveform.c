/*
 * 任意波形服务把 Flash 槽位当作带版本、序号和 CRC 的小型记录区。
 * 运行时只装载一个播放缓冲区，保存/加载过程用互斥量保护共享资源。
 */
#include "application/waveform/arbitrary_waveform/arbitrary_waveform.h"

#include "application/app_config.h"

#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U

#include <stddef.h>
#include <string.h>

#include "FreeRTOS.h"
#include "semphr.h"

#include "bsp/bsp.h"
#include "modules/dac/dac_output.h"

/*
 * 每个槽位占连续三个 1 KiB 主 Flash 扇区：前 64 字节为头，其余保存采样点。
 * 槽位步长固定，修改布局时必须同步考虑链接地址和最大采样点数。
 */
#define ARBITRARY_WAVEFORM_MAGIC       (UINT32_C(0x41525746))
#define ARBITRARY_WAVEFORM_VERSION     (1U)
#define ARBITRARY_WAVEFORM_FLASH_BASE  (UINT32_C(0x0001DC00))
#define ARBITRARY_WAVEFORM_SLOT_STRIDE (UINT32_C(0x00000C00))
#define ARBITRARY_WAVEFORM_HEADER_SIZE (UINT32_C(64))
#define ARBITRARY_WAVEFORM_SECTOR_SIZE (UINT32_C(1024))
#define ARBITRARY_WAVEFORM_SLOT_SECTORS (3U)

/* 64 字节固定头；crc32 覆盖元数据和采样数据，写头放在最后以防掉电半写。 */
typedef struct {
    uint32_t magic;
    uint16_t version;
    uint8_t slot_id;
    uint8_t reserved0;
    uint16_t sample_count;
    uint16_t cycle_count;
    uint32_t sample_rate_hz;
    uint32_t actual_frequency_millihz;
    uint16_t minimum_raw;
    uint16_t maximum_raw;
    uint32_t crc32;
    uint32_t sequence;
    uint32_t reserved[8];
} ArbitraryWaveformFlashHeader;

typedef char ArbitraryWaveformHeaderMustBe64Bytes[
    (sizeof(ArbitraryWaveformFlashHeader) == 64U) ? 1 : -1];

/* Flash 擦写和唯一 DAC 自定义缓冲区共用同一把互斥量串行化。 */
static SemaphoreHandle_t arbitrary_waveform_mutex;
static StaticSemaphore_t arbitrary_waveform_mutex_control;
static bool arbitrary_waveform_initialized;
static uint32_t arbitrary_waveform_sequence;

static bool ArbitraryWaveformLock(void);
static void ArbitraryWaveformUnlock(void);
static bool ArbitraryWaveformSlotIsValid(uint8_t slot_id);
static uint32_t ArbitraryWaveformSlotAddress(uint8_t slot_id);
static const ArbitraryWaveformFlashHeader *
    ArbitraryWaveformGetFlashHeader(uint8_t slot_id);
static const uint16_t *ArbitraryWaveformGetFlashSamples(uint8_t slot_id,
    uint16_t sample_count);
static uint32_t ArbitraryWaveformCRC32Update(uint32_t crc,
    const uint8_t *data, size_t size);
static uint32_t ArbitraryWaveformCalculateCRC(
    const ArbitraryWaveformFlashHeader *header, const uint16_t *samples);
static bool ArbitraryWaveformHeaderIsValid(uint8_t slot_id,
    const ArbitraryWaveformFlashHeader *header);
static bool ArbitraryWaveformSampleRateIsSupported(uint32_t sample_rate_hz);
static bool ArbitraryWaveformEraseSlot(uint8_t slot_id);
static bool ArbitraryWaveformProgramWords(uint32_t address,
    const uint16_t *data, uint16_t word_count);
static void ArbitraryWaveformFillInfo(uint8_t slot_id,
    const ArbitraryWaveformFlashHeader *header, ArbitraryWaveformInfo *info);

bool ArbitraryWaveformInit(void)
{
    uint8_t slot;

    if (arbitrary_waveform_initialized) {
        return true;
    }
    if (arbitrary_waveform_mutex == NULL) {
        arbitrary_waveform_mutex = xSemaphoreCreateMutexStatic(
            &arbitrary_waveform_mutex_control);
        if (arbitrary_waveform_mutex == NULL) {
            return false;
        }
    }
    /* 启动时恢复最大记录序号，后续写入仍保持单调递增。 */
    arbitrary_waveform_sequence = 0U;
    for (slot = 0U; slot < APP_ARBITRARY_WAVEFORM_SLOT_COUNT; ++slot) {
        const ArbitraryWaveformFlashHeader *header =
            ArbitraryWaveformGetFlashHeader(slot);
        if (ArbitraryWaveformHeaderIsValid(slot, header) &&
            (header->sequence > arbitrary_waveform_sequence)) {
            arbitrary_waveform_sequence = header->sequence;
        }
    }
    arbitrary_waveform_initialized = true;
    return true;
}

bool ArbitraryWaveformSave(uint8_t slot_id, const uint16_t *samples,
    uint16_t sample_count, uint32_t sample_rate_hz, uint16_t cycle_count)
{
    ArbitraryWaveformFlashHeader header;
    uint16_t index;
    uint16_t minimum_raw = UINT16_MAX;
    uint16_t maximum_raw = 0U;
    uint16_t *buffer;
    uint16_t flash_sample_count;
    bool result = false;

    if (!ArbitraryWaveformLock() || !ArbitraryWaveformSlotIsValid(slot_id) ||
        (samples == NULL) || (sample_count < 2U) ||
        (sample_count > APP_ARBITRARY_WAVEFORM_MAX_SAMPLES) ||
        (cycle_count == 0U) || (cycle_count > (sample_count / 2U)) ||
        !ArbitraryWaveformSampleRateIsSupported(sample_rate_hz)) {
        if (arbitrary_waveform_mutex != NULL) {
            ArbitraryWaveformUnlock();
        }
        return false;
    }

    for (index = 0U; index < sample_count; ++index) {
        if (samples[index] > 4095U) {
            ArbitraryWaveformUnlock();
            return false;
        }
        if (samples[index] < minimum_raw) {
            minimum_raw = samples[index];
        }
        if (samples[index] > maximum_raw) {
            maximum_raw = samples[index];
        }
    }

    /* 修改 Flash 槽位前停止 DMA，避免输出端和存储操作同时进行。 */
    (void)DACOutputStop();
    buffer = DACOutputGetCustomWaveformBuffer();
    if (buffer == NULL) {
        ArbitraryWaveformUnlock();
        return false;
    }
    /* Flash 按 64 位写入；尾部补 0xFFFF，但头部仍记录真实点数。 */
    flash_sample_count = (uint16_t)((sample_count + 3U) & ~3U);
    if (flash_sample_count > APP_ARBITRARY_WAVEFORM_MAX_SAMPLES) {
        ArbitraryWaveformUnlock();
        return false;
    }
    /* FromRAM 编程接口的源数据必须位于 SRAM；同时不增加第二份缓冲区。 */
    (void)memcpy(buffer, samples,
        (size_t)sample_count * sizeof(uint16_t));
    (void)memset(&buffer[sample_count], 0xFF,
        (size_t)(flash_sample_count - sample_count) * sizeof(uint16_t));
    (void)memset(&header, 0, sizeof(header));
    header.magic = ARBITRARY_WAVEFORM_MAGIC;
    header.version = ARBITRARY_WAVEFORM_VERSION;
    header.slot_id = slot_id;
    header.sample_count = sample_count;
    header.cycle_count = cycle_count;
    header.sample_rate_hz = sample_rate_hz;
    header.actual_frequency_millihz = (uint32_t)(
        (((uint64_t)cycle_count * sample_rate_hz * 1000ULL) +
            (sample_count / 2U)) / sample_count);
    header.minimum_raw = minimum_raw;
    header.maximum_raw = maximum_raw;
    header.sequence = ++arbitrary_waveform_sequence;
    header.crc32 = ArbitraryWaveformCalculateCRC(&header, samples);

    /* 先写数据、最后写有效头；中途掉电时旧头已擦除，新记录不会被误认为有效。 */
    result = ArbitraryWaveformEraseSlot(slot_id) &&
        ArbitraryWaveformProgramWords(
            ArbitraryWaveformSlotAddress(slot_id) +
                ARBITRARY_WAVEFORM_HEADER_SIZE,
            buffer, flash_sample_count) &&
        ArbitraryWaveformProgramWords(
            ArbitraryWaveformSlotAddress(slot_id),
            (const uint16_t *)&header,
            (uint16_t)(sizeof(header) / sizeof(uint16_t)));
    ArbitraryWaveformUnlock();
    return result;
}

bool ArbitraryWaveformLoad(uint8_t slot_id)
{
    const ArbitraryWaveformFlashHeader *header;
    const uint16_t *samples;
    uint16_t *buffer;
    bool result;

    if (!ArbitraryWaveformLock() || !ArbitraryWaveformSlotIsValid(slot_id)) {
        if (arbitrary_waveform_mutex != NULL) {
            ArbitraryWaveformUnlock();
        }
        return false;
    }
    header = ArbitraryWaveformGetFlashHeader(slot_id);
    if (!ArbitraryWaveformHeaderIsValid(slot_id, header)) {
        ArbitraryWaveformUnlock();
        return false;
    }
    buffer = DACOutputGetCustomWaveformBuffer();
    samples = ArbitraryWaveformGetFlashSamples(slot_id,
        header->sample_count);
    if ((buffer == NULL) || (samples == NULL)) {
        ArbitraryWaveformUnlock();
        return false;
    }
    (void)DACOutputStop();
    (void)memcpy(buffer, samples,
        (size_t)header->sample_count * sizeof(uint16_t));
    result = true;
    ArbitraryWaveformUnlock();
    return result;
}

bool ArbitraryWaveformStart(uint8_t slot_id)
{
    const ArbitraryWaveformFlashHeader *header;
    bool result;

    if (!ArbitraryWaveformLoad(slot_id)) {
        return false;
    }
    if (!ArbitraryWaveformLock()) {
        return false;
    }
    header = ArbitraryWaveformGetFlashHeader(slot_id);
    result = DACOutputStartCustomWaveform(header->sample_count,
        header->sample_rate_hz, header->cycle_count);
    ArbitraryWaveformUnlock();
    return result;
}

bool ArbitraryWaveformStop(void)
{
    if (!ArbitraryWaveformLock()) {
        return false;
    }
    (void)DACOutputStop();
    ArbitraryWaveformUnlock();
    return true;
}

bool ArbitraryWaveformDelete(uint8_t slot_id)
{
    bool result;

    if (!ArbitraryWaveformLock() || !ArbitraryWaveformSlotIsValid(slot_id)) {
        if (arbitrary_waveform_mutex != NULL) {
            ArbitraryWaveformUnlock();
        }
        return false;
    }
    (void)DACOutputStop();
    result = ArbitraryWaveformEraseSlot(slot_id);
    ArbitraryWaveformUnlock();
    return result;
}

bool ArbitraryWaveformGetInfo(uint8_t slot_id, ArbitraryWaveformInfo *info)
{
    const ArbitraryWaveformFlashHeader *header;

    if (!ArbitraryWaveformLock() || !ArbitraryWaveformSlotIsValid(slot_id) ||
        (info == NULL)) {
        if (arbitrary_waveform_mutex != NULL) {
            ArbitraryWaveformUnlock();
        }
        return false;
    }
    header = ArbitraryWaveformGetFlashHeader(slot_id);
    if (!ArbitraryWaveformHeaderIsValid(slot_id, header)) {
        (void)memset(info, 0, sizeof(*info));
        info->slot_id = slot_id;
        ArbitraryWaveformUnlock();
        return false;
    }
    ArbitraryWaveformFillInfo(slot_id, header, info);
    ArbitraryWaveformUnlock();
    return true;
}

bool ArbitraryWaveformIsInitialized(void)
{
    return arbitrary_waveform_initialized;
}

static bool ArbitraryWaveformLock(void)
{
    return arbitrary_waveform_initialized &&
        (arbitrary_waveform_mutex != NULL) &&
        (xSemaphoreTake(arbitrary_waveform_mutex, portMAX_DELAY) == pdPASS);
}

static void ArbitraryWaveformUnlock(void)
{
    (void)xSemaphoreGive(arbitrary_waveform_mutex);
}

static bool ArbitraryWaveformSlotIsValid(uint8_t slot_id)
{
    return slot_id < APP_ARBITRARY_WAVEFORM_SLOT_COUNT;
}

static uint32_t ArbitraryWaveformSlotAddress(uint8_t slot_id)
{
    return ARBITRARY_WAVEFORM_FLASH_BASE +
        ((uint32_t)slot_id * ARBITRARY_WAVEFORM_SLOT_STRIDE);
}

static const ArbitraryWaveformFlashHeader *
    ArbitraryWaveformGetFlashHeader(uint8_t slot_id)
{
    return (const ArbitraryWaveformFlashHeader *)(uintptr_t)
        ArbitraryWaveformSlotAddress(slot_id);
}

static const uint16_t *ArbitraryWaveformGetFlashSamples(uint8_t slot_id,
    uint16_t sample_count)
{
    if ((sample_count < 2U) ||
        (sample_count > APP_ARBITRARY_WAVEFORM_MAX_SAMPLES)) {
        return NULL;
    }
    return (const uint16_t *)(uintptr_t)(
        ArbitraryWaveformSlotAddress(slot_id) +
        ARBITRARY_WAVEFORM_HEADER_SIZE);
}

/* 使用标准反射多项式逐字节累计 CRC-32，适合小型记录且不需要查表 RAM。 */
static uint32_t ArbitraryWaveformCRC32Update(uint32_t crc,
    const uint8_t *data, size_t size)
{
    size_t index;
    uint8_t bit;

    for (index = 0U; index < size; ++index) {
        crc ^= data[index];
        for (bit = 0U; bit < 8U; ++bit) {
            crc = (crc >> 1U) ^ (UINT32_C(0xEDB88320) &
                (uint32_t)-(int32_t)(crc & 1U));
        }
    }
    return crc;
}

static uint32_t ArbitraryWaveformCalculateCRC(
    const ArbitraryWaveformFlashHeader *header, const uint16_t *samples)
{
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    ArbitraryWaveformFlashHeader copy = *header;

    copy.crc32 = 0U;
    crc = ArbitraryWaveformCRC32Update(crc,
        (const uint8_t *)&copy, sizeof(copy));
    crc = ArbitraryWaveformCRC32Update(crc,
        (const uint8_t *)samples,
        (size_t)header->sample_count * sizeof(uint16_t));
    return ~crc;
}

/* 元数据范围和整份记录 CRC 均通过后，槽位才对加载与播放接口可见。 */
static bool ArbitraryWaveformHeaderIsValid(uint8_t slot_id,
    const ArbitraryWaveformFlashHeader *header)
{
    const uint16_t *samples;

    if ((header == NULL) || (header->magic != ARBITRARY_WAVEFORM_MAGIC) ||
        (header->version != ARBITRARY_WAVEFORM_VERSION) ||
        (header->slot_id != slot_id) || (header->sample_count < 2U) ||
        (header->sample_count > APP_ARBITRARY_WAVEFORM_MAX_SAMPLES) ||
        (header->cycle_count == 0U) ||
        (header->cycle_count > (header->sample_count / 2U)) ||
        !ArbitraryWaveformSampleRateIsSupported(header->sample_rate_hz)) {
        return false;
    }
    samples = ArbitraryWaveformGetFlashSamples(slot_id,
        header->sample_count);
    return (samples != NULL) &&
        (ArbitraryWaveformCalculateCRC(header, samples) == header->crc32);
}

static bool ArbitraryWaveformSampleRateIsSupported(uint32_t sample_rate_hz)
{
    switch (sample_rate_hz) {
        case 500UL:
        case 1000UL:
        case 2000UL:
        case 4000UL:
        case 8000UL:
        case 16000UL:
        case 100000UL:
        case 200000UL:
        case 500000UL:
        case 1000000UL:
            return true;
        default:
            return false;
    }
}

/* 一个逻辑槽跨三个物理扇区，任一扇区擦除失败即终止本次保存。 */
static bool ArbitraryWaveformEraseSlot(uint8_t slot_id)
{
    uint8_t sector;
    uint32_t address = ArbitraryWaveformSlotAddress(slot_id);

    for (sector = 0U; sector < ARBITRARY_WAVEFORM_SLOT_SECTORS; ++sector) {
        uint32_t sector_address = address +
            ((uint32_t)sector * ARBITRARY_WAVEFORM_SECTOR_SIZE);

        if (!BSPFlashEraseMainSector(sector_address)) {
            return false;
        }
    }
    return true;
}

/* BSP 每次按 64 位并带 ECC 编程，因此地址和字数都必须满足对应对齐。 */
static bool ArbitraryWaveformProgramWords(uint32_t address,
    const uint16_t *data, uint16_t word_count)
{
    uint16_t index;

    if ((data == NULL) || (word_count == 0U) || ((address & 7U) != 0U) ||
        ((word_count & 3U) != 0U)) {
        return false;
    }
    for (index = 0U; index < word_count; index = (uint16_t)(index + 4U)) {
        uint32_t source_words[2];

        /* 使用对齐的临时源，避免调用方缓冲区只有 4 字节对齐。 */
        (void)memcpy(source_words, &data[index], sizeof(source_words));
        if (!BSPFlashProgramMain64WithECC(address, source_words)) {
            return false;
        }
        address += sizeof(source_words);
    }
    return true;
}

static void ArbitraryWaveformFillInfo(uint8_t slot_id,
    const ArbitraryWaveformFlashHeader *header, ArbitraryWaveformInfo *info)
{
    info->slot_id = slot_id;
    info->sample_count = header->sample_count;
    info->sample_rate_hz = header->sample_rate_hz;
    info->cycle_count = header->cycle_count;
    info->actual_frequency_millihz = header->actual_frequency_millihz;
    info->minimum_raw = header->minimum_raw;
    info->maximum_raw = header->maximum_raw;
    info->crc32 = header->crc32;
    info->valid = true;
}

#endif /* APP_ENABLE_ARBITRARY_WAVEFORM */
