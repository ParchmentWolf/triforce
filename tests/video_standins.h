/* Stand-ins for compiling host/nn_video.c whole, as it is, with no game, no FFmpeg and no Media Foundation: the movie
   tests (tests/test_video_*.py) put this file in a folder as hos.h, libavcodec/avcodec.h and libswscale/swscale.h, with
   a copy of nn_video.c beside them, and include tests/video_play.h after it for the calls the game makes.

   What is here: the guest window and the HLE macros of hos.h; a clock that moves only when a decode or a sleep moves
   it; a log kept in memory; system events that remember whether they are set; a decoder that gives one picture a
   submission, of a format, a size and a cost the test sets (`si`), under the names of libavcodec's and of
   host/mf_av1.c's; a libswscale that counts its conversions. On Windows the notice's message box, its thread and its
   Store page are counted, never shown. */
#pragma once
#include <errno.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
static int si_boxes, si_threads;
#undef MessageBoxA
#undef ShellExecuteA
#undef CreateThread
#define MessageBoxA(window, text, title, type) (si_boxes++, 0)
#define ShellExecuteA(window, verb, file, args, dir, show) ((void)0)
#define CreateThread(security, stack, fn, arg, flags, id) (si_threads++, (void)(fn), (HANDLE)NULL)
#endif

/* ---- hos.h ---- */
typedef struct { uint64_t x[32]; } Ctx;
#define SI_GUEST 0x40000ull
static uint8_t si_guest[SI_GUEST];
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define GP(a) ((void *)(si_guest + (a)))
#define G64(a) (*(uint64_t *)GP(a))
#define G32(a) (*(uint32_t *)GP(a))
#define HOS_WRITTEN(p, n) ((void)0)
/* ((Triforce, 11-22) host_alloc.h's allocations (OS-04): away from Windows' commit limit they are the C library's */
void *hos_xmalloc(size_t n) { return malloc(n); }
void *hos_xcalloc(size_t count, size_t size) { return calloc(count, size); }
void *hos_xrealloc(void *p, size_t n) { return realloc(p, n); }
#define HLE(sym) void imp_##sym(Ctx *c)
static inline void *hos_guest_range(uint64_t a, uint64_t n) { return a < SI_GUEST && n <= SI_GUEST - a ? GP(a) : NULL; }

static char si_log[1 << 18];   /* every line logged, each ended by a newline */
static size_t si_log_len;
static void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    if (si_log_len + 1024 < sizeof si_log) {
        si_log_len += (size_t)vsnprintf(si_log + si_log_len, 1000, fmt, ap);
        si_log[si_log_len++] = '\n', si_log[si_log_len] = 0;
    }
    va_end(ap);
}
static int si_logged(const char *text) {   /* how many times the log has it */
    int n = 0;
    for (const char *p = si_log; (p = strstr(p, text)) != NULL; p += strlen(text)) n++;
    return n;
}
static void hos_fatal(Ctx *c, const char *fmt, ...) {
    (void)c;
    printf("FATAL: %s\n", fmt);
    exit(3);
}
static int64_t si_now = 5000000000ll;   /* the clock: a decode and a sleep move it, nothing else */
static int64_t hos_now_ns(void) { return si_now; }
static void hos_sleep_ns(int64_t ns) { si_now += ns; }
static int hos_vcore_away(void) { return 0; }
static void hos_vcore_back(void) {}
static uint64_t si_sys = 0x30000;
static uint64_t hos_sys_alloc(uint64_t size, uint64_t align) {
    (void)align;
    const uint64_t at = si_sys;
    si_sys += (size + 63) & ~63ull;
    if (si_sys > SI_GUEST) hos_fatal(NULL, "the stand-in system region is full");
    return at;
}

/* system events (host/nn_os_sync.c), by their guest address */
static struct { uint64_t key; int set, inits, signals, clears; } si_events[64];
static int si_nevents;
static int si_event(uint64_t key) {
    int i = 0;
    while (i < si_nevents && si_events[i].key != key) i++;
    if (i == si_nevents) {
        if (si_nevents == 64) hos_fatal(NULL, "more events than the stand-in keeps");
        si_events[si_nevents++].key = key;
    }
    return i;
}
static void hos_system_event_init(uint64_t key, int autoclear) {
    (void)autoclear;
    const int i = si_event(key);
    si_events[i].set = 0, si_events[i].inits++;
}
static void hos_system_event_signal(uint64_t key) {
    const int i = si_event(key);
    si_events[i].set = 1, si_events[i].signals++;
}
static void hos_system_event_signal_held(uint64_t key) { hos_system_event_signal(key); }   /* (under a host lock) */
static void hos_system_event_clear(uint64_t key) {
    const int i = si_event(key);
    si_events[i].set = 0, si_events[i].clears++;
}
static int si_event_set(uint64_t key) { return si_events[si_event(key)].set; }
static int si_event_clears(uint64_t key) { return si_events[si_event(key)].clears; }

