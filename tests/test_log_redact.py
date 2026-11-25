"""The game's log without the player's user name (host/log_redact.c, host/redact_line.h).

Players pass triforce_log.txt around. The game's own lines are written with the home folder as %USERPROFILE% (~ off
Windows) and the user's name, where it is a folder of a path, as <user>; the rest of each path stays.

The rule and the host's functions are compiled as they are and run on authored lines, no game:
- the rule (hos_redact_line): the home folder as a whole, in either case and with either separator on Windows, exact off
  it; not as the start of a longer name; the user's name as a folder of any path (another drive's Users folder,
  /run/media, /var/home), not as a word of the line; names with spaces and letters outside ASCII; a line redacted again
  comes out the same; a cut to fit never writes past the buffer;
- this PC's (hos_log_redact, hos_log_redact_text): the home folder and the name read from the environment, the home
  folder's own name when it is not the user's name, a text of several lines, and HOS_LOG_REDACT=0 leaving all as it is;
- the places that call it (source checks): hos_log and hos_fatal before the line is queued or written, and the bug
  capture's copy of the log's end.

python -I -B tests/test_log_redact.py [--cc clang]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

RULE = r'''#include "redact_line.h"
#include <stdio.h>
#include <string.h>
static int fails;
static void want(int line, const char *in, const char *home, const char *user, int windows, const char *expected) {
    char out[512], again[512];
    hos_redact_line(out, sizeof out, in, strlen(in), home, user, windows);
    hos_redact_line(again, sizeof again, out, strlen(out), home, user, windows);
    if (strcmp(out, expected) || strcmp(again, expected)) {
        printf("FAIL line %d: %s\n  got      %s\n  again    %s\n  expected %s\n", line, in, out, again, expected);
        fails++;
    }
}
#define WANT(in, home, user, windows, expected) want(__LINE__, in, home, user, windows, expected)
int main(void) {
    /* Windows: the home folder whole, either case, either separator; the rest of the path stays */
    WANT("fs: save at C:\\Users\\Jo Smith\\AppData\\Roaming\\Triforce\\save", "C:\\Users\\Jo Smith", "Jo Smith", 1,
         "fs: save at %USERPROFILE%\\AppData\\Roaming\\Triforce\\save");
    WANT("open c:/users/jo smith/Games/x.bin", "C:\\Users\\Jo Smith", "Jo Smith", 1, "open %USERPROFILE%/Games/x.bin");
    WANT("C:\\Users\\Jo Smith", "C:\\Users\\Jo Smith\\", "Jo Smith", 1, "%USERPROFILE%");
    /* not the start of a longer name, and not the end of another path */
    WANT("C:\\Users\\Jo Smith2\\a", "C:\\Users\\Jo Smith", "nobody", 1, "C:\\Users\\Jo Smith2\\a");
    WANT("D:\\x\\C:\\Users\\Jo\\a", "C:\\Users\\Jo", "", 1, "D:\\x\\C:\\Users\\Jo\\a");
    /* the user's name as a folder of any path; a word of the line is left alone */
    WANT("mods in D:\\Users\\jo\\mods, said jo", "C:\\Users\\jo", "jo", 1, "mods in D:\\Users\\<user>\\mods, said jo");
    WANT("E:\\Games\\JO\\triforce", "C:\\Users\\jo", "jo", 1, "E:\\Games\\<user>\\triforce");
    WANT("E:\\Games\\joanna\\triforce", "C:\\Users\\jo", "jo", 1, "E:\\Games\\joanna\\triforce");
    /* off Windows: exact case and separator, ~ */
    WANT("cache /home/jo/.cache/triforce and /run/media/jo/SD/game, /var/home/jo", "/home/jo", "jo", 0,
         "cache ~/.cache/triforce and /run/media/<user>/SD/game, /var/home/<user>");
    WANT("/home/Jo/x", "/home/jo", "jo", 0, "/home/Jo/x");
    WANT("/home/j\xc3\xb6/x and /media/j\xc3\xb6/y", "/home/j\xc3\xb6", "j\xc3\xb6", 0, "~/x and /media/<user>/y");
    /* nobody known: as it is */
    WANT("C:\\Users\\jo\\a", NULL, NULL, 1, "C:\\Users\\jo\\a");
    WANT("C:\\Users\\jo\\a", "", "", 1, "C:\\Users\\jo\\a");
    {   /* cut to fit: never past the buffer, always ended */
        char small[9];
        memset(small, 'x', sizeof small);
        const size_t n = hos_redact_line(small, 8, "C:\\Users\\jo\\abc", 15, "C:\\Users\\jo", "jo", 1);
        if (n != 7 || small[7] != 0 || small[8] != 'x' || memcmp(small, "%USERPR", 7)) printf("FAIL: the cut\n"), fails++;
    }
    printf(fails ? "%d FAILED\n" : "rule: all passed\n", fails);
    return fails != 0;
}
'''

HOST = r'''#include "log_redact.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    /* argv[1]: a line; argv[2]: a text of lines. Printed redacted, the two apart by a line of ---- */
    char out[1024];
    (void)argc;
    hos_log_redact(out, sizeof out, argv[1]);
    printf("%s\n----\n", out);
    size_t n = 0;
    char *text = hos_log_redact_text(argv[2], strlen(argv[2]), &n);
    if (!text) return 2;
    fwrite(text, 1, n, stdout);
    free(text);
    return 0;
}
'''


FILE_PROGRAM = r'''#include "log_redact.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    /* argv[1]: a log file, redacted in place for run argv[2] ("-": any run); argv[3]: a text, as the crash window's report */
    (void)argc;
    printf("%d\n----\n", hos_log_redact_file(argv[1], strcmp(argv[2], "-") ? argv[2] : NULL));
    size_t n = 0;
    char *text = hos_log_redact_report(argv[3], strlen(argv[3]), &n);
    if (!text) return 2;
    fwrite(text, 1, n, stdout);
    free(text);
    return 0;
}
'''


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    windows = os.name == "nt"
    with tempfile.TemporaryDirectory(prefix="triforce-log-redact-") as tmp:
        tmp = Path(tmp)
        (tmp / "rule.c").write_text(RULE, encoding="utf-8")
        (tmp / "host.c").write_text(HOST, encoding="utf-8")
        flags = ["-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host")]
        for name, sources in (("rule", [tmp / "rule.c"]), ("host", [tmp / "host.c", ROOT / "host" / "log_redact.c"])):
            exe = tmp / (name + ".exe")
            build = subprocess.run([a.cc] + flags + [str(s) for s in sources] + ["-o", str(exe)], capture_output=True, text=True)
            check(build.returncode == 0, name + " does not compile:\n" + build.stderr)
        run = subprocess.run([str(tmp / "rule.exe")], capture_output=True, text=True, encoding="utf-8", errors="replace")
        check(run.returncode == 0 and "rule: all passed" in run.stdout, "the rule:\n" + run.stdout + run.stderr)
        # this PC's: a home folder whose own name is not the user's name
        if windows:
            home, user, folder = r"C:\Users\link.HYRULE", "link", "link.HYRULE"
            line = r"fs: OpenFile: C:\Users\link.HYRULE\Games\Triforce\romfs\a.bin is there (D:\Users\link\b, E:\x\link.HYRULE\c)"
            clean = r"fs: OpenFile: %USERPROFILE%\Games\Triforce\romfs\a.bin is there (D:\Users\<user>\b, E:\x\<user>\c)"
            env = dict(os.environ, USERPROFILE=home, USERNAME=user)
        else:
            home, user, folder = "/var/home/link.hyrule", "link", "link.hyrule"
            line = "fs: OpenFile: /var/home/link.hyrule/Games/Triforce/romfs/a.bin is there (/run/media/link/b, /mnt/x/link.hyrule/c)"
            clean = "fs: OpenFile: ~/Games/Triforce/romfs/a.bin is there (/run/media/<user>/b, /mnt/x/<user>/c)"
            env = dict(os.environ, HOME=home, USER=user)
        env.pop("HOS_LOG_REDACT", None)
        text = "first " + line + "\nno path here, " + user + " said\n" + line + " last, no line end"
        clean_text = "first " + clean + "\nno path here, " + user + " said\n" + clean + " last, no line end"
        run = subprocess.run([str(tmp / "host.exe"), line, text], capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        check(run.returncode == 0, "the host's functions: " + run.stderr)
        got_line, _, got_text = run.stdout.replace("\r\n", "\n").partition("\n----\n")
        check(got_line == clean, "a line:\n  got      %s\n  expected %s" % (got_line, clean))
        check(got_text == clean_text, "a text of lines:\n  got      %r\n  expected %r" % (got_text, clean_text))
        check(folder not in run.stdout and home not in run.stdout, "the home folder's name is still there")
        run = subprocess.run([str(tmp / "host.exe"), line, text], capture_output=True, text=True, env=dict(env, HOS_LOG_REDACT="0"),
                             encoding="utf-8", errors="replace")
        got_line, _, got_text = run.stdout.replace("\r\n", "\n").partition("\n----\n")
        check(run.returncode == 0 and got_line == line and got_text == text, "HOS_LOG_REDACT=0 does not leave the lines as they are")
        # ((Triforce) a run's log file redacted in place once it ended (what other code wrote to stderr), only that run's; and
        # the crash window's report copy, redacted even with HOS_LOG_REDACT=0)
        (tmp / "file.c").write_text(FILE_PROGRAM, encoding="utf-8")
        exe = tmp / "file.exe"
        build = subprocess.run([a.cc] + flags + [str(tmp / "file.c"), str(ROOT / "host" / "log_redact.c"), "-o", str(exe)],
                               capture_output=True, text=True)
        check(build.returncode == 0, "file does not compile:\n" + build.stderr)
        log = tmp / "triforce_log.txt"
        body = "[hos host] triforce v1\n[hos host] run_id: " + "a" * 32 + "\nloader: " + line + "\n"
        log.write_bytes(body.encode("utf-8"))
        run = subprocess.run([str(exe), str(log), "b" * 32, text], capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        check(run.stdout.startswith("0\n") and log.read_bytes() == body.encode("utf-8"), "another run's log was rewritten: " + run.stdout)
        run = subprocess.run([str(exe), str(log), "a" * 32, text], capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        after = log.read_bytes().decode("utf-8")
        check(run.stdout.startswith("1\n") and after == body.replace(line, clean), "the run's log was not redacted: " + run.stdout + after)
        run = subprocess.run([str(exe), str(log), "-", text], capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
        check(run.stdout.startswith("0\n"), "a clean log was rewritten again: " + run.stdout)
        log.write_bytes(body.encode("utf-8"))
        run = subprocess.run([str(exe), str(log), "-", text], capture_output=True, text=True, env=dict(env, HOS_LOG_REDACT="0"),
                             encoding="utf-8", errors="replace")
        report = run.stdout.replace("\r\n", "\n").partition("\n----\n")[2]
        check(run.stdout.startswith("0\n") and log.read_bytes() == body.encode("utf-8"), "HOS_LOG_REDACT=0 rewrote the log")
        check(report == clean_text, "the crash window's report is not redacted with HOS_LOG_REDACT=0: %r" % report)
    # the places that call it
    thread = (ROOT / "host" / "hos_thread.c").read_text(encoding="utf-8")
    # ((Triforce) hos_log and hos_log_at write through hos_vlog, the line's level after the thread's tag)
    log = thread[thread.index("static void hos_vlog(int level, const char *fmt, va_list ap) {"):]
    log = log[:log.index("\n}\n")]
    for caller in ("void hos_log(const char *fmt, ...) {", "void hos_log_at(int level, const char *fmt, ...) {"):
        body = thread[thread.index(caller):]
        check("hos_vlog(" in body[:body.index("\n}\n")], "%s does not write through hos_vlog" % caller)
    at = [log.index(s) for s in ("vsnprintf(buf, sizeof buf, fmt, ap);", "hos_log_redact(line + at, sizeof line - (size_t)at - 1, buf);",
                                 "if (log_queue(line)) return;", "fputs(line, stderr);")]
    check(at == sorted(at), "hos_log does not redact its line before it is queued or written")
    fatal = thread[thread.index("void hos_fatal(Ctx *c, const char *fmt, ...) {"):]
    fatal = fatal[:fatal.index("\n}\n")]
    check(fatal.index("hos_log_redact(clean, sizeof clean, buf);") < fatal.index('fprintf(stderr, "[hos %s] FATAL: %s"'),
          "hos_fatal does not redact its line before it is written")
    capture = (ROOT / "host" / "bug_capture.c").read_text(encoding="utf-8")
    check("hos_log_redact_text(from, (size_t)(tail + n - from), &clean_n);" in capture and
          "write_file(other, clean, clean_n)" in capture, "the bug capture's log-tail.txt is not the redacted copy")
    main_c = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check(main_c.index('snprintf(to + n, 32, "triforce_log.%d.txt", k);') < main_c.index("hos_log_redact_file(to, NULL);") <
          main_c.index('if (freopen(path, "w", stderr))'), "the start does not redact the run before's log after its rotation")
    dialog = (ROOT / "host" / "hos_crash_dialog.c").read_text(encoding="utf-8")
    check(dialog.index("hos_log_redact_file(log->path, run_id);") < dialog.index("read_log(log, &s.who);"),
          "the crash window's helper does not redact its run's log before it reads it")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_LOG_REDACT=0`" in dev, "docs/development.md: HOS_LOG_REDACT=0 is not in the switches table")
    print("PASS: the game's log lines, hos_fatal's and the bug capture's copy leave the home folder and the user's name out")


if __name__ == "__main__":
    main()
