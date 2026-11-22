"""A decoded movie picture is kept as NV12 alone, from libdav1d's planar 4:2:0 as from Media Foundation's NV12: its RGBA
is made only when the game reads RGBA (host/video_nv12.h, host/nn_video.c queue_frame; no game, no FFmpeg).

(Triforce, 11-22, the performance audit's IO-36, after Source A's.) queue_frame converted every planar picture to RGBA
on the movie thread (a swscale pass, an 8 MB allocation and an 8 MB row copy at 1080p), zeroed its NV12 buffer and
interleaved U and V one byte at a time, for a game that reads only the NV12. Now planar 4:2:0 without alpha is kept as
NV12 alone, the buffer is zeroed only where a copy leaves bytes out, and the interleave does 16 pairs a step.
HOS_VIDEO_RGBA=1 makes the RGBA of every planar picture, as before.

On every system this compiles video_nv12.h alone (which pictures are lazy, when the buffer is zeroed, the interleave
against one byte at a time for every length up to 70 with guard bytes around it) and reads the source: queue_frame asks
the rule, builds its swscale context and its RGBA only for a picture that is not lazy, zeroes by the rule, interleaves
with the header's loop; the switch is read once and is in the switches table.

On Windows it also compiles nn_video.c whole over tests/video_standins.h and decodes pictures of each format: planar
4:2:0 at 1920x1080, 70x10 and 35x7 has no swscale context and no conversion, no RGBA, and an NV12 equal to a
reference built one byte at a time (the bytes an odd size leaves out are 0); with HOS_VIDEO_RGBA=1 there is one
conversion a picture and the same NV12; planar 4:2:0 with alpha is converted either way; a format queue_frame does
not copy is converted and its NV12 is zeros; Media Foundation's NV12 is lazy with or without the switch. And a lazy
picture taken by the game leaves its pool's RGBA to be made when ReadDecoderOutputImageRgba asks: one conversion then,
none before.

    python -I -B tests/test_video_lazy_rgba.py [--cc clang]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_fixture as vf   # noqa: E402

RUN_ALL_ARGS = ["--cc", "clang"]

RULES = r"""
#include <stdio.h>
#include <string.h>
#include "video_nv12.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    /* video_rgba_lazy(eager, nv12, planar 4:2:0 without alpha) */
    CHECK(video_rgba_lazy(0, 1, 0) && video_rgba_lazy(1, 1, 0));    /* NV12: always, as before */
    CHECK(video_rgba_lazy(0, 0, 1) && !video_rgba_lazy(1, 0, 1));   /* planar: unless HOS_VIDEO_RGBA=1 */
    CHECK(!video_rgba_lazy(0, 0, 0) && !video_rgba_lazy(1, 0, 0));  /* with alpha, or any other format: never */
    /* video_nv12_zero(w, h, a format queue_frame copies) */
    CHECK(!video_nv12_zero(1920, 1080, 1) && !video_nv12_zero(64, 36, 1));
    CHECK(video_nv12_zero(35, 8, 1) && video_nv12_zero(36, 7, 1) && video_nv12_zero(35, 7, 1));
    CHECK(video_nv12_zero(1920, 1080, 0));
    /* the interleave: every length to 70, at every offset of 0 to 3 (unaligned rows), nothing written past 2n */
    static uint8_t u[80], v[80], out[4 + 160 + 32], want[4 + 160 + 32];
    for (int i = 0; i < 80; i++) u[i] = (uint8_t)(i * 5 + 1), v[i] = (uint8_t)(200 - i * 3);
    for (int n = 0; n <= 70; n++)
        for (int at = 0; at < 4; at++) {
            memset(out, 0xC3, sizeof out), memset(want, 0xC3, sizeof want);
            for (int x = 0; x < n; x++) want[at + 2 * x] = u[at + x], want[at + 2 * x + 1] = v[at + x];
            video_uv_interleave(out + at, u + at, v + at, n);
            CHECK(!memcmp(out, want, sizeof out));
        }
#if defined(__x86_64__) || defined(_M_X64)
    CHECK(VIDEO_NV12_SSE2);   /* (the 16-pair step is compiled here) */
