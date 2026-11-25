/* Authored mixes, packets and samples around the actual effect bodies and setters. No audio device or game is opened.
   Run with HOS_AUDIO_EFFECTS=0 it checks that every effect leaves the samples as they were. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint64_t x[32]; uint8_t vreg[32][16]; } Ctx;
static _Alignas(8) uint8_t guest[65536];
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
static void *guest_ptr(uint64_t address) { CHECK(address < sizeof guest); return guest + address; }
#define GP(a) guest_ptr(a)
#define G64(a) (*(uint64_t *)GP(a))
#define G32(a) (*(uint32_t *)GP(a))
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define HLE(sym) void imp_##sym(Ctx *c)
#define AUT(...) ((void)0)

/* Single-threaded test boundaries: the lock is checked for balance only. */
static int lock_depth;
static void au_lock(void) { CHECK(lock_depth++ == 0); }
static void au_unlock(void) { CHECK(--lock_depth == 0); }

#include "actual_audio_effects.inc"

/* the voice's source: one authored sample a frame (render_voice's resampler at 1.0 hands them through a frame late) */
static float tone[4096];
static int tone_pos;
static int silent_voice = -1;   /* (this voice plays silence) */
static int next_source_frame(Voice *v) {
    if (v - voices == silent_voice) { v->cur[0] = 0; return 1; }
    v->cur[0] = tone[tone_pos++ % 4096];
    return 1;
}

#define PI 3.14159265358979f
enum { CONFIG = 0x10, MIX0 = 0x40, MIX1 = 0x50, BQ = 0x100, DL = 0x110, RV = 0x120, SPLIT = 0x130, PACKET = 0x200,
       IN_CH = 0x300, OUT_CH = 0x310, BUFFER = 0x1000 };
static int effects;   /* (HOS_AUDIO_EFFECTS: what this run expects) */

static Ctx call(uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3, uint64_t a4, uint64_t a5, uint64_t a6) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = a0; c.x[1] = a1; c.x[2] = a2; c.x[3] = a3; c.x[4] = a4; c.x[5] = a5; c.x[6] = a6;
    return c;
}
static Ctx with_float(uint64_t obj, float f) {
    Ctx c = call(obj, 0, 0, 0, 0, 0, 0);
    memcpy(&c.vreg[0][0], &f, 4);
    return c;
}
static void reset(void) {
    memset(guest, 0, sizeof guest);
    memset(mixes, 0, sizeof mixes);
    memset(splitters, 0, sizeof splitters);
    memset(voices, 0, sizeof voices);
    memset(biquads, 0, sizeof biquads);
    for (int e = 0; e < MAX_FX; e++) free(delays[e].line);
    memset(delays, 0, sizeof delays);
    memset(reverbs, 0, sizeof reverbs);
    ncmds = 0;
    for (int m = 0; m < 2; m++) mixes[m].used = 1, mixes[m].buffers = 2, mixes[m].volume = 1.0f;
    put_handle(MIX0, K_MIX, 0);
    put_handle(MIX1, K_MIX, 1);
}
static void channels(const int8_t *in, const int8_t *out, int n) {
    memcpy(GP(IN_CH), in, (size_t)n);
    memcpy(GP(OUT_CH), out, (size_t)n);
}
static void float_packet(int on, const float coefs[5]) {
    uint8_t packet[24];
    memset(packet, 0xa5, sizeof packet);
    packet[0] = (uint8_t)on;
    memcpy(packet + 4, coefs, 5 * sizeof *coefs);
    memcpy(GP(PACKET), packet, sizeof packet);
}
static float rms(const float *x, int n) {
    double e = 0;
    for (int i = 0; i < n; i++) e += (double)x[i] * x[i];
    return (float)sqrt(e / n);
}

