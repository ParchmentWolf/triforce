"""The log's writer thread on Linux too, and the recordings' two log lines out of their lock (no game needed).

(Triforce, 11-22, the performance audit's THREAD-56, after Source A's.) On Windows a writer thread makes every log
write; on Linux and the Steam Deck hos_log wrote stderr in the thread that logged, a game thread with its virtual core
held, and nvnCommandBufferEndRecording did so with the recordings' lock held exclusively: one blocked write stopped
every thread that records or calls a recording. Source A saw a 717 ms frame of it.

Reads the source:
  host/hos_thread.c: the writer's guard leaves out only the web build; HOS_LOG_SYNC still turns it off; on the
    systems other than Windows the queue is also flushed at quick_exit, which is how the POSIX shim's ExitProcess
    ends the process (atexit's functions do not run there);
  every Win32 name the writer block uses is declared in host/posix/windows.h;
  host/nvn_native.c: sweep_overwritten_copies returns its count and logs nothing; EndRecording calls hos_log nowhere
    between taking copy_lock and releasing it.
And cuts EndRecording's tail (from the recordings' counter to the end of its two lines) out of host/nvn_native.c and
runs it 120,000 times over stand-ins for the lock, the sweep, the virtual core and the log:
  no line is logged with the lock held; every line is logged with the virtual core given up, and the core is taken
  back after; the sweep's line comes at most 12 times with the count the sweep returned; the 50,000-recording line
  comes twice, with the numbers as they were under the lock; the lock is released exactly once a recording.

    python -I -B tests/test_log_off_lock.py [--cc clang]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "clang"]


def block(text, marker, what):
    start = text.find(marker)
    if start < 0:
        raise SystemExit("FAIL: %s has no '%s'" % (what, marker))
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef long long LONG64;
typedef int SRWLOCK;
static SRWLOCK copy_lock;
static int held, releases, away_now, aways, backs, fails;
static int swept_lines, made_lines, sweeps;
static size_t ncopies = 100, npins = 7;
static volatile LONG64 copy_bytes = 3 << 20, seg_bytes = 5 << 20, seg_count = 9;
#define SWEEP_EVERY 1024u
#define FAIL(...) do { fails++; if (fails < 10) { printf("FAIL: " __VA_ARGS__); printf("\n"); } } while (0)
static void AcquireSRWLockExclusive(SRWLOCK *l) { (void)l; if (held) FAIL("the lock taken twice"); held = 1; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { (void)l; if (!held) FAIL("the lock released while not held"); held = 0; releases++; }
static int vcore_held = 1;   /* (the calling game thread holds a virtual core) */
static int hos_vcore_away(void) { if (held) FAIL("the virtual core given up with the lock held"); aways++; if (!vcore_held) return 0; vcore_held = 0; away_now = 1; return 1; }
static void hos_vcore_back(void) { backs++; vcore_held = 1; away_now = 0; }
static size_t sweep_overwritten_copies(void) {   /* (copy_lock held: every third sweep lets 5 copies go) */
    if (!held) FAIL("the sweep ran without the lock");
    sweeps++;
    if (sweeps % 3) return 0;
    ncopies -= 5;
    return 5;
}
static size_t live_at_made[4];
static void hos_log(const char *fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    if (held) FAIL("logged with copy_lock held: %s", line);
    if (!away_now || vcore_held) FAIL("logged with the virtual core held: %s", line);
    if (strstr(line, "let go")) {
        swept_lines++;
        static const char pre[] = "nvn: 5 copies of recordings whose control memory was reused let go (";
        if (strncmp(line, pre, sizeof pre - 1)) FAIL("the sweep's line: %s", line);
    } else if (strstr(line, "recordings made")) {
        char want[256];
        if (made_lines < 4) {
            snprintf(want, sizeof want, "nvn: %d recordings made, %zu live copies (3.0 MB), 7 texture copies; 9 command buffers' segments (5.0 MB)",
                     50000 * (made_lines + 1), live_at_made[made_lines]);
            if (strcmp(line, want)) FAIL("the recordings' line: %s (expected %s)", line, want);
        }
        made_lines++;
    } else FAIL("another line: %s", line);
}
static void end_recording_tail(void) {
    AcquireSRWLockExclusive(&copy_lock);
    ncopies++;
@CUT@
    if (held) FAIL("the lock still held after the tail");
}
int main(void) {
    for (int i = 1; i <= 120000; i++) {
        /* (what the 50,000-recording line must say: the live copies as they are under the lock at that recording) */
        if (i % 50000 == 0) live_at_made[i / 50000 - 1] = ncopies + 1 - ((i % 1024 == 0 && (sweeps + 1) % 3 == 0) ? 5 : 0);
        end_recording_tail();
        if (!vcore_held) FAIL("the virtual core not taken back after recording %d", i);
    }
    if (releases != 120000) FAIL("the lock released %d times in 120000 recordings", releases);
    if (sweeps != 120000 / 1024) FAIL("%d sweeps", sweeps);
    if (swept_lines != 12) FAIL("the sweep's line came %d times (39 sweeps let copies go; 12 lines at most)", swept_lines);
    if (made_lines != 2) FAIL("the 50,000-recording line came %d times", made_lines);
    if (aways != backs || aways < 13 || aways > 14) FAIL("the core was given up %d times and taken back %d times for 14 lines", aways, backs);
    if (fails) printf("log off lock: FAILED (%d)\n", fails);
    else printf("log off lock: EndRecording's tail passed (120000 recordings, %d sweep lines, %d recordings' lines)\n", swept_lines, made_lines);
    return fails != 0;
}
'''

# (C's own names the writer block spells in capitals, and the block's own: not Win32's)
NOT_WIN32 = {"NULL", "LOG_BATCH_FULL", "HOS_LOG_BATCH_MS", "HOS_LOG_SYNC", "CRT"}


def check_writer(thread_c):
    start_marker = "#if !defined(__EMSCRIPTEN__)\nstatic SRWLOCK log_lock = SRWLOCK_INIT, log_write_lock = SRWLOCK_INIT;"
    end_marker = "\n#else\nstatic int log_queue(const char *line) { (void)line; return 0; }\nstatic void log_flush(void) {}\n#endif"
    if thread_c.count(start_marker) != 1 or thread_c.count(end_marker) != 1:
        raise SystemExit("FAIL: host/hos_thread.c: the log's writer is not built for every system but the web build "
                         "(its guard must be #if !defined(__EMSCRIPTEN__))")
    writer = thread_c[thread_c.index(start_marker):thread_c.index(end_marker)]
    if "_WIN32) && !defined(__EMSCRIPTEN__)\nstatic SRWLOCK log_lock" in thread_c:
        raise SystemExit("FAIL: host/hos_thread.c: the log's writer is Windows only")
    queue = block(writer, "static int log_queue(const char *line) {", "the writer")
    order = [queue.find(n) for n in ('int on = !getenv("HOS_LOG_SYNC");', "CreateThread(NULL, 0, log_main, NULL, 0, NULL)",
                                     "if (on) atexit(log_flush);", "#ifndef _WIN32", "if (on) at_quick_exit(log_flush);",
                                     "#endif", "log_async = on;")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("FAIL: host/hos_thread.c log_queue: HOS_LOG_SYNC, the writer's start, atexit and (off Windows) "
                         "at_quick_exit are not there in that order (%r)" % (order,))
    shim_c = (ROOT / "host/posix/win32_posix.c").read_text(encoding="utf-8")
    if "quick_exit((int)code);" not in block(shim_c, "void ExitProcess(UINT code) {", "host/posix/win32_posix.c"):
        raise SystemExit("FAIL: the POSIX shim's ExitProcess no longer ends with quick_exit: look again at how the log's "
                         "queue is flushed when the game ends on Linux")
    # every Win32 name the writer uses is one the POSIX shim declares
    shim_h = (ROOT / "host/posix/windows.h").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", " ", writer, flags=re.S)
    code = re.sub(r'"(\\.|[^"\\])*"', '""', code)
    names = set(re.findall(r"\b(?:[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*|[A-Z][A-Z0-9_]{2,}|_strdup)\b", code)) - NOT_WIN32
    for must in ("SRWLOCK", "CONDITION_VARIABLE", "SleepConditionVariableSRW", "WakeConditionVariable", "CreateThread",
                 "GetCurrentThreadId", "GetTickCount64", "WriteFile", "GetStdHandle", "SetUnhandledExceptionFilter",
                 "TryAcquireSRWLockExclusive", "_strdup"):
        if must not in names:
            raise SystemExit("FAIL: the writer block was not read as expected (%s not found in it)" % must)
    missing = sorted(n for n in names if not re.search(r"\b%s\b" % re.escape(n), shim_h))
    if missing:
        raise SystemExit("FAIL: host/posix/windows.h does not declare what the log's writer uses on Linux: " + ", ".join(missing))
    return len(names)


def check_recordings(nvn_c):
    sweep = block(nvn_c, "static size_t sweep_overwritten_copies(void) {", "host/nvn_native.c")
    if "hos_log(" in sweep or "return swept;" not in sweep or "if (off || !rec_buckets) return 0;" not in sweep:
        raise SystemExit("FAIL: sweep_overwritten_copies (copy_lock held) must return its count and log nothing")
    if "static void sweep_overwritten_copies(" in nvn_c:
        raise SystemExit("FAIL: sweep_overwritten_copies still returns nothing")
    end = block(nvn_c, "NV(nvnCommandBufferEndRecording) {", "host/nvn_native.c")
    if end.count("AcquireSRWLockExclusive(&copy_lock);") != 1 or end.count("ReleaseSRWLockExclusive(&copy_lock);") != 1:
        raise SystemExit("FAIL: nvnCommandBufferEndRecording no longer takes and releases copy_lock once")
    locked = end[end.index("AcquireSRWLockExclusive(&copy_lock);"):end.index("ReleaseSRWLockExclusive(&copy_lock);")]
    if "hos_log(" in locked or "fprintf(" in locked or "fputs(" in locked:
        raise SystemExit("FAIL: nvnCommandBufferEndRecording writes a log line with copy_lock held")
    if "sweep_overwritten_copies()" not in locked:
        raise SystemExit("FAIL: nvnCommandBufferEndRecording no longer sweeps under copy_lock")
    first, last = "    static uint64_t made;\n", "        if (away) hos_vcore_back();\n    }\n"
    if end.count(first) != 1 or end.count(last) != 1 or end.index(first) > end.index(last):
        raise SystemExit("FAIL: nvnCommandBufferEndRecording's tail (the counter, the sweep, the lines) was not found")
    tail = end[end.index(first):end.index(last) + len(last)]
    order = [tail.find(n) for n in ("ReleaseSRWLockExclusive(&copy_lock);", "const int away = hos_vcore_away();",
                                    "let go (%zu live)", "recordings made, %zu live copies", "if (away) hos_vcore_back();")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("FAIL: nvnCommandBufferEndRecording's two lines are not written after the lock is released, "
                         "with the virtual core given up (%r)" % (order,))
    return tail


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    n = check_writer((ROOT / "host/hos_thread.c").read_text(encoding="utf-8"))
    print("log off lock: the writer is every system's but the web build's; its %d Win32 names are in host/posix/windows.h" % n)
    tail = check_recordings((ROOT / "host/nvn_native.c").read_text(encoding="utf-8"))
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "| `HOS_LOG_SYNC=1`, `HOS_LOG_BATCH_MS=<ms>` |" not in docs:
        raise SystemExit("FAIL: docs/development.md: the switches table has no HOS_LOG_SYNC row")
    with tempfile.TemporaryDirectory(prefix="log-off-lock-") as tmp:
        src, exe = Path(tmp) / "log_off_lock_test.c", Path(tmp) / "log-off-lock.exe"
        src.write_text(FIXTURE.replace("@CUT@", tail), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print((r.stdout + r.stderr).rstrip())
        if r.returncode:
            raise SystemExit("FAIL: EndRecording's tail logs under its lock, or with the virtual core held")


if __name__ == "__main__":
    main()