#endif
    return fails ? 1 : 0;
}
"""

PICTURES = r"""
static int fails = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
/* picture n as NV12, one byte at a time from the stand-in decoder's planes; what no copy reaches is 0 */
static uint8_t *reference(int w, int h, int64_t n, int copied) {
    uint8_t *r = (uint8_t *)calloc(1, (size_t)w * h * 3 / 2);
    if (!copied) return r;
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) r[(size_t)y * w + x] = si_byte(0, x, y, n);
    for (int y = 0; y < h / 2; y++)
        for (int x = 0; x < w / 2; x++) {
            r[(size_t)w * h + (size_t)y * w + 2 * x] = si_byte(1, x, y, n);
            r[(size_t)w * h + (size_t)y * w + 2 * x + 1] = si_byte(2, x, y, n);
        }
    return r;
}
int main(int argc, char **argv) {
    CHECK(argc == 4);
    const char *name = argv[1];
    const int w = atoi(argv[2]), h = atoi(argv[3]);
    const int copied = strcmp(name, "other") != 0;
    si.format = !strcmp(name, "yuv420p") ? AV_PIX_FMT_YUV420P : !strcmp(name, "yuva420p") ? AV_PIX_FMT_YUVA420P :
                !strcmp(name, "nv12") ? AV_PIX_FMT_NV12 : AV_PIX_FMT_YUV420P10LE;
    si.w = w, si.h = h;
    si_open(w, h, 2, 3);   /* (pools of format 3, as the game's) */
    Dec *d = si_dec();
    CHECK(d && (d->ctx || d->mf));
    /* three pictures decoded into the queue, as dec_acquire's first lines do */
    int rgba = 0, equal = 0, filled = 0;
    for (int n = 0; n < 3; n++) {
        CHECK(si_submit(n * 16683333ll, 0) == 0);
        const int before = d->qn;
        decode_next(d);
        CHECK(d->qn == before + 1);
        const Picture *p = &d->queue[(d->qhead + d->qn - 1) % MAX_QUEUE];
        uint8_t *want = reference(w, h, n, copied);
        CHECK(p->w == w && p->h == h && p->nv12 != NULL);
        equal += !memcmp(p->nv12, want, (size_t)w * h * 3 / 2);
        rgba += p->rgba != NULL;
        filled += p->rgba && p->rgba[0] == 0x5A && p->rgba[(size_t)w * h * 4 - 1] == 0x5A;   /* (the stand-in's conversion) */
        free(want);
    }
    printf("decoder %s\n", d->ctx ? d->ctx->codec->name : "Media Foundation");
    printf("queued: rgba %d, nv12-equal %d, contexts %d, conversions %d, rgba-filled %d\n", rgba, equal, si.sws_contexts,
           si.sws_scales, filled);
    /* the game takes the first: its NV12 in the pool; the pool's RGBA only once it is read */
    const int b = si_acquire();
    CHECK(b >= 0);
    Pool *o = si_pool(b);
    uint8_t *want = reference(w, h, 0, copied);
    int pool_equal = 1;   /* (the pool's rows, at the pool's width: the same size here) */
    for (int y = 0; y < h + h / 2; y++) pool_equal &= !memcmp(o->nv12 + (size_t)y * w, want + (size_t)y * w, (size_t)w);
    const int before = si.sws_scales, stale = o->rgba_stale;
    if (w <= 64 && h <= 36) {
        Ctx c;
        memset(&c, 0, sizeof c);
        c.x[0] = SI_POOLS + (uint64_t)b * 0x40, c.x[4] = (uint64_t)w, c.x[5] = (uint64_t)h, c.x[6] = 0x4000, c.x[7] = (uint64_t)w * 4;
        imp__ZN2nn5codec26ReadDecoderOutputImageRgbaEPKNS0_25VideoDecoderImagePoolTypeEjttttPvmm(&c);
        imp__ZN2nn5codec26ReadDecoderOutputImageRgbaEPKNS0_25VideoDecoderImagePoolTypeEjttttPvmm(&c);   /* (twice: made once) */
    }
    printf("taken: pool-nv12-equal %d, rgba-left-for-the-read %d, conversions-at-the-read %d, read-is-0x5A %d\n", pool_equal,
           stale, si.sws_scales - before, si_guest[0x4000] == 0x5A && si_guest[0x4000 + (size_t)w * h * 4 - 1] == 0x5A);
    free(want);
    return fails ? 1 : 0;
}
"""

# (format, w, h, HOS_VIDEO_RGBA, HOS_AV1) -> pictures with an RGBA of 3, swscale contexts, conversions
CASES = [
    (("yuv420p", 1920, 1080, None, None), 0, 0, 0),    # libdav1d's pictures: NV12 alone
    (("yuv420p", 70, 10, None, None), 0, 0, 0),        # (35 pairs a row: two steps of 16 and three single)
    (("yuv420p", 35, 7, None, None), 0, 0, 0),         # (odd both ways: 17 pairs, a byte and rows no copy reaches)
    (("yuv420p", 64, 36, None, None), 0, 0, 0),
    (("yuv420p", 1920, 1080, "1", None), 3, 1, 3),     # HOS_VIDEO_RGBA=1: one conversion a picture, one context
    (("yuv420p", 35, 7, "1", None), 3, 1, 3),
    (("yuv420p", 64, 36, "1", None), 3, 1, 3),
    (("yuv420p", 64, 36, "0", None), 0, 0, 0),         # (=0 is not the switch)
    (("yuva420p", 64, 36, None, None), 3, 1, 3),       # with alpha: made at once, either way
    (("yuva420p", 64, 36, "1", None), 3, 1, 3),
    (("other", 64, 36, None, None), 3, 1, 3),          # a format that is not copied: converted, its NV12 zeros
    (("nv12", 64, 36, None, "mf"), 0, 0, 0),           # Media Foundation's NV12: as before
    (("nv12", 64, 36, "1", "mf"), 0, 0, 0),            # ... with the switch too, as before
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    video = vf.video_source()

    vf.check('#include "video_nv12.h"' in video, "nn_video.c does not take video_nv12.h")
    eager = vf.block(video, "static int rgba_eager(void) {")
    vf.check('if (on < 0) on = getenv("HOS_VIDEO_RGBA") != NULL && atoi(getenv("HOS_VIDEO_RGBA")) != 0;' in eager,
             "HOS_VIDEO_RGBA is not read once")
    queue = vf.block(video, "static void queue_frame(Dec *d, const AVFrame *f) {")
    lazy = "const int lazy = video_rgba_lazy(rgba_eager(), f->format == AV_PIX_FMT_NV12, f->format == AV_PIX_FMT_YUV420P);"
    vf.check(lazy in queue, "queue_frame does not ask the rule whether the picture is kept as NV12 alone")
    vf.check("if (!lazy && (!d->sws || d->sws_w != w || d->sws_h != h || d->sws_fmt != f->format)) {" in queue
             and queue.index(lazy) < queue.index("sws_getContext("), "queue_frame builds a swscale context for a lazy picture")
    vf.check("p.rgba = lazy ? NULL : (uint8_t *)malloc((size_t)w * h * 4);" in queue, "queue_frame allocates RGBA for a lazy picture")
    vf.check("if (d->sws && p.rgba) sws_scale(" in queue, "queue_frame converts a picture that has no RGBA buffer")
    vf.check("calloc(" not in queue and "p.nv12 = (uint8_t *)malloc((size_t)w * h * 3 / 2);" in queue
             and "if (video_nv12_zero(w, h, nv12 || planar)) memset(p.nv12, 0, (size_t)w * h * 3 / 2);" in queue,
             "queue_frame zeroes every picture's NV12 buffer, or none")
    vf.check("video_uv_interleave(uv + (size_t)y * w, f->data[1] + (size_t)y * f->linesize[1]," in queue
             and "uv[(size_t)y * w + 2 * x]" not in queue, "queue_frame interleaves U and V one byte at a time")
    vf.check("if (p->rgba && o->rgba) memcpy(" in video and "o->rgba_stale = !p->rgba;" in video,
             "dec_acquire no longer leaves a lazy picture's RGBA to its pool")
    dev = (vf.ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    vf.check("`HOS_VIDEO_RGBA=1`" in dev, "docs/development.md: HOS_VIDEO_RGBA=1 is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="video-lazy-rgba-") as tmp:
        src, exe = Path(tmp) / "rules.c", Path(tmp) / "rules.exe"
        src.write_text(RULES, encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(vf.HOST), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        vf.check(r.returncode == 0, "the lazy rule, the zeroing rule or the interleave:\n" + r.stdout)
        if not vf.WINDOWS:
            print(vf.WINDOWS_ONLY)
            print("PASS: planar 4:2:0 pictures are kept as NV12 alone unless HOS_VIDEO_RGBA=1 (the rules and the source)")
            return
        exe = vf.build(tmp, args.cc, PICTURES)
        for (fmt, w, h, rgba_env, av1_env), rgba, contexts, conversions in CASES:
            out = vf.run(exe, fmt, str(w), str(h), HOS_VIDEO_RGBA=rgba_env, HOS_AV1=av1_env)
            case = "%s %dx%d, HOS_VIDEO_RGBA=%s, HOS_AV1=%s" % (fmt, w, h, rgba_env, av1_env)
            vf.check("FAIL:" not in out, case + ":\n" + out)
            vf.check(("decoder Media Foundation" in out) == (av1_env == "mf"), case + ": the wrong decoder:\n" + out)
            m = re.search(r"^queued: rgba (\d+), nv12-equal (\d+), contexts (\d+), conversions (\d+), rgba-filled (\d+)$", out, re.M)
            vf.check(m is not None, case + ":\n" + out)
            got = tuple(int(x) for x in m.groups())
            vf.check(got == (rgba, 3, contexts, conversions, rgba),
                     "%s: of 3 pictures %d have an RGBA, %d an NV12 equal to the reference, with %d swscale contexts and %d "
                     "conversions (%d RGBA filled); expected %d, 3, %d, %d" % ((case,) + got + (rgba, contexts, conversions)))
            m = re.search(r"^taken: pool-nv12-equal (\d), rgba-left-for-the-read (\d), conversions-at-the-read (\d+), read-is-0x5A (\d)$", out, re.M)
            vf.check(m is not None and m.group(1) == "1", case + ": the pool's NV12 is not the picture's:\n" + out)
            vf.check(m.group(2) == ("0" if rgba else "1"), case + ": whether the pool's RGBA waits for a read:\n" + out)
            if w <= 64 and h <= 36:   # (the read into the stand-in's guest window)
                vf.check(m.group(3) == ("0" if rgba else "1") and m.group(4) == "1",
                         case + ": ReadDecoderOutputImageRgba does not make a lazy picture's RGBA once, then give it:\n" + out)
    print("PASS: planar 4:2:0 pictures are kept as NV12 alone, their RGBA made when it is read; HOS_VIDEO_RGBA=1 as before")


if __name__ == "__main__":
    main()
