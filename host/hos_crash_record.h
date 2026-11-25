/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <stddef.h>
#include <stdint.h>

/* No renderer ABI: crash-reports/pending/crash-<UTC>.txt is the boundary. All strings copied by
   the crash writer are bounded; arbitrary fatal messages and memory are omitted. */
typedef struct HosCrashContext {
    const char *reason;                /* a fixed diagnostic label, never a formatted message */
    const char *thread;
    uint32_t code;
    int signal_number, signal_code;
    uintptr_t pc, sp, fp, fault_address;
    uintptr_t guest_base;
    uint64_t guest_size;
    const uint64_t *guest_registers;    /* x0..x31; read without dereferencing a bad pointer */
    void *native_context;             /* Windows CONTEXT when available */
    int exception_filter;             /* only this path actually requests the opt-in dump */
} HosCrashContext;

/* Normal startup, before installing handlers. dir is the game folder, not cwd.
   log_path is the game's own log (triforce_log.txt) chosen before rotation, or NULL when the
   game does not open one (stderr kept). Failure (read-only folder etc.) disables recording without affecting the game. */
void hos_crash_record_start(const char *dir, const char *version, const char *log_path);
/* Explicit process-exit sites (ExitProcess/_exit do not run atexit). Never removes
   a report; only this process's running marker and its empty staging file. */
void hos_crash_clean_end(void);
/* The player asked to quit (host/rx_backend.c rx_close_asked): a note in the marker, so an end while closing is no crash. */
void hos_crash_quit_asked(void);
/* The crash window (host/hos_crash_dialog.c): this run's id, log path ("" for none) and game folder; NULL when not recording. */
const char *hos_crash_record_run(void);
const char *hos_crash_record_log(void);
const char *hos_crash_record_dir(void);
/* The crash window's helper, after its game ended: a start's recovery, without a marker of its own. */
int hos_crash_record_recover(const char *dir);
/* A run's marker: 0 gone, 1 this run's, 2 there but unreadable (locked by its live owner), 3 another run's. */
int hos_crash_record_marker(const char *dir, uint64_t pid, const char *run_id);
/* Normal startup, after the version/run-id banner: at most one fixed pruning warning. */
void hos_crash_record_log_notes(void);
/* Failing-thread path: fixed buffers, OS reads/writes, no allocation or stdio.
   The first caller wins; reentry and competing faults never overwrite a record. */
int hos_crash_record_write(const HosCrashContext *context); /* 1 only for the publishing caller */
/* mkw_glue.c: adapt a normal fatal call, including hos_fatal and renderer FATAL. */
void hos_crash_record_fatal(const uint64_t *guest_registers, const char *reason);

/* A record's single-line label (version, thread, module, the log's file name): the home folder and the user's name out, as
   the game's log leaves them out (host/log_redact.c, the one redactor; HOS_LOG_REDACT=0: as it is), and any control or
   non-ASCII byte written '?', so a label never breaks the record's "key: value" lines. No allocation: the crash path's */
size_t hos_crash_redact(char *out, size_t cap, const char *text, size_t size);
#ifdef _WIN32
/* After the text is durable: request the startup-created, opt-in dump worker (HOS_CRASH_MINIDUMP=1, off by default).
   exception is EXCEPTION_POINTERS; the worker uses a copied exception/context. */
void hos_crash_record_dump(void *exception);
#endif
