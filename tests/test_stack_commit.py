"""A thread's stack at Windows' commit limit (host/mkw_glue.c stack_on_touch; no game). A thread's stack is only reserved
(the guest's 64 MB, host/hos_thread.c), each page committed as it grows. At the commit limit Windows can't commit the next
one and raises a stack overflow (0xc00000fd) with the stack nearly unused. Guest memory already waits there for commit to
come back (commit_wait); a stack now does too, and the thread goes on.

The real handler is cut out of host/mkw_glue.c (its enum and statics to the end of stack_on_touch) and compiled with
tests/stack_commit_test.c, registered as hos_commit_init registers it. Each case in its own process, which puts itself in
a Job object with a commit limit and fills it:

- recovers: commit comes back 300 ms after a thread with a reserved 64 MB stack starts growing it: it gets 6.4 MB deep and
  returns (before, it died with 0xc00000fd);
- never: nothing comes back: after the wait (HOS_COMMIT_WAIT_MS, 1 s here), the out-of-memory line, then 0xc00000fd (the
  crash report's, as before); with HOS_COMMIT_WAIT_MS=0 the same with no wait at all;
- both again with 512-byte frames ("small"), whose stack pointer is in the last committed page when the next is refused:
  the handler has under 4 KB to run on, and the stand-in hos_log takes the real one's 4.3 KB, so a handler that logs
  before it has committed room below the stack dies there with no line;
- both again on a thread that asked for 32 KB for its own overflow first ("guarantee": SetThreadStackGuarantee, as the
  game's threads and fibers do, host/hos_thread.c hos_stack_guarantee), with large frames and small ones;
- ran-out: a stack that really runs out (1.6 GB deep): 0xc00000fd at once, never tried again for ever.

Windows only (Job objects, the stack's guard page); skipped elsewhere.

    python -I -B tests/test_stack_commit.py [--cc clang]
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "clang"]
RUN_ALL_SKIP = {"linux": "Windows only: a Job object's commit limit and a thread stack's guard page"}
STACK_OVERFLOW = 0xC00000FD
OOM_LINE = "mem: Windows is out of memory (RAM and page file)"
START = "enum { STACK_ROOM = 0x10000, STACK_SPARE = 1 << 20 };"
HANDLER = "static LONG CALLBACK stack_on_touch(EXCEPTION_POINTERS *info) {"


def fail(message):
    raise SystemExit("FAIL: " + message)


def cut(glue):
    """mkw_glue.c's stack handler: its enum and statics to the end of stack_on_touch"""
    start, at = glue.find(START), glue.find(HANDLER)
    if start < 0 or at < start:
        fail("mkw_glue.c has no stack_on_touch after its STACK_ROOM enum")
    end = glue.index("{", at) + 1
    depth = 1
    while depth:
        depth += (glue[end] == "{") - (glue[end] == "}")
        end += 1
    return glue[start:end] + "\n"


def handlers(glue, code):
    """hos_commit_init's lines for the cut code, in its order: the AddVectoredExceptionHandler call whose handler is in it,
    and what it sets of the cut code's own statics (stack_spare, the commit held back for a stack that never grew, and
    stack_wait_ms, the wait's length)"""
    init = glue.find("void hos_commit_init(void)")
    body = glue[init:glue.index("\n}", init)] if init >= 0 else ""
    kept = []
    for line in body.splitlines():
        line = line.strip()
        call = re.fullmatch(r"AddVectoredExceptionHandler\((\d+), (\w+)\);", line)
        if call and re.search(r"static LONG CALLBACK %s\(" % call.group(2), code):
            kept.append(line)
        static = re.fullmatch(r"(\w+) = .*;", line)
        if static and re.search(r"^static [^;(]*\b%s;" % static.group(1), code, re.M):
            kept.append(line)
    if not any(line.startswith("AddVectoredExceptionHandler") for line in kept):
        fail("hos_commit_init registers no handler from the cut code")
    if not any(line.startswith("stack_spare = ") for line in kept) or "stack_wait_ms = hos_commit_wait_ms();" not in kept:
        fail("hos_commit_init no longer commits the spare for a stack that never grew, or no longer reads the wait's length")
    return kept


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    if os.name != "nt":
        print("SKIP: " + RUN_ALL_SKIP["linux"])
        return
    cc = shutil.which(args.cc) or shutil.which("gcc")
    if not cc:
        raise SystemExit("test_stack_commit: no C compiler %r (pass --cc)" % args.cc)
    glue = (ROOT / "host/mkw_glue.c").read_text(encoding="utf-8")
    code = cut(glue)
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    base = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}
    with tempfile.TemporaryDirectory(prefix="stack-commit-") as temporary:
        folder = Path(temporary)
        (folder / "stack_commit.inc").write_text(code, encoding="utf-8")
        (folder / "stack_commit_handlers.inc").write_text("\n".join(handlers(glue, code)) + "\n", encoding="utf-8")
        executable = folder / "stack_commit_test.exe"
        built = subprocess.run([cc, "-std=gnu11", "-O1", "-Wall", "-Wno-unused-function", "-I", str(folder), "-I", str(ROOT / "host"),
                                str(ROOT / "tests/stack_commit_test.c"), "-o", str(executable)], capture_output=True, text=True,
                               creationflags=flags)
        if built.returncode:
            print(built.stdout + built.stderr)
            fail("the fixture did not build")

        def run(case, *more, wait=None):
            env = dict(base) if wait is None else dict(base, HOS_COMMIT_WAIT_MS=wait)
            result = subprocess.run([str(executable), case, *more], env=env, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=60, creationflags=flags)
            code = result.returncode & 0xFFFFFFFF
            print("%s%s: exit %#x\n%s" % (" ".join((case,) + more), "" if wait is None else " (HOS_COMMIT_WAIT_MS=%s)" % wait, code,
                                          result.stderr), end="")
            if code == 4:
                raise SystemExit("SKIP: " + result.stderr.strip())
            return code, result.stderr

        kinds = ((), ("small",), ("guarantee",), ("small", "guarantee"))
        for more in kinds:
            what = "".join(" " + m for m in more)
            code, err = run("recovers", *more)
            if code == STACK_OVERFLOW:
                fail("recovers%s: a thread whose stack page was refused at the commit limit died with a stack overflow "
                     "(0xc00000fd), with commit given back 300 ms later and most of its 64 MB unused" % what)
            if code or "returned 0" not in err:
                fail("recovers%s: the thread did not grow its stack and return (exit %#x)" % (what, code))
        for more in kinds:
            for wait in ("1000", "0"):
                code, err = run("never", *more, wait=wait)
                if code != STACK_OVERFLOW or OOM_LINE not in err:
                    fail("never%s: wanted the out-of-memory line, then 0xc00000fd (exit %#x)" % ("".join(" " + m for m in more), code))
                waited = re.search(r"still could not grow after (\d+) ms", err)
                if not waited or int(waited.group(1)) != int(wait):
                    fail("never: the wait was not HOS_COMMIT_WAIT_MS's %s ms" % wait)
        code, err = run("ran-out")
        if code != STACK_OVERFLOW:
            fail("ran-out: a stack that really ran out did not end with 0xc00000fd (exit %#x)" % code)
    print("PASS: a stack page refused at the commit limit waits for commit and the thread goes on; one that never comes, "
          "or a stack that really ran out, still ends as a stack overflow")


if __name__ == "__main__":
    main()
