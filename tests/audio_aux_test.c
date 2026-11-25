/* The actual Aux entry points and effect code of host/nn_audio.c around authored memory and a worker that applies a
   known gain. No audio device or game is opened. Run with HOS_AUDIO_AUX=0 it checks that an Aux is accepted and passed
   through, as before. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; uint8_t vreg[32][16]; } Ctx;
typedef int CRITICAL_SECTION;
static void InitializeCriticalSection(int *lock) { *lock = 0; }
static void EnterCriticalSection(int *lock) { CHECK(!*lock); *lock = 1; }
static void LeaveCriticalSection(int *lock) { CHECK(*lock); *lock = 0; }
static void hos_log(const char *format, ...) { (void)format; }
/* (the fixture's "guest memory" is the host's own: an address is its pointer) */
static void *hos_guest_range(uint64_t a, uint64_t n) { (void)n; return (void *)(uintptr_t)a; }
#define HLE(name) void imp_##name(Ctx *c)
#define ARG(n) (c->x[n])
#define RET(value) (c->x[0] = (uint64_t)(value))
#define GP(value) ((void *)(uintptr_t)(value))
#define G64(value) (*(uint64_t *)GP(value))
#define G32(value) (*(uint32_t *)GP(value))
#include "audio_aux.inc"

#define AUX_ADD imp__ZN2nn5audio6AddAuxEPNS0_19AudioRendererConfigEPNS0_7AuxTypeEPNS0_10SubMixTypeEPvS7_m
#define AUX_COUNT imp__ZN2nn5audio17GetAuxSampleCountEPKNS0_7AuxTypeE
#define AUX_READ imp__ZN2nn5audio17ReadAuxSendBufferEPNS0_7AuxTypeEPii
#define AUX_WRITE imp__ZN2nn5audio20WriteAuxReturnBufferEPNS0_7AuxTypeEPKii
#define AUX_MAP imp__ZN2nn5audio17SetAuxInputOutputEPNS0_7AuxTypeEPKaS4_i
#define AUX_ENABLE imp__ZN2nn5audio13SetAuxEnabledEPNS0_7AuxTypeEb
#define AUX_ENABLED imp__ZN2nn5audio12IsAuxEnabledEPKNS0_7AuxTypeE
#define AUX_REMOVE imp__ZN2nn5audio9RemoveAuxEPNS0_19AudioRendererConfigEPNS0_7AuxTypeEPNS0_10SubMixTypeE
#define AUX_REMOVABLE imp__ZN2nn5audio14IsAuxRemovableEPKNS0_7AuxTypeE
#define AUX_SIZE imp__ZN2nn5audio43GetRequiredBufferSizeForAuxSendReturnBufferEPKNS0_22AudioRendererParameterEii

static uint64_t mix_object, aux_object;
static int32_t send_storage[32 + FRAME * 4 + 4], return_storage[32 + FRAME * 4 + 4];
static const size_t buffer_bytes = 128 + FRAME * 4 * sizeof(int32_t);
static int32_t data[FRAME * MAX_BUF];

