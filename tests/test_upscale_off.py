"""The upscaler Off: which network dispatches the plain stretch stands in for (gpu/vk/upscale_off.h; no game, no GPU).

(Triforce, 11-22, the performance audit's GPUWORK-20, after Source A's.) With RX_VK_UPSCALE_OFF=1 the game's gameplay
upscale networks are not dispatched: their input is stretched linearly into their output. Before, only the first
network was stood in for, and only on cards that run the networks on software matrix multiplies.

The rule, compiled and run: not Off, only a listed program is stood in for, with the stand-in's own FXAA and history
bound; Off, both networks known by key and every network of a gameplay upscale's shape, with the plain stretch, and the
ones taken by shape marked so that the caller looks at their input's format; a program that is neither is left alone.

The source: taau_stand_in asks the rule, checks the scene's input format for a network taken by its shape, and hands
typed_upscale the rule's choice of stretch; compute_dispatch still gives DLSS and FSR the dispatch first; the compile
skips still ask taau_key alone (the networks are compiled as before, so leaving Off needs nothing made); the switch is
in the switches table. tests/test_taau_env_lookup.py runs taau_stand_in itself with Off on and off.

    python -I -B tests/test_upscale_off.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "upscale_off.h"
#include <cstdio>
static int checks, fails;
static void want(const char* what, upscale_off::Choice c, bool stand_in, bool temporal, bool by_shape) {
    checks++;
    if (c.stand_in != stand_in || (stand_in && (c.temporal != temporal || c.by_shape != by_shape)))
        fails++, printf("FAIL %s: stand_in %d temporal %d by_shape %d\n", what, c.stand_in, c.temporal, c.by_shape);
}
int main() {
    using upscale_off::choose;
    //                                              listed off   by_key shaped
    want("not Off, nothing",                 choose(false, false, false, false), false, false, false);
    want("not Off, a network by key",        choose(false, false, true, true), false, false, false);
    want("not Off, a share's network",       choose(false, false, false, true), false, false, false);
    want("not Off, the listed network",      choose(true, false, true, true), true, true, false);
    want("not Off, a listed other program",  choose(true, false, false, false), true, true, false);
    want("Off, a network by key",            choose(false, true, true, true), true, false, false);
    want("Off, a network by key, any shape", choose(false, true, true, false), true, false, false);
    want("Off, a share's network",           choose(false, true, false, true), true, false, true);
    want("Off, a program that is neither",   choose(false, true, false, false), false, false, false);
    want("Off, the listed network",          choose(true, true, true, true), true, false, false);
    want("Off, a listed other program",      choose(true, true, false, false), true, true, false);
    want("Off, a listed program of the shape", choose(true, true, false, true), true, true, false);
    if (fails) printf("upscale off: FAILED (%d of %d checks)\n", fails, checks);
    else printf("upscale off: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def function(src, head):
    at = src.index(head)
    return src[at:src.index("\n}\n", at)]


def check_source():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    if '#include "upscale_off.h"' not in draw:
        raise SystemExit("vk_draw.cpp does not include upscale_off.h")
    on = function(draw, "static bool upscale_off_on() {")
    if 'getenv("RX_VK_UPSCALE_OFF")' not in on or 'lab_ab::on("upoff")' not in on:
        raise SystemExit("upscale_off_on() does not read RX_VK_UPSCALE_OFF and the lab's upoff phases")
    stand = function(draw, "bool taau_stand_in(VkCommandBuffer cmd, const NvnState& s, const Program& p) {")
    order = [stand.find(n) for n in (
        "const bool off = upscale_off_on();",
        "upscale_off::choose(taau_key(p.key), off, gameplay_network(p.key), shaped);",
        "if (!ch.stand_in) return false;",
        "if (ch.by_shape) {",
        "if (!in || in->format != VK_FORMAT_E5B9G9R9_UFLOAT_PACK32) return false;",
        "if (!out || out->format != VK_FORMAT_B10G11R11_UFLOAT_PACK32) return false;",
        "done = typed_upscale(cmd, dw().imgs[0].imageView, dw().imgs[ntex].imageView, out, level, p.key, keys, ch.temporal);",
        "if (done) hudless_after_dispatch(cmd, p.key);")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("taau_stand_in no longer asks upscale_off.h, checks both ends' formats, and stretches as it chose: %s" % order)
    if "st.info.uses_cooperative_matrix && st.info.texture_descriptors.size() == 1" not in stand:
        raise SystemExit("taau_stand_in does not take the shares' networks by their shape")
    # (DLSS, FSR 4 and FSR 3.1 take the dispatch first: Off is the game's own upscaler's)
    at = [draw.find(n) for n in ("if (fsr3_stand_in(cmd, s, p)) return void(st_dispatches++);",
                                 "if (temporal_stand_in(cmd, s, p)) return void(st_dispatches++);",
                                 "if (taau_stand_in(cmd, s, p)) return void(st_dispatches++);")]
    if min(at) < 0 or at != sorted(at):
        raise SystemExit("compute_dispatch no longer gives FSR 3.1, then DLSS or FSR 4, the network before the stand-in")
    # (the networks are still compiled under Off: the skips ask the env list alone)
    rest = draw.replace(on, "").replace(stand, "")
    if rest.count("taau_key(p.key)") < 5 or "upscale_off_on()" in rest:
        raise SystemExit("a compile skip asks upscale_off_on(): Off would leave the networks unmade, and leaving Off would wait for them")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    if "`RX_VK_UPSCALE_OFF=1`" not in docs:
        raise SystemExit("docs/development.md: RX_VK_UPSCALE_OFF is not in the switches table")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="upscale-off-") as tmp:
        cpp, exe = Path(tmp) / "upscale_off_test.cpp", Path(tmp) / "upscale-off.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the upscaler Off's rule")


if __name__ == "__main__":
    main()
