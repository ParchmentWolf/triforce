"""A game folder from the user's own dump: what the builder app (builder/) runs.

    python -I nx2/make_game.py --nup <file.nup> --out <folder> [--work <folder>] [--jobs <n>]
    python -I nx2/make_game.py --romfs <dir> --exefs <dir> --out <folder> [--work <folder>] [--jobs <n>]
    python -I nx2/make_game.py --check --nup <file.nup>       (or --exefs <dir>: is this the right game and version?)
    python -I nx2/make_game.py --update <folder>             (a folder built before, again with these tools: the game files it keeps)
    python -I nx2/make_game.py --game <.nup or folder> --prepare   (RecompLauncher: --out defaults to ~/Games/Hookshot; no window,
                                                                    "progress <0..1> <text>" lines and an "error <text>" line on stdout,
                                                                    exit 0 when the game is built; with --check, its "check ok|bad" line)

The folder holds the executable and all it needs, started with a double click: nothing goes back into the repository, and no game
data ever comes with the tools. Lines the app reads, each on its own line of stdout:

    @@stage <id> <text>      a step begins
    @@progress <0..1>        how far that step is
    @@plan <changed> <total> how many files the compile rebuilds, of all of them
    @@file <name> <seconds> <new|cached|again>   one module's build
    @@eta <seconds>          the compile's time left, from what the earlier builds measured on this PC
    @@times <total> <compile> <previous|-1>      finished: this build's times beside the last one's
    @@check <ok|bad> <text>  (--check) the answer
    @@done <folder>          finished
    @@error <text>           stopped

and one plain line the builders also read (older ones only show it): "the shaders were not prepared now (<why>): ..." when the
build's last step, the shaders' preparation, was skipped or failed and is left to the game's first start (NOT_PREPARED)
"""
import argparse
import atexit
import contextlib
import errno
import ntpath
import filecmp
import hashlib
import importlib.util
import json
import locale
import os
import queue
import re
import shutil
import stat
import subprocess
import threading
import time
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = [sys.executable, "-I", "-u", "-X", "utf8"]   # (utf8: every step's output in UTF-8 whatever the console's code page: lift.py crashed on a letter, #180)   # (-u: the steps' output as it comes, not in 8 KB blocks minutes apart)
BUILD_ID = "e0f3ccfa"   # (the version the patches, the hot list and the profile were made from)
STARTED = time.time()   # (the build's total time, kept in build_times.json and said as @@times)
sys.path[:0] = [HERE, os.path.join(ROOT, "third_party", "a64-kit", "tools")]   # (python -I leaves the script folder off)
import toolchain as _toolchain
import disk as _disk
import object_store as _object_store
import build_jobs as _build_jobs
import code_mods as _code_mods   # (Triforce: the mods' patches of the game's code, applied before the lift)
import lift_store as _lift_store   # ((Triforce, 11-24) translations kept for other work folders, HOOKSHOT_LIFT_STORE: off unless set)
# (hookshot) RX_TARGET=windows on Linux: the Windows game, with llvm-mingw's Linux release (HOOKSHOT_MINGW, or llvm-mingw
# beside the builder), to run under Proton or copy to a Windows PC
LINUX, CROSS = not _toolchain.windows(), _toolchain.windows() and os.name != "nt"
# (SDL2.dll is sdl2-compat: it loads SDL3.dll from beside the exe. Left out of bin\ since v2.0.0, it said "Failed loading SDL3
# library" three times and no controller worked: Discord #bug-reporting, 11-08)
# ((Triforce) renhdrum.dll, renhdrum.so: RenHDrum, when scripts/renhdrum.py built it (nx2/build.py copy_renhdrum); optional)
BESIDE = ["triforce", "triforce_vk.so", "libSDL2-2.0.so.0", "renhdrum.so"] if LINUX else ["Triforce.exe", "triforce_vk.dll", "SDL2.dll", "SDL3.dll", "wgpu_native.dll", "renhdrum.dll"]
LANGUAGES = [("en-US", "English (US)"), ("en-GB", "English (UK)"), ("fr", "French (France)"), ("fr-CA", "French (Canada)"), ("de", "German"),
             ("it", "Italian"), ("es", "Spanish (Spain)"), ("es-419", "Spanish (Latin America)"), ("pt-BR", "Portuguese (Brazil)"), ("nl", "Dutch"),
             ("pl", "Polish"), ("ru", "Russian"), ("ja", "Japanese"), ("ko", "Korean"), ("zh-Hans", "Chinese (Simplified)"),
             ("zh-Hant", "Chinese (Traditional)")]


def no_throttle(handle=None):
    """(issue 87) Windows' power throttling (EcoQoS) slows a background window's processes to almost nothing on some machines: the
    build sat at 0% CPU. Turned off for this process, or the one whose handle this is"""
    if os.name != "nt":
        return
    import ctypes
    class State(ctypes.Structure):
        _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    s = State(1, 1, 0)   # (PROCESS_POWER_THROTTLING_EXECUTION_SPEED in the mask, off in the state)
    try:
        k.SetProcessInformation(ctypes.c_void_p(int(handle)) if handle else k.GetCurrentProcess(), 4, ctypes.byref(s), ctypes.sizeof(s))
    except (OSError, ValueError, TypeError):
        pass


PREPARE = False   # (--prepare) say() prints RecompLauncher's "progress <0..1> <text>" lines instead of the builder app's @@ lines
STAGE_SPAN = {"read": (0.0, 0.05), "lift": (0.05, 0.25), "compile": (0.25, 0.95), "finish": (0.95, 1.0)}   # (a share of the whole each stage takes)
_stage = {"span": (0.0, 1.0), "text": ""}


def say_prepare(words):
    if words[0] == "stage" and len(words) > 2:
        _stage["span"], _stage["text"] = STAGE_SPAN.get(words[1], _stage["span"]), " ".join(words[2:])
        print("progress %.3f %s" % (_stage["span"][0], _stage["text"]), flush=True)
    elif words[0] == "progress" and len(words) > 1:
        lo, hi = _stage["span"]
        print("progress %.3f %s" % (lo + (hi - lo) * float(words[1]), _stage["text"]), flush=True)
    elif words[0] in ("error", "check"):   # (on stdout, the only stream a launcher reads; HookshotBuilder --cli also takes its "error" line)
        print(" ".join(words), flush=True)
    elif words[0] == "done":
        print("progress 1.000 Done", flush=True)


STAGE_TIMES = []   # ((stage, when it began)): what each step of this build took, said at its end (stage_times)


def stage_times(now):
    """ "before the game files 0:41, read 1:32, lift 2:10, compile 7:42, finish 1:17": each stage's time up to the next
    one's start, the last one's up to now, and what came before the first (the tools' checks and what was fetched)"""
    if not STAGE_TIMES:
        return ""
    parts = [("before the game files", STAGE_TIMES[0][1] - STARTED)]
    for (name, began), (_, ended) in zip(STAGE_TIMES, STAGE_TIMES[1:] + [("", now)]):
        parts.append((name, ended - began))
    return ", ".join("%s %s" % (name, clock(seconds)) for name, seconds in parts)


def say(*words):
    if words and words[0] == "stage" and len(words) > 1:
        STAGE_TIMES.append((str(words[1]), time.time()))
    if PREPARE:
        return say_prepare([str(w) for w in words])
    print("@@" + " ".join(str(w) for w in words), flush=True)


def fail(text):
    say("error", text)
    sys.exit(1)


def game_copy(path, roots):
    """((Triforce, 11-24, after Source A's) Whether the process running path is a copy of the game being updated: Triforce.exe
    directly in one of roots (the game folder, or its bin folder), each root normcased and ending in a separator. Another
    program the player keeps in the folder is not (a launcher's portable exe there was taken for the game, named as the game
    still running, and the update stopped)"""
    path = os.path.normcase(path)
    return os.path.basename(path) == "triforce.exe" and os.path.dirname(path) + os.sep in roots


def end_stale_games(folders):
    """((Triforce, 11-24, after Source A's; Windows) The running copies of the game (game_copy) in one of folders, the game
    being updated: those with no visible window, a copy left behind (a shader preparation that hung, a game whose window
    closed but whose process did not end), are ended and waited for, as their file could not be replaced while they ran
    ("Could not replace ... Triforce.exe"). Returns the process ids of those with a window, which the player is to close: a
    game in play is never ended"""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []
    k32, u32 = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("user32", use_last_error=True)
    roots = [os.path.normcase(os.path.abspath(f)) + os.sep for f in folders]

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    found = []
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.th32ProcessID != os.getpid() and e.szExeFile.lower() == "triforce.exe":
                h = k32.OpenProcess(0x1000, False, e.th32ProcessID)   # (PROCESS_QUERY_LIMITED_INFORMATION)
                if h:
                    buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and game_copy(buf.value, roots):
                        found.append(e.th32ProcessID)
                    k32.CloseHandle(h)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    if not found:
        return []
    visible = set()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in found:
                visible.add(pid.value)
        return True
    u32.EnumWindows(proc(each), 0)
    for pid in found:
        if pid in visible:
            continue
        h = k32.OpenProcess(0x0001 | 0x00100000, False, pid)   # (PROCESS_TERMINATE | SYNCHRONIZE)
        if h:
            print("A copy of Triforce left running without a window (process %d) was ended so the update can replace it" % pid,
                  flush=True)
            k32.TerminateProcess(h, 1)
            k32.WaitForSingleObject(h, 10000)
            k32.CloseHandle(h)
    return sorted(visible)


# ((Triforce, 11-24, after Source A's) Windows' answers for a drive that cannot give back what it holds: ERROR_CRC,
# ERROR_IO_DEVICE, ERROR_FILE_CORRUPT, ERROR_DISK_CORRUPT)
DRIVE_ERRORS = {23: "a read failed its data check", 1117: "the drive reported an I/O error",
                1392: "the file or folder is corrupted and unreadable", 1393: "the disk structure is corrupted and unreadable"}


def drive_error(error):
    """((Triforce, 11-24, after Source A's) A drive that could not read its own files, said as that with what to do, or None
    for any other error. Listing the unpacked romfs's Tex folder stopped a build with "an error it did not expect: OSError:
    [WinError 1392]" and a request to report it: nothing in the tools or the game files is wrong there, and a rebuild meets it
    again until the drive is repaired"""
    if not isinstance(error, OSError):
        return None
    code = getattr(error, "winerror", None)
    if code in DRIVE_ERRORS:
        reason = "%s (Windows error %d)" % (DRIVE_ERRORS[code], code)
    elif code is None and error.errno == errno.EIO:
        reason = "the drive reported an I/O error"
    else:
        return None
    path = error.filename if isinstance(error.filename, str) else None
    drive = os.path.splitdrive(path)[0] if path and code is not None else ""
    check = ('open a terminal as administrator and run "chkdsk %s /f"' % drive if re.fullmatch("[A-Za-z]:", drive)
             else "check the drive for errors")
    return ("Your drive could not read %s: %s. This is a fault of the drive or its file system, not of Triforce or your "
            "game files. To repair it, %s, then build again. If it keeps happening the drive may be failing: build on "
            "another drive." % (path or "one of the build's files", reason, check))


def failure_reason(lines):
    """The line a stopped step is named with. Only the last 12 lines used to be kept, so a compiler's "error:" hundreds
    of lines earlier was replaced by "compiled in 790s, 1 failed"."""
    tail, seen = [], None
    for line in lines:
        tail = (tail + [line])[-12:]
        if "error:" in line.lower() and "CalledProcessError" not in line:
            seen = line
    if seen is not None:
        return seen
    return tail[-1] if tail else "no output"


def killed_reason():
    """(issues 478, 768, 807) A step stopped by SIGKILL or SIGTERM from outside the build: the builder's own Cancel stops make_game
    with it, so this is the system's, the kernel's or a desktop's low-memory killer most likely. Its last lines then said nothing
    of that (the lift's emit processes failing on their result pipe, BrokenPipeError, or the lift's last progress line)"""
    total = None
    try:
        with open("/proc/meminfo") as f:
            total = next((round(int(l.split()[1]) / (1 << 20)) for l in f if l.startswith("MemTotal:")), None)   # (kB, to the nearest GB)
    except (OSError, ValueError, IndexError):
        pass
    return ("the system stopped it, most likely because the PC ran out of memory%s. Close other programs and build again"
            % (" (%d GB here)" % total if total else ""))


def reported(line):
    """The sentence a builder shows. @@check is '@@check <ok|bad> <text>'; @@error is '@@error <text>'. None otherwise."""
    if line.startswith("@@error "):
        return line[len("@@error "):]
    if line.startswith("@@check "):
        parts = line.split(" ", 2)
        return parts[2] if len(parts) == 3 else ""
    return None


class LogStream:
    """Keep console output live while also saving it to the build log."""
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        result = self.console.write(text)
        self.log.write(text)
        self.flush()
        return result

    def flush(self):
        self.console.flush()
        self.log.flush()

    def __getattr__(self, name):
        return getattr(self.console, name)


@contextlib.contextmanager
def build_log(path):
    if path is None:
        yield
        return
    try:
        log = open(path, "w", encoding="utf-8", newline="\n")
    except OSError as e:
        fail("Could not open build log %s: %s" % (path, e))
    with log:
        with contextlib.redirect_stdout(LogStream(sys.stdout, log)), contextlib.redirect_stderr(LogStream(sys.stderr, log)):
            yield


TIMES_FORMAT = 1
KEEP_BUILDS = 20


def times_path(work):
    """Where the builds' times are kept: beside the object cache, in the builder's own folder (LOCALAPPDATA\\HookshotBuilder
    on Windows, ~/.cache/hookshot-builder on Linux). A builder update keeps it, so the next build still knows what this PC
    took, and the one after that can compare."""
    return os.path.join(work, "build_times.json")


