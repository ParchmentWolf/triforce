/* (Triforce, 11-21, the performance audit's OS-31, after Source A's) How sleeps under a millisecond wait.

   The game's idle job workers, and its main thread at its barriers, sleep 20 us and look again, about 7,600 times a
   second. A sleep under a millisecond is yielded away until its time (the timer wakes about 0.5 ms late, which made
   those waits 25 times longer on the frame's critical path), so each sleeper keeps a processor busy. On a PC with few
   processors that is time the frame's own threads need: Source A measured, with the game held to 4 processors, a tenth
   more frames, no frame over 250 ms where the yielding runs had them, and on 6 the same frame rate for a tenth less CPU;
   from 8 on, no gain. So with 6 or fewer logical processors in the process's mask the game's own short sleeps wait on
   the high-resolution timer, and the host's own (the frame limiter, the audio renderer) keep yielding. Above 6 nothing
   changes.

   HOS_SHORT_SLEEP_TIMER: not set, by the processors; 1 (any value that is not off): every short sleep on the timer; 0,
   off, no, false: every short sleep yields.

   (Triforce, 11-22, the performance audit's OS-32, after Source A's) Off Windows the processors are not counted, so
   every short sleep yielded there whatever the PC, the Steam Deck's 8 logical processors included. Source A, off
   Windows and with the switch not set, puts the game's own short sleeps on the timer at any processor count (the
   timer there is the POSIX shim's clock_nanosleep, which wakes tens of microseconds late, not half a millisecond),
   so idle workers stop holding processors the frame needs. That mode was never measured in the game by itself (with
   every short sleep on the timer a 24-thread Linux PC lost 2.9% of its frame rate for a fifth less CPU), and it
   cannot be run on the PC this was written on: it is built, and is not the default. HOS_SHORT_SLEEP_TIMER=game asks
   for it on any system; SHORT_SLEEP_ELSEWHERE below is what a build that is not Windows' does with the switch not
   set: SHORT_SLEEP_YIELD, as before, until a Steam Deck A/B says SHORT_SLEEP_GUEST_TIMER (Source A's default).
   (Triforce, 11-24) Now SHORT_SLEEP_GUEST_TIMER, Source A's default, measured there on Linux by itself: Hyrule Field on a
   24-thread 7900X with an RTX 3090, the frame's CPU 44.8 -> 35.4 ms at the same median frame (11.30 / 11.32 ms), the
   five idle job workers and sead::MainThread no longer yielding 3.3-3.6 ms a frame each; the workers are off the frame's
   critical path there. On 4-8 thread PCs (the Steam Deck: 8) those yields held processors the frame needs. Windows is
   unchanged (it counts the processors). HOS_SHORT_SLEEP_TIMER=0: all yield, as before

   The rule alone, no threads and no clock: tests/test_short_sleep_timer.py compiles it. */
#pragma once
#include <stdint.h>
#include <string.h>

enum { SHORT_SLEEP_TIMER_THREADS = 6 };   /* (no more than the game's six cores) */
enum { SHORT_SLEEP_YIELD = 0, SHORT_SLEEP_GUEST_TIMER = 1, SHORT_SLEEP_ALL_TIMER = 2 };

/* A switch's value that turns it off: 0, off, no, false (and nothing at all) */
static inline int short_sleep_value_off(const char *v) {
    return !v || !*v || !strcmp(v, "0") || !strcmp(v, "off") || !strcmp(v, "no") || !strcmp(v, "false");
}

/* How short sleeps wait. asked: HOS_SHORT_SLEEP_TIMER's value, NULL when it is not set. threads: the logical processors
   the process may run on, 0 when not known (more than one processor group, or not Windows) */
static inline int short_sleep_timer(const char *asked, int threads) {
    if (asked) return short_sleep_value_off(asked) ? SHORT_SLEEP_YIELD : SHORT_SLEEP_ALL_TIMER;
    return threads > 0 && threads <= SHORT_SLEEP_TIMER_THREADS ? SHORT_SLEEP_GUEST_TIMER : SHORT_SLEEP_YIELD;
}

/* ((Triforce, 11-22, the performance audit's OS-32) what a build that is not Windows' does with the switch not set */
#define SHORT_SLEEP_ELSEWHERE SHORT_SLEEP_GUEST_TIMER

/* The same with the system: windows, a Windows build (the processors count there); elsewhere, what any other build does
   with the switch not set (SHORT_SLEEP_ELSEWHERE). "game": the game's own short sleeps on the timer, the host's
   yield, at any processor count on any system */
