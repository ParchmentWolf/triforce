"""The x64 stack walks in host/mkw_glue.c (the crash report's, HOS_SAMPLE's and HOS_SAMPLE_ALL's) can't fault: each goes
one frame at a time through unwind_step, which checks the stack pointer, and the frame register when the function has
one, against the walked thread's own stack before RtlVirtualUnwind reads through them, and the new stack pointer after
(an unchecked walk read 0x438 in ntdll from sample_all_thread and took the game down).

The source checks run everywhere. Where the compiler targets Windows the helpers (StackRange to unwind_step, cut out
unchanged) are also built and run: a thread that calls and returns without end is stopped 3,000 times wherever it is and
walked on its own stack, as the samplers walk the game's threads, and the walk never faults and reaches a caller; a
context whose stack pointer is no stack (0x438, 0, the end of the stack, another thread's stack) steps nowhere and reads
nothing; and a thread's stack is its TEB's.

    python -I -B tests/test_sampler_stack_walk.py [--cc clang]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(ok, what):
    if not ok:
        raise SystemExit("FAIL: sampler stack walk: " + what)


def sources():
    src = (ROOT / "host/mkw_glue.c").read_text(encoding="utf-8")
    step = block(src, "static int unwind_step(CONTEXT *ctx, StackRange s)")
    # (the unwinder is called in one place, the step, and nowhere else in the file)
    need(src.count("RtlVirtualUnwind(") == 1 and "RtlVirtualUnwind(" in step, "RtlVirtualUnwind called outside unwind_step")
    need(src.count("RtlLookupFunctionEntry(") == 1, "RtlLookupFunctionEntry called outside unwind_step")
    # (the stack pointer is checked before anything is read, the frame register before the unwind, the result after)
    first = step.index("if (!on_stack(s, ctx->Rsp)) return 0;")
    need(first < step.index("RtlLookupFunctionEntry("), "the stack pointer is not checked before the unwind data is read")
    need(step.index("if (frame_reg && !on_stack(s, (&ctx->Rax)[frame_reg])) return 0;") < step.index("RtlVirtualUnwind("),
         "the frame register is not checked before the unwind")
    need("return on_stack(s, ctx->Rsp) || !ctx->Rip;" in step, "the unwound stack pointer is not checked")
    need("if (rf->UnwindData & 1)" in step, "a chained RUNTIME_FUNCTION entry is read as unwind info")
    stack = block(src, "static StackRange thread_stack(HANDLE th)")
    need('"NtQueryInformationThread"' in stack and "tbi.teb->StackLimit" in stack and "tbi.teb->StackBase" in stack,
         "the walked thread's stack is not taken from its TEB")
    # (each walk steps through it, on the right stack)
    walks = (("static LONG WINAPI report_crash(", "const StackRange stack = own_stack();", "unwind_step(&ctx, stack)"),
             ("static DWORD WINAPI sample_thread(void *p)", "thread_stack(th)", "unwind_step(&ctx, stack)"),
             ("static DWORD WINAPI sample_all_thread(void *p)", "thread_stack(th[i])", "unwind_step(&ctx, stack)"))
    for marker, stack_of, call in walks:
        body = block(src, marker)
        need(stack_of in body and call in body, "%s does not walk through unwind_step on its thread's stack" % marker)
    return src


RUN = r"""
static volatile LONG stop;
static volatile LONG64 spins;
__attribute__((noinline)) static int leaf(int n) { volatile char pad[200]; pad[0] = (char)n; InterlockedIncrement64(&spins); return pad[0] + n; }
__attribute__((noinline)) static int middle(int n) { volatile char pad[3000]; pad[0] = (char)n; return n > 0 ? middle(n - 1) + pad[0] : leaf(n); }
static DWORD WINAPI churn(LPVOID unused) {
    (void)unused;
    int sum = 0;
    while (!stop) sum += middle((int)(spins & 31));   /* (frames made and ended without end, as a game thread's) */
    return (DWORD)sum;
}
static DWORD WINAPI idle(LPVOID unused) { (void)unused; Sleep(INFINITE); return 0; }
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
int main(void) {
    HANDLE th = CreateThread(NULL, 0, churn, NULL, 0, NULL), other = CreateThread(NULL, 0, idle, NULL, 0, NULL);
    long walked = 0, frames = 0, deepest = 0;
    while (!spins) Sleep(1);
    for (int i = 0; i < 3000; i++) {
        if (SuspendThread(th) == (DWORD)-1) break;
        CONTEXT ctx = {0};
        ctx.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        if (GetThreadContext(th, &ctx)) {
            const StackRange stack = thread_stack(th);
            CHECK(stack.lo && stack.lo < stack.hi);
            long depth = 0;
            while (depth < 48 && ctx.Rip && unwind_step(&ctx, stack)) depth++;
            walked++, frames += depth;
            if (depth > deepest) deepest = depth;
        }
        ResumeThread(th);
        if (!(i & 63)) Sleep(0);
    }
    CHECK(walked == 3000);
    CHECK(deepest >= 2);   /* (it reached a caller: the walk works where the frame is whole) */
    {   /* contexts that are no frame of that stack: nothing is read, the walk ends at once */
        SuspendThread(th);
        CONTEXT ctx = {0};
        ctx.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        GetThreadContext(th, &ctx);
        const StackRange stack = thread_stack(th), none = {0, 0}, elsewhere = thread_stack(other);
        CONTEXT bad = ctx;
        bad.Rsp = 0x438;
        CHECK(!unwind_step(&bad, stack));
        bad = ctx, bad.Rsp = 0;
        CHECK(!unwind_step(&bad, stack));
        bad = ctx, bad.Rsp = stack.hi - 4;   /* (its 8 bytes would end past the stack) */
        CHECK(!unwind_step(&bad, stack));
        bad = ctx;
        CHECK(!unwind_step(&bad, none));     /* (the limits could not be read: no step) */
        CHECK(elsewhere.lo && (elsewhere.hi <= stack.lo || elsewhere.lo >= stack.hi));
        bad = ctx;
        CHECK(!unwind_step(&bad, elsewhere));   /* (another thread's stack is not this one's) */
        CHECK(bad.Rsp == ctx.Rsp && bad.Rip == ctx.Rip);   /* (and a refused step leaves the context as it was) */
        ResumeThread(th);
    }
    {
        const StackRange own = own_stack();
        volatile char here;
        CHECK(own.lo <= (uint64_t)(uintptr_t)&here && (uint64_t)(uintptr_t)&here < own.hi);
    }
    stop = 1;
    WaitForSingleObject(th, 5000);
    printf("%ld walks, %ld frames, the deepest %ld\n", walked, frames, deepest);
    printf(fails ? "%d failed\n" : "ok\n", fails);
    return fails != 0;
}
"""


def compiled(cc, src):
    """the helpers built and run on their own, where cc builds for Windows (windows.h and the unwinder)"""
    try:
        target = subprocess.run([cc, "-dumpmachine"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        print("skip the run: no %s" % cc)
        return False
    if os.name != "nt" or ("mingw" not in target and "windows" not in target):
        print("skip the run: %s builds for %s, not Windows" % (cc, target.strip()))
        return False
    start = src.index("typedef struct { uint64_t lo, hi; } StackRange;")
    end = src.index("#endif", src.index("static int unwind_step(CONTEXT *ctx, StackRange s)"))
    unit = "#include <stdint.h>\n#include <stdio.h>\n#include <windows.h>\n" + src[start:end] + RUN
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    with tempfile.TemporaryDirectory(prefix="sampler-walk-") as tmp:
        f, exe = Path(tmp) / "walk.c", Path(tmp) / "walk.exe"
        f.write_text(unit, encoding="utf-8")
        r = subprocess.run([cc, "-std=gnu11", "-O1", "-Wall", "-Werror", "-Wno-deprecated-declarations", str(f), "-o", str(exe)],
                           capture_output=True, text=True)
        need(r.returncode == 0, "the helpers don't build on their own:\n" + r.stdout + r.stderr)
        done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120, creationflags=flags)
        print(done.stdout, end="")
        need(done.returncode == 0 and "ok" in done.stdout, "the walk of a running thread failed (exit %#x)" % (done.returncode & 0xFFFFFFFF))
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cc", default="clang")
    a = ap.parse_args()
    src = sources()
    ran = compiled(a.cc, src)
    print("PASS: the three stack walks step through unwind_step, which stays on the walked thread's stack%s"
          % (" (run on a thread stopped 3,000 times)" if ran else ""))


if __name__ == "__main__":
    main()