static uint64_t call(void (*fn)(Ctx *), uint64_t object, uint64_t arg1, uint64_t arg2) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = object; c.x[1] = arg1; c.x[2] = arg2;
    fn(&c);
    return c.x[0];
}
static void fill(float left, float right) {
    for (int i = 0; i < FRAME; i++) mixes[0].buf[0][i] = left, mixes[0].buf[1][i] = right;
}
static void mapping(int cross) {
    int8_t in[2] = {0, 1}, out[2] = {(int8_t)cross, (int8_t)!cross};
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = (uintptr_t)&aux_object; c.x[1] = (uintptr_t)in; c.x[2] = (uintptr_t)out; c.x[3] = 2;
    AUX_MAP(&c);
    in[0] = out[0] = -1;   /* (the caller may use these arrays again before the update) */
}
static void add(void) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[1] = (uintptr_t)&aux_object; c.x[2] = (uintptr_t)&mix_object;
    c.x[3] = (uintptr_t)send_storage; c.x[4] = (uintptr_t)return_storage; c.x[5] = buffer_bytes;
    AUX_ADD(&c);
    CHECK(c.x[0] == 0);
}
static void setup(void) {
    memset(mixes, 0, sizeof mixes);
    memset(reverbs, 0, sizeof reverbs);
    memset(auxes, 0, sizeof auxes);
    memset(send_storage, 0x5a, sizeof send_storage);
    memset(return_storage, 0x5a, sizeof return_storage);
    ncmds = 0;
    mixes[0].used = 1; mixes[0].buffers = 2;
    put_handle((uintptr_t)&mix_object, K_MIX, 0);
    aux_object = 0;
    add();
    mapping(1);
}
static int read_samples(int n) { return (int)call(AUX_READ, (uintptr_t)&aux_object, (uintptr_t)data, (uint64_t)n); }
static int write_samples(int n) { return (int)call(AUX_WRITE, (uintptr_t)&aux_object, (uintptr_t)data, (uint64_t)n); }
static void enable(int enabled) { call(AUX_ENABLE, (uintptr_t)&aux_object, (uint64_t)enabled, 0); }

/* HOS_AUDIO_AUX=0 (or HOS_AUDIO_EFFECTS=0): no Aux of ours is made, and every call answers as the old stubs did */
static int passed_through(void) {
    setup();
    CHECK(!aux_object && !auxes[0].used && send_storage[0] == 0x5a5a5a5a);
    commit();
    fill(0.25f, -0.5f);
    effects_frame(0);
    CHECK(mixes[0].buf[0][0] == 0.25f && mixes[0].buf[1][0] == -0.5f);
    CHECK(read_samples(FRAME * 2) == 0 && write_samples(FRAME * 2) == FRAME * 2);
    CHECK(call(AUX_ENABLED, (uintptr_t)&aux_object, 0, 0) == 1 && call(AUX_REMOVABLE, (uintptr_t)&aux_object, 0, 0) == 1);
    CHECK(call(AUX_COUNT, (uintptr_t)&aux_object, 0, 0) == 0);
    puts("PASS (HOS_AUDIO_AUX=0 or HOS_AUDIO_EFFECTS=0): an Aux is accepted and passed through, as before");
    return 0;
}

