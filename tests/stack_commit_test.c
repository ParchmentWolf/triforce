/* A thread's stack at Windows' commit limit (host/mkw_glue.c stack_on_touch), around the real handler cut out by
   tests/test_stack_commit.py (stack_commit.inc), registered as hos_commit_init registers it (stack_commit_handlers.inc).
   Windows only: the process puts itself in a Job object whose commit limit it then fills, as a PC at its limit is, and a
   thread with a 64 MB stack that is only reserved (as host/hos_thread.c makes the guest's) grows it. No game, window or GPU.

   stack_commit_test.exe recovers [small] [guarantee] | never [small] [guarantee] | ran-out
   - recovers: commit comes back 300 ms after the thread starts (another thread gives back 8 MB, as the renderer's textures
     give commit back): the thread grows its stack 6.4 MB deep and returns; exit 0.
   - never: nothing is given back: the thread dies with 0xc00000fd after the out-of-memory line (the process's exit code).
   - small (with recovers or never): the thread's frames are 512 bytes, not 16 KB, so its stack pointer is in the last
     committed page when the next is refused (16 KB frames probe ahead of it, leaving the handler plenty).
   - guarantee (with recovers or never): the thread asks for 32 KB of stack for its own overflow first
     (SetThreadStackGuarantee), as the game's threads and fibers do (host/hos_thread.c hos_stack_guarantee).
   - ran-out: no commit limit, a stack (1 MB asked for) that really runs out, 1.6 GB deep: 0xc00000fd at once, not tried
     again for ever. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "host_alloc.h"   /* (host/: HOS_COMMIT_WAIT_MS's rule and the step the handler waits in) */

/* ---- stand-ins for what the cut code calls ---- */
/* (as much stack as the real one, hos_thread.c's hos_vlog: 4.3 KB of buffers. A handler that logs before its stack has room
   runs off the page Windows committed, as it would in the game. Written with no heap: the process is at its commit limit) */
static void hos_log(const char *fmt, ...) {
    char buf[1024], line[3300];
    va_list a;
    va_start(a, fmt);
    int n = vsnprintf(buf, sizeof buf, fmt, a);
    va_end(a);
    if (n < 0) return;
    n = snprintf(line, sizeof line, "[hos test] %s\n", buf);
    if (n < 0) return;
    if (n > (int)sizeof line - 1) n = (int)sizeof line - 1;
    DWORD w;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), line, (DWORD)n, &w, NULL);
}
static DWORD WINAPI hos_out_of_memory_box(LPVOID unused) { (void)unused; return 0; }   /* (no notice window in a test) */
int hos_commit_wait_ms(void) { return host_alloc_wait_ms(getenv("HOS_COMMIT_WAIT_MS")); }   /* (host_alloc.h declares it) */

#include "stack_commit.inc"

static void register_handlers(void) {
#include "stack_commit_handlers.inc"
}

/* ---- the case ---- */
static void *ballast[8];
static HANDLE go, ready;
static int guarantee;

/* (16 KB frames: each probed a page at a time below a stack pointer that is still well above, as large frames are) */
static int deep(int n) {
    volatile char buf[16384];
    buf[0] = (char)n;
    if (n == 0) return buf[0];
    return deep(n - 1) + buf[0];
}
/* (512-byte frames: the stack pointer itself is in the page Windows committed when the next one is refused, so the handler
   has under 4 KB to run on where the thread asked for no guarantee) */