/* ---- what the test sets, and what the stand-ins count ---- */
enum AVCodecID { AV_CODEC_ID_NONE, AV_CODEC_ID_VP8, AV_CODEC_ID_VP9, AV_CODEC_ID_AV1 };
enum AVPixelFormat { AV_PIX_FMT_NONE = -1, AV_PIX_FMT_YUV420P, AV_PIX_FMT_NV12, AV_PIX_FMT_YUVA420P, AV_PIX_FMT_RGBA,
                     AV_PIX_FMT_YUV420P10LE };
static struct {
    int have_dav1d, have_native;   /* what the FFmpeg has: libdav1d by name, a decoder of its own for the codec */
    int open_fails;                /* avcodec_open2 fails */
    int mf_ok;                     /* Media Foundation has an AV1 decoder */
    int format, w, h, pad;         /* the pictures: an AVPixelFormat, their size, bytes of a row past its width */
    int64_t decode_ns;             /* what decoding one submission takes, on the stand-in clock */
    int64_t first_decode_ns;       /* ... and the first one after a start or a flush, when not 0 */
    char order[64];                /* what dec_init asked for, in order: d libdav1d by name, a libaom by name, n FFmpeg's own
                                      decoder, o avcodec_open2, M Media Foundation quietly, T Media Foundation telling why */
    int sws_contexts, sws_scales;  /* libswscale's conversions asked for */
    int64_t decodes, pictures;     /* submissions decoded, pictures given */
    int started;
} si = {1, 1, 0, 1, AV_PIX_FMT_YUV420P, 64, 36, 32, 1000000, 0, "", 0, 0, 0, 0, 0};

static void si_ask(char what) {
    const size_t n = strlen(si.order);
    if (n + 1 < sizeof si.order) si.order[n] = what, si.order[n + 1] = 0;
}
static void si_decode_cost(void) {   /* one submission's decode, on the clock */
    si_now += !si.started && si.first_decode_ns ? si.first_decode_ns : si.decode_ns;
    si.started = 1;
    si.decodes++;
}
/* a picture's planes, written again for each one: plane p's byte at (x, y) of picture n */
static inline uint8_t si_byte(int p, int x, int y, int64_t n) { return (uint8_t)(x * 3 + y * 7 + p * 61 + (int)n * 5 + 1); }
static uint8_t *si_planes[4];
static int si_stride[4];
static void si_picture(int64_t n) {
    for (int p = 0; p < 4; p++) {
        const int chroma = p == 1 || p == 2;
        const int semi = si.format == AV_PIX_FMT_NV12 && p == 1;   /* (NV12's second plane: U and V in turns, a full row) */
        const int w = chroma && !semi ? (si.w + 1) / 2 : si.w, h = chroma ? (si.h + 1) / 2 : si.h;
        si_stride[p] = w + si.pad;
        free(si_planes[p]);
        si_planes[p] = (uint8_t *)malloc((size_t)si_stride[p] * h);
        memset(si_planes[p], 0xEE, (size_t)si_stride[p] * h);   /* (a row's padding is never the picture's) */
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
                si_planes[p][(size_t)y * si_stride[p] + x] = semi ? si_byte(1 + (x & 1), x / 2, y, n) : si_byte(p, x, y, n);
    }
}

