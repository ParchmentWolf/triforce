/* (Triforce, 11-22, the performance audit's IO-32, after Source A's) What one movie cost to decode: a count kept by the
   decoder (nn_video.c decode_next, queue_frame, the catch-up in dec_acquire) and one line in the log when the movie is
   stopped, flushed or its decoder finalized. Nothing was timed before: whether a decoder keeps up with a movie (a
   picture is due every 16.7 ms) could only be guessed from the pictures skipped.

   (Triforce, 11-22, THREAD-82) The line also has the gap between two pictures as the movie plays, and says when the
   decoder is slower than that: such a movie falls behind its sound (video_catchup.h).

   The counts and the line alone, no decoder and no clock: tests/test_video_av1_order.py compiles them. */
#pragma once
#include <stdint.h>
#include <stdio.h>

typedef struct {
    int64_t pictures;    /* pictures decoded since the movie's start */
    int64_t decode_ns;   /* the time its submissions took to decode, pictures made ready for the game included */
    int64_t worst_ns;    /* the longest of them */
    int64_t skipped;     /* pictures dropped to catch up with the movie's clock */
    int64_t refused;     /* ((Triforce, 11-22, IO-34) submissions refused while the decoder's input was full: video_input.h) */
} VideoMovie;

/* one submission decoded, in ns by the clock */
static inline void video_movie_decoded(VideoMovie *m, int64_t ns) {
    if (ns < 0) ns = 0;
    m->decode_ns += ns;
    if (ns > m->worst_ns) m->worst_ns = ns;
}

/* The movie's line into out (without the log's "video: "): 0 and nothing written when no picture was decoded, so a
   Stop followed by a Flush, or a decoder finalized after its Stop, says it once. spacing_ns: the gap between two
   pictures as the movie plays, 0 when it is not known (video_catchup.h) */
static inline int video_movie_line(const VideoMovie *m, const char *decoder, int64_t spacing_ns, char *out, size_t size) {
    if (m->pictures <= 0) return 0;
    char shown[80] = "";
    if (spacing_ns > 0)
        snprintf(shown, sizeof shown, ", one shown every %.2f ms%s", (double)spacing_ns / 1e6,
                 m->decode_ns / m->pictures > spacing_ns ? " (slower than it plays)" : "");
    char refused[80] = "";
    if (m->refused > 0)
        snprintf(refused, sizeof refused, ", %lld submissions refused while its input was full", (long long)m->refused);
    snprintf(out, size, "a movie of %lld pictures on %s: %.2f ms to decode each (worst %.2f)%s; %lld skipped to catch up%s",
             (long long)m->pictures, decoder, (double)m->decode_ns / 1e6 / (double)m->pictures, (double)m->worst_ns / 1e6,
             shown, (long long)m->skipped, refused);
    return 1;
}
