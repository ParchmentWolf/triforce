"""Compile shaders, All or Most: how much of the driver's work the shader preparation does before the title.

What must hold: gpu/vk/compile_level.h's rules (compiled and run here, no game or GPU): All unless RX_VK_COMPILE_SHADERS says
most or the options file's compile_shaders= is 1 (the switch over the file; anything else as not set); the prediction runs
before the title on All after a preparation that translated, or where a preparation on Most left it owed, never on Most; the
mark is left on Most only where All would have run it; the compute switches' own values win, and on Most an unset one is
"listed". And the sources: every caller of predict_run asks predict_before_title, which keeps and clears the mark; prepare_run's
compute warm and the precompile's compute programs take the switches through compile_level::computes; the Debug tab's row
and its default (All); the switch in docs/development.md.

python -I -B tests/test_compile_level.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

PROGRAM = r"""
#include "compile_level.h"
#include <cstdio>
#include <cstring>
using namespace compile_level;
static int failed = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); failed++; } } while (0)
int main() {
    const char* from = nullptr;
    CHECK(level(nullptr, -1, &from) == kAll && !std::strcmp(from, "the default"));
    CHECK(level(nullptr, 0) == kAll);
    CHECK(level(nullptr, 1, &from) == kMost && !std::strcmp(from, "the Compile shaders row"));
    CHECK(level(nullptr, 7) == kAll);
    CHECK(level("most", 0, &from) == kMost && !std::strcmp(from, "RX_VK_COMPILE_SHADERS"));
    CHECK(level("all", 1) == kAll);
    CHECK(level("", 1) == kMost);          // (empty: not set, the file decides)
    CHECK(level("bogus", -1) == kAll);     // (not a level: not set)
    CHECK(level("bogus", 1) == kMost);
    // (the prediction before the title)
    CHECK(predict_now(kAll, true, false));
    CHECK(predict_now(kAll, false, true));     // (owed by a preparation on Most)
    CHECK(!predict_now(kAll, false, false));   // (nothing translated, nothing owed: as before)
    CHECK(!predict_now(kMost, true, false));
    CHECK(!predict_now(kMost, true, true));
    CHECK(mark_owed(kMost, true));
    CHECK(!mark_owed(kMost, false));
    CHECK(!mark_owed(kAll, true));
    // (the compute switches)
    CHECK(computes(kAll, nullptr) == nullptr);
    CHECK(!std::strcmp(computes(kMost, nullptr), "listed"));
    CHECK(!std::strcmp(computes(kMost, ""), "listed"));
    CHECK(!std::strcmp(computes(kMost, "all"), "all"));
    CHECK(!std::strcmp(computes(kAll, "listed"), "listed"));
    CHECK(!std::strcmp(computes(kAll, "none"), "none"));
    if (failed) return 1;
    std::printf("compile_level: all checks passed\n");
    return 0;
}
"""


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit(where + " no longer has: " + needle)


def body(text, head):
    start = text.index(head)
    return text[start:text.index("\n}\n", start)]


def check_source():
    vk = ROOT / "gpu/vk"
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    main = (vk / "vk_main.cpp").read_text(encoding="utf-8")
    menu = (vk / "vk_menu.cpp").read_text(encoding="utf-8")
    menu_h = (vk / "vk_menu.h").read_text(encoding="utf-8")
    need("vk_draw.cpp", draw, ['#include "compile_level.h"'])
    level = body(draw, "compile_level::Level compile_level_now() {")
    need("vk_draw.cpp: compile_level_now()", level,
         ['"triforce_options.ini"', '"compile_shaders="', 'compile_level::level(getenv("RX_VK_COMPILE_SHADERS"), ini, &from)'])
    before = body(draw, "bool predict_before_title(bool prepared) {")
    need("vk_draw.cpp: predict_before_title()", before,
         ["compile_level::mark_owed(level, prepared)", "compile_level::predict_now(level, prepared, owed)",
          "!predicted_read(pstamp).count(kPredictedAll)", "remove(mark.c_str())", "warmed_stamp(gpl_wanted())"])
    run = body(draw, "void predict_run(void (*progress)(size_t done, size_t total)) {")
    need("vk_draw.cpp: predict_run()", run, ["remove(predict_most_path().c_str());"])
    # (every caller of predict_run asks first)
    lines = main.split("\n")
    calls = [i for i, line in enumerate(lines) if "predict_run(" in line and "void predict_run" not in line]
    asked = [i for i in calls if any("predict_before_title(" in lines[j] for j in range(max(0, i - 4), i + 1))]
    if len(calls) != 3 or asked != calls:
        raise SystemExit("vk_main.cpp: a predict_run call that does not ask predict_before_title: %r" %
                         [lines[i] for i in calls if i not in asked])
    prepare = body(draw, "bool prepare_run(void (*progress)(size_t done, size_t total), bool background) {")
    need("vk_draw.cpp: prepare_run()", prepare,
         ['compile_level::computes(compile_level_now(), getenv("RX_VK_WARM_COMPUTES"))', "computes_named(true)"])
    need("vk_draw.cpp: precompile_run()", body(draw, "void precompile_run(void (*progress)(size_t done, size_t total)) {"),
         ['compile_level::computes(compile_level_now(), getenv("RX_VK_PRECOMPILE_COMPUTES"))'])
    need("vk_menu.cpp", menu, ['{TAB_DEBUG, "Compile shaders", &opts.compile_shaders, 0, 1, 1, tx_compile_shaders,'])
    need("vk_menu.h", menu_h, ["int compile_shaders = 0;"])
    need("docs/development.md", (ROOT / "docs/development.md").read_text(encoding="utf-8"),
         ["`RX_VK_COMPILE_SHADERS=all` or `most`"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="compile-level-") as tmp:
        src = Path(tmp) / "compile_level_test.cpp"
        src.write_text(PROGRAM, encoding="utf-8")
        exe = Path(tmp) / "compile-level"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(src), "-o",
                        str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: Compile shaders: All by default, Most from the row or RX_VK_COMPILE_SHADERS; the prediction before the title "
          "only on All (and once owed after Most); the compute switches listed on Most where unset")


if __name__ == "__main__":
    main()
