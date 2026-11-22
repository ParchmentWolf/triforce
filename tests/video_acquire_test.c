/* tests/test_video_acquire_wait.py's fixture: host/nn_video.c's decoder record and its Submit, Stop/Flush and Acquire
   calls (video_acquire_block.inc, cut out unchanged by the test) run over stand-ins: a clock that moves only when a
   sleep moves it (each sleep 5 ms long, as a 2 ms sleep is on Windows), a decoder whose one picture comes out at a set
   time, and a virtual core whose giving up and taking back are watched (never taken back under a lock).

   video_acquire_test <case>: empty (nothing will come), stopped (a Stop, then nothing), resubmit (a Stop, a submission,
   a picture 30 ms later), pending (a picture 60 ms later), noslot (no buffer registered). One RESULT line. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint64_t x[32]; } Ctx;
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define G64(a) (*(uint64_t *)(uintptr_t)(a))
#define G32(a) (*(uint32_t *)(uintptr_t)(a))
#define HOS_WRITTEN(p, n) ((void)(p), (void)(n))
#define RESULT_NO_OUTPUT 0x2a1ca
#define POOL_MAGIC 0x4c4f4f50u
#define DEC_MAGIC 0x43454456u
#define MAX_SLOTS 16
#define MAX_QUEUE 8
#define SYNC_IDLE_TAG 0x5ec0000000000000ull
#define SYNC_IDLE_MASK 0x0000ffffffffffffull
#define AV_INPUT_BUFFER_PADDING_SIZE 64
#define InterlockedCompareExchange64(p, a, b) ((void)(a), (void)(b), *(p))

typedef struct AVCodecContext AVCodecContext;
typedef struct AVFrame AVFrame;
struct SwsContext;
typedef struct { uint8_t *data; int64_t pts; } AVPacket;
typedef struct { int held; } SRWLOCK;

static int64_t clock_ns, arrive_ns = -1;
static int core = 1, locks_held, decodes, decoded_with_core, back_under_lock, slept_under_lock, arrived;
static volatile int64_t submissions;

static void AcquireSRWLockExclusive(SRWLOCK *l) {
    if (l->held) { puts("FAIL: a lock taken twice"); exit(2); }
    l->held = 1, locks_held++;
}
static void ReleaseSRWLockExclusive(SRWLOCK *l) {
    if (!l->held) { puts("FAIL: a lock let go that was not held"); exit(2); }
    l->held = 0, locks_held--;
}
static int64_t hos_now_ns(void) { return clock_ns; }
static void hos_sleep_ns(int64_t ns) {
    (void)ns;
    if (locks_held) slept_under_lock++;
    clock_ns += 5000000;
}
static int hos_vcore_away(void) {
    if (!core) return 0;
    core = 0;
    return 1;
}
static void hos_vcore_back(void) {
    if (locks_held) back_under_lock++;
    core = 1;
}
static void hos_log(const char *f, ...) { (void)f; }
static int video_log(void) { return 0; }
static void *hos_guest_range(uint64_t a, uint64_t n) { (void)a, (void)n; return NULL; }
static void *host_of(uint64_t obj, uint32_t magic) { (void)magic; return (void *)(uintptr_t)obj; }
static uint64_t submitted(void) { return 1; }
static AVPacket *av_packet_alloc(void) { return NULL; }
static int av_new_packet(AVPacket *p, int n) { (void)p, (void)n; return -1; }
static void av_packet_free(AVPacket **p) { *p = NULL; }
static void avcodec_flush_buffers(AVCodecContext *x) { (void)x; }
static void mf_av1_flush(void *m) { (void)m; }

#include "../host/video_movie.h"   /* (the Dec cut out keeps a movie's counts: VideoMovie) */
#include "../host/video_catchup.h"   /* (and its pictures' pace: VideoPace, the catch-up's rule) */
#include "../host/video_input.h"     /* (and the submissions' limit: its rule and result) */
#include "video_acquire_types.inc"

static void pending_push(Dec *d, AVPacket *pkt) { (void)d, (void)pkt; }
static void pending_free(Dec *d) { d->phead = d->ptail = NULL; }
static void picture_free(Picture *p) {
    free(p->rgba), free(p->nv12);
    memset(p, 0, sizeof *p);
}
static void pool_rgba(Pool *o) { (void)o; }
static void decode_pending(Dec *d) {   /* (the decoder: its one picture out at arrive_ns) */
    decodes++;
    if (core) decoded_with_core++;
    if (arrive_ns >= 0 && clock_ns >= arrive_ns && d->qn < MAX_QUEUE) {
        Picture *p = &d->queue[(d->qhead + d->qn) % MAX_QUEUE];
        memset(p, 0, sizeof *p);
        p->w = p->h = 4;
        p->nv12 = calloc(4 * 4 * 3 / 2, 1);
        d->qn++;
        arrive_ns = -1, arrived = 1;
    }
}
static void decode_next(Dec *d) { decode_pending(d); }
static void movie_end(Dec *d) { memset(&d->movie, 0, sizeof d->movie); }   /* (the movie's log line: not tested here) */
/* (IO-34: the submissions' limit off here, as with HOS_VIDEO_INPUT_LIMIT=0; this fixture's waits are the acquire's) */
static int input_limit(void) { return 0; }
static void input_room(Dec *d) { (void)d; }
static void hos_system_event_clear(uint64_t key) { (void)key; }

#include "video_acquire_block.inc"

int main(int argc, char **argv) {
    const char *k = argc > 1 ? argv[1] : "";
    static Dec dec;
    static Pool pool;
    Ctx ctx, *c = &ctx;
    uint32_t index = 0xffffffffu;
    uint64_t sync = 0;
    dec.ctx = (AVCodecContext *)(uintptr_t)1;
    pool.w = pool.h = 4;
    pool.nv12 = calloc(4 * 4 * 3 / 2, 1);
    if (strcmp(k, "noslot")) dec.slots[0] = (uint64_t)(uintptr_t)&pool;
    if (!strcmp(k, "stopped") || !strcmp(k, "resubmit")) {
        memset(c, 0, sizeof *c);
        ARG(0) = (uint64_t)(uintptr_t)&dec;
        dec_flush(c, "Stop");
    }
    if (!strcmp(k, "resubmit")) {
        uint64_t id = 0;
        memset(c, 0, sizeof *c);
        ARG(0) = (uint64_t)(uintptr_t)&id, ARG(1) = (uint64_t)(uintptr_t)&dec;
        dec_submit(c);
        arrive_ns = clock_ns + 30000000;
    }
    if (!strcmp(k, "pending")) arrive_ns = clock_ns + 60000000;
    if (locks_held || !core) { puts("FAIL: the set-up left a lock held or the core away"); return 2; }
    const int64_t began = clock_ns;
    memset(c, 0, sizeof *c);
    ARG(0) = (uint64_t)(uintptr_t)&index, ARG(1) = (uint64_t)(uintptr_t)&sync, ARG(2) = (uint64_t)(uintptr_t)&dec;
    dec_acquire(c);
    const int delivered = arrived && !dec.qn && c->x[0] == 0;   /* (the picture decoded and handed out) */
    printf("RESULT %s elapsed_ms=%lld ret=%#llx index=%d decodes=%d decoded_with_core=%d back_under_lock=%d "
           "slept_under_lock=%d core=%d locks=%d delivered=%d\n",
           k, (long long)((clock_ns - began) / 1000000), (unsigned long long)c->x[0], index == 0xffffffffu ? -1 : (int)index,
           decodes, decoded_with_core, back_under_lock, slept_under_lock, core, locks_held, delivered);
    return 0;
}
