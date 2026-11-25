/* (Triforce, 11-24) OoT's job barriers wait for their masks instead of sleeping (host/oot_barrier.h has the protocol and why):
   nx2/oot_patches.py patch_barrier_wait makes the lifted f_800998a0, f_800738e0 and f_8007e200 call hos_oot_barrier_wait in
   place of the 20 us SleepThread of each of their five barrier loops, and hos_oot_barrier_wake right after each atomic OR
   into a mask word those loops poll.

   HOS_OOT_BARRIER_WAIT: unset or on, the waits (the default); off (0, false, off, no), the game's sleeps as before. Read
   once, through hos_oot_barrier_on, the one place the hooks ask. */
#include "hos.h"
#include <stdlib.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

/* (a wait's longest: the safety net, as the game's loop looks again after it. A wait ends at the OR that moves a word it
   polls; only a word moved by code without the wake call waits this long. The game asked for 20 us, which Windows' timer
   gave as ~0.5 ms; WaitOnAddress counts milliseconds) */
#define OOT_BARRIER_TIMEOUT_NS 1000000

#ifdef _WIN32
/* (from kernelbase.dll, without linking Synchronization.lib) */
typedef BOOL(WINAPI *BarrierWaitFn)(volatile VOID *, PVOID, SIZE_T, DWORD);
typedef VOID(WINAPI *BarrierWakeFn)(PVOID);
static BarrierWaitFn barrier_wait_fn;
static BarrierWakeFn barrier_wake_fn;
static int barrier_bind(void) {
    const HMODULE k = GetModuleHandleA("kernelbase.dll");
    if (!k) return 0;
    barrier_wait_fn = (BarrierWaitFn)(void *)GetProcAddress(k, "WaitOnAddress");
    barrier_wake_fn = (BarrierWakeFn)(void *)GetProcAddress(k, "WakeByAddressAll");
    return barrier_wait_fn && barrier_wake_fn;
}
#define OOT_BARRIER_WAIT_ON(a, v, ms) \
    do { uint32_t seen_ = (v); barrier_wait_fn((volatile VOID *)(a), &seen_, 4, (DWORD)(ms)); } while (0)
#define OOT_BARRIER_WAKE_ALL(a) barrier_wake_fn((PVOID)(uintptr_t)(a))
#else
/* (host/posix's WaitOnAddress and WakeByAddressAll: a futex on the word) */
static int barrier_bind(void) { return 1; }
#define OOT_BARRIER_WAIT_ON(a, v, ms) \
    do { uint32_t seen_ = (v); WaitOnAddress((volatile void *)(a), &seen_, 4, (DWORD)(ms)); } while (0)
#define OOT_BARRIER_WAKE_ALL(a) WakeByAddressAll((void *)(uintptr_t)(a))
#endif
#define OOT_BARRIER_NOW_NS() hos_now_ns()
#include "oot_barrier.h"

static OotBarrier barrier;
static int barrier_mode = -1;   /* (-1 not read yet, 0 off, 1 on) */
static volatile long long barrier_how[3], barrier_waited_ns, barrier_wakes;

/* (a switch's value that turns it off: 0, off, no, false, spaces around it let through; nothing at all is not off here) */
static int barrier_value_off(const char *v) {
    while (*v == ' ' || *v == '\t') v++;
    size_t n = strlen(v);
    while (n && (v[n - 1] == ' ' || v[n - 1] == '\t' || v[n - 1] == '\r' || v[n - 1] == '\n')) n--;
    return (n == 1 && v[0] == '0') || (n == 3 && !memcmp(v, "off", 3)) || (n == 2 && !memcmp(v, "no", 2)) ||
           (n == 5 && !memcmp(v, "false", 5));
}

/* whether the hooks wait (1) or the game sleeps as before (0): HOS_OOT_BARRIER_WAIT, read once. The one function the
   lifted code asks. WaitOnAddress is looked up whatever the switch says.
   On by default: no wait here is longer than OOT_BARRIER_TIMEOUT_NS (the game's loop then looks again, as after its
   sleep), so a wake that never came costs a millisecond and not a job. Source A's in-run A/Bs standing in Castle Town's
   market (18 Nov), 4 cores: frame time -3.2 % in both runs (frames of 16.7 ms or more 30 -> 19 % and 26 -> 16 %); 16
   cores: no difference either way. Not measured here. HOS_OOT_BARRIER_WAIT=0: the game's sleeps, as before. */