def load_times(work):
    """The seconds each module took on this PC, and the last builds' totals; a fresh record when there is none to trust
    (missing, half written, or written by another version of the tools)."""
    data = {"format": TIMES_FORMAT, "builds": [], "seconds": {}}
    try:
        with open(times_path(work), encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return data
    if not isinstance(old, dict) or old.get("format") != TIMES_FORMAT:
        return data
    builds = old.get("builds")
    if isinstance(builds, list):
        data["builds"] = [b for b in builds
                          if isinstance(b, dict) and isinstance(b.get("total_seconds"), (int, float))][-KEEP_BUILDS:]
    seconds = old.get("seconds")
    if isinstance(seconds, dict):
        data["seconds"] = {str(k): float(v) for k, v in seconds.items()
                           if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return data


def save_times(work, data):
    """The whole file at once: a build stopped while writing it leaves the last record in place."""
    path = times_path(work)
    try:
        os.makedirs(work, exist_ok=True)
        with open(path + ".new", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(path + ".new", path)
    except OSError as e:
        print("the build times were not saved (%s)" % e, flush=True)


def record_times(work, files, compile_seconds, total_seconds, modules=0, kind="build"):
    """This build in the record: what each module it compiled took (a module a cache already held keeps the time it took
    before), the compile's and the whole build's seconds. Returns the last build's total, to show beside this one."""
    data = load_times(work)
    previous = data["builds"][-1]["total_seconds"] if data["builds"] else None
    data["seconds"].update({str(k): round(float(v), 1) for k, v in files.items() if v > 0})
    data["builds"].append({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "modules": int(modules),
                           "compiled": len(files), "compile_seconds": round(compile_seconds, 1),
                           "total_seconds": round(total_seconds, 1)})
    data["builds"] = data["builds"][-KEEP_BUILDS:]
    save_times(work, data)
    return previous


def clock(seconds):
    """A length of time the way the build's lines say it: '1:02:03'"""
    s = int(round(seconds))
    return "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60)


class Silent(Exception):
    """a step printed nothing for longer than run()'s silence"""


def output_lines(p, silence):
    """A step's lines as they come; with silence (seconds), read on a thread so that a step which goes quiet that long (a hung
    driver, a crash dialog left open) raises Silent instead of waiting for ever"""
    if silence is None:
        yield from p.stdout
        return
    lines = queue.Queue()

    def read():
        try:
            for line in p.stdout:
                lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError, ValueError):
                p.stdout.close()   # (here, not by run(): a stopped step's pipe may still be read by this thread)
            lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    while True:
        try:
            line = lines.get(timeout=silence)
        except queue.Empty:
            raise Silent() from None
        if line is None:
            return
        yield line


def stop_asked(p, stop, wait):
    """A silent step asked to stop by the file `stop` (written here), given `wait` seconds to end by itself, then killed. True:
    it ended by itself"""
    try:
        with open(stop, "wb"):
            pass
    except OSError:
        return False
    try:
        p.wait(timeout=wait)
        return True
    except subprocess.TimeoutExpired:
        return False


def run(cmd, env=None, on_line=None, check=True, output=None, show=None, cwd=ROOT, base=None, silence=None, stop=None,
        stop_wait=60, again=None, allow=()):
    """A step, its output printed as it comes. show: what of each line is printed (its None: nothing; on_line and a failure's
    reason still get the line itself). base: the environment it starts from (os.environ). silence: seconds without a line after
    which the step is stopped; it returns None then (with check, the build fails). stop: a file the step reads as a request to
    stop (the game's triforce_prepare.stop): on silence it is written first, and the step killed only if it has not ended
    stop_wait seconds later. again: asked before a step that failed fails the build; its True returns the status instead.
    allow: exit statuses returned as they are, not a failure ((Triforce) build.py's KEPT_STALE)"""
    e = dict(os.environ if base is None else base, PYTHONIOENCODING="utf-8")
    e.update(env or {})
    p = subprocess.Popen(cmd, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", bufsize=1)
    no_throttle(getattr(p, "_handle", None))
    lines = []
    try:
        for line in output_lines(p, silence):
            line = line.rstrip()
            shown = show(line) if show else line
            if shown is not None:
                print(shown, file=output, flush=True)
            lines.append(line)
            if on_line:
                on_line(line)
    except Silent:
        if not (stop and stop_asked(p, stop, stop_wait)):
            p.kill()
            p.wait()
        if check:
            fail("%s printed nothing for %s and was stopped" % (os.path.basename(cmd[0]), span(silence)))
        return None
    p.stdout.close()
    code = p.wait()
    if code and check and code not in allow and not (again and again()):
        step = next((os.path.basename(c) for c in cmd[1:] if c.endswith(".py")), os.path.basename(cmd[-1]))   # (issue 154: not "-u")
        status = "signal %d" % -code if os.name == "posix" and code < 0 else "exit status %d" % code
        fail("%s stopped (%s): %s" % (step, status, killed_reason() if os.name == "posix" and -code in (9, 15) else failure_reason(lines)))
    return code


def build_id(main):
    """the module id of an NSO, plain or compressed: the header is the same"""
    with open(main, "rb") as f:
        head = f.read(0x60)
    if head[:4] != b"NSO0":
        fail("%s is not a game executable" % main)
    return head[0x40:0x60].hex()


def check_modules(exefs):
    """Every module of the exefs is one the tools can read: said here, not as a Python error from the translator"""
    for name in os.listdir(exefs):
        if name != "main.npdm" and not name.endswith(".part"):
            with open(os.path.join(exefs, name), "rb") as f:
                head = f.read(16)
            if head[:4] != b"NSO0":
                fail("The file %s in this dump is not a game module (it starts %s). Try another dump of the game, or send this message to the "
                     "Triforce developers." % (name, head.hex()))


def check_supported_build(exefs):
    bid = build_id(os.path.join(exefs, "main"))
    if not bid.startswith(BUILD_ID):
        fail("This is build %s. Triforce supports build %s." % (bid[:8], BUILD_ID))


# ((Triforce, 11-24) Translate's bar as the lift's steps end: a line nx2/lift.py prints at each, and how far into the lift and
# split_hot it ends, from a lift of OoT with 8 spawned processes on a 16-thread PC (11-24: discovery 12 s, the coverage report
# 21 s, emit, write and split 38 s, patches, runtime tables and standalone files 65 s, page marks 67 s, split_hot 70 s). Before
# this the bar sat at Translate's start for the whole lift and then jumped to its end, so the build looked stuck)
LIFT_STEPS = ((re.compile(r"discovered \d+ functions"), 0.17), (re.compile(r"coverage report \("), 0.30),
              (re.compile(r"chunks: \d+, boundaries"), 0.54), (re.compile(r"standalone: hos_image\.c"), 0.93),
              (re.compile(r"wrote \d+ code files"), 0.96))


def lift_progress(tell=None):
    """An on_line for the lift's run(): Translate's '@@progress' as each of its steps ends (LIFT_STEPS), never back. A line the
    lift no longer prints only leaves the bar where it was"""
    tell = tell or (lambda f: say("progress", "%.3f" % f))
    at = [0.0]

    def on_line(line):
        for pattern, f in LIFT_STEPS:
            if f > at[0] and pattern.match(line):
                at[0] = f
                tell(f)
                return
    return on_line


def file_progress(verb, clock=time.monotonic):
    """A progress(done, total) for a long pass over many files: "@@progress" for the builder's bar of the step it is in, at most
    4 times a second and at the end, and a plain line at each tenth ("checked 40,000 of 102,185 files (40%, 51 s)"), so a log or a
    terminal shows it moving too"""
    start = clock()
    last = [None, 0]   # (when the last @@progress went out; the last tenth said)
    def progress(done, total):
        now = clock()
        if last[0] is None or now - last[0] >= 0.25 or done >= total:
            last[0] = now
            print("@@progress %.3f" % (done / total if total else 1.0), flush=True)
        tenth = done * 10 // total if total else 10
        if tenth > last[1]:
            last[1] = tenth
            print("%s %s of %s files (%d%%, %d s)" % (verb, format(done, ","), format(total, ","), tenth * 10, now - start),
                  flush=True)
    return progress


def unpack_seen(game):
    """What the unpack itself saw of the romfs .zs files it wrote (nx2/nup.py ZS_CHECKED, in the folder it extracted to):
    {"files": how many, "damaged": [paths under romfs]}, or None when it left no such note or one that cannot be right
    (then every file is opened and looked at, as before)"""
    import json
    import nup
    try:
        with open(os.path.join(game, nup.ZS_CHECKED), encoding="utf-8") as f:
            seen = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(seen, dict) or not isinstance(seen.get("files"), int) or not isinstance(seen.get("damaged"), list):
        return None
    for rel in seen["damaged"]:
        if not isinstance(rel, str):
            return None
        parts = rel.split("/")
        if not rel.endswith(".zs") or "\\" in rel or ":" in rel or any(p in ("", ".", "..") for p in parts):
            return None
    return seen


def read_stamp(path):
    """((Triforce, 11-24, after Source A's) An unpack's stamp, which holds the .nup's name: UTF-8, or the Windows code page an
    earlier builder wrote it in. Decoded exactly or not at all: a replaced letter would let another .nup's name match, and its
    unpack be skipped. A stamp that cannot be read is "", which no unpack's stamp equals"""
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8", locale.getpreferredencoding(False)):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return ""


def write_stamp(path, stamp):
    """((Triforce, 11-24) in UTF-8, not the code page: a .nup name outside it stopped the build (UnicodeEncodeError)"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(stamp)


def stand_in_damaged_files(out, romfs, seen=None):
    """An incomplete dump's damaged textures replaced by whole ones of the same kind, and said: without them the game
    leaves out the walls and floors that use them (the Water Temple, #1002). Only in a romfs this builder unpacked (its
    .triforce_romfs stamp), and once per unpack: .triforce_romfs_checked holds the stamp it was checked under.
    seen: what this unpack saw of its own .zs files as it wrote them (unpack_seen): the damaged ones are then known and
    no file is opened to find them. Opening all 102,185 took 292 s of an 18 minute build on a PC whose virus scanner
    looks at each file opened; a folder unpacked by an earlier builder, or read from this .nup before without the
    check's note, is still gone through file by file"""
    good = os.path.join(out, ".triforce_romfs")
    checked = os.path.join(out, ".triforce_romfs_checked")
    if not os.path.isfile(good) or not os.path.isdir(romfs):
        return
    check_cache_paths(out, (good, checked, romfs))
    stamp = read_stamp(good)
    # ((Triforce, 11-24, after Source A's) marked checked only once every damaged file has its stand-in: earlier checks marked
    # a dump with files that have none as checked too, and every later build went on without them)
    checked_stamp = "resolved-v2\n" + stamp   # (v2: also files still in the .nup's zstd frame, nup.still_in_nup_frame)
    if os.path.isfile(checked):
        if read_stamp(checked) == checked_stamp:
            return
    import nup
    if seen is not None:
        print("your game files were checked for damaged textures as they were unpacked: %s .zs files, %d damaged"
              % (format(seen["files"], ","), len(seen["damaged"])), flush=True)
        done = nup.stand_in_damaged(romfs, known=seen["damaged"])
    else:
        print("checking your game files for damaged textures (once after an unpack): every .zs file is opened, which can take "
              "minutes", flush=True)
        done = nup.stand_in_damaged(romfs, file_progress("checked"))
    if done:
        too_many = len(done) > nup.MOST_STAND_INS   # ((Triforce, 11-24) none was looked for: nup.stand_in_damaged)
        print("Your game dump is incomplete: %d game file%s in it %s damaged (a complete dump is about 23.8 GB, an incomplete "
              "one 23.3 GB). %s Dump the game again for the original files:"
              % (len(done), "" if len(done) == 1 else "s", "is" if len(done) == 1 else "are",
                 "That is too many to replace with similar files (an incomplete dump has a few)." if too_many else
                 "Similar files are used where there are some, with different textures in those places."), flush=True)
        if len(done) > 50:   # ((Triforce) the first 50 named: 1,896 filled the launcher's log)
            print("  (the first 50 of them:)", flush=True)
        for path, other in done[:50]:
            print("  %s: %s" % (os.path.relpath(path, romfs),
                                "in its place " + os.path.basename(other) if other else "no replacement found: the build cannot go on"),
                  flush=True)
        # ((Triforce, 11-24, after Source A's) a damaged file with no stand-in stops the build: left as it was, the game leaves
        # out the walls and floors that use it, and the build said only "left as it is" in output that scrolls away)
        unresolved = sum(other is None for _, other in done)
        if unresolved:
            fail("The game dump still has %d damaged file%s with no replacement. The build stopped before compiling. Dump the game "
                 "again and choose the complete dump. The affected files are listed above." % (unresolved, "" if unresolved == 1 else "s"))
    write_stamp(checked, checked_stamp)


def check_cache_paths(out, paths):
    """Resolve generated paths and reject symbolic links/reparse points before replacement."""
    root = os.path.realpath(out)
    for path in paths:
        try:
            inside = os.path.commonpath((root, os.path.realpath(path))) == root
        except ValueError:
            inside = False
        attrs = os.lstat(path) if os.path.lexists(path) else None
        linked = os.path.islink(path) or bool(
            getattr(attrs, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if not inside or linked:
            fail("The generated cache path %s is not a normal path inside the build folder (symbolic links and reparse points are not supported). "
                 "Choose a different output folder." % path)


def check_cpu():
    """(linux) The AppImage's Vulkan back end (HOOKSHOT_VK_PREBUILT) is built for x86-64-v3 elsewhere
    (scripts/linux/appimage.sh), while the game follows this PC (nx2/host_cpu.py): on a CPU without AVX2 it would stop at
    its start. Said now, before the game is read, not 40 minutes in (issue 363)"""
    if not os.environ.get("HOOKSHOT_VK_PREBUILT") or os.environ.get("RX_MARCH"):
        return
    sys.path.insert(0, HERE)
    from host_cpu import host_march
    m = host_march()
    if m != "x86-64-v3":
        fail("Your processor has no AVX2 (it runs %s), and the AppImage's renderer needs it. Build Hookshot from source "
             "instead (see the readme): a source build follows your processor." % m)


def check(a, work):
    check_windows_sdk(work)   # (first: said in plain words when the game is chosen, not after it has been read)
    check_cpu()
    if a.nup:
        probe = os.path.join(work, "probe")
        shutil.rmtree(probe, ignore_errors=True)
        run(PY + ["nx2/nup.py", a.nup, "--extract", probe, "--only", "exefs"])
        check_modules(os.path.join(probe, "exefs"))
        bid = build_id(os.path.join(probe, "exefs", "main"))
        shutil.rmtree(probe, ignore_errors=True)
    else:
        refuse_packed_romfs(a.romfs)   # (Setup passes the romfs folder too since 11-18)
        bid = build_id(os.path.join(a.exefs, "main"))
    if bid.startswith(BUILD_ID):
        say("check", "ok", "This is the version Triforce supports (build %s)." % bid[:8])
    else:
        say("check", "bad", "This is build %s. Triforce supports build %s." % (bid[:8], BUILD_ID))


def compiler_failure(r):
    """((Triforce, 11-24, after Source A's) What a compiler run that failed said, for one line of a message: its first error, else
    its last line (a clang that could not start said only "<clang.exe>: permission denied", and the message had "no message"),
    with the exit code when it names no error. A Windows code is an NTSTATUS in hex (0xC0000135: a DLL not found; 0xC0000022:
    access denied)"""
    lines = [l.strip() for l in ((r.stderr or "") + "\n" + (r.stdout or "")).splitlines() if l.strip()]
    errors = [l for l in lines if "error" in l]
    if errors:
        return errors[0].split("error:", 1)[-1].strip() or errors[0]
    code = "exit code 0x%08X" % (r.returncode & 0xFFFFFFFF) if os.name == "nt" else "exit code %d" % r.returncode
    return "%s, %s" % (lines[-1], code) if lines else "no output, %s" % code


def visual_studio_environment():
    """What Visual Studio's own vcvars64.bat sets, for a compiler that does not find it by itself; None without one"""
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.exists(vswhere):
        return None
    r = subprocess.run([vswhere, "-latest", "-prerelease", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                        "-property", "installationPath"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = r.stdout.strip().splitlines()
    if not lines:
        return None
    bat = os.path.join(lines[-1], "VC", "Auxiliary", "Build", "vcvars64.bat")
    if not os.path.exists(bat):
        return None
    r = subprocess.run('"%s" >nul && set' % bat, shell=True, capture_output=True, text=True, encoding="mbcs", errors="replace")
    keep = ("INCLUDE", "LIB", "LIBPATH", "PATH", "VCINSTALLDIR", "VCTOOLSINSTALLDIR", "VCTOOLSVERSION", "WINDOWSSDKDIR", "WINDOWSSDKVERSION",
            "UCRTVERSION", "UNIVERSALCRTSDKDIR")
    found = {}
    for line in r.stdout.splitlines():
        name, eq, value = line.partition("=")
        if eq and name.upper() in keep:
            found[name] = value
    return found if any(k.upper() == "INCLUDE" for k in found) else None


def windows_kits_environment(base):
    """INCLUDE and LIB with the Windows SDK's C library (ucrt) and headers added from where its installer puts them: Visual Studio's
    vcvars leaves them out when the SDK came apart from it (issue 89: 'stdio.h' file not found with MSVC installed). None without one"""
    kits = os.path.join(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"), "Windows Kits", "10")
    inc = os.path.join(kits, "Include")
    try:
        versions = sorted((v for v in os.listdir(inc) if os.path.exists(os.path.join(inc, v, "ucrt", "stdio.h"))),
                          key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")])
    except OSError:
        return None
    if not versions:
        return None
    v = versions[-1]
    env = dict(base or {})
    get = lambda k: next((env[n] for n in env if n.upper() == k), os.environ.get(k, ""))
    env["INCLUDE"] = ";".join(x for x in [get("INCLUDE")] + [os.path.join(inc, v, d) for d in ("ucrt", "um", "shared", "winrt")] if x)
    env["LIB"] = ";".join(x for x in [get("LIB")] + [os.path.join(kits, "Lib", v, d, "x64") for d in ("ucrt", "um")] if x)
    print("the Windows SDK %s from %s" % (v, kits), flush=True)
    return env


def compile_test(toolchain):
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            # (_UCRT: the C library of Visual Studio 2015 and later. An older one's stdio.h compiled, and the link failed 40 minutes later
            # on __iob_func: issue 80)
            f.write(chr(10).join(("#include <stdio.h>", "#ifndef _UCRT", "#error \"stdio.h is from an old C library (before Visual Studio 2015)\"",
                                  "#endif", "#include <windows.h>", "int main(void) { return 0; }", "")))
        return subprocess.run([toolchain.need(toolchain.find("clang"))] + toolchain.native_target() + ["-c", src, "-o", os.path.join(d, "t.o")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")


def link_test(toolchain):
    """A program links, not only compiles (issue 439: a default library a recent Windows SDK no longer ships stopped the
    build at 99%, after the game had been read and translated)"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write(chr(10).join(("#include <stdio.h>", "int main(void) { return 0; }", "")))
        return subprocess.run([toolchain.need(toolchain.find("clang"))] + toolchain.native_target() + toolchain.native_link() +
                              [src, "-o", os.path.join(d, "t.exe")], capture_output=True, text=True, encoding="utf-8", errors="replace")


def check_cpp_library(toolchain):
    """Check the renderer's C++20 library features before the long build (issues 39 and 100)."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.cpp")
        with open(src, "w") as f:
            # Projected find: frontend/maxwell/structured_control_flow.cpp; predicate find and
            # comparator sort: ir_opt/texture_pass.cpp (under gpu/vk/eden/shader_recompiler).
            f.write(chr(10).join(("#include <algorithm>", "#include <format>", "#include <string>", "#include <vector>",
                                  "std::string t(int v) { return std::vformat(\"{}\", std::make_format_args(v)); }",
                                  "namespace { struct Entry { int value; }; }",
                                  "bool ranges_test() {",
                                  "    std::vector<Entry> entries{{2}, {1}};",
                                  "    const auto found = std::ranges::find(entries, 1, &Entry::value);",
                                  "    const auto matching = std::ranges::find_if(entries, [](const Entry& e) { return e.value == 2; });",
                                  "    std::ranges::sort(entries, [](const Entry& a, const Entry& b) { return a.value < b.value; });",
                                  "    return found != entries.end() && matching != entries.end();",
                                  "}", "")))
        r = subprocess.run([toolchain.need(toolchain.find("clang++"))] + toolchain.native_target() + ["-std=c++20", "-c", src, "-o", os.path.join(d, "t.o")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stdout + r.stderr, flush=True)
        fail("Your Visual Studio is too old for this game's renderer. Open the Visual Studio Installer, press Update on "
             "Visual Studio 2022 (or install it), then build again.")


def check_linux_compiler():
    """(linux) A C compiler that builds and links a program here (the AppImage's own clang and sysroot, else the system's):
    found now, not 40 minutes in"""
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    cc = toolchain.find("clang")
    if not os.path.isfile(cc):
        fail("No C compiler was found. Install clang (and lld).")
    sysroot = os.environ.get("HOOKSHOT_SYSROOT")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write(chr(10).join(("#include <stdio.h>", "#include <pthread.h>", "int main(void) { return 0; }", "")))
        r = subprocess.run([cc] + (["--sysroot=" + sysroot] if sysroot else []) + ["-fuse-ld=lld", src, "-o", os.path.join(d, "t")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stdout + r.stderr, flush=True)
        errors = [l for l in r.stderr.splitlines() if "error" in l]
        fail("The compiler could not build a test program: %s (install clang, lld and your system's C library headers: "
             "libc6-dev on Debian and Ubuntu, glibc-devel on Fedora)" % (errors[0] if errors else "no message"))


def check_linux_prerequisites(work=None):
    """(linux) What a build here needs, found with the compile's own lookups before the game is read, and every missing one said
    in one message (it was one at a time: a Python module in the read, the compiler after the lift, the renderer's headers and
    FFmpeg in the compile): the Python modules requirements.txt pins (a source build; the AppImage brings its own), the
    renderer's headers (unless the prebuilt one is used), FFmpeg's libraries, clang (and clang++ for a source build or the
    renderer), and a test program built and linked with lld. Nothing is installed"""
    missing = []
    requirements = os.path.join(ROOT, "requirements.txt")
    source_build = os.path.isfile(requirements)
    if source_build:
        with open(requirements, encoding="utf-8") as f:
            for line in f:
                pin = re.match(r"([A-Za-z0-9_]+)==", line)   # (the top-level pins; -r nx2/prompt_requirements.txt stays optional)
                if pin and importlib.util.find_spec(pin[1]) is None:
                    missing.append("Python module %s (not on %s's isolated import path: install requirements.txt with that Python)"
                                   % (pin[1], sys.executable))
    try:
        import build
    except ImportError as e:   # (a module the compile itself needs: said with the rest)
        fail("Missing Linux build prerequisites: " + "; ".join(missing + ["Python: %s" % e]))
    prebuilt = build.prebuilt_renderer()
    if prebuilt:
        if not os.path.isfile(prebuilt):
            missing.append("Vulkan renderer %s (HOOKSHOT_VK_PREBUILT)" % prebuilt)
    else:
        for (name, package, probe, env), found in zip(build.VK_HEADERS, build.vulkan_headers(work)):
            if not found:
                missing.append("%s header %s (CPM package %s: RX_CPM, the checkout's cpm, work/eg/.cache/cpm, then the "
                               "mkw-recomp and Eglantine caches beside it; then %s, a package root or its include/; then /usr/local, "
                               "/usr)" % (name, probe, package, env))
    build.ffmpeg_linux(missing)
    cc = build.toolchain.find("clang")
    tools = [("clang", cc)]
    if source_build or not prebuilt:   # (a source checkout builds its native tools with clang++ too, prebuilt renderer or not)
        tools.append(("clang++", build.toolchain.find("clang++")))
    for name, path in tools:
        if not os.path.isfile(path):
            missing.append("%s compiler %s (install clang and lld, or use the AppImage)" % (name, path))
    if os.path.isfile(cc):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "t.c")
            with open(src, "w") as f:
                f.write(chr(10).join(("#include <stdio.h>", "#include <pthread.h>", "int main(void) { return 0; }", "")))
            try:
                r = subprocess.run([cc] + build.target() + ["-fuse-ld=lld", src, "-o", os.path.join(d, "t")],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                if r.returncode:
                    print(r.stdout + r.stderr, flush=True)   # (all of it, for Show details)
                    errors = [l.strip() for l in r.stderr.splitlines() if "error" in l]
                    last = (r.stdout + r.stderr).strip().splitlines()
                    missing.append("a test program built with clang and lld (HOOKSHOT_SYSROOT when set; install clang, lld and "
                                   "your system's C library headers: libc6-dev on Debian and Ubuntu, glibc-devel on Fedora): " +
                                   (errors[0] if errors else "%s (exit status %d)" % (last[-1] if last else "no output",
                                                                                      r.returncode)))
            except OSError as e:
                missing.append("a test program built with %s: %s" % (cc, e))
    if missing:
        fail("Missing Linux build prerequisites: " + "; ".join(" ".join(m.splitlines()) for m in missing))   # (one line: the
        # builder shows the whole set)
    print("Linux build prerequisites: OK", flush=True)


def requested_jobs(value):
    """The builder's explicit worker override, or None to keep its automatic selection."""
    if value is None or value == "":
        return None
    error = "HOOKSHOT_JOBS must be a whole number: use 1 or more, or 0 for automatic."
    try:
        jobs = int(value)
    except ValueError:
        raise ValueError(error) from None
    if jobs < 0:
        raise ValueError(error)
    return jobs or None


def default_jobs():
    """(issue 418) One compiler per CPU thread: nx2/build.py starts each one only when the memory free holds it (MemoryGate), so the
    count no longer has to fit the biggest files in the memory free at the start. HOOKSHOT_JOBS or --jobs choose"""
    cpus = os.cpu_count() or 2
    print("build: up to %d compilers at once (one per CPU thread), as the memory allows; HOOKSHOT_JOBS=<n> to change" % cpus, flush=True)
    return cpus


def chosen_jobs(given):
    """--jobs when it is given (1 or more), else HOOKSHOT_JOBS, else what default_jobs chooses: worked out only when it is
    needed, so the "compilers at once" line is the number the build uses"""
    if given:
        return given
    try:
        return requested_jobs(os.environ.get("HOOKSHOT_JOBS")) or default_jobs()
    except ValueError as e:
        fail(str(e))


def bundled_mingw():
    """(as TotK Recomp's installer) llvm-mingw in the tools folder: its clang, headers and libraries build the game, and nothing of
    Visual Studio or the Windows SDK is needed. HOOKSHOT_MINGW set already wins; HOOKSHOT_MSVC=1: the Visual Studio route"""
    if LINUX or os.environ.get("HOOKSHOT_MSVC") == "1":
        return os.environ.get("HOOKSHOT_MINGW", "")
    if not os.environ.get("HOOKSHOT_MINGW"):
        here = os.path.join(ROOT, "llvm-mingw")
        if os.path.isfile(os.path.join(here, "bin", "clang" + (".exe" if os.name == "nt" else ""))):
            os.environ["HOOKSHOT_MINGW"] = here
        elif os.path.isdir(here):
            # (the folder is there and its compiler is not: an antivirus took it (false positives on unsigned tools), or the
            # zip was not unpacked whole. It went on to the Visual Studio route and said "The Windows SDK was not found")
            missing = [n for n in ("clang.exe", "clang++.exe", "ld.lld.exe")
                       if not os.path.isfile(os.path.join(here, "bin", n))]
            fail("Files of the builder's own compiler are missing (%s in %s). Your antivirus most likely removed them "
                 "(a false alarm on unsigned programs): restore them from its quarantine or allow the Hookshot Builder folder, "
                 "then unzip HookshotBuilder.zip again and build. Visual Studio is not needed."
                 % (", ".join(missing) or "bin", os.path.join(here, "bin")))
    return os.environ.get("HOOKSHOT_MINGW", "")


def check_mingw():
    """The bundled compiler builds and links a Windows program: found now, not 40 minutes in"""
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    cc = toolchain.find("clang")   # (HOOKSHOT_MINGW's, else the one toolchain.py finds: the same as the build uses)
    if not os.path.isfile(cc):   # (HOOKSHOT_MINGW set to a folder without the compiler: said here, not as a silent SystemExit)
        fail("The builder's own compiler was not found at %s. Set HOOKSHOT_MINGW to an llvm-mingw folder, or unpack the "
             "Hookshot Builder zip again into a folder your antivirus allows." % cc)
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write(chr(10).join(("#include <stdio.h>", "#include <windows.h>", "int main(void) { return 0; }", "")))
        r = subprocess.run([cc] + toolchain.native_target() + toolchain.native_link() +
                           [src, "-o", os.path.join(d, "t.exe")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stdout + r.stderr, flush=True)
        errors = [l for l in r.stderr.splitlines() if "error" in l]
        fail("The builder's own compiler (tools/llvm-mingw) could not build a test program: %s. Unpack the zip again into a folder "
             "your antivirus allows." % (errors[0] if errors else "no message"))
    print("the compiler: %s (no Visual Studio needed)" % os.environ["HOOKSHOT_MINGW"], flush=True)


def check_windows_sdk(work=None):
    """The compiler is bundled; Microsoft's C library and Windows SDK may not be, by their licences. Found now, not 40 minutes in."""
    if LINUX:
        return check_linux_prerequisites(work)   # ((Triforce) all of what a build here needs, before the game is read)
    if bundled_mingw():
        return check_mingw()
    if CROSS:
        fail("Building for Windows on Linux needs llvm-mingw: unpack its Linux release (github.com/mstorsjo/llvm-mingw) and set "
             "HOOKSHOT_MINGW to its folder.")
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    cc = toolchain.find("clang")
    if not os.path.isfile(cc):   # (toolchain.need() would raise SystemExit, which the builder cannot show: said in its protocol)
        fail("No C compiler was found. Install clang (and lld) and put it on PATH, set EMSDK to an emsdk checkout, or set "
             "HOOKSHOT_MINGW to an llvm-mingw folder. (%s)" % cc)
    # (an INCLUDE set for the whole machine, by an old Visual Studio or another tool, is all clang reads: without the Windows SDK's C
    # library in it, it is dropped and the compiler looks for Visual Studio itself. Issues 80 and 89)
    for k in [n for n in os.environ if n.upper() == "INCLUDE"]:
        if "ucrt" not in os.environ[k].lower():
            print("INCLUDE is set on this PC without the Windows SDK's C library: not used (%s)" % os.environ[k][:200], flush=True)
            for n in [n for n in os.environ if n.upper() in ("INCLUDE", "LIB", "LIBPATH")]:
                del os.environ[n]
            break
    r = compile_test(toolchain)
    found = None
    if r.returncode:   # (clang looks for Visual Studio its own way, and does not always find it: then ask Visual Studio)
        found = visual_studio_environment()
        if found:
            print("the compiler did not find Visual Studio by itself: using vcvars64", flush=True)
            os.environ.update(found)
            r = compile_test(toolchain)
    if r.returncode and found and ("stdio.h" in r.stderr or "windows.h" in r.stderr.lower()):
        # (only on top of vcvars' INCLUDE: clang takes INCLUDE as all of its system headers once it is set)
        kits = windows_kits_environment(found)
        if kits:
            for k in [n for n in os.environ if n.upper() in ("INCLUDE", "LIB")]:
                del os.environ[k]
            os.environ.update(kits)
            r = compile_test(toolchain)
    if not r.returncode:
        check_cpp_library(toolchain)
        link = link_test(toolchain)
        if not link.returncode:
            return
        print(link.stdout + link.stderr, flush=True)
        why = compiler_failure(link)
        fail("The compiler could not link a test program: %s. In the Visual Studio Installer choose Modify on Visual Studio 2022, "
             "tick \"Desktop development with C++\" with a Windows 11 SDK, then build again." % why)
    print(r.stdout + r.stderr, flush=True)   # (all of it, for Show details)
    why = compiler_failure(r)
    if "old c library" in why.lower():
        fail("The compiler found an old Visual Studio's C library (from before 2015) instead of the Windows SDK's. In the Visual Studio "
             "Installer choose Modify on Visual Studio 2022, tick \"Desktop development with C++\" with a Windows 11 SDK, then build again. (%s)" % why)
    if "windows.h" in why.lower() or "stdio.h" in why.lower():
        fail("The Windows SDK was not found. In the Visual Studio Installer choose Modify, and under \"Desktop development with C++\" tick a "
             "Windows 11 SDK, then build again. (%s)" % why)
    if "file not found" in why:
        fail("Visual Studio's C++ tools were not found. In the Visual Studio Installer choose Modify, tick \"Desktop development with C++\" "
             "and its MSVC x64/x86 build tools, then build again. (%s)" % why)
    fail("The compiler could not run a test build: %s" % why)


OLD_NAMES = [(".hookshot_exefs", ".triforce_exefs"), (".hookshot_romfs", ".triforce_romfs"), ("hookshot_version.txt", "triforce_version.txt"),
             ("hookshot_env.txt", "triforce_env.txt"), ("hookshot_options.ini", "triforce_options.ini"),
             ("hookshot_shaders.bin", "triforce_shaders.bin"), ("hookshot_pipelines.bin", "triforce_pipelines.bin"),
             ("hookshot_programs.bin", "triforce_programs.bin"), ("hookshot_prepared.bin", "triforce_prepared.bin"),
             ("hookshot_prepare_skipped", "triforce_prepare_skipped"),
             (os.path.join("user", "hookshot_update_skip.txt"), os.path.join("user", "triforce_update_skip.txt"))]
OLD_PROGRAM = ["hookshot", "hookshot_vk.so"] if LINUX else ["hookshot.exe", "hookshot_vk.dll", "hookshot_log.txt"]


def migrate_names(out):
    """(Triforce) A game folder built when the files were named hookshot_*: its files under their new names, so an update finds its game
    files (.triforce_exefs) and the shader caches stay (no first-start compile again). A name already taken is left as it is"""
    for old, new in OLD_NAMES:
        a, b = os.path.join(out, old), os.path.join(out, new)
        if os.path.exists(a) and not os.path.exists(b):
            try:
                os.replace(a, b)
                print("renamed %s -> %s" % (old, new), flush=True)
            except OSError as e:
                print("could not rename %s: %s" % (old, e), flush=True)


def drop_old_program(out):
    """(Triforce) the old hookshot executable and renderer, once Triforce's are in the folder"""
    if not os.path.exists(os.path.join(out, BESIDE[0])):
        return
    for name in OLD_PROGRAM:
        p = os.path.join(out, name)
        if os.path.exists(p):
            try:
                os.remove(p)
                print("removed the old %s" % name, flush=True)
            except OSError as e:
                print("could not remove the old %s: %s" % (name, e), flush=True)


def _cleanup_argv(command):
    """((Triforce, 11-24, after Source A's) A Windows command line as its arguments, quoted as Windows quotes them (backslashes
    escape quotes, not ordinary path characters). An unmatched quote gives nothing: an ambiguous command proves no ownership"""
    args, word, quoted, started = [], [], False, False
    i = 0
    while i < len(command):
        char = command[i]
        if char in " \t" and not quoted:
            if started:
                args.append("".join(word))
                word, started = [], False
            i += 1
            continue
        started = True
        if char == "\\":
            j = i
            while j < len(command) and command[j] == "\\":
                j += 1
            count = j - i
            if j < len(command) and command[j] == '"':
                word.extend("\\" * (count // 2))
                if count % 2:
                    word.append('"')
                    i = j + 1
                    continue
            else:
                word.extend("\\" * count)
                i = j
                continue
            i = j
            char = command[i]
        if char == '"':
            if quoted and i + 1 < len(command) and command[i + 1] == '"':
                word.append('"')
                i += 2
                continue
            quoted = not quoted
        else:
            word.append(char)
        i += 1
    if quoted:
        return []
    if started:
        args.append("".join(word))
    return args


def _cleanup_path(path):
    """A whole Windows path, normalised; None for a relative or drive-relative one (the process list has no working folder:
    those prove nothing)"""
    drive, tail = ntpath.splitdrive(path)
    if not drive or not tail.startswith(("\\", "/")):
        return None
    return ntpath.normcase(ntpath.normpath(path))


def _cleanup_python(argv):
    """A Python command's script and its arguments, or None (-c, -m and other forms are no script)"""
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] in ("-I", "-u", "-B", "-E", "-s", "-S", "-O", "-OO"):
            i += 1
        elif argv[i] in ("-X", "-W") and i + 1 < len(argv):
            i += 2
        else:
            return None
    return (argv[i], argv[i + 1:]) if i < len(argv) else None


def _cleanup_owns(q, work, default_work):
    """Whether process q (the process list's entry) is proven to be a build on this work folder: a make_game.py or lift.py
    whose --work is it (a make_game.py without --work when it is the default one), or a compiler or linker whose every output
    is inside it. Inputs, includes and response files say nothing of where a compiler writes"""
    argv = _cleanup_argv(q.get("CommandLine") or "")
    name = (q.get("Name") or "").lower()
    if not argv or not work:
        return False
    if name in ("python.exe", "pythonw.exe", "python3.exe"):
        invocation = _cleanup_python(argv)
        if not invocation:
            return False
        script, options = invocation
        entry = ntpath.basename(script).lower()
        if entry not in ("make_game.py", "lift.py", "build.py"):
            return False
        works = []
        for j, option in enumerate(options):
            if option == "--work":
                if j + 1 == len(options):
                    return False
                works.append(_cleanup_path(options[j + 1]))
            elif option.startswith("--work="):
                works.append(_cleanup_path(option[7:]))
        if works:
            # (build.py is given OOT_WORK in its environment: it has no --work)
            return entry != "build.py" and all(w == work for w in works)
        return entry == "make_game.py" and work == _cleanup_path(default_work)
    if name not in ("clang.exe", "clang++.exe", "clang-cl.exe", "ld.lld.exe", "lld-link.exe"):
        return False
    outputs = []
    for i, arg in enumerate(argv[1:], 1):
        if arg == "-o" and i + 1 < len(argv):
            outputs.append(_cleanup_path(argv[i + 1]))
        elif name == "lld-link.exe" and arg.lower().startswith("/out:"):
            outputs.append(_cleanup_path(arg[5:]))
        elif name == "clang-cl.exe" and arg.startswith("/Fo"):
            outputs.append(_cleanup_path(arg[3:]))
    return bool(outputs) and all(o and o.startswith(work.rstrip("\\") + "\\") for o in outputs)


def _cleanup_build_child(child, parent):
    """A build.py --standalone that a proven make_game.py (parent, alive) started: make_game runs that child with OOT_WORK,
    which the process list does not show. An orphan has no such proof"""
    python_names = ("python.exe", "pythonw.exe", "python3.exe")
    if child.get("Name", "").lower() not in python_names or parent.get("Name", "").lower() not in python_names:
        return False
    c = _cleanup_python(_cleanup_argv(child.get("CommandLine") or ""))
    p = _cleanup_python(_cleanup_argv(parent.get("CommandLine") or ""))
    if not c or not p or not _cleanup_path(p[0]) or ntpath.basename(p[0]).lower() != "make_game.py":
        return False
    expected = ntpath.join(ntpath.dirname(p[0]), "build.py")
    script, options = c
    return ("--standalone" in options and
            (_cleanup_path(script) == _cleanup_path(expected) or ntpath.normcase(script) == "nx2\\build.py"))


def stop_stray_compilers(work, default_work):
    """(issues 501, 530) A build left running by an earlier one on this work folder (the builder closed, crashed, or replaced by an
    update mid-build) keeps its files open: the next build stopped at once with 'OSError: [Errno 22]' writing sa/gen/a64_fpx.h, or
    WinError 1224 on the play profile. Only that build goes. Never this build or what started it.
    ((Triforce, 11-24, after Source A's) Only what is proven to be a build on this work folder (_cleanup_owns: the parsed command
    line, whole paths, at a folder's boundary), and a build.py started by such a make_game. A build.py or lift.py whose make_game
    was gone used to go whatever folder it worked on (another work folder's build, mid-lift), and a work folder whose path began
    another's ("D:\\work" in "D:\\work2") counted that one's compilers as its own. Each is stopped alone, not with its
    children (/T), whose folder was never looked at)"""
    if LINUX:
        return
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'clang*' -or $_.Name -like 'ld.lld*' -or $_.Name -like 'lld-link*' "
          "-or $_.Name -like 'python*' } | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress")
    try:
        import json
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, timeout=90)
        if r.returncode:
            print("could not look for an earlier build's processes: the process query ended with %d" % r.returncode, flush=True)
            return 0
        procs = json.loads(r.stdout or "[]")
        if isinstance(procs, dict):
            procs = [procs]
        alive = {q["ProcessId"]: q for q in procs}
        mine, pid = set(), os.getpid()        # (this process and the chain that started it)
        while pid in alive and pid not in mine:
            mine.add(pid)
            pid = alive[pid]["ParentProcessId"]
        mine.add(pid)
        w = _cleanup_path(os.path.abspath(work))
        doomed = {q["ProcessId"]: q["Name"].lower() for q in procs
                  if q["ProcessId"] not in mine and _cleanup_owns(q, w, os.path.abspath(default_work))}
        owned = set(doomed)
        for q in procs:
            parent = alive.get(q["ParentProcessId"])
            if q["ProcessId"] not in mine and q["ParentProcessId"] in owned and parent and _cleanup_build_child(q, parent):
                doomed[q["ProcessId"]] = q["Name"].lower()
        stopped = []
        for k, name in doomed.items():
            result = subprocess.run(["taskkill", "/F", "/PID", str(k)], capture_output=True, timeout=60)
            if result.returncode == 0:
                stopped.append(name)
        if stopped:
            print("stopped %d process(es) an earlier build left running on this work folder: %s"
                  % (len(stopped), " ".join(sorted(set(stopped)))), flush=True)
            time.sleep(2)
        return len(stopped)   # (lock_work waits for a stopped build's lock: Windows frees it late)
    except Exception as e:   # (not finding them is no reason to stop)
        print("could not look for an earlier build's processes: %s" % e, flush=True)


# (Triforce, 11-22, the performance audit's IO-47, after Source A's) One build at a time per work folder: make_game.py
# holds an OS lock on <work>/make_game.lock for as long as it runs. A second build on the folder stopped nothing on Linux
# (two builders, a builder beside the launcher, AppRun --cli): both compiled the same objects and raced on the staged
# game folder. On Windows stop_stray_compilers still stops an earlier build first, and the lock is what is left when it
# finds none. The lock is the operating system's and ends with its process, so a build that crashed never blocks the
# next one. The first byte is the locked one; the holder's process id is written after it, for the refusal to name.
# HOOKSHOT_WORK_LOCK=0: no lock, as before.
WORK_LOCK = "make_game.lock"
WORK_LOCK_HELD = (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES, getattr(errno, "EDEADLOCK", errno.EDEADLK))
_work_lock = None   # ((the open file, its work folder) while this process holds one)


def _lock_first_byte(f):
    """The OS lock itself, without waiting: an OSError of WORK_LOCK_HELD when another process holds it"""
    if os.name == "nt":
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def work_lock_holder(path):
    """The process id the holder of a work folder's lock wrote after the locked byte, or None"""
    try:
        with open(path, "rb") as f:
            f.seek(1)
            return int(f.read(32).split()[0])
    except (OSError, ValueError, IndexError):
        return None


def lock_work(work, wait=0.0):
    """Takes the work folder's lock for this process, or stops the build (fail) when another build holds it. wait: the
    seconds to keep trying first, for after stop_stray_compilers stopped a build (Windows frees a killed process's lock
    a little late). Asked again for the same folder it does nothing; for another folder the old lock is let go first.
    Only "held by another" refuses: any other error is said and the build goes on without the lock, as before"""
    global _work_lock
    if os.environ.get("HOOKSHOT_WORK_LOCK") == "0":
        return False
    work = os.path.abspath(work)
    if _work_lock:
        if os.path.normcase(_work_lock[1]) == os.path.normcase(work):
            return True
        release_work()
    path = os.path.join(work, WORK_LOCK)
    try:   # (made when it is not there, never emptied: the holder's process id stays readable)
        f = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666), "r+b")
    except OSError as e:
        print("could not open %s (%s): this build runs without the work folder's lock" % (path, e), flush=True)
        return False
    until = time.monotonic() + wait
    while True:
        try:
            _lock_first_byte(f)
            break
        except OSError as e:
            if e.errno not in WORK_LOCK_HELD:
                f.close()
                print("could not lock %s (%s): this build runs without the work folder's lock" % (path, e), flush=True)
                return False
            if time.monotonic() >= until:
                f.close()
                pid = work_lock_holder(path)
                fail("Another build is already working in %s%s. Wait for it to finish, or stop it, then build again."
                     % (work, " (process %d)" % pid if pid else ""))
            time.sleep(0.2)
    try:   # (after the locked byte, where another process may read on Windows)
        f.seek(1)
        f.truncate()
        f.write(b"%d\n" % os.getpid())
        f.flush()
    except OSError:
        pass
    _work_lock = (f, work)
    return True


def release_work():
    """Lets this process's work folder lock go (the file stays): for a lock on another folder, and for the tests that run
    main() in temporary folders. A build never calls it: its lock ends with the process"""
    global _work_lock
    if _work_lock:
        f, _work_lock = _work_lock[0], None
        with contextlib.suppress(OSError, ValueError):
            f.close()   # (closing the file frees its lock, on Windows and with flock alike)


def makefile_words(text):
    """Decode clang -M words, preserving ordinary Windows backslashes."""
    text = re.sub(r"\\\r?\n", " ", text)
    words = re.findall(r"(?:\\[ \t]|\S)+", text)
    # clang doubles backslashes before an escaped space, but adds only one before #.
    def unescape(m):
        slashes, char = m.groups()
        return "\\" * ((len(slashes) - 1) // 2 if char != "#" else len(slashes) - 1) + char
    return [re.sub(r"(\\+)([ \t#])", unescape, word).replace("$$", "$") for word in words]


def _drop_stale_linux(work):
    """The AppImage's sysroot is a new /tmp/.mount_... path every start. The stamp is the compiler's version and stdio.h's
    bytes, not that path, so an update reuses the compiled game when the headers did not change (the Windows stamp leaves
    the builder's install folder out for the same reason, issue 565)."""
    import hashlib
    sysroot = os.environ.get("HOOKSHOT_SYSROOT", "")
    stdio = os.path.join(sysroot, "usr", "include", "stdio.h") if sysroot else "/usr/include/stdio.h"
    try:
        body = open(stdio, "rb").read()
    except OSError:
        return
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    try:
        cc = toolchain.need(toolchain.find("clang"))
        ver = subprocess.run([cc, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:
        return
    first = ver.stdout.splitlines()[:1]
    if ver.returncode or not first:
        return
    stamp = hashlib.sha1(body + first[0].encode(), usedforsecurity=False).hexdigest()
    note = os.path.join(work, "system_headers.txt")
    try:
        with open(note) as f:
            if f.read().strip() == stamp:
                return
    except OSError:
        pass
    for sub in (os.path.join(work, "objcache"), os.path.join(work, "sa", "build", "obj")):
        if os.path.isdir(sub):
            print("the system headers changed since the last build: its compiled objects are not reused (%s)" % sub, flush=True)
            shutil.rmtree(sub, ignore_errors=True)
    with open(note, "w") as f:
        f.write(stamp + chr(10))


def object_stamps(obj_dir):
    """The object keys the objects in obj_dir are stamped with (<obj>.sha1, nx2/build.py compile_one)"""
    keys = []
    with contextlib.suppress(OSError):
        for f in os.listdir(obj_dir):
            if f.endswith(".sha1"):
                with contextlib.suppress(OSError), open(os.path.join(obj_dir, f)) as h:
                    keys.append(h.read().strip())
    return keys


def prune_object_cache(work):
    """(issue 1287) The object cache down to the objects this build used: each object in sa/build/obj names its key in <obj>.sha1
    (nx2/build.py compile_one); cached objects no stamp names (earlier releases', other settings') go. Returns the bytes kept.
    Nothing is pruned when no stamp is found (a build that did not reach the compile keeps the cache as it was)"""
    cache, obj_dir = os.path.join(work, "objcache"), os.path.join(work, "sa", "build", "obj")
    used = set()
    if os.path.isdir(obj_dir):
        for f in os.listdir(obj_dir):
            if f.endswith(".sha1"):
                try:
                    with open(os.path.join(obj_dir, f)) as h:
                        used.add(h.read().strip())
                except OSError:
                    pass
    kept = 0
    if not os.path.isdir(cache):
        return kept
    for f in os.listdir(cache):
        p = os.path.join(cache, f)
        if used and f.endswith(".o") and f[:-2] not in used:
            try:
                os.remove(p)
            except OSError:
                pass
            continue
        try:
            kept += os.path.getsize(p)
        except OSError:
            pass
    return kept


def clear_folder(path):
    """(issue 1354) A folder this build makes again from nothing (the game's code, exefs): gone before it is made. rmtree with
    ignore_errors left it behind whenever a file in it was held (an antivirus scan, an explorer window, a game still closing), and the
    copy into it stopped with FileExistsError at every update. Tried a few times, then moved aside (deleted at the next build), and
    only then a clear stop"""
    for attempt in range(5):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(1)
    parent, name = os.path.split(path.rstrip("\\/"))
    for stale in os.listdir(parent or "."):   # (what an earlier build moved aside: gone now, if it can be)
        if stale.startswith(name + ".old-"):
            shutil.rmtree(os.path.join(parent, stale), ignore_errors=True)
    aside = "%s.old-%d" % (path.rstrip("\\/"), os.getpid())
    try:
        os.rename(path, aside)
        print("could not delete %s (a file in it is in use): moved aside to %s" % (path, aside), flush=True)
        return
    except OSError as e:
        fail("Could not clear %s (%s). A file in it is in use: close any window showing that folder, wait for your antivirus "
             "to finish, then try again." % (path, e))


def drop_stale_objects(work):
    """(issue 231) Objects compiled against other system headers are not reused. A first build that compiled with an old Visual Studio's
    stdio.h (before 2015) left its objects in the cache; once the PC was fixed every later build reused them and the link failed on
    __iob_func. The headers the compiler finds are noted, and when they change the compiled objects go"""
    if LINUX:
        _drop_stale_linux(work)
        return
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import hashlib
    import toolchain
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write(chr(10).join(("#include <stdio.h>", "#include <stdlib.h>", "#include <windows.h>", "")))
        r = subprocess.run([toolchain.need(toolchain.find("clang"))] + toolchain.native_target() + ["-M", src], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if r.returncode:
        return
    found = sorted({h.lower() for h in makefile_words(r.stdout) if h.endswith(".h")})

    # (issue 565) The paths are taken relative to the builder's own folder, with the compiler's version: under
    # versions\<tag>\ every release looked like new headers, and an update compiled everything again (2+ hours). clang
    # writes them with / where the folder has \: compared with / on both sides, each path's own spelling kept for the old stamp
    mine = os.path.normcase(os.path.abspath(ROOT)).lower().replace(os.sep, "/")
    ours = lambda h: h.replace(os.sep, "/").startswith(mine + "/")

    def stamp_for(root):   # (the old stamp: the headers' full paths, with the builder's own folder as it was in that version)
        root = root.replace(os.sep, "/")
        moved = [((root if "/" in h[:len(mine)] else root.replace("/", os.sep)) + h[len(mine):]) if ours(h) else h for h in found]
        return hashlib.sha1(chr(10).join(sorted(moved)).encode(), usedforsecurity=False).hexdigest()

    rel = sorted(("<tools>" + h[len(mine):].replace(os.sep, "/")) if ours(h) else h for h in found)
    ver = subprocess.run([toolchain.need(toolchain.find("clang")), "--version"], capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout.splitlines()[:1]
    stamp = hashlib.sha1(chr(10).join(ver + rel).encode(), usedforsecurity=False).hexdigest()
    note = os.path.join(work, "system_headers.txt")
    try:
        with open(note) as f:
            had = f.read().strip()
    except OSError:
        had = ""
    if had == stamp:
        return
    # (a stamp an installed version of the builder wrote the old way: the same headers, in its own folder; kept, and written anew)
    versions = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(ROOT))))
    olds = {stamp_for(mine)}
    if os.path.basename(versions).lower() == "versions" and os.path.isdir(versions):
        for v in os.listdir(versions):
            olds.add(stamp_for(os.path.normcase(os.path.join(versions, v, "HookshotBuilder", "tools")).lower()))
    if had and had in olds:
        print("the system headers are the same as the last build's (an earlier version of the builder): its objects are reused", flush=True)
        with open(note, "w") as f:
            f.write(stamp + chr(10))
        return
    for sub in (os.path.join(work, "objcache"), os.path.join(work, "sa", "build", "obj")):
        if os.path.isdir(sub):
            print("the system headers changed since the last build: its compiled objects are not reused (%s)" % sub, flush=True)
            shutil.rmtree(sub, ignore_errors=True)
    with open(note, "w") as f:
        f.write(stamp + chr(10))


def seed_pipelines(out):
    """The pipelines recorded on the development PC (hookshot_pipelines_seed.bin in the tools: program keys and draw states, no game
    code), as the game folder's list, so its first start builds them before the title, as TotK Recomp's shipped shader list does,
    instead of compiling each when it is first drawn (the stutter of a first visit). Each release ships the list its own build
    made: the file's first 8 bytes are that build's stamp, and a list the folder has from the same build is kept (it grows as
    the player plays)"""
    seed = os.path.join(ROOT, "hookshot_pipelines_seed.bin")
    dst = os.path.join(out, "triforce_pipelines.bin")
    if not os.path.isfile(seed):
        return
    with open(seed, "rb") as f:
        stamp = f.read(8)
    try:
        with open(dst, "rb") as f:
            if f.read(8) == stamp:
                return
    except OSError:
        pass
    shutil.copyfile(seed, dst)
    print("the shipped pipeline list: %d KB, built before the first title" % (os.path.getsize(seed) >> 10), flush=True)


def ship_state_list(out):
    """The pipeline state list made from a play of the game on the development PC (work/pipeline_states.bin: each pipeline's stage
    code keys, vertex and target formats and draw state; hashes and state only, no game code), as the folder's
    triforce_pipeline_states_shipped.bin: the first start's shader preparation builds those pipelines before the title, from the
    player's own shaders (triforce_shaders.bin), instead of compiling each when it is first drawn. Good for any build: optional"""
    src = os.path.join(ROOT, "work", "pipeline_states.bin")
    dst = os.path.join(out, "triforce_pipeline_states_shipped.bin")
    if not os.path.isfile(src):
        return
    if not (os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False)):
        shutil.copyfile(src, dst)
    print("the shipped pipeline state list: %d pipelines" % ((os.path.getsize(src) - 12) // 528), flush=True)


def ship_triforce_assets(out):
    """(Triforce, v0.5.0) Triforce's own files the game reads beside it (assets/triforce_assets: the Mods screen's mask, CC BY 4.0,
    its credits in CREDITS.txt), as <out>/triforce_assets. None is a game file. Without them the game runs as before: the Mask
    Salesman stands without the mask (gpu/vk/vk_salesman.cpp)"""
    src = os.path.join(ROOT, "assets", "triforce_assets")
    if not os.path.isdir(src):
        return
    dst = os.path.join(out, "triforce_assets")
    os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isfile(s) and not (os.path.isfile(d) and filecmp.cmp(s, d, shallow=False)):
            copy_writable(s, d)
    print("Triforce's own files beside the game: %s" % ", ".join(sorted(os.listdir(src))), flush=True)


# (the builders read this line's start: the step was skipped or failed, and the shaders' row says so instead of a check mark)
NOT_PREPARED = "the shaders were not prepared now"
# (a run that prints nothing this long is stopped. Not its whole length: that is 25 minutes on some AMD GPUs, and the driver's own
# step near the end can sit at 99% for minutes)
PREPARE_SILENCE = 15 * 60
# ((Triforce, 11-18) a silent run is asked to stop first (gpu/vk/vk_main.cpp PrepareStopWatch: it ends its driver's part
# cleanly and keeps what it made; killed, a start in that part used one of its three tries and left variants out for good),
# and killed only when it has not ended this long after)
PREPARE_STOP = "triforce_prepare.stop"
PREPARE_STOP_WAIT = 60
GAME_ENV_DROP = ("HOOKSHOT_", "PYTHON", "APPDIR", "APPIMAGE", "ARGV0", "OWD")


def span(seconds):
    return "%d minutes" % (seconds // 60) if seconds >= 120 else "%g seconds" % seconds


def game_env(environ=None):
    """The environment the game runs in when the tools start it: without what the AppImage runtime and the tools put there (their
    libraries first on the search path, Python's settings, the HOOKSHOT_ build switches), so it loads its own SDL and the system's
    Vulkan, as when the player starts it. The Linux builder's Play button uses it too; builder/linux/hookshot-launch drops the same"""
    env = {k: v for k, v in (os.environ if environ is None else environ).items() if not k.startswith(GAME_ENV_DROP)}
    env.pop("LD_LIBRARY_PATH", None)
    return env


def not_prepared(why):
    print("%s (%s): the game prepares them at its first start" % (NOT_PREPARED, why), flush=True)


def prepare_skipped(a, environ=None):
    """Why the build leaves the shaders to the first start, or None: it prepares them"""
    environ = os.environ if environ is None else environ
    if a.no_prepare_shaders:
        return '"Prepare shaders now" is unticked'
    if environ.get("HOOKSHOT_NO_PREPARE", "0") != "0":   # (set and not 0, as the game reads HOOKSHOT_NO_UPDATE_CHECK)
        return "HOOKSHOT_NO_PREPARE is set"
    if CROSS:   # (Triforce.exe can't run here, and under Wine it would prepare for this PC's GPU, not the one that plays it)
        return "a Windows game built on Linux prepares them on the PC it runs on"
    return None


def show_prepared(line):
    """The game's @@stage and @@progress lines go on to the builder; its own @@done and @@error would end or fail the build there,
    so they go on as plain text"""
    return line if line.startswith(("@@stage ", "@@progress ")) or not line.startswith("@@") else line[2:]


def prepare_shaders(cmd, folder=None, silence=PREPARE_SILENCE, stop=None, stop_wait=PREPARE_STOP_WAIT):
    """The shaders prepared now, under the builder's progress bar, not at the game's first start behind a black window (minutes on
    some GPUs, issue 711): hookshot --prepare-shaders (host/hos_main.c, gpu/vk/vk_main.cpp), the same work as that first start, in
    the game's folder and environment, as the builders' Play starts it. A PC whose Vulkan can't (exit 3), a run silent for `silence` seconds (then stopped), or
    any other failure leaves the work to the first start, as before: never a failed build. Returns its exit code (None: stopped).
    stop: the game's stop request, PREPARE_STOP beside it (a stale one is removed first, and the one written here after)"""
    stop = stop or os.path.join(os.path.dirname(os.path.abspath(cmd[0])), PREPARE_STOP)
    with contextlib.suppress(OSError):
        os.remove(stop)
    try:
        # ((Triforce) a count asked for: the game started on that many CPUs; nx2/build_jobs.py)
        with _build_jobs.children_on_cpus(_build_jobs.asked()):
            code = run(cmd, check=False, show=show_prepared, cwd=folder or os.path.dirname(cmd[0]) or None,
                       base=game_env(), silence=silence, stop=stop, stop_wait=stop_wait)
    except OSError as e:
        not_prepared(str(e))
        return 1
    finally:
        with contextlib.suppress(OSError):
            os.remove(stop)
    if code is None:
        not_prepared("the game printed nothing for %s and was stopped" % span(silence))
    elif code == 3:
        not_prepared("no usable Vulkan here")
    elif code:
        not_prepared("the game stopped with exit status %d" % code)
    return code


def folder_language(out):
    """the language a game folder was built in: the code line of its language.txt"""
    try:
        with open(os.path.join(out, "language.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and any(line == code for code, _ in LANGUAGES):
                    return line
    except OSError:
        pass
    return None


def windows_ui_language():
    """Windows' display language ("de-DE"): the first of the user's preferred UI languages, else the user's default UI language;
    "" when neither can be read. Not GetUserDefaultLocaleName: that is the regional format (Settings > Region), often another"""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    count, size = wintypes.ULONG(0), wintypes.ULONG(0)
    if k32.GetUserPreferredUILanguages(0x8, ctypes.byref(count), None, ctypes.byref(size)) and size.value:   # (MUI_LANGUAGE_NAME)
        buf = ctypes.create_unicode_buffer(size.value)
        if k32.GetUserPreferredUILanguages(0x8, ctypes.byref(count), buf, ctypes.byref(size)) and buf.value:
            return buf.value   # (a list ended by an empty name: the first)
    buf = ctypes.create_unicode_buffer(85)
    return buf.value if k32.LCIDToLocaleName(k32.GetUserDefaultUILanguage(), buf, 85, 0) else ""


def system_language(name=None):
    """The game language closest to the system's own, as the Windows builder's window picks its first one: the exact one, then the same
    family; None when the game has none of it. name: the system's, "de-DE" or "pt_BR.UTF-8" (asked for when not given)"""
    if name is None and os.name == "nt":   # (the display language, as .NET's CurrentUICulture, not the regional format)
        name = windows_ui_language()
    elif name is None:   # (as gettext reads them: the first of these that is set, and LANGUAGE's first over it unless that is C)
        name = next((v for v in map(os.environ.get, ("LC_ALL", "LC_MESSAGES", "LANG")) if v), "")
        first = os.environ.get("LANGUAGE", "").split(":")[0]
        if first and name and re.split("[.@]", name)[0] not in ("C", "POSIX"):
            name = first
    name = re.split("[.@]", name)[0].replace("_", "-")
    family = name.split("-")[0].lower()
    for code, _ in LANGUAGES:
        if code.lower() == name.lower():
            return code
    if family == "zh":
        return "zh-Hant" if any(t in name for t in ("TW", "HK", "MO", "Hant")) else "zh-Hans"
    if family == "es" and name.lower() not in ("es", "es-es"):
        return "es-419"
    if family == "pt":
        return "pt-BR"
    return next((code for code, _ in LANGUAGES if code == family), None)


def build_language(a, out):
    """The language a build writes to the folder's language.txt: the one asked for (--language); else the one the folder has,
    from the build before or the player's own change to the file; else, in a launcher's build (--prepare: no window to choose
    one in), the system's own; else English (US). An update keeps the folder's, whatever was asked."""
    kept = folder_language(out)
    if a.update and kept:
        return kept
    return a.language or kept or (system_language() if a.prepare else None) or "en-US"


def profile_readable(prof):
    """(linux) the profile is made by a recent clang (the Windows tools'): an older one, the system's, cannot read it and stops the
    build. Then the game is built without it (a little slower in play), not at all"""
    if not LINUX:
        return True
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write("int f(int x) { return x + 1; }" + chr(10))
        r = subprocess.run([toolchain.find("clang"), "-O2", "-Wno-everything", "-fprofile-instr-use=" + prof, "-c", src, "-o",
                            os.path.join(d, "t.o")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        try:
            ver = subprocess.run([toolchain.find("clang"), "--version"], capture_output=True, text=True, encoding="utf-8",
                                 errors="replace").stdout
        except OSError:
            ver = ""
        print(profile_unread_message(prof, ver, r.stderr, LINUX, build_tools_llvm()), flush=True)
    return r.returncode == 0


def build_tools_llvm(root=ROOT):
    """((Triforce, 11-24, after Source A's) The LLVM of the Linux build tools (the AppImage's: scripts/linux/deps.sh's
    LLVM_VER), or None without it"""
    try:
        with open(os.path.join(root, "scripts", "linux", "deps.sh"), encoding="utf-8") as f:
            m = re.search(r"^LLVM_VER=(\S+)", f.read(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None


def profile_unread_message(prof, version_text, stderr, linux, wanted):
    """((Triforce, 11-24, after Source A's) The line a build prints when this clang cannot read a play profile: which clang,
    which profile, what it costs (nothing stops), and on Linux, with a clang older than the build tools' LLVM (a system
    clang: a distribution's 18 reads no LLVM 23 profile), where the one that reads it is. version_text: clang --version's
    output; stderr: the test compile's"""
    m = re.search(r"clang version (\d+)([\w.]*)", version_text or "")
    who = "clang %s%s" % (m.group(1), m.group(2)) if m else "this compiler"
    why = (stderr or "").strip().splitlines()
    line = "%s cannot read the play profile %s (%s): building without it (a little slower in play)" % (
        who, os.path.basename(prof), why[-1] if why else "?")
    if linux and m and wanted and int(m.group(1)) < int(wanted.split(".")[0]):
        line += ("; the profile is LLVM %s's: the AppImage's own clang reads it (build from the AppImage, or put an LLVM %s "
                 "clang first on PATH)" % (wanted, wanted.split(".")[0]))
    return line


def copy_writable(src, dst):
    """src's bytes at dst, writable whatever src's mode: copy2 took the mode along, and from a read-only install (a Nix
    store, a packaged tools folder) the copies in the work folder were read-only, so lift.py could not write chunks.txt
    again (PermissionError) and every later build failed on the same file"""
    if os.path.exists(dst):
        if os.path.samefile(src, dst):   # ((Triforce) --work is the checkout's own work folder: the file is there already)
            return
        os.chmod(dst, stat.S_IREAD | stat.S_IWRITE)
    shutil.copyfile(src, dst)


# (Triforce, 11-22, the performance audit's IO-45, after Source A's) What the finish put into the game folder, noted in
# the folder: for each file it installed, the SHA-1 of the source it was copied from and the installed file's size,
# modification time, file number and mode right after the swap. The next finish passes over a file whose source hashes
# the same and whose installed copy still has that size, time, number and mode: every build copied and swapped every
# file, image.bin and the prebuilt DLLs included, and the installed file is never read to find out (a cold read of the
# exe is seconds). Anything not noted, not readable or not as noted is copied as before, and so is everything on a file
# system that gives no file number (FAT, exFAT). HOOKSHOT_FINISH_COPY_ALL=1: every file copied and swapped, no note.
INSTALLED_NOTE = ".triforce_installed.json"


def file_sha1(path):
    """The SHA-1 of a file's bytes, as hex; None when it cannot be read"""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for piece in iter(lambda: f.read(1 << 20), b""):
                h.update(piece)
    except OSError:
        return None
    return h.hexdigest()


def installed_stat(path):
    """What tells an installed file is still the one the finish put there, without reading it: [size, modification time
    in ns, file number, mode]. None when it is not there, is no plain file, or the file system gives no file number"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_ino == 0:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ino, st.st_mode]


def read_installed(out):
    """The game folder's note: {a file's path under the folder, with /: {"sha1": its source's, "stat": installed_stat's}}.
    Empty when there is none or it is not what write_installed writes (then everything is copied)"""
    try:
        with open(os.path.join(out, INSTALLED_NOTE), encoding="utf-8") as f:
            note = json.load(f)
        files = note["files"] if note.get("format") == 1 else {}
        if not isinstance(files, dict):
            return {}
        return {k: v for k, v in files.items()
                if isinstance(v, dict) and isinstance(v.get("sha1"), str) and isinstance(v.get("stat"), list)}
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return {}


def installed_name(out, dst):
    """An installed file's name in the note: its path under the game folder, with / between the parts"""
    return os.path.relpath(dst, out).replace(os.sep, "/")


def installed_same(note, out, dst, digest):
    """Whether dst in the game folder is still the copy of a source with this SHA-1 that the note says the finish
    installed: the note's hash is this one and the file's size, time, number and mode are the noted ones"""
    was = note.get(installed_name(out, dst))
    now = installed_stat(dst)
    return bool(digest and was and now and was["sha1"] == digest and was["stat"] == now)


def write_installed(out, files):
    """The note, whole: written beside itself and moved in, so a build stopped here leaves the old note or the new one.
    A note that cannot be written is said and costs the next build its copies, nothing more"""
    path = os.path.join(out, INSTALLED_NOTE)
    try:
        with open(path + ".new", "w", encoding="utf-8", newline="\n") as f:
            json.dump({"format": 1, "files": files}, f, indent=1, sort_keys=True)
        os.replace(path + ".new", path)
    except OSError as e:
        print("could not note what was installed in %s (%s): the next build copies every file again" % (out, e), flush=True)
        with contextlib.suppress(OSError):
            os.remove(path + ".new")


def refuse_dump_links(folder):
    """An extracted dump holds only files and folders: a link in it was followed, and hard-linked or copied the file it
    names (anywhere on this PC) into the game folder. The folder itself may be one. (Walked as a long path: #1468)

    (Triforce, 11-21, the performance audit's IO-41, after Source A's) From the folders' listings: os.scandir gives each
    entry's kind and, on Windows, its attributes with the listing itself (the reparse-point bit is in them), so no file is
    opened or asked about one by one. An os.lstat per entry took 36 to 49 s over the game's 186,583 files where the
    listings take 1.3 to 1.5 s (Source A's, Windows 11, NTFS). And a folder that cannot be listed stops the build: os.walk
    passed over it silently, and what it held was never looked at. HOOKSHOT_DUMP_LINKS_LSTAT=1: an os.lstat each, as before"""
    if os.environ.get("HOOKSHOT_DUMP_LINKS_LSTAT", "") not in ("", "0"):
        return refuse_dump_links_lstat(folder)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    stack = [long_path(folder)]
    while stack:
        d = stack.pop()
        try:
            listing = os.scandir(d)
        except OSError as e:
            fail("Could not read the game files at %s (%s: %s)." % (folder, d, e.strerror or e))
        with listing:
            for entry in listing:
                try:
                    link = entry.is_symlink() or getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & reparse
                    folder_too = not link and entry.is_dir(follow_symlinks=False)
                except OSError as e:
                    fail("Could not read the game files at %s (%s: %s)." % (folder, entry.path, e.strerror or e))
                if link:
                    fail("The game files at %s contain a link (%s): copy them without links and choose that folder."
                         % (folder, entry.path))
                if folder_too:
                    stack.append(entry.path)


def refuse_dump_links_lstat(folder):
    """(HOOKSHOT_DUMP_LINKS_LSTAT=1) refuse_dump_links as it was: os.walk, an os.lstat per entry"""
    for d, dirs, files in os.walk(long_path(folder)):
        for name in dirs + files:
            path = os.path.join(d, name)
            attrs = os.lstat(path)
            if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                fail("The game files at %s contain a link (%s): copy them without links and choose that folder."
                     % (folder, path))


PACKED_ROMFS = ("This romfs folder is NX2navi's: it holds the game's data packed in one file (romfs.bin), which Triforce cannot "
                "read, so the game would crash at start. Choose your game file (.nup) instead, or romfs and exefs folders with "
                "the game's files unpacked in them.")


def refuse_packed_romfs(folder):
    """(Triforce, 11-18) NX2navi keeps the game's RomFS as one image, <its game folder>\\romfs\\romfs.bin (+ index.json), not as
    files: chosen as the romfs folder, it passed (only the exefs is checked) and the game was built without its data. It then
    crashed at start in the game's own setup, a 0x268-byte allocation coming back null (f_80c4afa0: two players, 11-18)"""
    if folder and os.path.isfile(os.path.join(folder, "romfs.bin")):
        fail(PACKED_ROMFS)


# ((Triforce, 11-24, after Source A's) What a romfs must hold for the build and the game's start, each as (any one of its
# names, test): the build reads Pack/ZsDic.pack.zs and System/Resource (prompt_assets.py, shader_census.py), and the game
# cannot start without its heap definition, which it opens as Product. then Default. (a romfs with no System folder crashed
# at boot every time, "write 0x100000000000, guest 0", its heaps set up without their sizes; that file alone missing does too)
ROMFS_NEEDED = ((("Pack/ZsDic.pack.zs",), os.path.isfile), (("System/Resource",), os.path.isdir),
                (("System/HeapSize/Product.Nin_Ounce_NVN2.HeapDef.byml.zs",
                  "System/HeapSize/Default.Nin_Ounce_NVN2.HeapDef.byml.zs"), os.path.isfile))


def romfs_missing(romfs):
    """The first of ROMFS_NEEDED that romfs lacks (its first name), or None"""
    folder = long_path(romfs)
    return next((names[0] for names, there in ROMFS_NEEDED
                 if not any(there(os.path.join(folder, *name.split("/"))) for name in names)), None)


def check_romfs_folder(romfs, source=None):
    """((Triforce, 11-24, after Source A's) A romfs folder holds what the build and the game's start need (ROMFS_NEEDED), said
    before anything is built: another tool's packed copy or a folder without the game's files was built for 15 minutes, and
    the game stopped at boot without its system files. source: what the folder is, when it is not the player's choice (a
    .nup's unpack, or the game folder's copy for an update)"""
    missing = romfs_missing(romfs)
    if not missing:
        return
    if source:
        fail("%s has no %s in its game files: a game built from it could not start. Dump the game again (a complete dump) "
             "and build from that." % (source, missing))
    packed = (" It holds a romfs.bin, a packed copy of the game's files: extract it first."
              if os.path.isfile(os.path.join(long_path(romfs), "romfs.bin")) else "")
    fail("The romfs folder %s does not hold the game's files (no %s): choose the extracted RomFS.%s" % (romfs, missing, packed))


def long_path(p):
    """(Windows) p as an extended-length path (\\\\?\\...): a game folder whose deepest file passes 260 characters still links
    and is read (#1468); Python takes these without Windows' long-paths setting. Elsewhere, or one already: as is (nup.py's)"""
    if os.name != "nt" or not p:
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p


def link_or_copy(src, dst):
    """the romfs by hard links where the disk allows: 26 GB not written twice

    (Triforce, 11-21, the performance audit's IO-41, after Source A's) One walk; each folder made once, not asked for at
    every file of it; and no os.path.exists before each link: os.link says FileExistsError itself for a file a retry left,
    which is passed over. The staged copy, for a disk that cannot link, is as it was"""
    src, dst = long_path(src), long_path(dst)
    walked = [(d, fs) for d, _, fs in os.walk(src)]
    total, i = sum(len(fs) for _, fs in walked), 0
    for d, fs in walked:
        rel = os.path.relpath(d, src)
        # (the top folder is dst itself: an extended-length path keeps "dst\\." as it is written, a folder named ".")
        to = dst if rel == os.curdir else os.path.join(dst, rel)
        os.makedirs(to, exist_ok=True)
        for f in fs:
            s, t = os.path.join(d, f), os.path.join(to, f)
            try:
                os.link(s, t)
            except FileExistsError:
                pass   # (a retry: what an earlier try put there stays)
            except OSError:
                if not os.path.exists(t):
                    # A retry skips existing targets, so publish the copy only after it is complete.
                    fd, staged = tempfile.mkstemp(prefix=".romfs-", dir=to)
                    try:
                        os.close(fd)
                        shutil.copy2(s, staged)
                        os.replace(staged, t)
                    except BaseException:
                        with contextlib.suppress(FileNotFoundError):
                            if os.name == "nt":
                                # copy2 can carry the source's read-only attribute over.
                                os.chmod(staged, stat.S_IWRITE)
                            os.unlink(staged)
                        raise
            if i % 500 == 0:
                say("progress", "%.3f" % (i / max(1, total)))
            i += 1


def shader_census_cmd(romfs, out):
    """The shader list, under the same UTF-8 mode as the other steps. -I alone follows the console's code page, and an
    archive name that page cannot print stopped this step: the game then compiled its shaders as it played."""
    return PY + [os.path.join(HERE, "shader_census.py"), long_path(romfs), "--out", out]


# ((Triforce) the shader list made again only when its inputs changed: every build ran shader_census.py (4-7 s) and wrote the
# 514 MB triforce_shaders.bin again. A note in the work folder says what the list in the game folder was made from: the
# script, the Python running it, the names, sizes and times of the game files the census reads (CENSUS_READS), and the list
# file itself (its path, size and time). HOOKSHOT_SHADER_LIST_ALWAYS=1: made at every build, as before)
SHADER_LIST_NOTE = "shader_list.txt"   # (in <work>: what the game folder's triforce_shaders.bin was made from)
CENSUS_READS = ("Shader", "Layout2Shader", "Lib", "Movie", "Effect", os.path.join("Pack", "ZsDic.pack.zs"))   # (shader_census.py)


def shader_list_key(romfs):
    """What shader_census.py's list depends on: the script, the Python running it, and the game files it reads (CENSUS_READS: their
    names, sizes and times)"""
    h = hashlib.sha1(sys.version.encode(), usedforsecurity=False)
    with open(os.path.join(HERE, "shader_census.py"), "rb") as f:
        h.update(f.read())
    for top in CENSUS_READS:
        p = os.path.join(long_path(romfs), top)
        if os.path.isfile(p):
            files = [p]
        else:
            files = []
            for d, dirs, names in os.walk(p):
                dirs.sort()
                files += [os.path.join(d, n) for n in sorted(names)]
        for f in files:
            st = os.stat(f)
            h.update(("%s %d %d\n" % (os.path.relpath(f, long_path(romfs)).replace(os.sep, "/"), st.st_size, st.st_mtime_ns)).encode())
    return h.hexdigest()


def shader_list_note(romfs, out):
    try:
        st = os.stat(out)
    except OSError:
        return None
    return "%s %s %d %d" % (shader_list_key(romfs), os.path.normcase(os.path.abspath(out)), st.st_size, st.st_mtime_ns)


def shader_list_current(work, romfs, out):
    """out (the game folder's triforce_shaders.bin) is the list the last build made in this work folder from the same files and
    tools"""
    if os.environ.get("HOOKSHOT_SHADER_LIST_ALWAYS") == "1":
        return False
    try:
        with open(os.path.join(work, SHADER_LIST_NOTE), encoding="utf-8") as f:
            had = f.read().strip()
    except (OSError, UnicodeDecodeError):
        return False
    try:
        return bool(had) and had == shader_list_note(romfs, out)
    except OSError:
        return False


def note_shader_list(work, romfs, out):
    try:
        note = shader_list_note(romfs, out)
        if note:
            with open(os.path.join(work, SHADER_LIST_NOTE), "w", encoding="utf-8") as f:
                f.write(note + "\n")
    except OSError:
        pass


LIFT_KEY = ".lift_key"   # (in <work>/sa/gen: what the lifted C there was made from)


def game_linked_first(lines):
    """((Triforce, 11-24, after Source A's) Whether build.py linked the game itself ("linked <...>/Triforce.exe: N MB (", or
    triforce on Linux) before it failed: what failed came after it, the renderer's link or its symbol check, made of gpu/vk
    and its libraries alone"""
    return any(re.match(r"linked .*[\\/](Triforce\.exe|triforce): \d+ MB \(", line) for line in lines)


def forget_renderer_objects(work):
    """((Triforce, 11-24, after Source A's) The renderer's objects (sa/build/obj/vk_*, nx2/build.py's vk_jobs) out of the work
    folder and its object cache: the next build compiles the renderer again, and nothing else"""
    obj_dir = os.path.join(work, "sa", "build", "obj")
    try:
        names = [f for f in os.listdir(obj_dir) if f.startswith("vk_")]
    except OSError:
        return
    keys = []
    for f in names:
        if f.endswith(".sha1"):
            with contextlib.suppress(OSError), open(os.path.join(obj_dir, f)) as h:
                keys.append(h.read().strip())
    for key in keys:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(work, "objcache", key + ".o"))
    _object_store.forget(_object_store.folder(work), keys)   # ((Triforce) HOOKSHOT_OBJ_STORE: and from the store, or the next try takes them
    for f in names:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(obj_dir, f))


def compile_alone_failed(lines):
    """Whether a build that failed in nx2/build.py failed in its compile and never came to a link: build.py's own lines say
    so ("compiled in 412s, 2 failed", and no "link FAILED" after it). The objects that compile did make are then whole,
    each stamped and cached under the hash of its source and flags only once its compiler ended well, and are worth
    keeping: a compiler that ran out of memory, or a disk that filled, used to cost the next build every one of the ~600
    files again (make_game deleted them all), an hour and more on the PCs where a compile fails in the first place. A
    build that got as far as its link and failed there, or that ended without saying how its compile went, is not
    trusted: its objects go, as before (a stale object linked "compiled in 0s" at every try, issue 1197)"""
    failed = None
    for line in lines:
        m = re.match(r"compiled in \d+s, (\d+) failed", line)
        if m:
            failed = int(m.group(1))
        elif "link FAILED" in line:
            return False
    return bool(failed)


COMPILE_ERROR = re.compile(r".*\.[ch]:\d+:\d+: (?:fatal )?error: ")   # (clang's, at a place in a source; one out of memory names none)


def lifted_sums(gen):
    """{name: the contents' SHA-1} of the lift's C and headers (<work>/sa/gen): ~0.8 s for the game's 1.5 GB"""
    sums = {}
    for f in sorted(os.listdir(gen)):
        if f.endswith((".c", ".h")):
            with open(os.path.join(gen, f), "rb") as h:
                sums[f] = hashlib.sha1(h.read(), usedforsecurity=False).hexdigest()
    return sums


def refused_lift(gen, failed, errors):
    """(HOOKSHOT_LIFT_RECHECK) The compile failed in the lift's files alone (failed: build.py's "FAILED <name>" lines), with a
    compiler's error at a place in a source in each (errors: one boolean a FAILED line). Not a compiler that ran out of memory,
    nor a source of the repository"""
    return bool(failed) and len(errors) == len(failed) and all(errors) and all(os.path.isfile(os.path.join(gen, n)) for n in failed)


def changed_lift(gen, translate):
    """(HOOKSHOT_LIFT_RECHECK; translate(): the game translated again) The lift's files that came out different, and how many
    there are of both. The same inputs give the same files, byte for byte, so the PC changed one of the two"""
    before = lifted_sums(gen)
    translate()
    after = lifted_sums(gen)
    both = before.keys() & after.keys()
    return sorted(f for f in both if before[f] != after[f]), len(both)


LIFT_KEPT_ONCE = ".lift_kept_after_failure"   # (in <work>/sa, not in sa/gen, whose files gen_print vouches for: the lift was kept after a failed compile, once)


def failed_only_own_sources(lines, work):
    """(Triforce, 11-22, the performance audit's LIFT-27, after Source A's) Whether a build that failed in its compile
    (compile_alone_failed) failed only in the program's own sources, host/ and the renderers, and in nothing the lift
    wrote: then the translated game is not what failed, and its key can stay, so that the next build does not translate
    the game again (a compiler out of memory on a renderer's file cost the retry the whole lift, a minute to several).
    lines: build.py's own, "FAILED <file> (...)" for each file that failed alone too and "compiled in Ns, K failed".
    False unless every one of the K files is named, none is a lifted file (code_*) and none is a file of the lift's
    folder or of the build's generated one (<work>/sa/gen, <work>/sa/build/gen): a lifted file cut short or left by
    another builder fails there or at the link (issues 1197, 1176), and the lift is then forgotten as before"""
    names, count = [], None
    for line in lines:
        m = re.match(r"FAILED (\S+) \(", line)
        if m:
            names.append(m.group(1))
        m = re.match(r"compiled in \d+s, (\d+) failed", line)
        if m:
            count = int(m.group(1))
    if not names or count != len(names):
        return False
    made = (os.path.join(work, "sa", "gen"), os.path.join(work, "sa", "build", "gen"))
    return not any(n.startswith("code_") or any(os.path.exists(os.path.join(d, n)) for d in made) for n in names)


def keep_lift_after_failure(lines, work, environ=None):
    """Whether a failed build keeps the lift's key: HOOKSHOT_KEEP_LIFT is not 0, the compile alone failed, only the
    program's own sources failed (failed_only_own_sources), and the build before this one did not keep it the same way.
    That last: a generated header cut short fails the program's own files, which name nothing of the lift; kept twice,
    such a lift would fail at every try, so the second failure in a row forgets it, as every failure did before.
    Leaves LIFT_KEPT_ONCE in <work>/sa when it says yes and removes it when it says no (main removes it after a build
    that compiled)"""
    environ = os.environ if environ is None else environ
    mark = os.path.join(work, "sa", LIFT_KEPT_ONCE)
    again = os.path.exists(mark)
    keep = environ.get("HOOKSHOT_KEEP_LIFT", "1") != "0" and not again and compile_alone_failed(lines) and \
        failed_only_own_sources(lines, work)
    try:
        if keep:
            open(mark, "w").close()
        elif again:
            os.remove(mark)
    except OSError:
        keep = False   # (the mark cannot be kept: not twice in a row cannot be told, so the lift is forgotten)
    return keep
PROMPT_KEY = ".made_from"   # (in <out>/prompts: prompts_key of what that folder was made from)


def prompt_game_files(romfs):
    """((Triforce, 11-21, the performance audit's IO-43) The game's files nx2/prompt_assets.py reads, as names under the
    romfs, each once and in a fixed order: the zstd dictionaries' pack, the font, the textures, the layouts, the camera's
    pack, the resource size table and every language's messages. None when the tool's own names cannot be had.
    tests/test_prompts_background.py holds this list against what the tool opens"""
    try:
        import prompt_assets
    except Exception:   # (the tool is not beside this one, or does not load: the prompts are made at every build, as before)
        return None
    names = ["Pack/ZsDic.pack.zs", prompt_assets.FONT, prompt_assets.TEXTURES, prompt_assets.LAYOUTS, prompt_assets.CAMERA]
    try:   # ((Triforce VR) the letters of the hand controllers' icons, nx2/prompt_vr.py)
        import prompt_vr
        names.append(prompt_vr.LETTERS)
    except Exception:
        pass
    try:   # (the first by name, as prompt_assets.read_size_table takes it)
        names += ["System/Resource/" + n for n in sorted(os.listdir(os.path.join(romfs, "System", "Resource")))
                  if n.startswith("ResourceSizeTable.") and n.endswith(".rsizetable.zs")][:1]
    except OSError:
        pass
    try:
        names += [prompt_assets.MALS + "/" + n for n in sorted(os.listdir(os.path.join(romfs, prompt_assets.MALS)))
                  if n.endswith(".sarc.zs")]
    except OSError:
        pass
    return names


def prompts_key(out, romfs=None):
    """What the button prompts of other controllers are made from, as one hash: the tools that draw them (nx2/prompt_*.py,
    the faces' drawings and parts in nx2/prompt_faces, the icon fonts in third_party/kenney_input), the packages they are
    drawn with (nx2/prompt_requirements.txt) and the game's files, by the unpack's stamp (.triforce_romfs: the .nup's name
    and size). (Triforce) The keyboard and mouse face's too: nx2/prompt_keys.py, which draws it, and the font its
    labels are set in (third_party/fonts/libertinus: that one file, the menus' other fonts are not the prompts')

    (Triforce, 11-21, the performance audit's IO-43, after Source A's) A romfs with no such stamp (the player's own
    folders, linked in) had no key, and its prompts were drawn at every build and every update, 60 to 87 s each time:
    its key is now the content of the game's files the tool reads (prompt_game_files, about 100 MB hashed). And for
    every game the key holds host/prompts.c, which reads what is drawn, and the release these tools are (version.txt or
    VERSION; a checkout has neither). None, the prompts made at every build as before: with no stamp and no romfs given,
    when the tool's names cannot be had, or with HOOKSHOT_PROMPTS_FOLDER_KEY=0"""
    stamp = os.path.join(out, ".triforce_romfs")
    game = []   # (the game's files by content, where no stamp says which dump they are)
    if not os.path.isfile(stamp):
        if not romfs or os.environ.get("HOOKSHOT_PROMPTS_FOLDER_KEY", "") == "0":
            return None
        names = prompt_game_files(romfs)
        if names is None:
            return None
        game = [("romfs/" + n, os.path.join(long_path(romfs), *n.split("/"))) for n in names]
        stamp = None
    # (each file under a name that does not depend on where the tools are installed)
    files = [("nx2/" + n, os.path.join(HERE, n))
             for n in ("prompt_assets.py", "prompt_draw.py", "prompt_faces.py", "prompt_requirements.txt", "prompt_keys.py")]
    labels = "third_party/fonts/libertinus/LibertinusSans-Bold.ttf"
    files.append((labels, os.path.join(ROOT, *labels.split("/"))))
    # ((Triforce, 11-21, IO-43) what reads the drawn files in the game, and which release these tools are)
    files.append(("host/prompts.c", os.path.join(ROOT, "host", "prompts.c")))
    files += [("release/" + n, os.path.join(ROOT, n)) for n in ("version.txt", "VERSION")]
    for name, root in (("nx2/prompt_faces", os.path.join(HERE, "prompt_faces")),
                       ("third_party/kenney_input", os.path.join(ROOT, "third_party", "kenney_input"))):
        for folder, dirs, names in os.walk(root):
            dirs.sort()
            files += [(name + "/" + os.path.relpath(os.path.join(folder, n), root).replace(os.sep, "/"), os.path.join(folder, n))
                      for n in sorted(names)]
    h = hashlib.sha1()
    if stamp:
        with open(stamp, "rb") as f:
            h.update(f.read())
    else:
        h.update(b"the game's files, by content\n")
    for name, path in game + files:
        if os.path.isfile(path):
            h.update(name.encode())
            with open(path, "rb") as f:
                for piece in iter(lambda: f.read(1 << 20), b""):
                    h.update(piece)
        elif (name, path) in game:
            h.update(name.encode() + b": none\n")   # (a file the tool would miss: not the key of a romfs that has it)
    return h.hexdigest()


class EarlyCompile:
    """(Windows) The files that need nothing of the translated game, compiled while the game is being translated
    (nx2/build.py RX_EARLY): libopus and the two renderers with their libraries, ~520 of the build's ~630 files. The lift was
    one process there and left every other processor idle for its two minutes, and then the compile had those files to do
    on top of the game's. (The lift's emit has processes of its own there now, nx2/emit_pool.py: at most half the
    processors, and its first part, the discovery, is still one process.) finish() waits for it before the build proper starts, which then finds their objects made.
    A failure here costs nothing: the build compiles whatever is missing, as before. HOOKSHOT_EARLY_COMPILE=0: not done"""

    def __init__(self, work, env, jobs):
        self.proc = None
        if os.name != "nt" or os.environ.get("HOOKSHOT_EARLY_COMPILE") == "0":
            return
        self.log = os.path.join(work, "early_compile.log")
        e = dict(os.environ, PYTHONIOENCODING="utf-8")
        e.update(env)
        e["RX_EARLY"] = "1"
        e.pop("HOOKSHOT_TIMES", None)   # (no countdown lines: nobody reads them here)
        with open(self.log, "w", encoding="utf-8") as log:
            self.proc = subprocess.Popen(PY + ["nx2/build.py", "--standalone", "--jobs", str(max(1, jobs - 1))], cwd=ROOT, env=e,
                                         stdout=log, stderr=subprocess.STDOUT)
        no_throttle(getattr(self.proc, "_handle", None))

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    def finish(self):
        if self.proc is None:
            return
        waited = time.time()
        code = self.proc.wait()
        said = ""
        try:
            with open(self.log, encoding="utf-8", errors="replace") as f:
                said = next((line.strip() for line in reversed(f.read().splitlines()) if line.startswith("compiled in ")), "")
        except OSError:
            pass
        print("the files that need no translated code were compiled beside the lift: %s%s (%s more after the lift ended)%s"
              % (said or "no result", "" if not code else ", stopped with status %d" % code, clock(time.time() - waited),
                 "" if not code else ": the build compiles what is missing"), flush=True)
        self.proc = None


def vr_texts(out, romfs):
    """((Triforce VR) VR's texts and HUD hints (scripts/vr_text: the team's wording in edits/, none of the game's): made from
    this game's own files into <out>/vr_text/gesture and /simplified, one per Control Scheme; host/mods.c serves the scheme's
    while VR is on, and none in flat-screen play. Without them, or when they fail, VR shows the game's own texts"""
    tool = os.path.join(ROOT, "scripts", "vr_text", "vr_build.py")
    folder = os.path.join(out, "vr_text")
    shutil.rmtree(folder, ignore_errors=True)
    if not os.path.exists(tool) or importlib.util.find_spec("zstandard") is None:
        return
    if run(PY + [tool, out, "--romfs", romfs], check=False, output=sys.stderr):
        shutil.rmtree(folder, ignore_errors=True)
        print("VR's texts were not made: VR shows the game's own", flush=True)
    else:
        print("VR's texts made (vr_text/)", flush=True)


class Prompts:
    """The button prompts of other controllers (host/prompts.c): the game's icon font and textures redrawn per controller by
    nx2/prompt_assets.py, with fontTools. It took 87 s at the end of every build and every update, with nothing else
    running. It reads only the game's files, so it now starts as soon as they are read, beside the lift and the compile,
    into <out>/prompts.new, and finish() puts the folder in place; and it is not run at all when the folder there was made
    from the same tools and the same game files (prompts_key). Without it, or when it fails, the game shows its own icons,
    as before"""

    def __init__(self, romfs, out, work):
        self.out, self.folder, self.new = out, os.path.join(out, "prompts"), os.path.join(out, "prompts.new")
        self.key = prompts_key(out, romfs)   # ((Triforce, 11-21, IO-43) the romfs: its files' content where it has no stamp)
        self.proc = self.log = None
        self.state = "no fontTools" if importlib.util.find_spec("fontTools") is None else None
        if self.state:
            return
        try:
            with open(os.path.join(self.folder, PROMPT_KEY), encoding="utf-8") as f:
                if self.key and f.read().strip() == self.key:
                    self.state = "kept"
                    return
        except OSError:
            pass
        shutil.rmtree(self.new, ignore_errors=True)
        self.log = os.path.join(work, "prompts.log")
        with open(self.log, "w", encoding="utf-8") as log:
            self.proc = subprocess.Popen(PY + [os.path.join(HERE, "prompt_assets.py"), "--romfs", romfs, "--out", self.new],
                                         cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=log,
                                         stderr=subprocess.STDOUT)
        no_throttle(getattr(self.proc, "_handle", None))

    def stop(self):
        """(the build failed or was stopped) the drawing ended and what it wrote taken away: the folder in place stays"""
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        shutil.rmtree(self.new, ignore_errors=True)

    def finish(self):
        """Waits for the drawing, says what it said, and puts the new folder in the old one's place"""
        if self.state == "no fontTools":
            shutil.rmtree(self.folder, ignore_errors=True)
            print("the button prompts of other controllers were not made (no fontTools): the game shows its own", flush=True)
            return
        if self.state == "kept":
            print("the button prompts of other controllers are as the last build made them (the same tools and game files): kept",
                  flush=True)
            return
        code = self.proc.wait()
        try:
            with open(self.log, encoding="utf-8", errors="replace") as f:
                sys.stderr.write(f.read())
                sys.stderr.flush()
        except OSError:
            pass
        shutil.rmtree(self.folder, ignore_errors=True)
        if code:
            print("the button prompts of other controllers were not made: the game shows its own", flush=True)
            shutil.rmtree(self.new, ignore_errors=True)
            return
        os.replace(self.new, self.folder)
        if self.key:
            with open(os.path.join(self.folder, PROMPT_KEY), "w", encoding="utf-8") as f:
                f.write(self.key + chr(10))


# (Triforce) Files of nx2/ that are not the translator's and that the lift (nx2/lift.py, nx2/split_hot.py and what they
# import) cannot read: this driver, the steps before and after the lift, the version, the button prompts, and the tests
# kept in nx2/. They were part of the lift key, so an update that changed one of them, and every release changes the
# version and most change this file, translated the whole game again on every player's PC: 2:48 of a 3:05 update build
# on a 16-thread PC, for C that came out the same byte for byte. tests/test_lift_key_files.py holds the list to what
# the lift can import and to what its files name.
LIFT_KEY_NOT = ("make_game.py", "build.py", "nup.py", "lift_store.py", "version.py", "shader_census.py", "prompt_assets.py", "prompt_draw.py",
                "prompt_faces.py", "prompt_requirements.txt", "prompt_keys.py",
                "code_mods.py",   # (the mods' code patches: what it does to the game's code is in the key, the exefs's files)
                # ((Triforce, 11-22, the performance audit's LIFT-27) the last release's shader translation stamp, which
                # build.py alone reads (RELEASED_STAMP): a release that changed the shader translator lifted the game again.
                # HOOKSHOT_KEEP_LIFT=0 puts it back in the key: lift_key)
                "released_translation_stamp.json",
                "cold_parts.py",   # ((Triforce, 11-22, LIFT-17) the compile's parts of a -O2 chunk: nx2/build.py's alone
                "object_store.py",   # ((Triforce) HOOKSHOT_OBJ_STORE: the compiled objects shared between work folders, build.py's
                "split_giants.py")   # ((Triforce) HOOKSHOT_SPLIT_GIANTS: the compile's copy of a chunk with its giants cut, build.py's


def lift_key_file(rel):
    """Whether a file of nx2/ (rel: its path under nx2/, with /) is part of the lift key: all but LIFT_KEY_NOT, the
    prompt_faces folder and the tests (test_*.py)"""
    name = rel.rsplit("/", 1)[-1]
    return not (rel in LIFT_KEY_NOT or rel.startswith("prompt_faces/") or (name.startswith("test_") and name.endswith(".py")))


def lift_key(exefs, work, env, chunks=True):
    """What the lift's output depends on: the game's code, the translator (nx2/ but for LIFT_KEY_NOT, the vendored a64-kit), the HLE
    functions host/ defines (hooked in the lift; the rest of host/ is compiled after it, so a change there alone does not lift again),
    the hot list and chunk boundaries, the lift's environment and the Python running it. A file the lift never reads may be in it (a
    new build then lifts again); one it reads must be. chunks=False: all of it but the chunk boundaries (key_after_lift)"""
    import kit  # noqa: F401  (a64-kit on the path, for standalone)
    import standalone
    h = hashlib.sha1(sys.version.encode(), usedforsecurity=False)
    h.update(" ".join(sorted(standalone.implemented())).encode())
    # ((Triforce, 11-22, the performance audit's LIFT-27, after Source A's) HOOKSHOT_KEEP_LIFT=0: the key as it was, with
    # every A64_, OOT_ and RX_ variable and the paths in it, and the release's translation stamp among its files. Read
    # here, inside the function, like COMPILE_ONLY_ENV below)
    key_as_before = os.environ.get("HOOKSHOT_KEEP_LIFT", "1") == "0"
    # (each file named from its own base: the exefs and the work folder may be on another drive than the source, which relpath refuses)
    files = [(exefs, os.path.join(exefs, f)) for f in sorted(os.listdir(exefs))]
    for top in (HERE, os.path.join(ROOT, "third_party", "a64-kit")):
        for d, dirs, fs in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            files += [(ROOT, os.path.join(d, f)) for f in sorted(fs) if f.endswith((".py", ".c", ".h", ".cpp", ".hpp", ".txt", ".json"))
                      and (top != HERE or lift_key_file(os.path.relpath(os.path.join(d, f), HERE).replace(os.sep, "/"))
                           or (key_as_before and d == HERE and f == "released_translation_stamp.json"))]
    files.append((work, os.path.join(work, "hot_funcs.txt")))
    if chunks:
        files.append((work, os.path.join(work, "image", "chunks.txt")))
    for base, f in files:
        if os.path.isfile(f):
            h.update(os.path.relpath(f, base).replace(os.sep, "/").encode() + bytes(1))
            with open(f, "rb") as src:
                h.update(hashlib.sha1(src.read(), usedforsecurity=False).digest())
    lift_env = dict(env, **{k: v for k, v in os.environ.items() if k.startswith(("A64_", "OOT_", "RX_"))})
    # ((Triforce, 11-21, LIFT-10) what only the compile after the lift reads: the renderer's profile translates no game code.
    # Named here, inside the function: tests/test_lift_key_files.py and test_spawn_emit.py run lift_key cut out by itself)
    COMPILE_ONLY_ENV = ("RX_VK_PGO", "RX_VK_PGO_FILE", "RX_A64_RT_O2")   # ((Triforce) and the A64 helpers' level: build.py's)
    for name in COMPILE_ONLY_ENV:
        lift_env.pop(name, None)
    # ((Triforce, 11-22, LIFT-27) only what shapes the C: the lifter's own switches (A64_*: nx2/fastvec.py and the kit's
    # a64_lift.py read no others) and the target (RX_TARGET: the kit's toolchain.windows). The rest that the lift's files
    # read are folders (OOT_WORK, OOT_DUMP, OOT_EXEFS, OOT_ROMFS: the files there are hashed above by their contents),
    # job counts and where the compiler is, and what the compile after the lift reads (RX_RELEASE, the profile's path):
    # a build from another folder, or one more variable in the environment, lifted the same C again.
    # tests/test_lift_key_env.py holds the lift's files to that list)
    if not key_as_before:
        # ((Triforce, 11-24) the build's value where the build sets one: run() gives the lift the build's env over the shell's, and
        # the line above took them the other way round, so an A64_HOT_CHUNK left in the shell was hashed where the lift reads the
        # build's 1: a translation again for nothing. And the hot list by what it holds, not by its path: <work>/hot_funcs.txt is
        # hashed above already; another list, named in the shell, by its contents (by its path where there is no such file), so an
        # edit to it translates again and the same list in another folder does not)
        lift_env = {k: v for k, v in lift_env.items() if k.startswith("A64_") or k == "RX_TARGET"}
        lift_env.update({k: v for k, v in env.items() if k.startswith("A64_") or k == "RX_TARGET"})
        hot = lift_env.get("A64_HOT_FUNCS")
        if hot and os.path.normcase(os.path.abspath(hot)) == os.path.normcase(os.path.abspath(os.path.join(work, "hot_funcs.txt"))):
            lift_env["A64_HOT_FUNCS"] = "<work>/hot_funcs.txt"   # (named: a hot list is used; its contents are hashed above)
        elif hot:
            try:
                with open(hot, "rb") as src:
                    lift_env["A64_HOT_FUNCS"] = "sha1:" + hashlib.sha1(src.read(), usedforsecurity=False).hexdigest()
            except OSError:
                pass   # (no such file: its path, as before)
    h.update(repr(sorted(lift_env.items())).encode())
    return h.hexdigest()


def lift_share_key(exefs, work, out, env):
    """(Triforce, 11-24; HOOKSHOT_LIFT_STORE, nx2/lift_store.py) The key a translation is kept under for other work folders: the
    lift key, which holds no folder's path (LIFT-27; the hot list by its contents). With HOOKSHOT_KEEP_LIFT=0 the paths are in it
    again, and so no other folder's translation is found"""
    return lift_key(exefs, work, env)


def key_after_lift(exefs, work, env, key, before, copied):
    """(Triforce, epicmemes46's 5df76bb) The key a finished lift is kept under. key: the one taken before it; before: that one
    without the chunk boundaries (lift_key's chunks=False); copied: the boundaries were copied in from the source's
    work/image/chunks.txt. The lift writes <work>/image/chunks.txt (nx2/chunks.py save): into a work folder that had none, the
    boundaries the sizes gave. The key taken before it had none in it, the next build's has those, and so the build after every
    lift into a fresh work folder translated the whole game again, the same game with the same tools. Boundaries the lift wrote
    are what its own inputs give, so the key is taken again now, as the next build takes it, when nothing but chunks.txt changed
    meanwhile (an update of the tools during the lift keeps the key from before it, and the next build lifts again). Boundaries
    copied in from the source are an input, copied again at each build: the key from before the lift stays"""
    if copied or lift_key(exefs, work, env, chunks=False) != before:
        return key
    return lift_key(exefs, work, env)


def gen_print(gen):
    """The lifted C's files as the lift left them (names, sizes, times): another builder's lift into the same work folder
    (an older one, or another branch's, which knows nothing of the key) changes it, and the key no longer vouches for it"""
    h = hashlib.sha1(usedforsecurity=False)
    for name in sorted(os.listdir(gen)):
        p = os.path.join(gen, name)
        # ((Triforce) KEPT_LIST: build.py's, written after the lift)
        if name not in (LIFT_KEY, KEPT_LIST, KEPT_LIST + ".new") and os.path.isfile(p):
            st = os.stat(p)
            h.update(("%s %d %d\n" % (name, st.st_size, st.st_mtime_ns)).encode())
    return h.hexdigest()


def write_lift_key(work, key):
    gen = os.path.join(work, "sa", "gen")
    with open(os.path.join(gen, LIFT_KEY), "w") as f:
        f.write(key + "\n" + gen_print(gen) + "\n")


def lifted_cut_short(gen):
    """The lifted C files (code_*.c) that do not end as every lifted file does, a function's closing brace and a newline: cut short
    (a run stopped while writing one, a full disk, a second build in the same folder: issue 1197)"""
    bad = []
    if not os.path.isdir(gen):
        return bad
    for f in sorted(os.listdir(gen)):
        if not (f.startswith("code_") and f.endswith(".c")):
            continue
        try:
            with open(os.path.join(gen, f), "rb") as h:
                h.seek(0, 2)
                n = h.tell()
                h.seek(max(0, n - 2))
                end = h.read()
        except OSError:
            end = b""
        if end != b"}\n":
            bad.append(f)
    return bad


def lifted_zero_bytes(gen):
    """The lifted C files (code_*.c) with a zero byte in them. The lift never writes one: the PC's memory or the drive changed the
    file after it was written, its size and end as they were (a player's build: 17 files refused in the compile, where the build
    can only stop, the error naming one of them). Each is read whole (0.2-0.6 s for the game's 1.5 GB just written), so it is
    asked only of a translation without a record of a successful check (the lift key's third line, "zero-checked")"""
    bad = []
    if not os.path.isdir(gen):
        return bad
    for f in sorted(os.listdir(gen)):
        if f.startswith("code_") and f.endswith(".c"):
            try:
                with open(os.path.join(gen, f), "rb") as h:
                    if b"\0" in h.read():
                        bad.append(f)
            except OSError:
                pass   # (lifted_cut_short names a file it cannot read)
    return bad


def lifted_before(work, key):
    """The lift (and split_hot) in <work>/sa finished before with this key, its C is as that lift left it, and what the later
    steps read of it is there"""
    gen, image = os.path.join(work, "sa", "gen"), os.path.join(work, "sa", "image")
    try:
        with open(os.path.join(gen, LIFT_KEY)) as f:
            lines = f.read().split()
    except OSError:
        return False
    # (a third line: "zero-checked", lifted_zero_bytes found none in this C)
    if (len(lines) not in (2, 3) or (len(lines) == 3 and lines[2] != "zero-checked")
            or lines[0] != key or lines[1] != gen_print(gen)):
        return False
    return os.path.isfile(os.path.join(image, "image.bin")) and os.path.isfile(os.path.join(gen, "a64_table.c"))


KEPT_LIST = "lifted_objects.txt"   # ((Triforce) nx2/build.py's list of the lifted files' object keys, in <work>/sa/gen)
KEPT_SCHEME = 1   # (that list's format: its first line names it with the lift key, nx2/build.py kept_header)
KEPT_STALE = 75   # (nx2/build.py's exit status when that list no longer fits the build: the game is translated again. Not 3: abort())


def kept_list_fits(gen, key):
    """KEPT_LIST is there and was written for the lift with this key, in this format"""
    try:
        with open(os.path.join(gen, KEPT_LIST), encoding="utf-8") as f:
            return f.readline() == "# lift %s %d\n" % (key, KEPT_SCHEME)
    except (OSError, UnicodeDecodeError):
        return False


def kept_before(work, key):
    """((Triforce) a player's update) The last build had this lift key and its clean-up let the lifted C go but kept the rest of
    the lift and the list of its object keys (keep_translation): the lift can be skipped, build.py linking the lifted files'
    objects from the cache by that list"""
    gen = os.path.join(work, "sa", "gen")
    try:
        with open(os.path.join(gen, LIFT_KEY)) as f:
            lines = f.read().split()
    except OSError:
        return False
    if len(lines) != 3 or lines[0] != key or lines[1] != gen_print(gen) or lines[2] != "kept":
        return False
    if any(f.startswith("code_") for f in os.listdir(gen)):
        return False
    return kept_list_fits(gen, key) and all(os.path.isfile(p) for p in (os.path.join(gen, "a64_table.c"),
                                                                        os.path.join(work, "sa", "image", "image.bin")))


def keep_translation(work, key):
    """((Triforce) after a build that compiled every file) What a player's clean-up keeps of the lift: everything but the lifted C
    itself (1.5 GB: code_*.c) and the build's outputs. The lift's other files (~130 MB: the headers the objects are keyed by, the
    runtime tables, the image) and build.py's list of the lifted files' object keys stay, with the lift key marked "kept"
    (kept_before): every update translated the whole game again (1-3 minutes, more on a slow PC) for C that came out the same.
    Returns the bytes kept, or None when there is nothing to keep it by (the lift and that list not from this build). A file it
    cannot remove (Windows: one still held open) is no failed build: the game folder is ready by then. All of sa goes as before,
    as far as it can. HOOKSHOT_KEEP_TRANSLATION=0: all of sa goes, as before"""
    if os.environ.get("HOOKSHOT_KEEP_TRANSLATION") == "0":
        return None
    gen = os.path.join(work, "sa", "gen")
    if not (lifted_before(work, key) or kept_before(work, key)) or not kept_list_fits(gen, key):
        return None
    try:
        for f in os.listdir(gen):
            if f.startswith("code_"):
                os.remove(os.path.join(gen, f))
        shutil.rmtree(os.path.join(work, "sa", "build"), ignore_errors=True)
        with open(os.path.join(gen, LIFT_KEY), "w") as f:
            f.write(key + "\n" + gen_print(gen) + "\nkept\n")
        kept = 0
        for d, _, fs in os.walk(os.path.join(work, "sa")):
            kept += sum(os.path.getsize(os.path.join(d, f)) for f in fs)
        return kept
    except OSError as e:
        print("the translation could not be kept for the next update (%s): it is translated again then" % e, flush=True)
        shutil.rmtree(os.path.join(work, "sa"), ignore_errors=True)
        return None


def ngx_script():
    """scripts/ngx_sdk.py: NVIDIA's DLSS SDK, its file table and where each file goes"""
    import importlib.util
    path = os.path.join(ROOT, "scripts", "ngx_sdk.py")
    if not os.path.isfile(path):   # (the AppImage carries no scripts/: its Vulkan back end comes built, without DLSS)
        fail("NVIDIA DLSS (HOOKSHOT_NGX_SDK) needs %s, which this builder does not carry: its renderer is built without DLSS. "
             "Unset HOOKSHOT_NGX_SDK, or build Hookshot from source for DLSS." % path)
    spec = importlib.util.spec_from_file_location("ngx_sdk", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ngx_platform():
    return "linux" if LINUX else "windows"


def fetch_ngx_sdk(a):
    """--fetch-ngx-sdk (the Hookshot Builder's NVIDIA DLSS tick): NVIDIA's DLSS SDK into HOOKSHOT_NGX_SDK before the build, once
    NVIDIA's license was accepted (--accept-nvidia-license: the builder asked first). Only what is missing or not the file
    expected is downloaded"""
    # ((Triforce, 11-24, after Source A's) without HOOKSHOT_NGX_SDK (a launcher asking through --cli has none) the folder is
    # work/ngx-sdk here, and the rest of the build, which reads the variable, finds the SDK there)
    sdk = os.environ.get("HOOKSHOT_NGX_SDK", "") or os.path.join(ROOT, "work", "ngx-sdk")
    os.environ["HOOKSHOT_NGX_SDK"] = sdk
    if not a.accept_nvidia_license:
        fail("NVIDIA DLSS needs NVIDIA's license accepted first (--accept-nvidia-license).")
    ngx = ngx_script()
    print(ngx.NOTICE, flush=True)
    print("NVIDIA's license accepted: getting NVIDIA's DLSS SDK into %s" % sdk, flush=True)
    try:
        ngx.fetch(sdk, ngx_platform(), say=lambda line: print(line, flush=True))
    except (OSError, ValueError) as e:
        fail("NVIDIA's DLSS SDK could not be downloaded (%s). Check the connection and build again, or untick NVIDIA DLSS." % e)


def fsr_script():
    """scripts/fsr_sdk.py: AMD's two FSR 4 libraries; None where the builder carries no scripts/"""
    import importlib.util
    path = os.path.join(ROOT, "scripts", "fsr_sdk.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("fsr_sdk", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fsr_runtime_dir(work):
    """Where AMD's FSR 4 libraries are kept between builds: HOOKSHOT_FSR_SDK, else the fsr-sdk folder of the work folder"""
    return os.environ.get("HOOKSHOT_FSR_SDK", "") or os.path.join(work, "fsr-sdk")


def fetch_fsr_runtime(work):
    """(--fsr, Windows) AMD's two signed FSR 4 libraries into fsr_runtime_dir, only what is missing. A download that fails
    is said and the build goes on: the game then does not offer AMD FSR 4 until a build gets them. (Triforce) And its
    frame generation library with them (scripts/fsr_sdk.py OPTIONAL): without that one the game has FSR 4 as before and
    the Frame generation row no AMD FSR 4"""
    fsr = fsr_script()
    if LINUX or fsr is None:
        return
    print(fsr.NOTICE, flush=True)
    try:
        fsr.fetch(fsr_runtime_dir(work), say=lambda line: print(line, flush=True))
    except (OSError, ValueError) as e:
        print("AMD's FSR 4 libraries could not be downloaded (%s): the game will not offer AMD FSR 4. Build again with a "
              "connection to get them." % e, flush=True)


def place_fsr_runtime(out, work, wanted):
    """(AMD FSR 4) a game built with it gets AMD's two libraries and their license text beside its exe, where
    gpu/vk/vk_fsr4.cpp looks, and (Triforce) AMD's frame generation library when it was fetched; a folder built with them
    before and without FSR 4 now loses them, all three. Returns what was placed"""
    fsr = fsr_script()
    if LINUX or fsr is None:
        return []
    if not wanted or not fsr.complete(fsr_runtime_dir(work)):
        if not wanted:
            fsr.remove_runtime(out)
        return []
    placed = fsr.install_runtime(fsr_runtime_dir(work), out)
    print("AMD FSR 4: %s (AMD's, MIT license)" % ", ".join(os.path.basename(p) for p in placed), flush=True)
    return placed


def streamline_script():
    """scripts/streamline_sdk.py: NVIDIA's Streamline files for DLSS frame generation; None where the builder carries no
    scripts/ (frame generation is then left out, DLSS itself is not)"""
    import importlib.util
    path = os.path.join(ROOT, "scripts", "streamline_sdk.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("streamline_sdk", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fetch_streamline_sdk(a):
    """With --fetch-ngx-sdk on Windows (the NVIDIA DLSS tick, NVIDIA's licenses accepted): NVIDIA's Streamline files for DLSS
    frame generation too, into HOOKSHOT_STREAMLINE_SDK (default: the streamline folder in HOOKSHOT_NGX_SDK), which
    nx2/build.py then builds gpu/vk/vk_dlssg.cpp with. A download that fails leaves frame generation out of this build and
    says so: the build goes on, with DLSS as before"""
    if LINUX or not a.accept_nvidia_license:
        return
    sl = streamline_script()
    if sl is None:
        return
    sdk = os.environ.get("HOOKSHOT_STREAMLINE_SDK", "") or os.path.join(os.environ.get("HOOKSHOT_NGX_SDK", ""), "streamline")
    print(sl.NOTICE, flush=True)
    try:
        sl.fetch(sdk, say=lambda line: print(line, flush=True))
    except (OSError, ValueError) as e:
        print("NVIDIA's Streamline could not be downloaded (%s): this build has no DLSS frame generation. Build again "
              "with a connection to get it." % e, flush=True)
        os.environ.pop("HOOKSHOT_STREAMLINE_SDK", None)
        return
    os.environ["HOOKSHOT_STREAMLINE_SDK"] = sdk


def place_dlssg_runtime(out):
    """(NVIDIA DLSS frame generation) a game built with NVIDIA's Streamline (HOOKSHOT_STREAMLINE_SDK, as nx2/build.py takes it)
    gets Streamline's DLLs, nvngx_dlssg.dll and their license texts in its dlssg folder, where gpu/vk/vk_dlssg.cpp looks. A
    folder built with them before and without them now loses them. Returns the folder, or None

    (Triforce, 11-18) DLSS's own runtime too, a copy of the one place_ngx_runtime put in ngx (so this runs after it): with
    Streamline up, NGX looks for nvngx_dlss.dll only in the dlssg folder, and without it there DLSS upscaling did not start
    ("not available on this GPU (0xbad00004)"), so the menu offered no DLSS while frame generation was on"""
    sl = streamline_script()
    if sl is None:
        return None
    sdk = os.environ.get("HOOKSHOT_STREAMLINE_SDK", "")
    dlss_copy = os.path.join(out, "dlssg", "nvngx_dlss.dll")
    if LINUX or not sl.complete(sdk):
        with contextlib.suppress(OSError):   # (before Streamline's files: the folder is left empty and goes with them)
            os.remove(dlss_copy)
        sl.remove_runtime(out)
        return None
    dst = sl.install_runtime(sdk, out)
    dlss = os.path.join(out, "ngx", "nvngx_dlss.dll")
    if os.path.isfile(dlss):
        copy_writable(dlss, dlss_copy)
    else:   # (a build without NVIDIA DLSS: no stale copy of an earlier one's)
        with contextlib.suppress(OSError):
            os.remove(dlss_copy)
    print("NVIDIA DLSS frame generation: %s (NVIDIA's, under NVIDIA's licenses: never share this game folder)" % dst, flush=True)
    return dst


def ngx_built():
    """This build has NVIDIA DLSS: HOOKSHOT_NGX_SDK holds this platform's library (what nx2/build.py takes)"""
    sdk = os.environ.get("HOOKSHOT_NGX_SDK", "")
    return bool(sdk) and os.path.isfile(ngx_script().library(sdk, ngx_platform()))


FSR_MARK = ".hookshot_fsr"   # (in a game folder built with AMD FSR 4: --update builds it with FSR again)


def fsr_wanted(a, out):
    """AMD FSR 4 in this build (--fsr; or --update of a folder built with it, unless --no-fsr): nothing to download, AMD's
    MIT headers are in third_party/fidelityfx and its DLLs are the player's (the readme)"""
    if getattr(a, "no_fsr", False):
        return False
    # ((Triforce) 11-20, ticket "No FSR4 option in game even though provided library apparently loaded": HOOKSHOT_FSR=1, which
    # nx2/build.py and the docs name, was taken away below unless --fsr was given too, so a Linux build with it set had no FSR 4.
    # Set in the environment, it asks for FSR 4 as --fsr does)
    if os.environ.get("HOOKSHOT_FSR", "") == "1":
        return True
    return bool(getattr(a, "fsr", False)) or bool(a.update and os.path.isfile(os.path.join(out, FSR_MARK)))


RENODX_MARK = ".hookshot_renodx"   # (in a game folder built with RenoDX's HDR: --update builds it with RenoDX again)


def write_mark(path):
    """A folder's mark (FSR_MARK, RENODX_MARK) for the next --update. It only remembers a choice: a drive that refuses the
    file (11-23 ticket 108774, OSError [Errno 22] on an X: drive) must not stop the build. A read-only or hidden one left there
    is cleared and written once more; failing that, a note and the build goes on (Setup passes the switch itself)"""
    for attempt in (0, 1):
        try:
            open(path, "w").close()
            return True
        except OSError as e:
            if attempt == 0 and os.path.exists(path):
                try:
                    os.chmod(path, 0o666)
                    if os.name == "nt":
                        import ctypes
                        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x80)   # (FILE_ATTRIBUTE_NORMAL)
                    os.remove(path)
                    continue
                except OSError:
                    pass
            print("note: the folder's mark %s could not be written (%s): the build goes on; the next update needs the same "
                  "choice in Setup" % (os.path.basename(path), e), flush=True)
            return False
    return False


def renodx_wanted(a, out):
    """RenoDX's HDR in this build. (Triforce, 11-13: every build has it, not only one that asks with --renodx; --no-renodx
    builds without. It acts only with the Insert menu's HDR set to Native.)"""
    return not getattr(a, "no_renodx", False)


def prepare_renodx(work):
    """--renodx: RenoDX's shaders fetched and compiled before the build (scripts/renodx_shaders.py), into HOOKSHOT_RENODX when
    set, else a renodx folder beside the work folder. Only what is missing or not the file expected is downloaded, and the
    shaders are compiled again only when the script's pinned sources or compiler changed. Returns the folder"""
    import importlib.util
    path = os.path.join(ROOT, "scripts", "renodx_shaders.py")
    if not os.path.isfile(path):   # (the AppImage carries no scripts/: its Vulkan back end comes built, without RenoDX)
        print("RenoDX's HDR: this builder does not carry %s: built without RenoDX" % path, flush=True)
        return None
    spec = importlib.util.spec_from_file_location("renodx_shaders", path)
    renodx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renodx)
    folder = os.environ.get("HOOKSHOT_RENODX") or os.path.join(os.path.dirname(work), "renodx")
    print(renodx.NOTICE, flush=True)
    try:
        renodx.prepare(folder, "linux" if LINUX else "windows", say=lambda line: print(line, flush=True))
    except (OSError, ValueError) as e:
        # (Triforce, 11-13: RenoDX is in every build now, so a PC without a connection, or a download that is not the file
        # expected, must not stop the game's build: this one is made without RenoDX and says so; the next build tries again)
        print("RenoDX's shaders could not be fetched or compiled (%s): this build is made without RenoDX's HDR. The next "
              "build tries again." % e, flush=True)
        return None
    return folder


def place_ngx_runtime(out):
    """(NVIDIA DLSS) a game built with NVIDIA's SDK (HOOKSHOT_NGX_SDK, as nx2/build.py takes it) gets DLSS's runtime in its ngx
    folder, where gpu/vk/vk_dlss.cpp looks first: nvngx_dlss.dll on Windows, libnvidia-ngx-dlss.so.<version> on Linux. Never
    NGX's core (_nvngx.dll is the driver's) and nothing beside the exe. Returns the file placed, or None"""
    ngx = ngx_script()
    platform = ngx_platform()
    sdk = os.environ.get("HOOKSHOT_NGX_SDK", "")
    if not sdk or not (os.path.isfile(ngx.library(sdk, platform)) and os.path.isfile(ngx.runtime(sdk, platform))):
        # (a folder built with DLSS before and rebuilt without it loses NVIDIA's runtime too)
        stale = os.path.join(out, "ngx", ngx.runtime_name(platform))
        if os.path.isfile(stale):
            with contextlib.suppress(OSError):
                os.remove(stale)
                os.rmdir(os.path.dirname(stale))
        return None
    dst = ngx.install_runtime(sdk, platform, os.path.join(out, "ngx"))
    print("NVIDIA DLSS: %s (NVIDIA's, under NVIDIA's license: never share this game folder)" % dst, flush=True)
    return dst


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--nup")
    p.add_argument("--romfs")
    p.add_argument("--exefs")
    p.add_argument("--out")
    # (Triforce: its own work folder, not HookshotBuilder's: upstream Hookshot's builder works there too)
    p.add_argument("--work", default=os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                                                  "triforce-build-windows" if CROSS else "triforce-build")   # (the objects apart)
                   if os.name != "nt" else os.path.join(os.environ.get("LOCALAPPDATA", ROOT), "Triforce", "build"))
    # (HOOKSHOT_JOBS: fewer compilers on a PC short of memory; the AppImage's builds pass no --jobs)
    p.add_argument("--jobs", type=int)
    p.add_argument("--language", help="the game's language: a code from LANGUAGES, written to language.txt. Not given: the one the "
                                      "folder has; else the system's with --prepare; else en-US")
    p.add_argument("--check", action="store_true")
    p.add_argument("--game", help="your copy: a .nup file, or a folder with romfs and exefs in it (the same as --nup, or --romfs and --exefs)")
    p.add_argument("--prepare", action="store_true", help="for RecompLauncher: no window, progress lines, --out ~/Games/Hookshot unless given")
    p.add_argument("--update", help="a game folder built before: built again from the game files it keeps (the game's update offer)")
    p.add_argument("--no-prepare-shaders", action="store_true",
                   help="leave the shaders' preparation to the game's first start (the builder's \"Prepare shaders now\" unticked)")
    p.add_argument("--log", metavar="FILE", help="also save build output to a UTF-8 file (replaces the file if it exists)")
    # (NVIDIA DLSS, off unless asked: NVIDIA's SDK into HOOKSHOT_NGX_SDK first, under NVIDIA's license. scripts/ngx_sdk.py)
    p.add_argument("--fetch-ngx-sdk", action="store_true", help="download NVIDIA's DLSS SDK into HOOKSHOT_NGX_SDK before the build")
    p.add_argument("--accept-nvidia-license", action="store_true", help="NVIDIA's DLSS SDK license, accepted (with --fetch-ngx-sdk)")
    # (AMD FSR 4, off unless asked: nothing is downloaded. gpu/vk/vk_fsr4.cpp)
    p.add_argument("--fsr", action="store_true", help="build with AMD FSR 4; on Windows AMD's two libraries, and the one for "
                   "its frame generation, are downloaded from AMD's repository and put beside the game (scripts/fsr_sdk.py)")
    p.add_argument("--no-fsr", action="store_true", help="with --update: build without AMD FSR 4 even if the folder had it")
    # (RenoDX's HDR, in every build since 11-13: its shaders and the Slang compiler are downloaded and compiled here.
    # scripts/renodx_shaders.py, gpu/vk/vk_renodx.cpp)
    p.add_argument("--renodx", action="store_true",
                   help="kept for old command lines: every build has RenoDX's HDR now (its shaders and the Slang compiler are downloaded, about 60 MB)")
    p.add_argument("--no-renodx", action="store_true", help="build without RenoDX's HDR: nothing of it is downloaded")
    a = p.parse_args()
    if a.prepare:   # (first: a bad --game below is said as RecompLauncher's "error" line)
        global PREPARE
        PREPARE = True
        a.out = a.out or os.path.join(os.path.expanduser("~"), "Games", "Hookshot")
    if a.game:   # (a path from a launcher: said plainly before any folder is made, not as a traceback halfway in)
        if os.path.isdir(a.game):
            a.romfs, a.exefs = os.path.join(a.game, "romfs"), os.path.join(a.game, "exefs")
            if not (os.path.isdir(a.romfs) and os.path.isdir(a.exefs)):
                fail("The folder %s needs both a romfs and an exefs folder in it." % a.game)
        elif os.path.isfile(a.game):
            a.nup = a.game
        else:
            fail("Your copy of the game was not found: %s" % a.game)
    a.default_work = p.get_default("work")   # (main: the builder's own work folder, stop_stray_compilers)
    return a


def spinning_disk(folder):
    """True on a hard drive, False on an SSD, None when the drive cannot be told (nx2/disk.py)"""
    return _disk.spinning(folder)


def overlap_package_read(jobs, package_stat, out, work, kept, romfs):
    """((Triforce, 11-24) A large first read of a .nup feeds the lift with the game's code while the rest of the package (the
    romfs) is extracted beside it: the lift reads only the code. Not for a package under 1 GiB, a build of one job, a game folder
    that has a copy already, less than 8 GB of memory free (the reader keeps its tables while the lift holds the decoded
    functions) or a work or game folder on a hard drive (both would read and write the one disk). HOOKSHOT_OVERLAP_READ=0: never"""
    if os.environ.get("HOOKSHOT_OVERLAP_READ", "1") == "0":
        return False
    if (jobs is not None and jobs <= 1) or (os.cpu_count() or 1) <= 2 or package_stat.st_size < 1 << 30 \
            or os.path.lexists(kept) or os.path.lexists(romfs):
        return False
    from build import free_mb
    return (free_mb() or 0) >= 8192 and not any(spinning_disk(folder) for folder in (out, work))


def package_identity(st):
    """What says a package is the same file (read twice when its parts are extracted apart)"""
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


@contextlib.contextmanager
def clean_incomplete_unpack(game):
    """An extraction that fails takes its half-written folder with it"""
    try:
        yield
    except (OSError, SystemExit):
        try:
            shutil.rmtree(game)
        except FileNotFoundError:
            pass
        except OSError as e:
            print("Could not remove the incomplete extraction at %s (%s)." % (game, e), flush=True)
        raise


def warn_slow_disk(*folders):
    """A build reads and writes tens of gigabytes, and on a hard drive it takes much longer than on an SSD. Say so, and build
    anyway: the player may have no other folder with the room. Said once, for the first folder on a hard drive."""
    for folder in folders:
        if spinning_disk(folder) is True:
            # (on stderr under --prepare: RecompLauncher reads stdout's progress lines only)
            print("Warning: %s is on a hard drive. An SSD builds the game much faster: build there if you can. "
                  "The build goes ahead on this drive." % folder, file=sys.stderr if PREPARE else sys.stdout, flush=True)
            return


def main(a=None):
    if a is None:
        a = parse_args()
    if a.jobs is not None and a.jobs < 0:
        fail("--jobs must be 1 or more, or 0 for automatic.")
    given = a.jobs or _build_jobs.asked()
    a.jobs = chosen_jobs(a.jobs)
    if given:   # ((Triforce) every step that runs work side by side takes at most this many, not only the compile: nx2/build_jobs.py)
        os.environ["HOOKSHOT_JOBS"] = str(a.jobs)
    os.makedirs(a.work, exist_ok=True)
    no_throttle()
    if os.name == "nt":   # (the PC kept awake while this runs: a build is 45 minutes, and sleep stopped it)
        import ctypes
        ctypes.WinDLL("kernel32").SetThreadExecutionState(0x80000000 | 0x00000001)
    if a.check:
        return check(a, a.work)
    if a.update:
        a.out = a.update
    if not a.out or not (a.update or a.nup or (a.romfs and a.exefs)):
        fail("needs --out, and --nup or --romfs with --exefs")
    out = os.path.abspath(a.out)
    work = os.path.abspath(a.work)
    a.language = build_language(a, out)   # (now: the folder's own language.txt is still the one the player left)
    warn_slow_disk(out, work)   # (a warning, not a stop: a hard drive still builds, only much slower)
    os.makedirs(out, exist_ok=True)
    migrate_names(out)
    # ((Triforce) on Linux what the build needs is checked below, after the DLSS SDK's fetch, which decides between the prebuilt
    # renderer and the compiled one; still before the game is read: check_linux_prerequisites)
    check_cpu()   # (no game read yet: the AppImage on a CPU without AVX2 stops here)
    if not LINUX:
        check_windows_sdk()
    stopped = stop_stray_compilers(work, a.default_work)
    # ((Triforce, 11-22, the performance audit's IO-47) after the stop, so that Windows still replaces a build left running)
    lock_work(work, wait=10 if stopped else 0)
    drop_stale_objects(work)
    if getattr(a, "fetch_ngx_sdk", False):
        fetch_ngx_sdk(a)
        fetch_streamline_sdk(a)   # (DLSS frame generation's files, with the same tick)
    if LINUX:   # ((Triforce) every missing prerequisite at once, before the game is read: check_linux_prerequisites)
        check_windows_sdk(work)
    # (AMD FSR 4: the build's switch for nx2/build.py, and the folder's mark for the next --update)
    if fsr_wanted(a, out):
        os.environ["HOOKSHOT_FSR"] = "1"
        fetch_fsr_runtime(work)   # (AMD's two libraries, for the game folder: place_fsr_runtime at the end)
        write_mark(os.path.join(out, FSR_MARK))
        if os.environ.get("HOOKSHOT_VK_PREBUILT"):   # (the AppImage's back end: built with FSR 4 since 11-20, appimage.sh)
            print("--fsr: this build uses the prebuilt Vulkan back end (HOOKSHOT_VK_PREBUILT), which has AMD FSR 4 built in "
                  "already: the Upscaler row offers it once amd_fidelityfx_upscaler_vk.so is in the game folder", flush=True)
    else:
        os.environ.pop("HOOKSHOT_FSR", None)
        if os.path.isfile(os.path.join(out, FSR_MARK)):
            os.remove(os.path.join(out, FSR_MARK))
    # (RenoDX's HDR: its shaders made first, then the build's switch for nx2/build.py and the folder's mark for the next
    # --update)
    if renodx_wanted(a, out):
        if os.environ.get("HOOKSHOT_VK_PREBUILT"):   # (the AppImage's back end, built without RenoDX)
            print("RenoDX's HDR: this build uses the prebuilt Vulkan back end (HOOKSHOT_VK_PREBUILT), which has no RenoDX: built "
                  "without it", flush=True)
            os.environ.pop("HOOKSHOT_RENODX", None)
        else:
            renodx_folder = prepare_renodx(work)
            if renodx_folder:
                os.environ["HOOKSHOT_RENODX"] = renodx_folder
                write_mark(os.path.join(out, RENODX_MARK))
            else:
                os.environ.pop("HOOKSHOT_RENODX", None)
                if os.path.isfile(os.path.join(out, RENODX_MARK)):
                    os.remove(os.path.join(out, RENODX_MARK))
    else:
        os.environ.pop("HOOKSHOT_RENODX", None)
        if os.path.isfile(os.path.join(out, RENODX_MARK)):
            os.remove(os.path.join(out, RENODX_MARK))
    exefs = os.path.join(work, "exefs")
    romfs = os.path.join(out, "romfs")

    remaining_assets = None   # ((Triforce, 11-24) the romfs still to read beside the lift: overlap_package_read)
    seen_holder = [None]
    say("stage", "read", "Reading your game files")
    clear_folder(exefs)
    kept = os.path.join(out, ".triforce_exefs")   # (the game's code as read, kept in the folder: what an update builds from again)
    if a.update:
        if not os.path.isdir(kept) or not os.path.isdir(romfs):
            fail("This game folder has no copy of the game files to update from: it was built before updates came in. Choose your game files "
                 "in Triforce Setup and build into the same folder once; updates after that work by themselves.")
        check_cache_paths(out, (kept, romfs))
        refuse_packed_romfs(romfs)   # (a folder built from NX2navi's before the check: it never started)
        check_romfs_folder(romfs, "This game folder's copy of the game files (%s)" % romfs)   # ((Triforce, 11-24))
        shutil.copytree(kept, exefs)
        check_modules(exefs)
        stand_in_damaged_files(out, romfs)   # (a folder unpacked by an earlier builder from a 23.3 GB dump)
    elif a.nup:
        # (what an earlier build left is not kept without a reason to trust it: builders before the compressed .nup fix wrote those files as
        # they lay, so a folder they left held broken game data, and the game crashed at start over its empty dictionaries)
        game = os.path.join(out, ".game")
        good = os.path.join(out, ".triforce_romfs")
        check_cache_paths(out, (game, good, kept, romfs))
        # (an update of the builder over the same .nup: nothing to read again, only what the build needs. Issues 21 and 28)
        try:
            st = os.stat(a.nup)
        except OSError as e:
            fail("Could not access your .nup file %s: %s. Check that the file is still there, reconnect its drive if needed, "
                 "or choose the file again in Hookshot Builder." % (a.nup, e))
        stamp = "unpacked by this builder: %s %d" % (os.path.basename(a.nup), st.st_size)
        same = False
        unpacked_seen = None
        if os.path.exists(good) and os.path.isdir(romfs) and os.path.isdir(kept):
            same = read_stamp(good).strip() == stamp
        if same:
            print("the game was read from this .nup before: reading it again is skipped", flush=True)
            shutil.copytree(kept, exefs)
        else:
            shutil.rmtree(game, ignore_errors=True)
            with contextlib.suppress(FileNotFoundError):   # (a new unpack is checked again)
                os.remove(os.path.join(out, ".triforce_romfs_checked"))
            # Keep the last usable cache until the new package has been read and validated.
            staged_exefs = os.path.join(game, "exefs")
            # ((Triforce, 11-24) a large first read: the code first, then the romfs beside the lift (overlap_package_read). The
            # same extractor and the same checks, only in two runs of it; the romfs is in place before the compile starts)
            overlap = overlap_package_read(a.jobs, st, out, work, kept, romfs)
            extract = PY + ["nx2/nup.py", a.nup, "--extract", game]

            def read_assets():
                with clean_incomplete_unpack(game):
                    run(extract + (["--only", "romfs"] if overlap else []))
                    if overlap:
                        if package_identity(os.stat(a.nup)) != package_identity(st):
                            fail("Your .nup file %s changed while it was being read. Start the build again once the file is "
                                 "complete." % a.nup)
                    else:
                        check_modules(staged_exefs)
                        check_supported_build(staged_exefs)
                    if not os.path.isdir(os.path.join(game, "romfs")):
                        fail("The package did not contain a romfs folder.")
                    check_romfs_folder(os.path.join(game, "romfs"), "Your .nup file %s" % a.nup)   # ((Triforce, 11-24))
                    if overlap and (os.path.lexists(romfs) or os.path.lexists(kept)):
                        fail("Another build filled this game folder while its files were being read. Start the build again.")
                if not overlap and os.path.exists(romfs):
                    shutil.rmtree(romfs)
                seen_holder[0] = unpack_seen(game)   # (the .zs files as the unpack saw them: stand_in_damaged_files below)
                shutil.move(os.path.join(game, "romfs"), romfs)
                if not overlap:
                    shutil.move(staged_exefs, exefs)
                shutil.rmtree(game, ignore_errors=True)
                shutil.rmtree(kept, ignore_errors=True)
                shutil.copytree(exefs, kept)
                write_stamp(good, stamp + chr(10))

            if overlap:
                with clean_incomplete_unpack(game):
                    run(extract + ["--only", "exefs"])
                    check_modules(staged_exefs)
                    check_supported_build(staged_exefs)
                    shutil.move(staged_exefs, exefs)
                remaining_assets = read_assets
            else:
                read_assets()
            unpacked_seen = seen_holder[0]
        check_modules(exefs)
        # (also when the .nup was read before: a folder built from a 23.3 GB dump by an earlier builder gets them too)
        if not remaining_assets:
            stand_in_damaged_files(out, romfs, unpacked_seen)
    else:
        check_cache_paths(out, (kept, romfs))
        refuse_packed_romfs(a.romfs)
        check_romfs_folder(a.romfs)   # ((Triforce, 11-24) the game's files, its heap definition among them)
        refuse_dump_links(a.exefs)
        refuse_dump_links(a.romfs)
        shutil.copytree(a.exefs, exefs)   # (unpacked in place: the user's copy stays as it is)
        run(PY + ["nx2/unpack.py", exefs])
        link_or_copy(a.romfs, romfs)
        shutil.rmtree(kept, ignore_errors=True)
        shutil.copytree(exefs, kept)
    check_supported_build(exefs)
    # (Triforce) code mods: the .ips and .pchtxt patches of the game folder's mods, applied to this copy of the game's code, which
    # the lift reads and whose files its key hashes: never to the player's files nor to the copy kept for updates (kept, above).
    # A patch added, taken away, switched off or edited so changes the key and the game is translated again (nx2/code_mods.py)
    code_patches = _code_mods.build_step(exefs, out, say=lambda line: print(line, flush=True))

    # (made once on the development PC: lists of addresses and counts, no game code)
    # ((Triforce, 11-21, the performance audit's LIFT-10) and the renderer's play profile, triforce_vk.profdata)
    for name in ("hot_funcs.txt", "hot_order.txt", "hookshot_pieces.prof", "triforce_vk.profdata", "hookshot.res"):
        src = os.path.join(ROOT, "work", name)
        dst = os.path.join(work, name)
        # (copied only when it differs: a compiler still ending from a cancelled build keeps the profile mapped, WinError 1224)
        if os.path.exists(src) and not (os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False)):
            copy_writable(src, dst)
    os.makedirs(os.path.join(work, "image"), exist_ok=True)
    src = os.path.join(ROOT, "work", "image", "chunks.txt")   # (where the lifted code's files begin: addresses)
    chunks_copied = os.path.exists(src)   # ((Triforce) an input then; otherwise the lift writes it: key_after_lift)
    if chunks_copied:
        copy_writable(src, os.path.join(work, "image", "chunks.txt"))
    env = {"OOT_WORK": work, "OOT_EXEFS": exefs, "OOT_ROMFS": romfs, "OOT_DUMP": out, "RX_RELEASE": "1", "A64_HOT_CHUNK": "1"}
    if os.path.exists(os.path.join(work, "hot_funcs.txt")):
        env["A64_HOT_FUNCS"] = os.path.join(work, "hot_funcs.txt")
    if os.path.exists(os.path.join(work, "hookshot_pieces.prof")) and profile_readable(os.path.join(work, "hookshot_pieces.prof")):
        env["RX_PGO"] = os.path.join(work, "hookshot_pieces.prof")
    # ((Triforce, 11-21, LIFT-10) the renderer's own code with the shipped profile, unless RX_VK_PGO says what to do (gen, a
    # file, 0) or this compiler cannot read it: nx2/build.py vk_pgo_flags)
    vk_profile = os.path.join(work, "triforce_vk.profdata")
    if "RX_VK_PGO" not in os.environ and os.path.exists(vk_profile) and profile_readable(vk_profile):
        env["RX_VK_PGO"] = vk_profile

    def start_prompts():
        prompts = Prompts(romfs, out, work)   # (drawn beside the lift and the compile: finish() below)
        atexit.register(prompts.stop)   # (a build that stops for any reason takes its drawing with it)
        return prompts
    # ((Triforce, 11-24) with the romfs still being read beside the lift, the prompts, which read it, start once it is in place)
    prompts = None if remaining_assets else start_prompts()

    say("stage", "lift", "Translating the game to PC code")
    # (the same game, tools and settings as the lift before: its C is what this lift would write, and nothing recompiles from it. A
    # rebuild after a change to host/ alone skips the minutes of the lift)
    key = lift_key(exefs, work, env)
    gen_dir = os.path.join(work, "sa", "gen")
    # (issue 1197: a lifted file cut short, "g_module_b" where g_module_base was, stopped the compile at every try. Before the compile
    # every one must end as a function does: one that does not is translated again, once; a second time says what to check)
    # ((Triforce) and hold no zero byte, which the lift never writes: lifted_zero_bytes, the same once-again rule)
    kept_lift = []   # ((Triforce) build.py's --kept-lift: the lift skipped, its objects by the kept list: keep_translation)

    def translate():   # ((Triforce) also the compile's, unless HOOKSHOT_LIFT_RECHECK=0: lift_changed below)
        nonlocal key, gen_dir
        for _ in range(2):
            checked = False   # (this translation's C was looked through for zero bytes before: its key's "zero-checked")
            compiled_kept = False   # ((Triforce) the lifted C let go after the last build, its objects kept: kept_before)
            if lifted_before(work, key):   # (never on the second pass: its key was taken away below)
                with open(os.path.join(work, "sa", "gen", LIFT_KEY)) as f:
                    checked = f.read().split()[-1] == "zero-checked"
                print("the game was translated with these tools before: translating it again is skipped", flush=True)
            elif kept_before(work, key):   # ((Triforce) a player's update with the same tools: keep_translation)
                compiled_kept = True
                print("the game was translated with these tools before (its compiled code kept): translating it again is skipped",
                      flush=True)
                kept_lift[:] = ["--kept-lift", os.path.join(gen_dir, KEPT_LIST)]
            else:
                kept_lift.clear()
                for name in (KEPT_LIST, KEPT_LIST + ".new"):   # ((Triforce) the list of the lift before: it names that lift's objects)
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(os.path.join(gen_dir, name))
                key_unchunked = lift_key(exefs, work, env, chunks=False)   # ((Triforce) the inputs but chunks.txt: key_after_lift)
                key_file = os.path.join(work, "sa", "gen", LIFT_KEY)
                if os.path.exists(key_file):
                    os.remove(key_file)   # (a lift stopped halfway leaves no key behind)
                # (hookshot) the lifted C of an earlier lift goes first: a file that lift made and this one does not (another builder's naming,
                # a chunk cut short) was compiled with the new ones, undefined or doubly defined game functions at the link (issue 1176).
                # The objects stay cached by their contents, so a file this lift writes the same is not compiled again
                gen_dir = os.path.join(work, "sa", "gen")
                if os.path.isdir(gen_dir):
                    for f in os.listdir(gen_dir):
                        if f.startswith("code_") and (f.endswith(".c") or f.endswith(".c.whole") or f.endswith(".part")):
                            try:
                                os.remove(os.path.join(gen_dir, f))
                            except FileNotFoundError:
                                pass   # (already gone: another cleanup removed it)
                            except OSError as e:
                                fail("Could not remove earlier translated file %s: %s. The new translation has not started." %
                                     (os.path.join(gen_dir, f), e))
                # ((Triforce, 11-24) HOOKSHOT_LIFT_STORE: the lift another work folder made from the same inputs, nx2/lift_store.py.
                # Its key is the one taken before the lift, from what this one starts from, as that folder's was; the restored
                # folder gets that lift's chunk boundaries and hot pieces too, so its own key is taken again after it)
                lifts = _lift_store.root()
                share = lift_share_key(exefs, work, out, env) if lifts else None
                if share and _lift_store.restore(lifts, share, work, bad=lambda: lifted_cut_short(gen_dir)):
                    print("the game was translated with these tools in another work folder: its translation is copied (%s)" %
                          os.path.join(lifts, share), flush=True)
                    key = lift_key(exefs, work, env)
                    write_lift_key(work, key)
                else:
                    early = EarlyCompile(work, env, a.jobs)   # (what needs no lifted code is compiled meanwhile)
                    atexit.register(early.stop)
                    run(PY + ["nx2/lift.py", "--standalone", "--write", "--exefs", exefs, "--work", work], env,
                        on_line=lift_progress())   # ((Triforce, 11-24) the bar moves as the lift's steps end)
                    if os.path.isfile(os.path.join(work, "sa", "gen", "code_hot.c")):
                        run(PY + ["nx2/split_hot.py", os.path.join(work, "sa", "gen")], env)   # (eight files side by side: ~6 minutes, not 79)
                    early.finish()
                    # (kept for other work folders only when nothing it read but chunks.txt changed while it ran, and its C is whole)
                    if share and lift_key(exefs, work, env, chunks=False) == key_unchunked and not lifted_cut_short(gen_dir):
                        _lift_store.save(lifts, share, work)
                    key = key_after_lift(exefs, work, env, key, key_unchunked, chunks_copied)   # ((Triforce) the chunks.txt it wrote in it)
                    write_lift_key(work, key)
            cut, zero = lifted_cut_short(gen_dir), [] if checked or compiled_kept else lifted_zero_bytes(gen_dir)
            if not cut and not zero:
                if not checked and not compiled_kept:   # (the key and its file fingerprint vouch for this check, on the next build too)
                    with open(os.path.join(gen_dir, LIFT_KEY), "a") as f:
                        f.write("zero-checked\n")
                break
            key_file = os.path.join(gen_dir, LIFT_KEY)
            if os.path.exists(key_file):
                os.remove(key_file)
            if zero:
                print("translated files with a zero byte, which the translation never writes (%s): the game is translated again" %
                      ", ".join(zero[:6]), flush=True)
            else:
                print("translated files cut short (%s): the game is translated again" % ", ".join(cut[:6]), flush=True)
        else:
            if zero:
                files = [f for f in os.listdir(gen_dir) if f.startswith("code_") and f.endswith(".c")]
                fail("The translated game came out damaged twice: %d of %d files have a zero byte (%s), which the translation never "
                     "writes, so this PC's memory or the drive with %s changes what is written. Turn off any memory overclock (XMP, "
                     "EXPO), test the memory, check the drive for errors, then build again." %
                     (len(zero), len(files), ", ".join(zero[:6]), work))
            fail("The translated game came out cut short twice (%s). Check that the drive with %s has free space, and that no antivirus "
                 "and no second Triforce Setup is working in that folder, then update again." % (", ".join(cut[:6]), work))

    reading = None
    if remaining_assets:   # ((Triforce, 11-24) the romfs read beside the lift: overlap_package_read)
        print("the rest of the game's files are read beside the translation", flush=True)
        import concurrent.futures
        reader = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        reading = reader.submit(remaining_assets)
        reader.shutdown(wait=False)   # (its thread ends with the read; a build that fails in the lift waits for it as it leaves)

    translate()

    if reading is not None:   # (the romfs in place, its damaged files stood in for, before the compile and the prompts)
        reading.result()
        stand_in_damaged_files(out, romfs, seen_holder[0])
        prompts = start_prompts()

    # (the compile's timer: build.py reads the record of the earlier builds on this PC, says which files this run really
    # rebuilds and how long the rest will take, and reports each module's seconds; they go into the record below)
    env["HOOKSHOT_TIMES"] = times_path(work)
    run_files, plan = {}, [0, 0]
    say("stage", "compile", "Compiling")
    compile_started = time.time()
    done = {"n": 0.0, "of": 1.0}
    # (the progress by each file's share of the compile time, not by the count of files: the build takes the biggest first, and
    # the 515 small files were 89% of the count and 10% of the time, so 45 of 579 files read as 8% when it was ~45%, and the
    # builder said "452 minutes left" an hour from the end. Seconds per MB measured on a full build: the eight hot files (-O2,
    # the play profile) 23.5, the other game files 3.4, the rest ~1.3 s each)
    gen = os.path.join(work, "sa", "gen")

    def cost(name, mb=None):
        if mb is None:
            try:
                mb = os.path.getsize(os.path.join(gen, name)) / (1 << 20)
            except OSError:
                mb = 0
        return 23.5 * mb if name.startswith("code_hot") else 3.4 * mb + 1 if name.startswith("code_") else 1.3

    said = []   # (build.py's lines about how its compile and its links went: compile_alone_failed)

    def compiled(line):
        # ((Triforce, 11-22, LIFT-27) and which files failed, "FAILED <file> (...": failed_only_own_sources)
        if line.startswith("compiled in ") or "link FAILED" in line or line.startswith("FAILED "):
            said.append(line)
        m = re.match(r"(\d+) files, ", line)
        if m:
            try:
                ours = [f for f in os.listdir(gen) if f.startswith("code_") and f.endswith(".c")]
            except OSError:
                ours = []
            done["of"] = sum(cost(f) for f in ours) + max(0, int(m.group(1)) - len(ours)) * 1.3
        else:
            m = re.match(r"\s+(\S+)\s+(\d+) MB\s+\d+s", line)
            if m:
                done["n"] += cost(m.group(1))
                say("progress", "%.3f" % min(1.0, done["n"] / max(1.0, done["of"])))
        if line.startswith("@@file "):
            parts = line.split(" ")
            if len(parts) == 4 and parts[3] in ("new", "again"):
                try:
                    seconds = float(parts[2])
                except ValueError:
                    return
                if seconds > 0:   # (a module a cache held is not a measurement of this PC)
                    run_files[parts[1]] = seconds
        elif line.startswith("@@plan "):
            parts = line.split(" ")
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                plan[:] = [int(parts[1]), int(parts[2])]

    # ((Triforce, on by default; HOOKSHOT_LIFT_RECHECK=0 turns it off) a compile that refuses translated files: they are made again, and
    # compiled again when they come out different (changed_lift). Players' builds stopped on one-character typos in the
    # translated C, in other files at each try ("uint65_t", "_src[4]$_dst[4]"): a bit the PC's memory changed, which the
    # compiler's error alone made look like the translator's. Not when the lift key changed (another translator, other settings)
    failed, errors, in_failure, changed = [], [], [], []

    def compile_line(line):
        m = re.match(r"FAILED (\S+) \(", line)
        if m:   # (build.py's last word on a file, its compiler's output on the lines after it)
            failed.append(m.group(1))
            errors.append(False)
            in_failure[:] = [True]
        elif line.startswith("@@") or re.match(r"\s+\S+\s+\d+ MB\s+\d+s", line) or line.startswith("compiled in "):
            in_failure.clear()
        elif in_failure and COMPILE_ERROR.match(line):
            errors[-1] = True
        compiled(line)

    def lift_changed():
        if os.environ.get("HOOKSHOT_LIFT_RECHECK") == "0" or not refused_lift(gen_dir, failed, errors) or \
                lift_key(exefs, work, env) != key:
            return False
        print("the compiler refused translated files (%s): the game is translated again, to see whether they come out the same "
              "(HOOKSHOT_LIFT_RECHECK=0: not)" % ", ".join(sorted(failed)[:6]), flush=True)

        def translate_again():
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(gen_dir, LIFT_KEY))
            say("stage", "lift", "Translating the game to PC code")
            translate()

        names, of = changed_lift(gen_dir, translate_again)
        say("stage", "compile", "Compiling")
        if not names:
            print("they came out the same", flush=True)
            return False
        changed.append("%d of %d files (%s%s)" % (len(names), of, ", ".join(names[:6]), ", ..." if len(names) > 6 else ""))
        print("translating the game again gave other contents for %s: this PC's memory, processor or drive changes what the build "
              "writes. They are compiled again. Turn off any overclock (XMP, EXPO) and test the memory: a game built with a changed "
              "file can fail in any way" % changed[0], flush=True)
        failed.clear(), errors.clear(), in_failure.clear(), said.clear()
        return True

    def changed_twice():
        if refused_lift(gen_dir, failed, errors):
            fail("The compiler refused translated files twice, and translating the game again gave other contents for %s: this "
                 "PC's memory, its processor or the drive with %s changes what the build writes. Turn off any overclock (XMP, "
                 "EXPO), test the memory, check the drive for errors, then build again." % (changed[0], work))
        return False

    try:
        if run(PY + ["nx2/build.py", "--standalone", "--jobs", str(a.jobs)] + kept_lift, env, compile_line,
               allow=(KEPT_STALE,) if kept_lift else (), again=lift_changed) == KEPT_STALE:
            # ((Triforce) the translation kept from the last build no longer fits: an object of it gone, other flags or headers.
            # Nothing was compiled: the game is translated, then compiled, as when nothing was kept)
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(gen_dir, LIFT_KEY))
            say("stage", "lift", "Translating the game to PC code")
            translate()
            say("stage", "compile", "Compiling")
            run_files.clear()
            done["n"] = 0.0
            run(PY + ["nx2/build.py", "--standalone", "--jobs", str(a.jobs)], env, compile_line, again=lift_changed)
        if changed:   # (what compiled is cached by its contents: the files that came out different, and those refused, compile)
            done["n"] = 0.0
            run(PY + ["nx2/build.py", "--standalone", "--jobs", str(a.jobs)], env, compile_line, again=changed_twice)
    except SystemExit:
        # (hookshot) a compile or link that failed forgets the lift: the next build translates the game again. A lifted file cut short
        # (an antivirus, a full disk, a stopped run: "g_module_b" for g_module_base, issue 1197) or lifted C another builder left (20
        # undefined game functions at the link, issue 1176) otherwise failed the same way at every try, the key still matching
        # ((Triforce, 11-22, the performance audit's LIFT-27, after Source A's) but for a compile that failed only in the
        # program's own sources, once: the translated game is not what failed. keep_lift_after_failure; HOOKSHOT_KEEP_LIFT=0:
        # forgotten after every failed build, as before)
        # ((Triforce, 11-24, after Source A's) a failure after the game itself linked (the renderer's link, its symbol check):
        # the translation and the game's objects linked, so they are kept; only the renderer's objects go, in case a cached
        # one is what failed (an extern written inside an anonymous namespace in gpu/vk cost a whole lift and compile)
        if game_linked_first(said):
            forget_renderer_objects(work)
            print("the build failed after the game linked, in the renderer: the next one keeps the translation and the game's "
                  "objects, and compiles only the renderer again", flush=True)
            prompts.stop()
            raise
        lift_kept = keep_lift_after_failure(said, work)
        key_file = os.path.join(work, "sa", "gen", LIFT_KEY)
        if os.path.exists(key_file) and not lift_kept:
            os.remove(key_file)
        # (and its compiled objects go too: a cached runtime object from another version linked with every object "compiled in 0s"
        # and a64_dirty, a64_icall, a64_lookup, recomp_cntpct undefined, at every try (issue 1197, Linux, v2.0.10))
        # (Triforce: but not when the compile alone failed, before any link: compile_alone_failed)
        if lift_kept:
            print("the build failed in its compile, in the program's own files only: the translated game and the files that "
                  "did compile are kept, and the next build compiles only the rest (a second failure like it translates the "
                  "game again)", flush=True)
        elif compile_alone_failed(said):
            print("the build failed in its compile: the files that did compile are kept, and the next build translates the game "
                  "again and compiles only the rest", flush=True)
        else:
            # ((Triforce) HOOKSHOT_OBJ_STORE: the objects this link was made from go from the store as well, or the next try takes
            # them from there)
            _object_store.forget(_object_store.folder(work), object_stamps(os.path.join(work, "sa", "build", "obj")))
            for sub in (os.path.join(work, "objcache"), os.path.join(work, "sa", "build", "obj")):
                shutil.rmtree(sub, ignore_errors=True)
            print("the build failed: the next one translates and compiles the game again (nothing of this one is reused)", flush=True)
        prompts.stop()
        raise
    with contextlib.suppress(OSError):   # ((Triforce, 11-22, LIFT-27) a build that compiled: no failure in a row any more)
        os.remove(os.path.join(work, "sa", LIFT_KEPT_ONCE))
    compile_seconds = time.time() - compile_started

    say("stage", "finish", "Putting the game folder together")
    built = os.path.join(work, "sa", "build")
    # (the new files are copied in beside the old ones as <name>.new and swapped in only once all are complete: a build stopped while
    # copying, or a full disk, left a half-written 460 MB Triforce.exe and no game to play. The old game stays playable until the swap)
    # (Windows) Triforce.exe in the folder is the game's launcher: the builder's small setup, which opens the installed builder as a
    # launcher for this folder (Play, and Update left of it when a newer release is out: builder/setup/setup.c launch mode), or starts
    # the game when no builder is installed. The game and its DLLs are in bin\; its files (image.bin, romfs, saves, settings, caches)
    # stay in the folder (host/hos_paths.h). Without the setup (a development build) the game stays Triforce.exe in the folder
    staged = []
    # (Linux) the same launcher, as a script, when this is a packaged builder (the AppImage sets HOOKSHOT_TOOLS). A source
    # checkout leaves hookshot in the folder, as a development build on Windows does when the setup exe is not beside it
    launcher = os.path.join(os.path.dirname(os.path.abspath(ROOT)), "HookshotBuilder-Setup.exe")
    if LINUX:
        script = os.path.join(ROOT, "builder", "linux", "hookshot-folder")
        launcher = script if os.environ.get("HOOKSHOT_TOOLS") and os.path.isfile(script) else None
    else:
        launcher = launcher if os.path.isfile(launcher) else None
    game_dir = os.path.join(out, "bin") if launcher else out
    os.makedirs(game_dir, exist_ok=True)
    ffmpeg_dlls = [] if LINUX else sorted(f for f in os.listdir(built) if f.endswith(".dll") and f.startswith(("av", "sw")))
    for n in BESIDE + ffmpeg_dlls:
        src = os.path.join(built, n)
        if os.path.exists(src):
            staged.append((src, os.path.join(game_dir, n)))
    staged.append((os.path.join(work, "sa", "image", "image.bin"), os.path.join(out, "image.bin")))
    if launcher:
        staged.append((launcher, os.path.join(out, BESIDE[0])))
    # ((Triforce, 11-22, the performance audit's IO-45) a file the folder already has from the same source is passed
    # over: INSTALLED_NOTE above. What is left in staged is copied and swapped as before)
    copy_all = os.environ.get("HOOKSHOT_FINISH_COPY_ALL", "0") not in ("", "0")
    installed_note = {} if copy_all else read_installed(out)
    installed_now, wanted, there = {}, staged, []
    staged = []
    for src, dst in wanted:
        digest = None if copy_all else file_sha1(src)
        if installed_same(installed_note, out, dst, digest):
            installed_now[installed_name(out, dst)] = installed_note[installed_name(out, dst)]
            there.append(installed_name(out, dst))
            with contextlib.suppress(OSError):   # (a <name>.new an interrupted build left: gone when it can go, never unlocked)
                os.remove(dst + ".new")
        else:
            staged.append((src, dst))
            installed_now[installed_name(out, dst)] = {"sha1": digest, "stat": None}
    if there:
        print("the game folder has %d of this build's %d files already (%s): not copied again"
              % (len(there), len(wanted), ", ".join(there)), flush=True)
    for src, dst in staged:
        try:
            if os.path.exists(dst + ".new"):
                os.remove(dst + ".new")
            shutil.copy2(src, dst + ".new")
        except PermissionError:
            fail("Could not stage the new build at %s. Check that %s is readable and the staged file and output folder are writable, "
                 "close any program using that file, then retry. No installed files were replaced; the compiled source is still available."
                 % (dst + ".new", src))
    if not LINUX and staged:   # ((Triforce) a copy of this game still running holds its exe: one with no window is a leftover, ended; else named)
        shown = end_stale_games([game_dir, out])
        if shown:
            fail("Triforce is still running from this folder (%s). Close it, then retry. No installed files were replaced."
                 % ", ".join("process %d" % pid for pid in shown))
    for src, dst in staged:
        try:
            os.replace(dst + ".new", dst)   # (linux: a running copy keeps its own file; windows: a running exe cannot be replaced)
        except PermissionError:
            fail("Could not replace %s. Close any running copy of Triforce and check that the file and folder are writable, then retry. "
                 "Staged replacements remain beside the installed files; the compiled source remains at %s." % (dst, src))
    # ((Triforce, 11-22, IO-45) noted only now, with every swap done: each file just installed as it is in the folder)
    if copy_all:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(out, INSTALLED_NOTE))
    else:
        for src, dst in staged:
            installed_now[installed_name(out, dst)]["stat"] = installed_stat(dst)
        installed_now = {k: v for k, v in installed_now.items() if v["sha1"] and v["stat"]}
        if installed_now != installed_note:   # (nothing installed and nothing gone: the note is the one there)
            write_installed(out, installed_now)
    if launcher:   # (a folder built before the launcher: its libraries left the folder for bin\; hookshot is the launcher now)
        stale = [] if LINUX else sorted(f for f in os.listdir(out) if f.endswith(".dll") and f.startswith(("av", "sw")))
        for n in BESIDE[1:] + stale + ["Triforce.map", "hookshot.map", "hookshot-game.exe"]:
            try:
                if os.path.isfile(os.path.join(out, n)):
                    os.remove(os.path.join(out, n))
            except OSError:
                pass
    drop_old_program(out)
    place_ngx_runtime(out)
    place_dlssg_runtime(out)
    place_fsr_runtime(out, work, os.environ.get("HOOKSHOT_FSR") == "1")
    # every shader of the game, for its first start to translate (gpu/vk/vk_shader.cpp seed_open). Without it the game still runs, compiling them
    # as it meets them: not worth stopping a finished build for
    # ((Triforce) made again only when the game's shader files, the census or the list itself changed: SHADER_LIST_NOTE)
    if shader_list_current(work, romfs, os.path.join(out, "triforce_shaders.bin")):
        print("the shader list is the one the last build made from the same files: not made again", flush=True)
    elif run(shader_census_cmd(romfs, os.path.join(out, "triforce_shaders.bin")), check=False, output=sys.stderr):
        print("the shader list was not made: the game will compile its shaders as it plays", flush=True)
    else:
        note_shader_list(work, romfs, os.path.join(out, "triforce_shaders.bin"))
    # (hookshot) the button prompts of other controllers (host/prompts.c): the game's icon font redrawn per controller, with fontTools.
    # Without it the game shows its own icons. (Triforce: drawn since the game files were read, or kept: class Prompts)
    prompts.finish()
    vr_texts(out, romfs)   # ((Triforce VR) VR's texts, from the prompts' text archive: after them
    icon = os.path.join(ROOT, "assets", "triforce.png")
    if LINUX and os.path.exists(icon):   # (the window's icon: host/posix/display_sdl.c)
        copy_writable(icon, os.path.join(out, "triforce.png"))   # (a second build overwrites the first's)
    seed_pipelines(out)
    ship_state_list(out)
    ship_triforce_assets(out)
    language = os.path.join(out, "language.txt")   # (the same text as host/nn_applet.c writes)
    with open(language, "w", encoding="utf-8", newline="\n") as f:
        f.write("# The game's language. Change the line below to one of the codes listed here, save, and start the game again.\n\n%s\n\n" % a.language)
        f.writelines("# %-8s %s\n" % l for l in LANGUAGES)
    # (what the game's update offer reads, host/hos_update.c: which release these tools are, and where the builder that made the folder is)
    tag = ""
    for version_name in ("version.txt", "VERSION"):   # (VERSION: the AppImage, which has no version.txt)
        version = os.path.join(ROOT, version_name)
        if os.path.isfile(version):
            with open(version, encoding="utf-8") as f:
                tag = f.readline().strip()
            if tag:
                break
    if tag:
        with open(os.path.join(out, "triforce_version.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("version=%s\n" % tag)
            if os.environ.get("HOOKSHOT_BUILDER_EXE"):
                f.write("builder=%s\n" % os.environ["HOOKSHOT_BUILDER_EXE"])
                # (the Python builder: builder is its pythonw.exe, and these the arguments before --update, host/hos_update.c)
                if os.environ.get("HOOKSHOT_BUILDER_ARGS"):
                    f.write("builder_args=%s\n" % os.environ["HOOKSHOT_BUILDER_ARGS"])
    # (Triforce) what code patches this game is built with, for the next build and for the game's start (host/mods.c)
    _code_mods.write_record(out, code_patches)
    # (the game's code as read: written again by every build, so not left behind in the work folder. The translated code (sa\gen)
    # and the compiled objects stay: the next build skips the lift when nothing it reads changed (#428) and compiles only what
    # changed; the builder says how much stays and lets it go. Kept in a development checkout)
    if os.path.normcase(work) != os.path.normcase(os.path.abspath(os.path.join(ROOT, "work"))):
        shutil.rmtree(exefs, ignore_errors=True)
        # (players asked for the space back: the translated code (1.5 GB) goes once the game is ready, on Windows and Linux alike. The
        # compiled objects of this build stay (~1 GB; those of earlier builds go): without them every update compiled all ~600 files
        # again, an hour and more on many PCs (issue 1287, "updates rebuild everything"), where the update changes a few. The next
        # update translates again (minutes) and compiles only what changed. The builder's Free up space lets them go too.
        # HOOKSHOT_KEEP_BUILD_FILES=1 keeps everything, as before)
        # ((Triforce) the rest of the lift (~130 MB: its headers, runtime tables and image) stays too, with build.py's list of the
        # lifted files' object keys: an update with the same tools then skips the lift (keep_translation, kept_before))
        if os.environ.get("HOOKSHOT_KEEP_BUILD_FILES", "0") in ("", "0"):
            kept = prune_object_cache(work)
            lift_kept = keep_translation(work, key)
            for sub in ("probe",) if lift_kept is not None else ("sa", "probe"):
                shutil.rmtree(os.path.join(work, sub), ignore_errors=True)
            print("the build files in %s were deleted but this build's compiled objects (%d MB)%s, so that an update compiles only "
                  "what changed (HOOKSHOT_KEEP_BUILD_FILES=1 keeps all)" % (
                      work, kept >> 20, "" if lift_kept is None else " and the translation's other files (%d MB)" % (lift_kept >> 20)),
                  flush=True)
    # ((Triforce) HOOKSHOT_OBJ_STORE: the store's own clean-up, after the folder's; nx2/object_store.py prune)
    removed, freed = _object_store.prune()
    if removed:
        print("object store: %d objects no work folder used lately let go (%d MB)" % (removed, freed >> 20), flush=True)
    total_seconds = time.time() - STARTED
    previous = record_times(work, run_files, compile_seconds, total_seconds, modules=plan[1],
                            kind="update" if a.update else "build")
    print("the build took %s, compiled in %s%s" % (clock(total_seconds), clock(compile_seconds),
                                                    "" if previous is None else " (the last one %s)" % clock(previous)), flush=True)
    say("times", "%.0f" % total_seconds, "%.0f" % compile_seconds, "-1" if previous is None else "%.0f" % previous)
    # (where the time went, for a report of a slow build and for measuring a change to the build itself)
    print("the build's steps: %s" % stage_times(time.time()), flush=True)
    # (after the times: they stay comparable from build to build, without a GPU's minutes that can be switched off)
    skipped = prepare_skipped(a)
    if skipped:
        not_prepared(skipped)
    else:
        prepare_shaders([os.path.join(game_dir, BESIDE[0]), "--prepare-shaders"], out)
    say("done", out)


def cli():
    # (an error nobody foresaw is said in the window, not as "The game files could not be read" or "something went wrong" with the reason
    # only in a console nobody sees: the traceback's last lines go to Show details, its last line to the message)
    with contextlib.ExitStack() as stack:
        try:
            for stream in (sys.stdout, sys.stderr):
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")   # (-I ignores PYTHONIOENCODING: a path's letters crashed a print)
                except (AttributeError, ValueError):
                    pass
            a = parse_args()
            stack.enter_context(build_log(a.log))
            main(a)
        except SystemExit as e:
            # (fail() exits with a number: it already said @@error. A library's SystemExit (toolchain.need) carries its message as
            # text, which would reach only stderr; the builder app does not show that, and said "The game files could not be read")
            if isinstance(e.code, str):
                say("error", e.code)
                sys.exit(1)
            raise
        except BaseException as e:
            import traceback
            print(traceback.format_exc(), flush=True)
            if drive_error(e):   # ((Triforce) not the tools' error to be sent in: the drive's, with its repair)
                say("error", drive_error(e))
                sys.exit(1)
            say("error", "The builder stopped on an error it did not expect: %s: %s. Please send the text under Show details to the "
                "Triforce issues page (github.com/ruckus7382sfgsgdf/CBeta0.2/issues)." % (type(e).__name__, str(e)[:300]))
            sys.exit(1)


if __name__ == "__main__":
    cli()
