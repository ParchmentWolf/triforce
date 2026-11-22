/* The calls the game's movie library makes to nn::codec's AV1 decoder, for the movie tests: included after the copy of
   host/nn_video.c that tests/video_standins.h lets them compile, so these call its entry points as the game does (the
   arguments in x0 to x7, the result in x0) and can look at its Dec and Pool. One decoder (SI_DEC) with up to 8 picture
   buffers, each an image pool of one image. */
#pragma once

#define SI_DEC 0x100ull      /* the game's decoder object */
#define SI_POOLS 0x200ull    /* its image pools, 0x40 apart */
#define SI_PREF 0x800ull     /* the image preference a pool is made from */
#define SI_OUT 0x900ull      /* what the calls write: a submission's id, a buffer's index, its sync handle, its properties */
#define SI_DATA 0x1000ull    /* a submission's bytes */
#define SI_FULL 0x1c266full  /* the result of a submission refused while the decoder's input is full */

static Dec *si_dec(void) { return (Dec *)host_of(SI_DEC, DEC_MAGIC); }
static Pool *si_pool(int i) { return (Pool *)host_of(SI_POOLS + (uint64_t)i * 0x40, POOL_MAGIC); }

/* the decoder for w x h pictures, with `buffers` picture buffers of that size in the pool format given (0 NV12) */
static void si_open(int w, int h, int buffers, int pool_format) {
    Ctx c;
    for (int i = 0; i < buffers; i++) {
        const Pref pref = {PREF_MAGIC, (uint16_t)w, (uint16_t)h, (uint32_t)pool_format, 0};
        memcpy(GP(SI_PREF), &pref, sizeof pref);
        memset(&c, 0, sizeof c);
        c.x[0] = SI_POOLS + (uint64_t)i * 0x40, c.x[3] = SI_PREF, c.x[4] = 1;
        imp__ZN2nn5codec26InitializeDecoderImagePoolEPNS0_25VideoDecoderImagePoolTypeEPvmRKNS0_27VideoDecoderImagePreferenceEj(&c);
    }
    memset(&c, 0, sizeof c);
    c.x[0] = SI_DEC, c.x[4] = (uint64_t)w, c.x[5] = (uint64_t)h;
    imp__ZN2nn5codec36InitializeAv1DecoderByTransferMemoryEPNS0_14Av1DecoderTypeEPvmmttjNS0_23VideoDecoderInputFormatENS0_24VideoDecoderOutputFormatENS0_22VideoDecoderOutputModeE(&c);
    for (int i = 0; i < buffers; i++) {
        memset(&c, 0, sizeof c);
        c.x[0] = SI_DEC, c.x[1] = (uint64_t)i, c.x[2] = SI_POOLS + (uint64_t)i * 0x40;
        imp__ZN2nn5codec24RegisterAv1DecoderBufferEPNS0_14Av1DecoderTypeEjPNS0_25VideoDecoderImagePoolTypeEj(&c);
    }
}
/* one submission of 16 bytes for the picture at pts (ns); last: the stream's last. The call's result */
static uint64_t si_submit(int64_t pts, int last) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = SI_OUT, c.x[1] = SI_DEC, c.x[2] = SI_DATA, c.x[3] = 16, c.x[4] = (uint64_t)pts, c.x[5] = (uint64_t)last;
    imp__ZN2nn5codec27SubmitAv1DecoderInputBufferEPmPNS0_14Av1DecoderTypeEPKvmNS_8TimeSpanEb(&c);
    return c.x[0];
}
/* The game's submit loop: pictures *next to total - 1, gap ns apart, until all are in or one is refused because the
   decoder's input is full (it is submitted again by the next call). How many were taken; -1 on any other result */
static int si_feed(int *next, int total, int64_t gap) {
    int taken = 0;
    while (*next < total) {
        const uint64_t result = si_submit(*next * gap, *next == total - 1);
        if (result == SI_FULL) break;
        if (result) return -1;
        (*next)++, taken++;
    }
    return taken;
}
/* a picture taken: its buffer's index, or -1 when the call failed */
static int si_acquire(void) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = SI_OUT + 8, c.x[1] = SI_OUT + 16, c.x[2] = SI_DEC;
    imp__ZN2nn5codec29AcquireAv1DecoderOutputBufferEPjPNS_2gs16NativeSyncHandleEPNS0_14Av1DecoderTypeE(&c);
    return c.x[0] ? -1 : (int)G32(SI_OUT + 8);
}
static void si_release(int buffer) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = SI_DEC, c.x[1] = (uint64_t)buffer;
    imp__ZN2nn5codec29ReleaseAv1DecoderOutputBufferEPNS0_14Av1DecoderTypeEjNS_2gs16NativeSyncHandleE(&c);
}
/* the pts of the picture in a buffer; *last: whether it is the stream's last */
static int64_t si_pts(int buffer, int *last) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[4] = SI_OUT + 24, c.x[5] = SI_OUT + 32, c.x[6] = SI_DEC, c.x[7] = (uint64_t)buffer;
    imp__ZN2nn5codec35GetAv1DecoderOutputBufferPropertiesEPtS1_S1_S1_PNS_8TimeSpanEPbPNS0_14Av1DecoderTypeEj(&c);
    if (last) *last = *(uint8_t *)GP(SI_OUT + 32);
    return (int64_t)G64(SI_OUT + 24);
}
static void si_stop(void) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = SI_DEC;
    imp__ZN2nn5codec14StopAv1DecoderEPNS0_14Av1DecoderTypeE(&c);
}
static void si_flush(void) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = SI_DEC;
    imp__ZN2nn5codec15FlushAv1DecoderEPNS0_14Av1DecoderTypeE(&c);
}
static void si_finalize(void) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = SI_DEC;
    imp__ZN2nn5codec18FinalizeAv1DecoderEPNS0_14Av1DecoderTypeE(&c);
}
static uint64_t si_ready_event(void) {   /* GetAv1DecoderSubmissionReadyEvent: the event's guest address */
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = SI_DEC;
    imp__ZN2nn5codec33GetAv1DecoderSubmissionReadyEventEPNS0_14Av1DecoderTypeE(&c);
    return c.x[0];
}
