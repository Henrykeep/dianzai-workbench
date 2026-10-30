/* pal_adc_block_read 的唯一实现，四个端口各自 #include 一次（PAL 1.6.0）。只用 pal_micros / pal_delay_us / pal_adc_read。 */
dz_err_t pal_adc_block_read(pal_id_t id, uint16_t *buf, uint16_t n, uint32_t rate_hz)
{
    if (buf == 0 || n == 0u || rate_hz == 0u || rate_hz > PAL_ADC_BLOCK_MAX_HZ || (1000000u % rate_hz) != 0u)
        return DZ_EINVAL;
    const uint32_t per = 1000000u / rate_hz;
    uint16_t dummy;
    dz_err_t e = pal_adc_read(id, &dummy);              /* 先确认 id 有效、通道可用 */
    if (e != DZ_OK) return e;
    const uint32_t t0 = pal_micros();
    for (uint32_t i = 0; i < n; i++) {
        const uint32_t due = i * per;
        uint32_t el = pal_micros() - t0;
        if (el < due) { pal_delay_us(due - el); el = pal_micros() - t0; }
        if (el >= due + per) return DZ_ETIMEOUT;        /* 迟到超过一个周期：采样率不可信 */
        e = pal_adc_read(id, &buf[i]);
        if (e != DZ_OK) return e;
    }
    return DZ_OK;
}
