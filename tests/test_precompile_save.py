"""The pipeline cache saved before the title after a long precompile, and after a preparation without stage libraries
(gpu/vk/precompile_save.h; vk_draw.cpp precompile_end_save, precompile_run, prepare_run, prepare_compute_pipeline,
pipeline_cache_save; no game, no GPU).

(Triforce, 11-22, the performance audit's PIPE-23, after Source A's.) A precompile that keeps its pipelines ended without
a save: what it compiled was first written in play, so a crash or a kill early in play cost the whole build again. From
RX_VK_PRECOMPILE_SAVE_S seconds of building (30) its end now saves, the play file alone while there is a play cache. And a
preparation without stage libraries, which built its compute pipelines into the main cache uncounted and ended unsaved,
counts them and saves before its record.

Compiles a driver against the header: 30 by default, 0 never, the clamp to a day; due only from that many seconds and
not when the game went on, after a stop or in a start that only prepares; what each outcome says; when the preparation
saves.

Cuts precompile_save_s and precompile_end_save out of vk_draw.cpp and runs them with a stand-in save: a short build
says and saves nothing; a long one saves once with the play-only mark set for the call and cleared after, and logs the
KB written; nothing new is said so; gone on, stopped, prepare-only and no cache each say why and do not save; with the
switch at 0 nothing happens however long the build.

Reads the source: the keep-all end of precompile_run calls it after the workers are joined or let go, the light branch
still saves by itself; pipeline_cache_save writes the play file alone under the mark while there is a play cache;
prepare_compute_pipeline counts pcache_main_built behind the switch; prepare_run's end without libraries calls
pcache_saved_now before its record; the switches table has the row.

    python -I -B tests/test_precompile_save.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

RULE = r'''
#include "precompile_save.h"
#include <cstdio>
#include <cstring>
#include <initializer_list>

using namespace mkwvk::precompile_save;
static int checks, fails;
static void want(const char* what, bool ok) {
    checks++;
    if (!ok) fails++, printf("FAIL %s\n", what);
}

int main() {
    want("30 s by default", after_s(nullptr) == 30 && after_s("") == 30 && kAfterS == 30);
    want("0 is never", after_s("0") == 0 && !on(after_s("0")));
    want("a negative number is never", after_s("-5") == 0);
    want("a number is taken", after_s("45") == 45 && after_s("1") == 1);
    want("clamped to a day", after_s("999999") == 86400 && after_s("86401") == 86400 && after_s("86400") == 86400);
    want("on by default", on(after_s(nullptr)));
    want("a long build from the seconds on", long_build(30.0, 30) && long_build(1454.0, 30) && !long_build(29.9, 30));
    want("never long with the switch at 0", !long_build(100000.0, 0));
    want("due at 30 s", due(30.0, 30, false, false, false));
    want("not due before", !due(29.9, 30, false, false, false));
    want("not due when the game went on", !due(500.0, 30, true, false, false));
    want("not due after a stop", !due(500.0, 30, false, true, false));
    want("not due in a start that only prepares", !due(500.0, 30, false, false, true));
    want("not due with the switch at 0", !due(500.0, 0, false, false, false));
    want("why: stopped first", why_not(true, true, true, true) == Outcome::Stopped);
    want("why: gone on", why_not(true, false, true, true) == Outcome::GoneOn);
    want("why: prepare only", why_not(false, false, true, true) == Outcome::PrepareOnly);
    want("why: no cache", why_not(false, false, false, false) == Outcome::NoCache && why_not(true, true, true, false) == Outcome::NoCache);
    want("the saved line's words", !strcmp(said(Outcome::Saved), "the pipeline cache saved before the title"));
    for (Outcome o : {Outcome::Saved, Outcome::Nothing, Outcome::GoneOn, Outcome::Stopped, Outcome::PrepareOnly, Outcome::NoCache})
        want("every outcome says something", said(o)[0] != 0);
    want("only the saved one says saved", !strstr(said(Outcome::GoneOn), "saved before the title (") &&
                                          strstr(said(Outcome::GoneOn), "not saved") && strstr(said(Outcome::Stopped), "not saved") &&
                                          strstr(said(Outcome::PrepareOnly), "not saved"));
    want("a preparation without libraries saves its computes", prepare_saves(30, false, false, 12));
    want("not one with libraries (their own save)", !prepare_saves(30, true, false, 12));
    want("not behind the game", !prepare_saves(30, false, true, 12));
    want("not with nothing built", !prepare_saves(30, false, false, 0));
    want("not with the switch at 0", !prepare_saves(0, false, false, 12));
    if (fails) printf("precompile save rule: FAILED (%d of %d checks)\n", fails, checks);
    else printf("precompile save rule: all %d checks passed\n", checks);
    return fails != 0;
}
'''

HOOK = r'''
#include "precompile_save.h"
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace precompile_save = mkwvk::precompile_save;
using VkPipelineCache = void*;
#define VK_NULL_HANDLE nullptr
static int one;
VkPipelineCache pcache = &one;
std::atomic<size_t> pcache_saved_size{0}, pcache_play_saved{0};
thread_local bool pcache_play_only_now = false;
bool stop = false;
bool prepare_stopped() { return stop; }
bool only_prepares = false;
bool prepare_only_start() { return only_prepares; }   // (vk_main.cpp)
std::string line;
int lines = 0;
void logf(const char* f, ...) {
    char b[1024];
    va_list ap;
    va_start(ap, f);
    vsnprintf(b, sizeof b, f, ap);
    va_end(ap);
    line = b, lines++;
}
int saves = 0;
bool forced = false, marked = false;
size_t next_play = 0, next_main = 0;
void pipeline_cache_save(bool force) {   // (what the real one would write: the play file, the main file)
    saves++, forced = force, marked = pcache_play_only_now;
    if (next_play) pcache_play_saved = next_play;
    if (next_main) pcache_saved_size = next_main;
}
/* CUT */

static int checks, fails;
static void want(const char* what, bool ok) {
    checks++;
    if (!ok) fails++, printf("FAIL %s (line: %s)\n", what, line.c_str());
}
static bool has(const char* s) { return line.find(s) != std::string::npos; }

int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "off") {   // (RX_VK_PRECOMPILE_SAVE_S=0)
        precompile_end_save(5000.0, false);
        want("with the switch at 0 nothing is saved or said", saves == 0 && lines == 0 && precompile_save_s() == 0);
    } else if (mode == "prepare-only") {   // (a start that only prepares the shaders)
        only_prepares = true;
        precompile_end_save(500.0, false);
        want("a start that only prepares saves at its own end", saves == 0 && lines == 1 && has("only prepares"));
    } else {
        want("30 s by default", precompile_save_s() == 30);
        precompile_end_save(29.0, false);
        want("a short build saves nothing and says nothing", saves == 0 && lines == 0);
        precompile_end_save(31.0, true);
        want("the game went on: not saved, and said", saves == 0 && lines == 1 && has("31 s of building") && has("went on"));
        stop = true;
        precompile_end_save(31.0, false);
        want("stopped: not saved, and said", saves == 0 && lines == 2 && has("the stop's own save"));
        stop = false;
        next_play = 5u << 20;
        precompile_end_save(1454.0, false);
        want("a long build saves once, forced", saves == 1 && forced);
        want("under the play-only mark, cleared after", marked && !pcache_play_only_now);
        want("and says what it wrote", lines == 3 && has("vk: precompile: 1454 s of building: the pipeline cache saved before the title (5120 KB in "));
        precompile_end_save(40.0, false);
        want("nothing new: saved again, nothing written, said so", saves == 2 && lines == 4 && has("nothing new"));
        next_main = 7u << 20, next_play = 6u << 20;
        precompile_end_save(40.0, false);
        want("both files' bytes are counted", saves == 3 && has("(13312 KB in "));
        pcache = nullptr;
        precompile_end_save(40.0, false);
        want("no cache: not saved, and said", saves == 3 && lines == 6 && has("no pipeline cache"));
    }
    if (fails) printf("precompile save hook (%s): FAILED (%d of %d checks)\n", mode.c_str(), fails, checks);
    else printf("precompile save hook (%s): all %d checks passed\n", mode.c_str(), checks);
    return fails != 0;
}
'''


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def ordered(text, parts, why):
    at, last = [], 0
    for p in parts:
        k = text.find(p, last)
        need(k >= 0, why + " (missing, or out of order: " + p + ")")
        at.append(k)
        last = k
    return at


def check_source(draw):
    need('#include "precompile_save.h"' in draw, "vk_draw.cpp does not include precompile_save.h")
    need('static const int s = precompile_save::after_s(getenv("RX_VK_PRECOMPILE_SAVE_S"));' in block(draw, "int precompile_save_s() {"),
         "the switch is not RX_VK_PRECOMPILE_SAVE_S, read once")
    end = block(draw, "void precompile_end_save(double build_s, bool gone_on) {")
    ordered(end, ["if (!precompile_save::long_build(build_s, save_s)) return;",
                  "if (!pcache || !precompile_save::due(build_s, save_s, gone_on, stopped, prepare_only)) {", "return;",
                  "Now() { pcache_play_only_now = true; }", "~Now() { pcache_play_only_now = false; }", "pipeline_cache_save(true);",
                  "precompile_save::said(precompile_save::Outcome::Saved)"],
            "precompile_end_save does not save under the play-only mark only when due")
    need("prepare_only = prepare_only_start();" in end and "prepare_stopped()" in end,
         "precompile_end_save does not ask whether the start was stopped or only prepares")
    run = block(draw, "void precompile_run(void (*progress)(size_t done, size_t total)) {")
    ordered(run, ["const auto build_from = std::chrono::steady_clock::now();", "threads.emplace_back(worker);", "checkpoints.end();",
                  "for (std::thread& t : threads) t.join();", "if (light && !prepare_stopped() && (!building.empty() || !computes_built)) {",
                  "pipeline_cache_save(true);", "built_write(built_stamp, built);",
                  "if (!light) precompile_end_save(std::chrono::duration<double>(std::chrono::steady_clock::now() - build_from).count(), gone_on);",
                  'logf("vk: precompile: %zu programs, '],
            "precompile_run's keep-all end does not save after a long build, or the light branch lost its own save")
    save = block(draw, "void pipeline_cache_save(bool force) {")
    ordered(save, ["const bool play_only = force && pcache_play_only_now;", "const file_writers::Writing writing;",
                   "const int64_t main_built = pcache_main_built.load();", "if (play_only && pcache_play_cache) {", "pcache_play_save(0);",
                   "return;", "if (!pcache_play_save(main_built) && pcache_preparing.load() == 0) return;",
                   "MoveFileExA(tmp.c_str(), pcache_path.c_str(),"],
            "pipeline_cache_save does not write the play file alone under the play-only mark, before the main file's turn")
    need("thread_local bool pcache_play_only_now = false;" in draw, "the play-only mark is not a thread's own")
    compute = block(draw, "bool prepare_compute_pipeline(Program& p) {")
    ordered(compute, ["built = guarded_compute(pcache, &ci, &pl) == VK_SUCCESS && pl;", "if (built) {", "pcache_built_since_save++;",
                      "if (precompile_save::on(precompile_save_s())) pcache_main_built++;"],
            "prepare_compute_pipeline does not count its builds for the main file's save, behind the switch")
    for name in ("bool fallback_compute_pipelines(Program& p) {", "VkResult shared_cache_compute("):
        if name in draw:
            need("pcache_main_built++" not in block(draw, name), "the mesh fallback's or the shared passes' pipelines are counted for the main file here")
    prep = block(draw, "bool prepare_run(void (*progress)(size_t done, size_t total), bool background) {")
    tail = prep[prep.rindex("if (!background) warm_end(warming);"):]
    ordered(tail, ["if (precompile_save::prepare_saves(precompile_save_s(), warm, background, libs.load())) pcache_saved_now();",
                   "prepared_for.warmed = warmed;", "prepared_write(path, prepared_for);", "return true;"],
            "prepare_run's end without stage libraries does not save the cache before its record")
    main_cpp = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    need("bool prepare_only_start() { return prepare_only(); }" in main_cpp and
         "bool prepare_only_start();" in (ROOT / "gpu/vk/vk_internal.h").read_text(encoding="utf-8"),
         "vk_main.cpp does not tell vk_draw.cpp whether the start only prepares")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need("`RX_VK_PRECOMPILE_SAVE_S=<seconds>`" in docs and "`gpu/vk/precompile_save.h`" in docs,
         "docs/development.md: the switches table has no RX_VK_PRECOMPILE_SAVE_S row")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_")}
    with tempfile.TemporaryDirectory(prefix="precompile-save-") as tmp:
        def build(name, text):
            cpp, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
            cpp.write_text(text, encoding="utf-8")
            subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                           check=True)
            return exe

        def run(exe, mode, more):
            r = subprocess.run([str(exe), mode], capture_output=True, text=True, env={**env, **more})
            print(r.stdout.rstrip())
            if r.returncode:
                raise SystemExit("FAIL: the precompile save's checks failed (%s)" % (mode or "rule"))

        run(build("rule", RULE), "", {})
        need("int precompile_save_s() {" in draw and "void precompile_end_save(double build_s, bool gone_on) {" in draw,
             "vk_draw.cpp has no precompile_save_s and precompile_end_save")
        cut = block(draw, "int precompile_save_s() {") + "\n" + block(draw, "void precompile_end_save(double build_s, bool gone_on) {")
        hook = build("hook", HOOK.replace("/* CUT */", cut))
        run(hook, "default", {})
        run(hook, "off", {"RX_VK_PRECOMPILE_SAVE_S": "0"})
        run(hook, "prepare-only", {})
    check_source(draw)
    print("PASS: a long precompile's end saves the pipeline cache before the title, the play file alone; a preparation without "
          "stage libraries counts and saves its compute pipelines; RX_VK_PRECOMPILE_SAVE_S=0 as before")


if __name__ == "__main__":
    main()