static inline int short_sleep_timer_os(const char *asked, int threads, int windows, int elsewhere) {
    if (asked && !strcmp(asked, "game")) return SHORT_SLEEP_GUEST_TIMER;
    if (!asked && !windows) return elsewhere;
    return short_sleep_timer(asked, threads);
}

/* Whether a sleep of ns is yielded away until its time. guest: the game's own sleep (SleepThread), not the host's */
static inline int short_sleep_yields(int64_t ns, int how, int guest) {
    return ns < 1000000 && how < (guest ? SHORT_SLEEP_GUEST_TIMER : SHORT_SLEEP_ALL_TIMER);
}

/* (Triforce, 11-22, the performance audit's OS-33, after Source A's) A cap on the game threads that yield through a short
   sleep at once. Where the game's short sleeps yield (more than 6 logical processors), every idle job worker keeps a
   processor busy. Source A lets at most a quarter of the processors' worth of game threads do so at a time (2 with 8, 4
   with 16, 6 with 24); the next sleeper waits on the timer, about 0.5 ms late. Its numbers are provisional: with 16
   processors 2.7% less CPU a frame for the same frame rate; a 24-thread run held to 2 yielding threads lost 1.7% of its
   frame rate. The game's MainThread and Presentation Thread, which the frame waits on, and the host's own sleeps are
   never counted and always yield.

   Off unless asked for, as it changes how the game's threads wait and was not measured here:
   HOS_SHORT_SLEEP_POLLERS not set, or 0, off, no, false: no limit, as before; a number: at most that many (1024 at
   most); auto (any other word): a quarter of the process's logical processors when they are more than 6, else no limit.
   Any HOS_SHORT_SLEEP_TIMER value turns the cap off (the switch then says how every short sleep waits), and so does a
   choice other than "all yield". */
enum { SHORT_SLEEP_POLLERS_MOST = 1024 };

/* The cap: 0 for no limit. asked: HOS_SHORT_SLEEP_POLLERS's value, NULL when not set; timer_asked: HOS_SHORT_SLEEP_TIMER's;
   how: short_sleep_timer's choice; threads: the process's logical processors, 0 when not known */
static inline int short_sleep_pollers(const char *asked, const char *timer_asked, int how, int threads) {
    if (timer_asked || how != SHORT_SLEEP_YIELD || short_sleep_value_off(asked)) return 0;
    if (asked[0] >= '0' && asked[0] <= '9') {
        int n = 0;
        for (const char *p = asked; *p >= '0' && *p <= '9' && n <= SHORT_SLEEP_POLLERS_MOST; p++) n = n * 10 + (*p - '0');
        return n > SHORT_SLEEP_POLLERS_MOST ? SHORT_SLEEP_POLLERS_MOST : n;
    }
    return threads > SHORT_SLEEP_TIMER_THREADS ? threads / 4 : 0;
}

/* The choice kept in one word, made once: how, and the cap above it */
static inline int short_sleep_word(int how, int cap) { return how | cap << 2; }
static inline int short_sleep_how(int word) { return word & 3; }
static inline int short_sleep_cap(int word) { return word >> 2; }

/* A thread the frame waits on, never counted: the game's MainThread (by any longer name too) and its Presentation Thread */
static inline int short_sleep_serial_name(const char *name) {
    return name && (strstr(name, "MainThread") != NULL || !strcmp(name, "Presentation Thread"));
}

/* The cap's gate, around the yielding. 1: this sleep yields; 0: it waits on the timer. pollers: the counted threads
   yielding now. cap 0, a host sleep or a serial thread: not counted, yields. A counted one yields while it is one of at
   most `cap`; one over the cap gives its count back here. *took: the count is held and must be given back with
   short_sleep_poll_leave once the yielding is over: one decrement on every path */
static inline int short_sleep_poll_enter(int *pollers, int cap, int guest, int serial, int *took) {
    *took = 0;
    if (cap <= 0 || !guest || serial) return 1;
    if (__atomic_add_fetch(pollers, 1, __ATOMIC_RELAXED) <= cap) {
        *took = 1;
        return 1;
    }
    __atomic_sub_fetch(pollers, 1, __ATOMIC_RELAXED);
    return 0;
}
static inline void short_sleep_poll_leave(int *pollers, int took) {
    if (took) __atomic_sub_fetch(pollers, 1, __ATOMIC_RELAXED);
}
