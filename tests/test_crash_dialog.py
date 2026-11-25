"""(Triforce) The window after a crash (host/hos_crash_dialog.c, host/hos_crash_dialog.h).

    python -I -B tests/test_crash_dialog.py [--cc gcc]

- Everywhere: the source is read: the helper is handed its command line before anything of the game starts (both mains),
  the watch starts after the run's id is logged, HOS_CRASH_TEST is the environment's only, the quit the player asked for is
  noted first, and nothing in the window's code opens a web page or sends anything (Report copies and saves; its box opens
  a folder, only a folder).
- Everywhere: the deciding parts (the header) in a small C program: the command line, the record's name, Triforce's log
  lines (its version line, the device chosen, the driver, a map line), the verdict (a crash, a start that failed, an
  unclean end, a quit, Triforce's own "could not start its renderer" box), the cause, the stage, and the texts.
- On Windows: the real helper (-DHOS_CRASH_DIALOG_TEST: the box, the clipboard and the folder stood in for) against a game
  folder: a crash shown with Report, the report saved and copied with the home folder taken out, no window for a quit,
  the ledger of records shown.
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
LF = chr(10)   # (records and logs as the game writes them: no CR)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def block(text, marker):
    assert text.count(marker) == 1, marker
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def source_checks():
    dialog, header = read("host/hos_crash_dialog.c"), read("host/hos_crash_dialog.h")
    for text, name in ((dialog, "hos_crash_dialog.c"), (header, "hos_crash_dialog.h")):
        for word in ("http:", "https:", "issues/new", "curl", "WinHttp", "InternetOpen", 'L"open"'):
            assert word not in text, (name, word)
    # (the folder opener opens folders only)
    win = dialog[dialog.index("static int open_folder(const char *folder) {"):]
    win = win[:win.index("\n}\n")]
    assert "FILE_ATTRIBUTE_DIRECTORY" in win and 'L"explore"' in win, win
    lin = dialog[dialog.rindex("static int open_folder(const char *folder) {"):]
    lin = lin[:lin.index("\n}\n")]
    assert "S_ISDIR(st.st_mode)" in lin and "folder[0] != '/'" in lin, lin
    assert dialog.count("open_folder(") >= 5 and "open_thing(" not in dialog
    main = read("host/hos_main.c")
    win_main = main.index("int main(int argc, char **argv) {\n#else\nstatic int game_main(")
    assert main.index("hos_crash_helper_main(argc, argv);", win_main) < main.index("narrow_paths_ok(argc, argv)", win_main)
    linux_main = main.rindex("int main(int argc, char **argv) {")
    assert main.index("hos_crash_helper_main(argc, argv);", linux_main) < main.index("load_hookshot_env();", linux_main)
    run_id = main.index('hos_log("run_id: %s", hos_report_run_id());')
    assert main.index("hos_log_flush();", run_id) < main.index("hos_crash_record_log_notes();", run_id)   # (the boundary on disk)
    assert run_id < main.index("hos_crash_watch_start(argc, argv);") < main.index("if (!reserve_guest()) {")
    assert main.index("if (!reserve_guest()) {") < main.index("hos_crash_test_arm();")
    assert 'names_file |= !strcmp(name, "HOS_CRASH_TEST");' in main
    assert 'hos_log("map: %s", line)' in main
    # (Triforce's own renderer box: its line is the one the header reads as said already)
    told = '] display: the renderer did not start: the game ends'
    assert told in header
    assert 'hos_log("display: the renderer did not start: the game ends");' in read("host/display.c")
    assert 'hos_log("display: the renderer did not start: the game ends");' in read("host/posix/display_sdl.c")
    assert 'hos_log("triforce %s", HOOKSHOT_VERSION);' in main and '"] triforce "' in header
    print("PASS: the helper starts nothing of the game, nothing opens a web page, a box opens a folder only")


LOGIC = r'''
#include "hos_crash_dialog.h"
#include <assert.h>
#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#endif
static HosCrashLog facts(const char *const *lines) {
    HosCrashLog f;
    memset(&f, 0, sizeof f);
    for (; *lines; lines++) hos_crash_log_line(&f, *lines);
    return f;
}
static HosCrashRecord record(const char *text) { HosCrashRecord r; hos_crash_record_parse(text, &r); return r; }
int main(void) {
    HosCrashArgs a;
    char *watch[] = {"Triforce.exe", "--crash-watch", "1234", "0123456789abcdef0123456789abcdef", "C:\\Games\\T", "-"};
    assert(hos_crash_args(6, watch, &a) == 1 && a.pid == 1234 && !a.log && !strcmp(a.dir, "C:\\Games\\T"));
    char *bad_id[] = {"x", "--crash-watch", "1234", "0123", "d", "l"};
    assert(hos_crash_args(6, bad_id, &a) == -1);
    char *show[] = {"x", "--crash-show", "crash-20261124T101500Z.txt", "d", "d/triforce_log.txt"};
    assert(hos_crash_args(5, show, &a) == 2 && !strcmp(a.log, "d/triforce_log.txt"));
    char *path_record[] = {"x", "--crash-show", "../crash-20261124T101500Z.txt", "d", "l"};
    assert(hos_crash_args(5, path_record, &a) == -1);
    char *game[] = {"x", "image.bin"};
    assert(hos_crash_args(2, game, &a) == 0);
    char when[17];
    assert(hos_crash_record_name("crash-20261124T101500Z-77-2.txt", when) == 1 && !strcmp(when, "20261124T101500Z"));
    assert(hos_crash_record_name("unclean-20261124T101500Z.txt", NULL) == 2);
    assert(!hos_crash_record_name("report-20261124T101500Z.txt", NULL));
    char *prep[] = {"x", "--prepare-shaders"};
    const char *id = "0123456789abcdef0123456789abcdef";
    assert(hos_crash_watch_wanted(1, prep, 0, 0, 0, 0, id) && !hos_crash_watch_wanted(2, prep, 0, 0, 0, 0, id));
    assert(!hos_crash_watch_wanted(1, prep, 1, 0, 0, 0, id) && !hos_crash_watch_wanted(1, prep, 0, 1, 0, 0, id));
    assert(!hos_crash_watch_wanted(1, prep, 0, 0, 0, 0, "unknown"));
    assert(hos_crash_under_gamescope(NULL, "KDE:gamescope") && !hos_crash_under_gamescope("", "KDE"));
#ifdef _WIN32
    {   /* (the quoting, read back as Windows reads a command line) */
        const char *args[] = {"C:\\Program Files\\T\\", "a \"b\" c", "x\\\\\"y", ""};
        char line[1024] = "x.exe";
        for (int i = 0; i < 4; i++) {
            char q[256];
            assert(hos_crash_quote_arg(q, sizeof q, args[i]));
            strcat(line, " "), strcat(line, q);
        }
        wchar_t w[1024];
        MultiByteToWideChar(CP_UTF8, 0, line, -1, w, 1024);
        int n = 0;
        wchar_t **back = CommandLineToArgvW(w, &n);
        assert(back && n == 5);
        for (int i = 0; i < 4; i++) {
            char got[256];
            WideCharToMultiByte(CP_UTF8, 0, back[i + 1], -1, got, sizeof got, NULL, NULL);
            assert(!strcmp(got, args[i]));
        }
        LocalFree(back);
    }
#endif
    /* (Triforce's own lines) */
    const char *play[] = {"[hos host] triforce v0.7.1-12-gabc (Sage Of Courage)\n", "[hos host] run_id: x\n",
                          "[hos render] vk: device 0: NVIDIA GeForce RTX 3080, Vulkan 1.4, driver 0x91c0c000, type 2\n",
                          "[hos render] vk: vendor fixes for NVIDIA (581.57): out-of-bounds texel fetches 0 0, NaN tests by bits 0, gather offset 0\n",
                          "[hos render] vk: NVIDIA GeForce RTX 3080, Vulkan 1.4, driver 0x91c0c000; mesh shaders yes, host memory import yes, pipeline libraries yes\n",
                          "[hos render] vk: start-up: the shaders took 3.1 s\n", "[hos MainThread] map: Field (child)\n", NULL};
    HosCrashLog f = facts(play);
    assert(!strcmp(f.version, "v0.7.1-12-gabc (Sage Of Courage)"));
    assert(!strcmp(f.gpu, "NVIDIA GeForce RTX 3080") && !strcmp(f.driver, "NVIDIA (581.57)"));
    assert(!strcmp(f.devices, "NVIDIA GeForce RTX 3080"));
    {   /* (the card with its driver; the renderer of a start-up crash) */
        char gpu[400];
        hos_crash_gpu(gpu, sizeof gpu, &f);
        assert(!strcmp(gpu, "NVIDIA GeForce RTX 3080, NVIDIA (581.57)"));
        assert(!strcmp(hos_crash_renderer(&f), "Vulkan (it was starting)"));
        const char *started[] = {"[hos host] rx: renderer: Vulkan (triforce_vk.dll)\n", NULL};
        HosCrashLog s = facts(started);
        assert(!strcmp(hos_crash_renderer(&s), "Vulkan (triforce_vk.dll)"));
        HosCrashLog early;
        memset(&early, 0, sizeof early);
        assert(!strcmp(hos_crash_renderer(&early), "none started yet"));
        hos_crash_gpu(gpu, sizeof gpu, &early);
        assert(!gpu[0]);
    }
    assert(f.map && hos_crash_stage(&f) == HOS_STAGE_PLAY && !hos_crash_start_failed(&f));
    const char *driver_only[] = {"[hos render] vk: AMD Radeon RX 7800 XT, Vulkan 1.3, driver 0x8000123; mesh shaders yes\n", NULL};
    f = facts(driver_only);
    assert(!strcmp(f.gpu, "AMD Radeon RX 7800 XT") && !strcmp(f.driver, "driver 0x8000123"));
    const char *preparing[] = {"[hos render] vk: start-up: 120 pipelines to make\n", NULL};
    f = facts(preparing);
    assert(hos_crash_stage(&f) == HOS_STAGE_PREPARING);
    /* (was it a crash) */
    HosCrashLog none;
    memset(&none, 0, sizeof none);
    const HosCrashRecord crash = record("Triforce crash record 1\nversion: v1\nrun_id: x\nreason: unhandled exception\n"
                                        "module_offset: nvoglv64.dll+0x12\nexception: 0xc0000005\n");
    const HosCrashRecord unclean = record("Triforce unclean record 1\nreason: ended without a clean exit\n");
    const HosCrashRecord quit = record("Triforce unclean record 1\nquit_asked: yes\n");
    const HosCrashRecord nothing = record("");
    assert(crash.kind == 1 && crash.code == 0xc0000005u && unclean.kind == 2 && quit.quit && !nothing.kind);
    assert(hos_crash_verdict(&crash, &none, 1, 0xc0000005ul, 0) == HOS_CRASH_SHOW_CRASH);
    assert(hos_crash_verdict(&crash, &none, 1, 0, 1) == HOS_CRASH_QUIET);   /* (replaced) */
    assert(hos_crash_cause(HOS_CRASH_SHOW_CRASH, &crash, &none, 0, 0) == HOS_CAUSE_GPU_DRIVER);
    assert(hos_crash_verdict(&unclean, &none, 1, 1, 0) == HOS_CRASH_SHOW_UNCLEAN);
    assert(hos_crash_verdict(&unclean, &none, 1, 0, 0) == HOS_CRASH_QUIET);   /* (exit code 0) */
    assert(hos_crash_verdict(&quit, &none, 1, 1, 0) == HOS_CRASH_QUIET);      /* (a quit never counts) */
    assert(hos_crash_cause(HOS_CRASH_SHOW_UNCLEAN, &unclean, &none, 1, 1) == HOS_CAUSE_ENDED);
    assert(hos_crash_verdict(&nothing, &none, 1, 1, 0) == HOS_CRASH_QUIET);   /* (a clean end: the marker removed) */
    const char *no_gpu[] = {"[hos render] vk: no Vulkan 1.3 GPU\n", "[hos host] rx: RX_BACKEND=vulkan, but x did not load (126): WebGPU\n", NULL};
    f = facts(no_gpu);
    assert(hos_crash_verdict(&nothing, &f, 1, 1, 0) == HOS_CRASH_SHOW_START);
    assert(hos_crash_cause(HOS_CRASH_SHOW_START, &nothing, &f, 1, 1) == HOS_CAUSE_VULKAN);
    const char *told[] = {"[hos render] vk: no Vulkan 1.3 GPU\n", "[hos host] display: the renderer did not start: the game ends\n", NULL};
    f = facts(told);
    assert(f.told && hos_crash_verdict(&nothing, &f, 1, 1, 0) == HOS_CRASH_QUIET);   /* (its own box said it) */
    assert(hos_crash_verdict(&crash, &f, 1, 1, 0) == HOS_CRASH_SHOW_CRASH);          /* (a crash still counts) */
    const char *window[] = {"[hos host] display: CreateWindowExW failed (error 5)\n", NULL};
    f = facts(window);
    assert(hos_crash_cause(hos_crash_verdict(&nothing, &f, 1, 1, 0), &nothing, &f, 1, 1) == HOS_CAUSE_WINDOW);
    const char *reserve[] = {"cannot reserve the guest window\n", NULL};
    f = facts(reserve);
    assert(hos_crash_verdict(&nothing, &f, 1, 1, 0) == HOS_CRASH_SHOW_START);
    assert(hos_crash_cause(HOS_CRASH_SHOW_START, &nothing, &f, 1, 1) == HOS_CAUSE_MEMORY);
    /* (the texts) */
    char text[2048];
    hos_crash_message(text, sizeof text, HOS_CRASH_SHOW_CRASH, HOS_STAGE_PLAY, HOS_CAUSE_GPU_DRIVER);
    assert(strstr(text, "Triforce closed unexpectedly while you were playing.") == text);
    assert(strstr(text, "Triforce itself sends nothing.") && !strstr(text, "browser") && !strstr(text, "http"));
    hos_crash_ready_text(text, sizeof text, 0, NULL);
    assert(strstr(text, "could not be put on the clipboard, nor saved") && !strstr(text, "is on your clipboard"));
    hos_crash_ready_text(text, sizeof text, 1, "C:\\T\\crash-reports\\pending\\report-x.txt");
    assert(strstr(text, "is on your clipboard") && strstr(text, "It is saved as C:\\T\\crash-reports\\pending\\report-x.txt."));
    hos_crash_ready_text(text, sizeof text, 2, "/t/r.txt");
    assert(strstr(text, "Keep this window open"));
    /* (what a setting's value shows) */
    assert(hos_crash_value_shown("HOS_X", "1") && hos_crash_value_shown(NULL, "1920x1080") && hos_crash_value_shown(NULL, "Off"));
    assert(!hos_crash_value_shown("HOS_DISCORD_TOKEN", "1") && !hos_crash_value_shown(NULL, "C:\\Users\\me") &&
           !hos_crash_value_shown(NULL, "-1x2"));
    /* (a start shows a crash record no helper showed, a day old at most; never an unclean end) */
    const int64_t now = hos_crash_epoch("20261124T120000Z");
    assert(hos_crash_epoch("19700102T000000Z") == 86400);
    assert(hos_crash_show_at_start("crash-20261124T110000Z.txt", "", now));
    assert(!hos_crash_show_at_start("crash-20261124T110000Z.txt", "crash-20261124T110000Z.txt\n", now));
    assert(!hos_crash_show_at_start("unclean-20261124T110000Z.txt", "", now));
    assert(!hos_crash_show_at_start("crash-20261122T110000Z.txt", "", now));
    puts("logic ok");
    return 0;
}
'''

FIXTURE = r'''
#define HOS_CRASH_DIALOG_TEST 1
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
void hos_log(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vfprintf(stderr, fmt, ap); va_end(ap); fputc('\n', stderr); }
void hos_log_flush(void) {}
const char *hos_version(void) { return "fixture"; }
static int next_button(void) {
    static int at;
    const char *list = getenv("CRASH_BUTTONS");
    int k = 0;
    for (const char *p = list ? list : ""; *p; p++) {
        if (k == at) { at++; return atoi(p); }
        if (*p == ',') k++;
    }
    at++;
    return -1;
}
int hos_crash_test_box(const char *title, const char *text, const char *const *buttons, int n) {
    printf("BOX %s |", title);
    for (int i = 0; i < n; i++) printf(" [%s]", buttons[i]);
    printf("\n");
    FILE *f = fopen(getenv("CRASH_BOXES"), "ab");
    if (f) fprintf(f, "=== %s\n%s\n", title, text), fclose(f);
    return next_button();
}
int hos_crash_test_clipboard(const char *text) {
    FILE *f = fopen(getenv("CRASH_CLIP"), "wb");
    if (f) fputs(text, f), fclose(f);
    return 1;
}
int hos_crash_test_open(const char *folder) { printf("OPEN %s\n", folder); return 1; }
int hos_crash_helper_main(int argc, char **argv);
int main(int argc, char **argv) { return hos_crash_helper_main(argc, argv); }
'''


def logic(cc, tmp):
    src, exe = Path(tmp) / "logic.c", Path(tmp) / "logic.exe"
    src.write_text(LOGIC, encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-O1", "-Wall", "-Wno-unused-function", "-Wno-incompatible-pointer-types-discards-qualifiers",
                    "-Wno-write-strings", "-I", str(HOST), str(src), "-o", str(exe)] + (["-lshell32"] if os.name == "nt" else []),
                   check=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "logic ok" in r.stdout, (r.returncode, r.stdout, r.stderr)
    print("PASS: the command line, Triforce's log lines, the verdicts, the causes and the texts")


def behaviour(cc, tmp):
    src, exe = Path(tmp) / "helper.c", Path(tmp) / "helper.exe"
    src.write_text(FIXTURE, encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-O1", "-DHOS_CRASH_DIALOG_TEST", "-I", str(HOST), str(src),
                    str(HOST / "hos_crash_dialog.c"), str(HOST / "hos_crash_record.c"), str(HOST / "hos_report_run.c"),
                    str(HOST / "log_redact.c"), "-o", str(exe), "-ldbghelp", "-lshell32", "-lole32", "-ladvapi32", "-luser32"],
                   check=True)
    home = os.environ["USERPROFILE"]
    run_id = "0123456789abcdef0123456789abcdef"
    game = Path(tmp) / "game"
    pending = game / "crash-reports" / "pending"
    pending.mkdir(parents=True)
    log = game / "triforce_log.txt"
    log.write_text("[hos host] triforce v0.7.1\n[hos host] run_id: %s\n[hos host] loading %s\\Saved Games\\x\n"
                   "[hos MainThread] map: Kakariko Village (adult)\n" % (run_id, home), encoding="utf-8", newline=LF)
    record = pending / "crash-20261124T101500Z.txt"
    record.write_text("Triforce crash record 1\nversion: v0.7.1\nrun_id: %s\nwhen: 20261124T101500Z\nuptime_s: 42\n"
                      "reason: unhandled exception\nmodule_offset: Triforce.exe+0x1234\nexception: 0xc0000005\n"
                      "record_complete: yes\n" % run_id, encoding="utf-8", newline=LF)
    boxes, clip = Path(tmp) / "boxes.txt", Path(tmp) / "clip.txt"

    def helper(*args, buttons=""):
        env = dict(os.environ, CRASH_BUTTONS=buttons, CRASH_BOXES=str(boxes), CRASH_CLIP=str(clip))
        for p in (boxes, clip):
            if p.exists():
                p.unlink()
        r = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=60, env=env)
        assert r.returncode == 0, (args, r.returncode, r.stdout, r.stderr)
        return r.stdout

    # (a game process long gone: the watch reads its run's crash record, and Open the log folder, then Report, then Open the
    # folder, then Done)
    out = helper("--crash-watch", 4000000000, run_id, str(game) + os.sep, log, buttons="1,0,0,1")
    lines = out.splitlines()
    assert lines[0].startswith("BOX Triforce closed unexpectedly | [Report] [Open the log folder] [Close]"), out
    assert lines[1] == "OPEN " + str(game), out
    assert lines[3].startswith("BOX Triforce: report ready | [Open the folder] [Done]"), out
    assert lines[4] == "OPEN " + str(pending), out
    shown = boxes.read_text(encoding="utf-8")
    assert "Triforce closed unexpectedly while you were playing." in shown and "is on your clipboard" in shown, shown
    report = clip.read_text(encoding="utf-8")
    assert "### Triforce version\n\nv0.7.1" in report and "Kakariko Village" in report, report
    assert home not in report and "%USERPROFILE%\\Saved Games\\x" in report, report
    assert "Triforce.exe+0x1234" in report and "http" not in report
    assert "Renderer: none started yet" in report, report   # (the log names no renderer line here)
    saved = [p.name for p in pending.iterdir() if p.name.startswith("report-")]
    assert len(saved) == 1 and (pending / saved[0]).read_text(encoding="utf-8") == report
    assert "crash-20261124T101500Z.txt" in (game / "crash-reports" / "shown.txt").read_text(encoding="utf-8")
    # (a quit, then an end with no crash handler: nothing said)
    record.unlink()
    (pending / "unclean-20261124T111500Z.txt").write_text(
        "Triforce unclean record 1\nrun_id: %s\nquit_asked: yes\nrecord_complete: yes\n" % run_id, encoding="utf-8", newline=LF)
    assert helper("--crash-watch", 4000000000, run_id, game, log) == ""
    # (the game's own "could not start its renderer" box said it: nothing more)
    (pending / "unclean-20261124T111500Z.txt").unlink()
    log.write_text("[hos host] triforce v0.7.1\n[hos host] run_id: %s\n[hos render] vk: no Vulkan 1.3 GPU\n"
                   "[hos host] display: the renderer did not start: the game ends\n" % run_id, encoding="utf-8", newline=LF)
    assert helper("--crash-watch", 4000000000, run_id, game, log) == ""
    # (a start that could not reserve its memory says so, Close)
    log.write_text("[hos host] triforce v0.7.1\n[hos host] run_id: %s\ncannot reserve the guest window\n" % run_id,
                   encoding="utf-8", newline=LF)
    (pending / "unclean-20261124T121500Z.txt").write_text(
        "Triforce unclean record 1\nrun_id: %s\nrecord_complete: yes\n" % run_id, encoding="utf-8", newline=LF)
    out = helper("--crash-watch", 4000000000, run_id, game, log, buttons="2")
    assert out.startswith("BOX Triforce couldn't start |"), out
    assert "Your PC ran out of memory" in boxes.read_text(encoding="utf-8")
    # (a log a restarted run appends to (Linux's Restart now): found past its first 8 KB, its facts from its own banner on)
    other = "f" * 32
    log.write_text("[hos host] triforce v0.7.0\n[hos host] run_id: %s\n[hos MainThread] map: Hyrule Field (child)\n" % other
                   + "[hos host] filler line of the run before\n" * 400
                   + "[hos host] triforce v0.7.1\n[hos host] run_id: %s\n[hos render] vk: start-up: the shaders took 1.0 s\n"
                   % run_id, encoding="utf-8", newline=LF)
    (pending / "unclean-20261124T121500Z.txt").unlink()
    record.write_text("Triforce crash record 1\nversion: v0.7.1\nrun_id: %s\nwhen: 20261124T131500Z\nreason: unhandled exception\n"
                      "record_complete: yes\n" % run_id, encoding="utf-8", newline=LF)
    out = helper("--crash-watch", 4000000000, run_id, game, log, buttons="0,1")
    said = boxes.read_text(encoding="utf-8")
    assert "Triforce closed unexpectedly during the start." in said, said
    report = clip.read_text(encoding="utf-8")
    assert "### Triforce version\n\nv0.7.1" in report and "triforce_log.txt\n\nNot found" not in report, report
    # (a bad command line does nothing)
    assert helper("--crash-show", "../x.txt", game, log) == ""
    print("PASS (Windows): the window, Report (copied, saved, the home folder out, no web page), quiet for a quit and for "
          "Triforce's own box")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    source_checks()
    with tempfile.TemporaryDirectory() as tmp:
        logic(args.cc, tmp)
        if os.name == "nt":
            behaviour(args.cc, tmp)
        else:
            print("SKIP: the helper's run is checked on Windows (its Linux paths are read above)")


if __name__ == "__main__":
    main()