int main(void) {
    uint32_t parameter[2] = {48000, 240};
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = (uintptr_t)parameter; c.x[1] = 6; c.x[2] = 5;
    AUX_SIZE(&c);
    CHECK(c.x[0] == 28928);   /* (30 whole channel frames and the 128 bytes before them; it was 376) */
    parameter[1] = 241;
    c.x[0] = (uintptr_t)parameter; c.x[1] = 1; c.x[2] = 1;
    AUX_SIZE(&c);
    CHECK(c.x[0] == 1152);   /* (964 bytes up to a cache line) */
    c.x[0] = (uintptr_t)parameter; c.x[1] = UINT32_MAX; c.x[2] = 1;
    AUX_SIZE(&c);
    CHECK(c.x[0] == 0x100);   /* (no size it can count: as before, never a wrapped one) */
    c.x[0] = (uintptr_t)parameter; c.x[1] = 0x7fffffff; c.x[2] = 0x7fffffff;
    AUX_SIZE(&c);
    CHECK(c.x[0] == (uint64_t)0x7fffffff * 0x7fffffff * 4 + 0x100);

    if (!aux_on()) return passed_through();

    setup();
    CHECK(aux_object);
    CHECK(call(AUX_COUNT, (uintptr_t)&aux_object, 0, 0) == FRAME * 4);
    CHECK(call(AUX_ENABLED, (uintptr_t)&aux_object, 0, 0) == 1);
    fill(0.25f, -0.5f);
    effects_frame(0);
    CHECK(mixes[0].buf[0][0] == 0.25f);   /* (the graph's change waits for the update) */
    commit();
    effects_frame(0);
    CHECK(mixes[0].buf[0][0] == 0 && mixes[0].buf[1][0] == 0);   /* (the return, never the dry send) */
    CHECK(read_samples(FRAME * 2) == FRAME * 2);
    for (int i = 0; i < FRAME; i++) CHECK(data[i] == 8192 && data[FRAME + i] == -16384);
    for (int i = 0; i < FRAME * 2; i++) data[i] /= 4;
    CHECK(write_samples(FRAME * 2) == FRAME * 2);
    fill(1, 1);
    effects_frame(0);
    for (int i = 0; i < FRAME; i++) CHECK(mixes[0].buf[0][i] == -0.125f && mixes[0].buf[1][i] == 0.0625f);
    CHECK(call(AUX_COUNT, (uintptr_t)&aux_object, 0, 0) == FRAME * 4);   /* (the room, not what waits) */
    effects_frame(0);
    CHECK(mixes[0].buf[0][0] == 0 && mixes[0].buf[1][0] == 0);   /* (a return is played once: a late worker is silence) */

    enable(0);
    CHECK(!call(AUX_ENABLED, (uintptr_t)&aux_object, 0, 0));
    CHECK(!call(AUX_REMOVABLE, (uintptr_t)&aux_object, 0, 0));
    commit();
    CHECK(call(AUX_REMOVABLE, (uintptr_t)&aux_object, 0, 0));
    CHECK(read_samples(FRAME * 2) == 0);
    fill(0.25f, -0.5f);
    effects_frame(0);
    CHECK(mixes[0].buf[0][0] == -0.5f && mixes[0].buf[1][0] == 0.25f);   /* (disabled, a crossed map: each input once) */

    enable(1); commit();
    for (int frame = 1; frame <= 12; frame++) { fill((float)frame, -(float)frame); effects_frame(0); }
    CHECK(read_samples(FRAME * 4) == FRAME * 4);   /* (the send ring holds two frames: the rest were not queued in part) */
    CHECK(data[0] == 32768 && data[FRAME] == -32768 && data[FRAME * 2] == 65536 && data[FRAME * 3] == -65536);
    fill(0.125f, -0.25f); effects_frame(0);
    CHECK(read_samples(FRAME * 2) == FRAME * 2 && data[0] == 4096 && data[FRAME] == -8192);
    CHECK(read_samples(-1) == 0 && write_samples(-1) == 0);
    for (int i = 0; i < FRAME * 4; i++) data[i] = i + 1;
    CHECK(write_samples(FRAME * 5) == FRAME * 4);   /* (a bounded write) */
    CHECK(write_samples(1) == 0);
    mapping(1); commit();   /* (the same map again keeps what waits) */
    fill(0, 0); effects_frame(0);
    CHECK(mixes[0].buf[1][0] == 1.0f / 32768.0f);
    mapping(0); commit();   /* (another map: the old layout's samples go) */
    fill(1, 2); effects_frame(0);
    CHECK(mixes[0].buf[0][0] == 0 && mixes[0].buf[1][0] == 0);
    CHECK(read_samples(FRAME * 2) == FRAME * 2 && data[0] == 32768 && data[FRAME] == 65536);

    fill(NAN, INFINITY); effects_frame(0);
    CHECK(read_samples(FRAME * 2) == FRAME * 2 && data[0] == 0 && data[FRAME] == 0);
    fill(1e30f, -1e30f); effects_frame(0);
    CHECK(read_samples(FRAME * 2) == FRAME * 2 && data[0] == INT32_MAX && data[FRAME] == INT32_MIN);

    /* removed: the mixer leaves the game's buffers alone at once, and the same guest object made again before the
       update is the new effect, which the queued release does not take */
    memset(&c, 0, sizeof c); c.x[1] = (uintptr_t)&aux_object;
    AUX_REMOVE(&c);
    CHECK(call(AUX_COUNT, (uintptr_t)&aux_object, 0, 0) == 0);
    memset(send_storage, 0x5a, sizeof send_storage);
    memset(return_storage, 0x5a, sizeof return_storage);
    fill(0.5f, 0.5f); effects_frame(0);
    CHECK(send_storage[32] == 0x5a5a5a5a && return_storage[32] == 0x5a5a5a5a);
    add(); mapping(0); commit();
    fill(0.5f, -0.5f); effects_frame(0);
    CHECK(read_samples(FRAME * 2) == FRAME * 2 && data[0] == 16384);
    CHECK(send_storage[32 + FRAME * 4] == 0x5a5a5a5a && return_storage[32 + FRAME * 4] == 0x5a5a5a5a);

    /* uneven reads cross the ring's end without losing the channels' order */
    setup(); commit();
    fill(1, -1); effects_frame(0);
    CHECK(read_samples(100) == 100);
    fill(2, -2); effects_frame(0);
    CHECK(read_samples(600) == 600);
    CHECK(data[139] == 32768 && data[140] == -32768 && data[380] == 65536);
    fill(3, -3); effects_frame(0);
    CHECK(read_samples(740) == 740);
    CHECK(data[19] == 65536 && data[20] == -65536 && data[260] == 98304 && data[500] == -98304);
    /* a worker may return one frame in several calls: a part of a frame is never played */
    for (int i = 0; i < FRAME * 2; i++) data[i] = 4096;
    CHECK(write_samples(100) == 100);
    fill(1, 1); effects_frame(0);
    CHECK(mixes[0].buf[0][0] == 0);
    CHECK(write_samples(FRAME * 2 - 100) == FRAME * 2 - 100);
    effects_frame(0);
    CHECK(mixes[0].buf[0][0] == 0.125f && mixes[0].buf[1][FRAME - 1] == 0.125f);

    /* the order the effects were added in, across a reverb and an Aux: a reverb with no wet part and half the dry */
    setup(); commit();
    Reverb *rv = &reverbs[0];
    rv->used = rv->enabled = 1; rv->mix = 0; rv->n = 2; rv->in[1] = rv->out[1] = 1;
    rv->room = -10000; rv->refl = -10000; rv->reverb = -10000; rv->dry = 0.5f; rv->seq = ++fx_seq;
    rv->decay_ns = 1000000000ll; rv->hf_ratio = 1.0f; rv->hf_ref = 5000; rv->density = 100; rv->diffusion = 100;
    for (int i = 0; i < FRAME * 2; i++) data[i] = 8192;
    CHECK(write_samples(FRAME * 2) == FRAME * 2);
    fill(1, 1); effects_frame(0);
    CHECK(fabsf(mixes[0].buf[0][0] - 0.125f) < 0.0001f);   /* (the Aux first, then the reverb) */
    CHECK(read_samples(FRAME * 2) == FRAME * 2 && data[0] == 32768);
    rv->seq = 0;
    fill(1, 1); effects_frame(0);
    CHECK(read_samples(FRAME * 2) == FRAME * 2 && abs(data[0] - 16384) < 8);   /* (the reverb first, then the Aux) */

    /* its mix released: it runs on none, and is still the game's to remove */
    setup(); commit();
    { const Cmd k = {.op = OP_MIX_RELEASE, .idx = 0}; submit(&k); commit(); }
    CHECK(auxes[0].used && auxes[0].mix == -1);
    mixes[0].used = 1; mixes[0].buffers = 2;
    fill(0.25f, 0.25f); effects_frame(0);
    CHECK(mixes[0].buf[0][0] == 0.25f && read_samples(FRAME * 2) == 0);
    memset(&c, 0, sizeof c); c.x[1] = (uintptr_t)&aux_object;
    AUX_REMOVE(&c); commit();
    CHECK(!auxes[0].used);

    free(cmds);
    puts("PASS: Aux sizing, PCM round trip, channel maps, update ordering, under- and overflow, reset, removal and slot reuse");
    return 0;
}
