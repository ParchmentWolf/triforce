/* SPDX-License-Identifier: GPL-3.0-or-later
   (Triforce) tests/test_crash_record.py's fixture: host/hos_crash_record.c as it is (included whole, for its statics), with
   host/mkw_glue.c's record_exception and hos_crash_record_fatal cut in at RECORD_EXCEPTION by the test. The game, its
   threads and its guest memory are stand-ins. One mode a run: argv[1] the game folder, argv[2] the mode. */
#define _GNU_SOURCE
#define _CRT_SECURE_NO_WARNINGS
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hos_crash_record.c"

void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
}
const char *hos_version(void) { return "fixture-v1"; }

typedef struct Ctx { uint64_t x[32]; } Ctx;
typedef struct HosThread { char name[64]; } HosThread;
static HosThread guest_thread = {"fixture-thread"};
static Ctx guest_context;
static unsigned char guest_memory[1024];
#define A64_MEM guest_memory
#define HOS_GUEST_SPACE sizeof guest_memory
static Ctx *hos_ctx(void) { return &guest_context; }
static HosThread *hos_self(void) { return &guest_thread; }
static const char *hos_thread_name(HosThread *t) { return t->name; }
/* RECORD_EXCEPTION */

static void authored_context(HosCrashContext *c) {
    memset(c, 0, sizeof *c);
    c->reason = "unhandled exception";
    c->thread = guest_thread.name;
    c->code = 0xc0000005u;
    c->pc = (uintptr_t)authored_context;
    c->sp = (uintptr_t)c;
    c->guest_base = (uintptr_t)guest_memory;
    c->guest_size = sizeof guest_memory;
    c->fault_address = c->guest_base + 64;
    c->guest_registers = guest_context.x;
}
#ifdef _WIN32
static LONG WINAPI filter(EXCEPTION_POINTERS *info) {
    record_exception(info);
    return EXCEPTION_CONTINUE_SEARCH;
}
#endif
static void quit_now(int code) {   /* (no atexit: a process ended from outside, or by the game's own ExitProcess) */
#ifdef _WIN32
    TerminateProcess(GetCurrentProcess(), (UINT)code);
#else
    _exit(code);
#endif
}

int main(int argc, char **argv) {
    assert(argc >= 3);
#ifdef _WIN32
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
#endif
    const char *mode = argv[2];
    char log[PATH_CAP];
    assert(join(log, sizeof log, argv[1], "triforce_log.txt"));
    hos_crash_record_start(argv[1], "fixture-v1", log);
    printf("run_id: %s\n", hos_report_run_id());
    fflush(stdout);
    hos_crash_record_log_notes();
    if (!strcmp(mode, "read-only")) { assert(!ready); return 0; }
    assert(ready);
    for (unsigned i = 0; i < 32; ++i) guest_context.x[i] = 0x1000 + i;
    guest_context.x[29] = 64, guest_context.x[30] = 0x80001234;
    const uint64_t frames[] = {80, 0x80005678, 0, 0x80009abc};
    memcpy(guest_memory + 64, frames, sizeof frames);
    { char stamp[17]; timestamp(0, stamp); assert(!strcmp(stamp, "19700101T000000Z")); }
    assert(hos_crash_record_marker(argv[1], session.pid, session.run_id) == (
#ifdef _WIN32
        2   /* (Windows: the live owner's lock) */
#else
        1
#endif
    ));
    if (!strcmp(mode, "clean")) { hos_crash_clean_end(); hos_crash_clean_end(); return 0; }
    if (!strcmp(mode, "return")) return 0;   /* (atexit) */
    if (!strcmp(mode, "killed")) quit_now(3);
    if (!strcmp(mode, "quit-killed")) { hos_crash_quit_asked(); hos_crash_quit_asked(); quit_now(3); }
    if (!strcmp(mode, "fatal")) { hos_crash_record_fatal(guest_context.x, "hos_fatal"); quit_now(3); }
    if (!strcmp(mode, "device-lost")) {
        hos_crash_record_fatal(NULL, "device lost");
        hos_crash_record_fatal(NULL, "Vulkan fatal");   /* (a second fatal line never replaces the first record) */
        quit_now(3);
    }
    if (!strcmp(mode, "label")) {
        char out[160];
        hos_crash_redact(out, sizeof out, "a\tb\x01" "c\xc3\xa9", 6);
        printf("label: %s\n", out);
        hos_crash_clean_end();
        return 0;
    }
#ifdef _WIN32
    if (!strcmp(mode, "crash")) {
        SetUnhandledExceptionFilter(filter);
        static volatile uintptr_t address = 0x40;
        *(volatile int *)address = 1;
        return 91;
    }
#endif
    HosCrashContext c;
    authored_context(&c);
    if (!strcmp(mode, "privacy")) {
        const char *home = getenv(
#ifdef _WIN32
            "USERPROFILE"
#else
            "HOME"
#endif
        );
        snprintf(guest_thread.name, sizeof guest_thread.name, "%s/t", home ? home : "");
    }
    if (!strcmp(mode, "bounds")) {
        struct { char bytes[8]; char guard; } small = {{0}, 'X'};
        Text out = {small.bytes, sizeof small.bytes, 0, 0};
        format_record(&out, &session, &c, epoch_now(), NULL);
        assert(out.full && small.guard == 'X');
    }
    assert(hos_crash_record_write(&c) == 1);
    assert(hos_crash_record_write(&c) == 0);   /* (reentry or a second fault: the first record stands) */
    hos_crash_clean_end();   /* (no effect once a record was claimed) */
    return 0;
}
