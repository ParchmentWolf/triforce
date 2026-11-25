/* (Triforce) The Audio tab's Microphone gain row: the microphone's samples made louder or quieter before the game's input
   streams get them (host/nn_audio_in.c pump), for a microphone too quiet for the ocarina's notes to be heard, or too loud.
   The rule alone, for tests/test_play_rows.py. */
#pragma once

#include <math.h>
#include <stdint.h>
#include <string.h>

enum { MIC_GAIN_PCM8 = 1, MIC_GAIN_PCM16 = 2, MIC_GAIN_PCM32 = 4, MIC_GAIN_FLOAT = 5 };   /* (host/nn_audio_in.c's FMT_*) */

/* bytes of samples of that format (little-endian, signed; float in -1 to 1), in place, at percent of what the microphone
   gave: 0 silence to 400, four times. 1 when a sample had to be held at full scale (it clipped). At 100, the default, and
   for a percent outside the row or a format that is none of these, nothing is read or written: the samples are the
   microphone's own, bit for bit. Read and written through memcpy: the buffer need not be aligned for them */
/* ((Triforce) 11-24) the loudest sample of bytes of that format, in thousandths of full scale (0 to 1000): the Test
   microphone row's level (host/nn_audio_in.c hos_mic_test) */
static inline int mic_peak_permille(int format, const uint8_t *buf, int bytes) {
    const int width = format == MIC_GAIN_PCM8 ? 1 : format == MIC_GAIN_PCM16 ? 2 : format == MIC_GAIN_PCM32 || format == MIC_GAIN_FLOAT ? 4 : 0;
    double most = 0, full = 1.0;
    for (int at = 0; width && at + width <= bytes; at += width) {
        double value;
        if (format == MIC_GAIN_FLOAT) {
            float v;
            memcpy(&v, buf + at, 4);
            value = isfinite(v) ? v : 0.0, full = 1.0;
        } else if (width == 1) {
            int8_t v;
            memcpy(&v, buf + at, 1);
            value = v, full = 128.0;
        } else if (width == 2) {
            int16_t v;
            memcpy(&v, buf + at, 2);
            value = v, full = 32768.0;
        } else {
            int32_t v;
            memcpy(&v, buf + at, 4);
            value = v, full = 2147483648.0;
        }
        if (value < 0) value = -value;
        if (value > most) most = value;
    }
    const int permille = (int)(most * 1000.0 / full);
    return permille > 1000 ? 1000 : permille;
}
static inline int mic_gain_apply(int format, uint8_t *buf, int bytes, int percent) {
    if (percent == 100 || percent < 0 || percent > 400) return 0;
    const int width = format == MIC_GAIN_PCM8 ? 1 : format == MIC_GAIN_PCM16 ? 2 : format == MIC_GAIN_PCM32 || format == MIC_GAIN_FLOAT ? 4 : 0;
    if (!width) return 0;
    int clipped = 0;
    for (int at = 0; at + width <= bytes; at += width) {
        double value, lo, hi;
        if (format == MIC_GAIN_FLOAT) {
            float v;
            memcpy(&v, buf + at, 4);
            value = isfinite(v) ? v : 0.0, lo = -1.0, hi = 1.0;
        } else if (width == 1) {
            int8_t v;
            memcpy(&v, buf + at, 1);
            value = v, lo = -128.0, hi = 127.0;
        } else if (width == 2) {
            int16_t v;
            memcpy(&v, buf + at, 2);
            value = v, lo = -32768.0, hi = 32767.0;
        } else {
            int32_t v;
            memcpy(&v, buf + at, 4);
            value = v, lo = -2147483648.0, hi = 2147483647.0;
        }
        double out = value * percent / 100.0;
        if (out > hi) out = hi, clipped = 1;
        if (out < lo) out = lo, clipped = 1;
        if (format == MIC_GAIN_FLOAT) {
            const float v = (float)out;
            memcpy(buf + at, &v, 4);
        } else if (width == 1) {
            const int8_t v = (int8_t)out;
            memcpy(buf + at, &v, 1);
        } else if (width == 2) {
            const int16_t v = (int16_t)out;
            memcpy(buf + at, &v, 2);
        } else {
            const int32_t v = (int32_t)out;
            memcpy(buf + at, &v, 4);
        }
    }
    return clipped;
}