int hos_oot_barrier_on(void) {
    int m = __atomic_load_n(&barrier_mode, __ATOMIC_ACQUIRE);
    if (__builtin_expect(m < 0, 0)) {
        const char *e = getenv("HOS_OOT_BARRIER_WAIT");
        m = !(e && barrier_value_off(e));
        /* (looked up before the mode is set, so a thread that reads a set mode has the two functions; every thread that
           gets here finds the same two) */
        if (!barrier_bind() && m) {
            hos_log("barrier: no WaitOnAddress on this system: the game's job barriers sleep as before");
            m = 0;
        }
        int unset = -1;
        if (__atomic_compare_exchange_n(&barrier_mode, &unset, m, 0, __ATOMIC_RELEASE, __ATOMIC_ACQUIRE) && m)
            hos_log("barrier: the game's job barriers (f_800998a0, f_800738e0, f_8007e200) wait until their masks move "
                    "instead of sleeping 20 us (HOS_OOT_BARRIER_WAIT=0: the sleeps, as before)");
        m = __atomic_load_n(&barrier_mode, __ATOMIC_ACQUIRE);
    }
    return m;
}

static void barrier_count(int how, int64_t waited) {
    __atomic_add_fetch(&barrier_how[how], 1, __ATOMIC_RELAXED);
    if (waited) __atomic_add_fetch(&barrier_waited_ns, waited, __ATOMIC_RELAXED);
    const long long n0 = barrier_how[0], n1 = barrier_how[1], n2 = barrier_how[2];
    /* (every 16,384 waits that waited: the barrier sleeps came ~1,400 times a second standing in the market on 4 logical
       processors, Source A's samples, so about every 12 s) */
    if (how != OOT_BARRIER_AT_ONCE && !((n1 + n2) & 16383))
        hos_log("barrier: %lld looks: %lld found the masks moved already, %lld waited until they moved, %lld for the whole "
                "%d ms (a wait %.0f us on average); %lld wakes", n0 + n1 + n2, n0, n1, n2, OOT_BARRIER_TIMEOUT_NS / 1000000,
                barrier_waited_ns / 1e3 / (double)(n1 + n2), barrier_wakes);
}

/* In place of the barrier's SleepThread. p: the job block; off1, off2: the offsets in it of the mask words the loop polls
   (the same twice for one word); seen1, seen2: their values when the loop's pass looked; full: the value at which the loop
   leaves. 1: the wait was done here (the loop then looks again, without the sleep); 0: the switch is off (the sleep runs) */
int hos_oot_barrier_wait(uint64_t p, uint32_t off1, uint32_t seen1, uint32_t off2, uint32_t seen2, uint32_t full) {
    if (!hos_oot_barrier_on()) return 0;
    volatile uint32_t *const w[OOT_BARRIER_WORDS] = {(volatile uint32_t *)GP(p + off1), (volatile uint32_t *)GP(p + off2)};
    const uint32_t seen[OOT_BARRIER_WORDS] = {seen1, seen2};
    const int n = off1 == off2 ? 1 : 2;
    if (oot_barrier_moved(w, seen, n, full)) {   /* (moved since the pass looked: back to the loop, the core kept) */
        barrier_count(OOT_BARRIER_AT_ONCE, 0);
        return 1;
    }
    const int64_t t0 = hos_now_ns();
    const int away = hos_vcore_away();   /* (the core given up, as a sleep does: host/hos_thread.c sleep_away) */
    const int how = oot_barrier_wait(&barrier, p, w, seen, n, full, OOT_BARRIER_TIMEOUT_NS);
    if (away) hos_vcore_back();
    const int64_t waited = hos_now_ns() - t0;
    barrier_count(how, waited > 0 ? waited : 1);
    return 1;
}

/* Right after an atomic OR into a polled mask word of job block p */
void hos_oot_barrier_wake(uint64_t p) {
    if (!hos_oot_barrier_on()) return;
    if (oot_barrier_wake(&barrier, p)) __atomic_add_fetch(&barrier_wakes, 1, __ATOMIC_RELAXED);
}