/* ---- libavcodec ---- */
#define AV_INPUT_BUFFER_PADDING_SIZE 64
#define AVERROR(e) (-(e))
typedef struct AVCodec { const char *name; enum AVCodecID id; } AVCodec;
typedef struct AVPacket { uint8_t *data; int size; int64_t pts; } AVPacket;
typedef struct AVFrame { uint8_t *data[8]; int linesize[8]; int width, height, format; int64_t pts; } AVFrame;
typedef struct AVCodecContext { const AVCodec *codec; int thread_count; int64_t held[4]; int nheld; } AVCodecContext;
static const AVCodec si_dav1d = {"libdav1d", AV_CODEC_ID_AV1}, si_native = {"native", AV_CODEC_ID_NONE};
static const AVCodec *avcodec_find_decoder_by_name(const char *name) {
    const int dav1d = !strcmp(name, "libdav1d");
    si_ask(dav1d ? 'd' : 'a');
    return dav1d && si.have_dav1d ? &si_dav1d : NULL;
}
static const AVCodec *avcodec_find_decoder(enum AVCodecID id) {
    (void)id;
    si_ask('n');
    return si.have_native ? &si_native : NULL;
}
static AVCodecContext *avcodec_alloc_context3(const AVCodec *codec) {
    AVCodecContext *ctx = (AVCodecContext *)calloc(1, sizeof *ctx);
    ctx->codec = codec;
    return ctx;
}
static int avcodec_open2(AVCodecContext *ctx, const AVCodec *codec, void *options) {
    (void)ctx, (void)codec, (void)options;
    si_ask('o');
    return si.open_fails ? -1 : 0;
}
static void avcodec_free_context(AVCodecContext **ctx) {
    free(*ctx);
    *ctx = NULL;
}
static void avcodec_flush_buffers(AVCodecContext *ctx) { ctx->nheld = 0, si.started = 0; }
static int avcodec_send_packet(AVCodecContext *ctx, const AVPacket *pkt) {
    if (!pkt) return 0;
    if (ctx->nheld == 4) return AVERROR(EAGAIN);
    si_decode_cost();
    ctx->held[ctx->nheld++] = pkt->pts;
    return 0;
}
static int avcodec_receive_frame(AVCodecContext *ctx, AVFrame *f) {
    if (!ctx->nheld) return AVERROR(EAGAIN);
    memset(f, 0, sizeof *f);
    si_picture(si.pictures);
    for (int p = 0; p < 4; p++) f->data[p] = si_planes[p], f->linesize[p] = si_stride[p];
    f->width = si.w, f->height = si.h, f->format = si.format, f->pts = ctx->held[0];
    memmove(ctx->held, ctx->held + 1, sizeof ctx->held - sizeof ctx->held[0]);
    ctx->nheld--;
    si.pictures++;
    return 0;
}
static AVPacket *av_packet_alloc(void) { return (AVPacket *)calloc(1, sizeof(AVPacket)); }
static int av_new_packet(AVPacket *pkt, int size) {
    pkt->data = (uint8_t *)calloc(1, (size_t)size + AV_INPUT_BUFFER_PADDING_SIZE);
    pkt->size = size;
    return pkt->data ? 0 : -1;
}
static void av_packet_free(AVPacket **pkt) {
    if (*pkt) free((*pkt)->data);
    free(*pkt);
    *pkt = NULL;
}
static AVFrame *av_frame_alloc(void) { return (AVFrame *)calloc(1, sizeof(AVFrame)); }
static void av_frame_free(AVFrame **f) {
    free(*f);
    *f = NULL;
}
static void av_frame_unref(AVFrame *f) { (void)f; }

/* ---- libswscale: a conversion is counted, and fills its picture with 0x5A ---- */
#define SWS_BILINEAR 2
struct SwsContext { int w, h, from; };
static struct SwsContext *sws_getContext(int w, int h, enum AVPixelFormat from, int dw, int dh, enum AVPixelFormat to, int flags,
                                         void *in_filter, void *out_filter, const double *param) {
    (void)dw, (void)dh, (void)to, (void)flags, (void)in_filter, (void)out_filter, (void)param;
    struct SwsContext *s = (struct SwsContext *)calloc(1, sizeof *s);
    s->w = w, s->h = h, s->from = from;
    si.sws_contexts++;
    return s;
}
static int sws_scale(struct SwsContext *s, const uint8_t *const *src, const int *src_stride, int y, int h, uint8_t *const *dst,
                     const int *dst_stride) {
    (void)s, (void)src, (void)src_stride, (void)y;
    si.sws_scales++;
    for (int r = 0; r < h; r++) memset(dst[0] + (size_t)r * dst_stride[0], 0x5A, (size_t)dst_stride[0]);
    return h;
}
static void sws_freeContext(struct SwsContext *s) { free(s); }

/* ---- host/mf_av1.c: NV12 pictures, one a submission ---- */
typedef void (*si_mf_picture_fn)(void *user, const uint8_t *y, const uint8_t *uv, int w, int h, int stride, int64_t pts);
static void *mf_av1_open(int w, int h, int tell) {
    (void)w, (void)h;
    si_ask(tell ? 'T' : 'M');
    return si.mf_ok ? (void *)&si : NULL;
}
static void mf_av1_decode(void *m, const uint8_t *data, size_t n, int64_t pts, si_mf_picture_fn fn, void *user) {
    (void)m, (void)n;
    if (!data) return;   /* (the end: nothing was held back) */
    const int format = si.format;
    si.format = AV_PIX_FMT_NV12;
    si_decode_cost();
    si_picture(si.pictures++);
    fn(user, si_planes[0], si_planes[1], si.w, si.h, si_stride[0], pts);
    si.format = format;
}
static void mf_av1_flush(void *m) { (void)m, si.started = 0; }
static void mf_av1_close(void *m) { (void)m; }
