"""(Triforce) The local crash and unclean-end records (host/hos_crash_record.c), beside the crash report in triforce_log.txt.

    python -I -B tests/test_crash_record.py [--cc gcc]

Everywhere: the source is read for where the record is written and where a run's marker is removed (every clean end), and
that Triforce's own crash report (host/mkw_glue.c report_crash, host/hos_thread.c hos_fatal) is still whole and still runs
after the record. On Windows a fixture (tests/crash_record_test.c) runs the real writer: a crash through an exception
filter, a fatal end, a device lost, a run killed with no clean end (an unclean-end record at the next start, with the quit
the player asked for), a clean end and a return (nothing left), the 15 records kept, the labels' privacy, and the
minidump off unless asked for. Nothing is sent anywhere.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"


def block(text, marker):
    assert text.count(marker) == 1, marker
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def source_contract():
    glue = read("host/mkw_glue.c")
    report = block(glue, "static LONG WINAPI report_crash(")
    # (Triforce's order: one ending, the other threads' state first, then the record, then the CRASH lines as before)
    assert report.index("hos_ending_enter()") < report.index("hos_crash_threads_begin();") < report.index(
        "record_exception(info);") < report.index("GetModuleHandleExA(")
    for line in ('CRASH: exception %#lx (%s %#llx, guest %#llx) at %s+%#llx', 'CRASH: host backtrace:',
                 'CRASH: thread %s, sp %#llx', 'CRASH: guest backtrace: lr %#llx', 'hos_crash_threads_end();'):
        assert line in report, line
    assert "if (code == 0xC0000374 || code == 0xC0000409) report_crash(info);" in glue
    assert "SetUnhandledExceptionFilter(report_crash);" in glue
    threads = read("host/hos_thread.c")
    fatal = block(threads, "void hos_fatal(")
    assert fatal.index("hos_ending_enter()") < fatal.index("hos_crash_threads_begin();") < fatal.index(
        'hos_crash_record_fatal(c ? c->x : NULL, "hos_fatal");') < fatal.index("fprintf(stderr,")
    log = block(threads, "static void hos_vlog(int level, const char *fmt, va_list ap) {")
    assert log.index("HOS_REPORT_DEVICE_LOST_PREFIX") < log.index("hos_log_redact(")
    assert 'strstr(buf, "VK_ERROR_DEVICE_LOST") ? "device lost" : "Vulkan fatal"' in log
    # (the renderer's lines the prefixes stand for)
    assert 'logf("vk: device lost: reading %s"' in read("gpu/vk/vk_draw.cpp")
    assert 'logf("vk: FATAL: %s", why);' in read("gpu/vk/vk_replay.cpp")
    writer = block(read("host/hos_crash_record.c"), "int hos_crash_record_write(")
    assert "hos_log(" not in writer and "malloc" not in writer and "printf" not in writer
    main = read("host/hos_main.c")
    # (the run before's marker read before its log moves to .1; the run's id right after the version line)
    prepare = main.index("hos_crash_record_prepare(path);")
    rotate = main.index('memcpy(to, path, n), snprintf(to + n, 32, "triforce_log.%d.txt", k);')
    assert prepare < rotate
    assert "} else hos_crash_record_prepare(NULL);" in main
    banner = main.index('hos_log("triforce %s", HOOKSHOT_VERSION);')
    assert banner < main.index('hos_log("run_id: %s", hos_report_run_id());') < banner + 600
    # (every clean end removes the marker: ExitProcess and quick_exit run no atexit)
    for rel, before in (("host/hos_relaunch.c", "if (again) relaunch();"), ("host/hos_svc.c", "ExitProcess(0);"),
                        ("host/hos_update.c", "ExitProcess(0);"), ("host/display.c", "ExitProcess(1);"),
                        ("host/posix/display_sdl.c", "ExitProcess(1);")):
        text = read(rel)
        at = text.index("hos_crash_clean_end();")
        assert 0 < text.index(before, at) - at < 200, rel
    assert main.count("hos_crash_clean_end();") >= 2   # (nnMain's return, Linux's game thread)
    assert "hos_crash_quit_asked();" in block(read("host/rx_backend.c"), "void rx_close_asked(void)")
    posix = read("host/posix/win32_posix.c")
    assert "rec.ExceptionInformation[13] = (ULONG_PTR)sig;" in posix and "SIGABRT};" in posix
    record = read("host/hos_crash_record.c")
    assert 'getenv("HOS_CRASH_MINIDUMP")' in record   # (off unless asked for)
    for word in ("http", "curl", "WinHttp", "InternetOpen", "connect("):
        assert word not in record, word
    print("PASS: the record is written first, Triforce's crash report stays whole, and every clean end removes the marker")


def fixture_source():
    glue = read("host/mkw_glue.c")
    cut = block(glue, "static void record_exception(") + "\n" + block(glue, "void hos_crash_record_fatal(")
    return read("tests/crash_record_test.c").replace("/* RECORD_EXCEPTION */", cut)


def pending(game):
    p = Path(game) / "crash-reports" / "pending"
    return sorted(x.name for x in p.iterdir()) if p.is_dir() else []


def running(game):
    p = Path(game) / "crash-reports" / "running"
    return sorted(x.name for x in p.iterdir()) if p.is_dir() else []


def text_of(game, name):
    return (Path(game) / "crash-reports" / "pending" / name).read_text(encoding="utf-8")


def run_fixture(cc):
    flags = subprocess.CREATE_NO_WINDOW
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture.exe"
        src.write_text(fixture_source(), encoding="utf-8")
        subprocess.run([cc, "-std=gnu11", "-O0", "-g0", "-I", str(HOST), str(src), str(HOST / "hos_report_run.c"),
                        str(HOST / "log_redact.c"), "-o", str(exe), "-ldbghelp", "-ladvapi32"], check=True)
        env = dict(os.environ)
        env.pop("HOS_CRASH_MINIDUMP", None)
        env.pop("HOS_LOG_REDACT", None)

        def game(name):
            g = Path(tmp) / name
            g.mkdir()
            return str(g)

        def run(g, mode, ok=(0,)):
            r = subprocess.run([str(exe), g, mode], capture_output=True, text=True, timeout=60, env=env, creationflags=flags)
            assert ok is None or r.returncode in ok, (mode, r.returncode, r.stdout, r.stderr)
            m = re.search(r"run_id: ([0-9a-f]{32})", r.stdout)
            assert m, (mode, r.stdout, r.stderr)
            return r, m.group(1)

        # a clean end, twice over, and a return (atexit): nothing pending, no marker left
        g = game("clean")
        run(g, "clean")
        run(g, "return")
        assert pending(g) == [] and running(g) == [], (pending(g), running(g))
        # a crash through the exception filter: one complete record, the marker gone
        g = game("crash")
        r, run_id = run(g, "crash", ok=(0xC0000005,))
        names = pending(g)
        assert len(names) == 1 and re.fullmatch(r"crash-\d{8}T\d{6}Z\.txt", names[0]), names
        t = text_of(g, names[0])
        assert t.startswith("Triforce crash record 1\n") and t.endswith("record_complete: yes\n"), t
        for want in ("run_id: " + run_id, "reason: unhandled exception", "thread: fixture-thread", "exception: 0xc0000005",
                     "fault_address_class: other", "host_backtrace_method: Windows unwind", "guest_register: x30=0x80001234",
                     "guest_backtrace: 0x80005678", "dump: off", "version: fixture-v1"):
            assert want in t, want
        assert running(g) == [], running(g)
        # a fatal end and a device lost: their fixed reasons, one record each run
        for mode, reason in (("fatal", "hos_fatal"), ("device-lost", "device lost")):
            g = game(mode)
            run(g, mode, ok=(3,))
            names = pending(g)
            assert len(names) == 1, names
            assert "reason: %s\n" % reason in text_of(g, names[0]), text_of(g, names[0])
        # killed with no clean end: an unclean-end record at the next start, and the quit the player asked for in it
        g = game("killed")
        _, first = run(g, "killed", ok=(3,))
        assert pending(g) == [] and sum(n.endswith(".running") for n in running(g)) == 1, running(g)
        run(g, "clean")
        names = pending(g)
        assert len(names) == 1 and names[0].startswith("unclean-"), names
        t = text_of(g, names[0])
        assert t.startswith("Triforce unclean record 1\n") and "run_id: " + first in t and "quit_asked" not in t, t
        assert "termination_note: ended from outside or lost power, not necessarily a crash" in t
        g = game("quit")
        run(g, "quit-killed", ok=(3,))
        run(g, "clean")
        assert "quit_asked: yes" in text_of(g, pending(g)[0])
        # a second write never replaces the first; a small buffer is never overrun; a label stays one plain line
        g = game("bounds")
        run(g, "bounds")
        assert len(pending(g)) == 1
        g = game("label")
        r, _ = run(g, "label")
        assert "label: a?b?c?\n" in r.stdout, r.stdout   # (6 bytes asked: the e-acute's second byte cut off)
        # the home folder never in a record (host/log_redact.c's rule)
        g = game("privacy")
        run(g, "privacy")
        t = text_of(g, pending(g)[0])
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
        assert home and home not in t and "thread: %USERPROFILE%/t" in t, t
        # the newest 15 kept at a start; other files left alone
        g = game("prune")
        p = Path(g) / "crash-reports" / "pending"
        p.mkdir(parents=True)
        for day in range(1, 21):
            (p / ("crash-202611%02dT000000Z.txt" % day)).write_text("x", encoding="utf-8")
        (p / "notes.txt").write_text("mine", encoding="utf-8")
        run(g, "clean")
        names = pending(g)
        assert len(names) == 16 and "notes.txt" in names and "crash-20261106T000000Z.txt" in names, names
        assert "crash-20261105T000000Z.txt" not in names
        # a folder it cannot write: no record, the game unaffected
        g = game("readonly")
        (Path(g) / "crash-reports").write_text("a file where the folder would be", encoding="utf-8")
        run(g, "read-only")
        # no minidump unless asked for; asked for (HOS_CRASH_MINIDUMP=1), a private one beside, never in the record's folder
        assert not any((Path(tmp) / d / "crash-reports" / "local-only").exists() for d in os.listdir(tmp)
                       if (Path(tmp) / d).is_dir())
        g = game("dump")
        env["HOS_CRASH_MINIDUMP"] = "1"
        run(g, "crash", ok=(0xC0000005,))
        env.pop("HOS_CRASH_MINIDUMP")
        names = pending(g)
        assert len(names) == 1 and "dump: requested locally, not for sharing" in text_of(g, names[0])
        local = sorted(x.name for x in (Path(g) / "crash-reports" / "local-only").iterdir())
        stem = names[0][:-4]
        assert stem + ".outcome.txt" in local, local
    print("PASS: crash, fatal, device lost, unclean end (with the quit asked), clean ends, pruning, privacy, no dump by default")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    source_contract()
    if os.name != "nt":
        print("SKIP: the fixture runs on Windows (its Linux paths are read above)")
        return
    run_fixture(args.cc)


if __name__ == "__main__":
    main()