/* ---- biquad filter: a Butterworth low pass at 1 kHz (the cookbook's, its denominator added and over a0) ---------- */
static void lowpass(float f0, float out[5]) {
    const float w = 2 * PI * f0 / RATE, alpha = sinf(w) / (2 * 0.7071068f), a0 = 1 + alpha;
    out[0] = (1 - cosf(w)) / 2 / a0;
    out[1] = (1 - cosf(w)) / a0;
    out[2] = out[0];
    out[3] = 2 * cosf(w) / a0;          /* (-a1 / a0) */
    out[4] = -(1 - alpha) / a0;         /* (-a2 / a0) */
}
static float biquad_tone(float hz) {   /* the filtered tone's level against its own, after it has settled */
    reset();
    Ctx c = call(CONFIG, BQ, MIX0, 0, 0, 0, 0);
    imp__ZN2nn5audio15AddBiquadFilterEPNS0_19AudioRendererConfigEPNS0_16BiquadFilterTypeEPNS0_10SubMixTypeE(&c);
    CHECK(c.x[0] == 0);
    channels((const int8_t[]){0, 1}, (const int8_t[]){0, 1}, 2);
    c = call(BQ, IN_CH, OUT_CH, 2, 0, 0, 0);
    imp__ZN2nn5audio26SetBiquadFilterInputOutputEPNS0_16BiquadFilterTypeEPKaS4_i(&c);
    float coefs[5];
    lowpass(1000, coefs);
    float_packet(1, coefs);
    c = call(BQ, PACKET, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio24SetBiquadFilterParameterEPNS0_16BiquadFilterTypeERKNS0_22TBiquadFilterParameterIfEE(&c);
    memset(GP(PACKET), 0xa5, 24);   /* (the game's packet is its own again at once) */
    c = call(BQ, 1, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio22SetBiquadFilterEnabledEPNS0_16BiquadFilterTypeEb(&c);
    c = call(BQ, 0, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio21IsBiquadFilterEnabledEPKNS0_16BiquadFilterTypeE(&c);
    CHECK(c.x[0] == 1);
    float in = 0, out = 0;
    for (int frame = 0; frame < 20; frame++) {
        for (int i = 0; i < FRAME; i++) {
            const float s = sinf(2 * PI * hz * (float)(frame * FRAME + i) / RATE);
            mixes[0].buf[0][i] = s;
            mixes[0].buf[1][i] = 0.5f * s;
        }
        if (frame == 19) in = rms(mixes[0].buf[0], FRAME);
        effects_frame(0);
        if (frame == 19) {
            out = rms(mixes[0].buf[0], FRAME);
            CHECK(fabsf(rms(mixes[0].buf[1], FRAME) - 0.5f * out) < 0.001f);   /* (each channel its own filter) */
        }
    }
    return out / in;
}
static void biquad(void) {
    const float low = biquad_tone(200), high = biquad_tone(10000);
    if (!effects) { CHECK(low == 1.0f && high == 1.0f); return; }
    CHECK(low > 0.95f && low < 1.05f);
    CHECK(high < 0.02f);   /* (two poles: 40 dB down a decade above) */
    /* disabled: the buffers as they came */
    Ctx c = call(BQ, 0, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio22SetBiquadFilterEnabledEPNS0_16BiquadFilterTypeEb(&c);
    for (int i = 0; i < FRAME; i++) mixes[0].buf[0][i] = (float)(i % 7) - 3.0f;
    effects_frame(0);
    for (int i = 0; i < FRAME; i++) CHECK(mixes[0].buf[0][i] == (float)(i % 7) - 3.0f);
}

/* ---- delay: 3 ms (144 frames), in gain 0.5, feedback 0.5 ---------------------------------------------------------- */
static void add_delay_on_mix0(float spread, float lowpass_amount) {
    reset();
    Ctx c = call(CONFIG, DL, BUFFER, 0x10000, MIX0, 10000000, 2);   /* (10 ms at most, 2 channels) */
    imp__ZN2nn5audio8AddDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPvmPNS0_10SubMixTypeENS_8TimeSpanEi(&c);
    CHECK(c.x[0] == 0);
    channels((const int8_t[]){0, 1}, (const int8_t[]){0, 1}, 2);
    c = call(DL, IN_CH, OUT_CH, 2, 0, 0, 0);
    imp__ZN2nn5audio19SetDelayInputOutputEPNS0_9DelayTypeEPKaS4_i(&c);
    c = call(DL, 3000000, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio12SetDelayTimeEPNS0_9DelayTypeENS_8TimeSpanE(&c);
    c = call(DL, 0, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio12GetDelayTimeEPKNS0_9DelayTypeE(&c);
    CHECK(c.x[0] == 3000000);
    c = with_float(DL, 0.5f); imp__ZN2nn5audio14SetDelayInGainEPNS0_9DelayTypeEf(&c);
    c = with_float(DL, 0.5f); imp__ZN2nn5audio20SetDelayFeedbackGainEPNS0_9DelayTypeEf(&c);
    c = with_float(DL, 1.0f); imp__ZN2nn5audio15SetDelayDryGainEPNS0_9DelayTypeEf(&c);
    c = with_float(DL, spread); imp__ZN2nn5audio21SetDelayChannelSpreadEPNS0_9DelayTypeEf(&c);
    c = with_float(DL, lowpass_amount); imp__ZN2nn5audio21SetDelayLowPassAmountEPNS0_9DelayTypeEf(&c);
    c = call(DL, 1, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio15SetDelayEnabledEPNS0_9DelayTypeEb(&c);
    c = call(DL, 0, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio14IsDelayEnabledEPKNS0_9DelayTypeE(&c);
    CHECK(c.x[0] == 1);
}
static void run_impulse(float out[2][4 * FRAME]) {   /* an impulse in channel 0 at frame 0, four frames out */
    for (int frame = 0; frame < 4; frame++) {
        memset(mixes[0].buf, 0, sizeof mixes[0].buf);
        if (frame == 0) mixes[0].buf[0][0] = 1.0f;
        effects_frame(0);
        for (int ch = 0; ch < 2; ch++) memcpy(out[ch] + frame * FRAME, mixes[0].buf[ch], FRAME * sizeof(float));
    }
}
static void close_to(float actual, float expected) { CHECK(fabsf(actual - expected) < 0.00001f); }
static void delay(void) {
    static float out[2][4 * FRAME];
    add_delay_on_mix0(0, 0);
    run_impulse(out);
    if (!effects) {
        for (int i = 0; i < 4 * FRAME; i++) CHECK(out[0][i] == (i == 0) && out[1][i] == 0);
        return;
    }
    /* the dry impulse, then echoes every 144 frames (across the frames' edges), each the feedback gain x 0.98 of the
       one before; nothing in between and nothing in the other channel */
    const float fb = 0.5f * 0.98f;
    for (int i = 0; i < 4 * FRAME; i++) {
        const float want = i == 0 ? 1.0f : i % 144 == 0 ? 0.5f * powf(fb, (float)(i / 144 - 1)) : 0.0f;
        close_to(out[0][i], want);
        CHECK(out[1][i] == 0);
    }
    /* the whole spread: each echo in the other channel than the one before */
    add_delay_on_mix0(1, 0);
    run_impulse(out);
    close_to(out[0][144], 0.5f); close_to(out[1][144], 0);
    close_to(out[1][288], 0.5f * fb); close_to(out[0][288], 0);
    close_to(out[0][432], 0.5f * fb * fb); close_to(out[1][432], 0);
    /* the low pass: the echo's first frame 1 - 0.95 x amount of it, the rest after it */
    add_delay_on_mix0(0, 0.5f);
    run_impulse(out);
    close_to(out[0][144], 0.5f * (1 - 0.475f));
    CHECK(out[0][145] > 0 && out[0][145] < out[0][144]);
    /* off: the buffers as they came */
    Ctx c = call(DL, 0, 0, 0, 0, 0, 0);
    imp__ZN2nn5audio15SetDelayEnabledEPNS0_9DelayTypeEb(&c);
    run_impulse(out);
    for (int i = 0; i < 4 * FRAME; i++) CHECK(out[0][i] == (i == 0) && out[1][i] == 0);
    /* removed: the game's buffer back, the handle gone */
    c = call(CONFIG, DL, MIX0, 0, 0, 0, 0);
    imp__ZN2nn5audio11RemoveDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPNS0_10SubMixTypeE(&c);
    CHECK(c.x[0] == BUFFER && G64(DL) == 0 && !delays[0].used);
}

/* ---- plain reverb: a tail after the dry impulse, and the dry signal alone at out gain 0 ------------------------- */
static void reverb(void) {
    reset();
    Ctx c = call(CONFIG, RV, BUFFER, 0x10000, MIX0, 2, 0);
    imp__ZN2nn5audio9AddReverbEPNS0_19AudioRendererConfigEPNS0_10ReverbTypeEPvmPNS0_10SubMixTypeEi(&c);
    CHECK(c.x[0] == 0);
    c = call(RV, 2, 0, 0, 0, 0, 0); imp__ZN2nn5audio18SetReverbEarlyModeEPNS0_10ReverbTypeENS1_9EarlyModeE(&c);
    c = call(RV, 1, 0, 0, 0, 0, 0); imp__ZN2nn5audio17SetReverbLateModeEPNS0_10ReverbTypeENS1_8LateModeE(&c);
    c = call(RV, 1500000000, 0, 0, 0, 0, 0); imp__ZN2nn5audio18SetReverbDecayTimeEPNS0_10ReverbTypeENS_8TimeSpanE(&c);
    c = call(RV, 10000000, 0, 0, 0, 0, 0); imp__ZN2nn5audio21SetReverbPredelayTimeEPNS0_10ReverbTypeENS_8TimeSpanE(&c);
    c = with_float(RV, 0.6f); imp__ZN2nn5audio18SetReverbEarlyGainEPNS0_10ReverbTypeEf(&c);
    c = with_float(RV, 0.6f); imp__ZN2nn5audio17SetReverbLateGainEPNS0_10ReverbTypeEf(&c);
    c = with_float(RV, 0.8f); imp__ZN2nn5audio19SetReverbReverbGainEPNS0_10ReverbTypeEf(&c);
    c = with_float(RV, 1.0f); imp__ZN2nn5audio16SetReverbOutGainEPNS0_10ReverbTypeEf(&c);
    c = with_float(RV, 0.5f); imp__ZN2nn5audio16SetReverbDryGainEPNS0_10ReverbTypeEf(&c);
    c = with_float(RV, 0.5f); imp__ZN2nn5audio32SetReverbHighFrequencyDecayRatioEPNS0_10ReverbTypeEf(&c);
    c = with_float(RV, 0.5f); imp__ZN2nn5audio19SetReverbColorationEPNS0_10ReverbTypeEf(&c);
    c = call(RV, 1, 0, 0, 0, 0, 0); imp__ZN2nn5audio16SetReverbEnabledEPNS0_10ReverbTypeEb(&c);
    c = call(RV, 0, 0, 0, 0, 0, 0); imp__ZN2nn5audio15IsReverbEnabledEPKNS0_10ReverbTypeE(&c);
    CHECK(c.x[0] == 1);
    static float out[2][4 * FRAME];
    run_impulse(out);
    if (!effects) {
        for (int i = 0; i < 4 * FRAME; i++) CHECK(out[0][i] == (i == 0) && out[1][i] == 0);
        return;
    }
    close_to(out[0][0], 0.5f);   /* (the dry gain; the wet part starts after the pre-delay) */
    float tail = 0;
    for (int i = 1; i < 4 * FRAME; i++) {
        CHECK(isfinite(out[0][i]) && isfinite(out[1][i]) && fabsf(out[0][i]) < 1 && fabsf(out[1][i]) < 1);
        tail += fabsf(out[0][i]) + fabsf(out[1][i]);
    }
    CHECK(tail > 0.05f);
    c = with_float(RV, 0.0f); imp__ZN2nn5audio16SetReverbOutGainEPNS0_10ReverbTypeEf(&c);
    run_impulse(out);
    for (int i = 0; i < 4 * FRAME; i++) { close_to(out[0][i], i == 0 ? 0.5f : 0.0f); CHECK(out[1][i] == 0); }
}

/* ---- a splitter destination's filter, through render_voice to the destination's mix ---------------------------- */
static float splitter_level(int filter_on) {
    reset();
    Splitter *s = &splitters[0];
    s->used = 1; s->channels = 1; s->dests = 1; s->dest_mix[0] = 1;
    s->vol[0][0][0] = s->ramp[0][0][0] = 1.0f;
    put_handle(SPLIT, K_SPLITTER, 0);
    /* a one-pole low pass, y = 0.1 x + 0.9 y': a tone at half the rate comes out at 0.1 / 1.9 */
    float_packet(filter_on, (const float[]){0.1f, 0, 0, 0.9f, 0});
    Ctx c = call(SPLIT, 0, MIX1, 1, PACKET, 0, 0);
    imp__ZN2nn5audio32SetSplitterBiquadFilterParameterEPNS0_12SplitterTypeEiPNS0_10SubMixTypeEiRKNS0_22TBiquadFilterParameterIfEE(&c);
    CHECK(ncmds == 1 && !s->bq_on[0][1]);   /* (queued, applied at the update) */
    commit();
    CHECK(s->bq_on[0][1] == filter_on && !s->bq_on[0][0]);
    Voice *v = &voices[0];
    v->used = 1; v->channels = 1; v->rate = RATE; v->pitch = 1; v->volume = v->ramp_volume = 1;
    v->state = PLAY_STARTED; v->dest_kind = DEST_SPLITTER; v->dest = 0;
    for (int i = 0; i < 4096; i++) tone[i] = i & 1 ? -1.0f : 1.0f;
    tone_pos = 0;
    float level = 0;
    for (int frame = 0; frame < 10; frame++) {
        memset(mixes[1].buf, 0, sizeof mixes[1].buf);
        render_voice(v);
        level = rms(mixes[1].buf[0] + 16, FRAME - 16);
    }
    return level;
}
/* Two voices through one splitter destination with its low pass on: the filter's history is each voice's own. The
   first plays a steady 1.0, the second silence: with one history in the splitter the second voice's samples came out of
   the first one's filter state, and the first one's level was taken down by the second's zeros */
static void splitter_voices(void) {
    reset();
    Splitter *s = &splitters[0];
    s->used = 1; s->channels = 1; s->dests = 1; s->dest_mix[0] = 1;
    s->vol[0][0][0] = s->ramp[0][0][0] = 1.0f;
    put_handle(SPLIT, K_SPLITTER, 0);
    float_packet(1, (const float[]){0.1f, 0, 0, 0.9f, 0});
    Ctx c = call(SPLIT, 0, MIX1, 0, PACKET, 0, 0);
    imp__ZN2nn5audio32SetSplitterBiquadFilterParameterEPNS0_12SplitterTypeEiPNS0_10SubMixTypeEiRKNS0_22TBiquadFilterParameterIfEE(&c);
    commit();
    for (int k = 0; k < 2; k++) {
        Voice *v = &voices[k];
        v->used = 1; v->channels = 1; v->rate = RATE; v->pitch = 1; v->volume = v->ramp_volume = 1;
        v->state = PLAY_STARTED; v->dest_kind = DEST_SPLITTER; v->dest = 0;
    }
    for (int i = 0; i < 4096; i++) tone[i] = 1.0f;
    tone_pos = 0;
    silent_voice = 1;
    float first = 0;
    for (int frame = 0; frame < 10; frame++) {
        memset(mixes[1].buf, 0, sizeof mixes[1].buf);
        render_voice(&voices[0]);
        first = mixes[1].buf[0][FRAME - 1];
        memset(mixes[1].buf, 0, sizeof mixes[1].buf);
        render_voice(&voices[1]);
        for (int i = 0; i < FRAME; i++) CHECK(mixes[1].buf[0][i] == 0.0f);   /* (silence in, silence out) */
    }
    silent_voice = -1;
    CHECK(fabsf(first - 1.0f) < 0.001f);   /* (a steady 1.0 through y = 0.1 x + 0.9 y' settles at 1.0, filtered or not) */
    /* the filter turned off and on again starts over in the voices: nothing of the level it had settled at */
    float_packet(0, (const float[]){0.1f, 0, 0, 0.9f, 0});
    c = call(SPLIT, 0, MIX1, 0, PACKET, 0, 0);
    imp__ZN2nn5audio32SetSplitterBiquadFilterParameterEPNS0_12SplitterTypeEiPNS0_10SubMixTypeEiRKNS0_22TBiquadFilterParameterIfEE(&c);
    float_packet(1, (const float[]){0.1f, 0, 0, 0.9f, 0});
    c = call(SPLIT, 0, MIX1, 0, PACKET, 0, 0);
    imp__ZN2nn5audio32SetSplitterBiquadFilterParameterEPNS0_12SplitterTypeEiPNS0_10SubMixTypeEiRKNS0_22TBiquadFilterParameterIfEE(&c);
    commit();
    memset(mixes[1].buf, 0, sizeof mixes[1].buf);
    render_voice(&voices[0]);
    if (effects) CHECK(fabsf(mixes[1].buf[0][0] - 0.1f) < 0.001f);
    else CHECK(fabsf(mixes[1].buf[0][0] - 1.0f) < 0.001f);
}
static void splitter(void) {
    const float plain = splitter_level(0), filtered = splitter_level(1);
    CHECK(fabsf(plain - 1.0f) < 0.0001f);
    if (!effects) CHECK(filtered == plain);
    else CHECK(fabsf(filtered - 0.1f / 1.9f) < 0.001f);
    splitter_voices();
}

int main(void) {
    const char *e = getenv("HOS_AUDIO_EFFECTS");
    effects = !(e && atoi(e) == 0);
    CHECK(effects_on() == effects);
    biquad();
    delay();
    reverb();
    splitter();
    reset();
    free(cmds);
    printf("PASS (%s): biquad low pass, delay echo/feedback/spread/low pass, plain reverb tail, splitter filter\n",
           effects ? "effects on" : "HOS_AUDIO_EFFECTS=0: samples unchanged");
    return 0;
}