static int shallow(int n) {
    volatile char buf[480];
    buf[0] = (char)n;
    if (n == 0) return buf[0];
    return shallow(n - 1) + buf[0];
}
static void begin(void) {
    if (guarantee) {   /* (host/hos_thread.c hos_stack_guarantee) */
        ULONG bytes = 32768;
        SetThreadStackGuarantee(&bytes);
    }
    SetEvent(ready);
    WaitForSingleObject(go, INFINITE);
}
static DWORD WINAPI grower(LPVOID depth) {
    begin();
    return (DWORD)deep((int)(intptr_t)depth) == 0xFFFFFFFF;
}
static DWORD WINAPI grower_small(LPVOID depth) {
    begin();
    return (DWORD)shallow((int)(intptr_t)depth) == 0xFFFFFFFF;
}
static DWORD WINAPI giver(LPVOID unused) {
    (void)unused;
    WaitForSingleObject(go, INFINITE);
    Sleep(300);
    for (int i = 0; i < 8; i++) VirtualFree(ballast[i], 0, MEM_RELEASE);
    return 0;
}

int main(int argc, char **argv) {
    const char *c = argc > 1 ? argv[1] : "";
    int small = 0;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "small")) small = 1;
        if (!strcmp(argv[i], "guarantee")) guarantee = 1;
    }
    register_handlers();
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    go = CreateEventA(NULL, TRUE, FALSE, NULL);
    ready = CreateEventA(NULL, TRUE, FALSE, NULL);
    if (!strcmp(c, "ran-out")) {
        HANDLE t = CreateThread(NULL, 1 << 20, grower, (LPVOID)(intptr_t)100000, STACK_SIZE_PARAM_IS_A_RESERVATION, NULL);
        SetEvent(go);
        const DWORD waited = WaitForSingleObject(t, 20000);
        DWORD code = 0;
        GetExitCodeThread(t, &code);
        hos_log("FAIL: a 1 MB stack 1.6 GB deep came back (wait %lu, thread exit %#lx, error %lu)", waited, code, GetLastError());
        return 1;
    }
    if (strcmp(c, "recovers") && strcmp(c, "never")) return 2;
    /* the threads first (their first stack pages, and the guarantee's), then the process's commit filled to the limit */
    HANDLE t = small ? CreateThread(NULL, 64 << 20, grower_small, (LPVOID)(intptr_t)12800, STACK_SIZE_PARAM_IS_A_RESERVATION, NULL)
                     : CreateThread(NULL, 64 << 20, grower, (LPVOID)(intptr_t)400, STACK_SIZE_PARAM_IS_A_RESERVATION, NULL);   /* (6.4 MB) */
    /* (the giver's 256 KB of stack committed now, not as it grows: at the limit it would need commit itself to give any back) */
    HANDLE g = !strcmp(c, "recovers") ? CreateThread(NULL, 256 << 10, giver, NULL, 0, NULL) : NULL;
    if (t) WaitForSingleObject(ready, INFINITE);
    HANDLE job = CreateJobObjectA(NULL, NULL);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION li = {0};
    li.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY;
    li.ProcessMemoryLimit = 256 << 20;
    if (!t || !job || !SetInformationJobObject(job, JobObjectExtendedLimitInformation, &li, sizeof li) ||
        !AssignProcessToJobObject(job, GetCurrentProcess())) {
        hos_log("SKIP: no Job object with a commit limit here (error %lu)", GetLastError());
        return 4;
    }
    for (int i = 0; i < 8; i++) ballast[i] = VirtualAlloc(NULL, 1 << 20, MEM_COMMIT, PAGE_READWRITE);
    for (SIZE_T step = 1 << 20; step >= 4096; step >>= 4)
        while (VirtualAlloc(NULL, step, MEM_COMMIT, PAGE_READWRITE)) {}
    if (!ballast[7] || GetLastError() != ERROR_COMMITMENT_LIMIT) {
        hos_log("FAIL: the commit limit was not reached (error %lu)", GetLastError());
        return 1;
    }
    SetEvent(go);
    WaitForSingleObject(t, INFINITE);
    DWORD code = 0;
    GetExitCodeThread(t, &code);
    if (g) WaitForSingleObject(g, INFINITE);
    hos_log("the thread grew its stack 6.4 MB deep at the commit limit and returned %lu", code);
    return (int)code;
}
