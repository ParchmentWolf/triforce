"""A character's or an object's shadow map's side is rounded up to a multiple of 64 (host/oot_shadow_step.h, host/
oot_shadow_step.c, nx2/oot_patches.py patch_shadow_step, HOS_OOT_SHADOW_STEP; no game).

(Triforce, 11-21, the performance audit's GAME-05, after Source B's.) The game sizes each nearby character's or object's
shadow map by its size on screen, so while anything moves each frame asks for depth textures of sides not seen before;
the render targets' pool gives an image back only to a target of exactly its shape.

1. The rule, host/oot_shadow_step.h compiled alone: a side goes up to the next multiple of the step and a multiple stays;
   sides from 384 to 1,920 become 25 sizes; no side crosses 768 (the renderer's rule for maps of 768 and less); at most
   63 more texels; step 0 or 1 leaves the side; the switch's values.
2. The host's function (source): the step is the rule's of HOS_OOT_SHADOW_STEP, read once and logged; the answer the rule's.
3. The lift's patch: the one read of the side in f_802640a0 goes through the host, in either form the lifter writes a
   register in, once, with its declaration; the same line in another function is not touched; a text patched before is
   left as it is; a text without the function, with the read twice, or without the include is not touched; it is among
   the supported build's patches, with a warning when its place is not found.

    python -I -B tests/test_oot_shadow_step.py [--cc clang]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <stdint.h>
#include <stdio.h>
#include "oot_shadow_step.h"
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
int main(void) {
    CHECK(oot_shadow_side(385, 64) == 448 && oot_shadow_side(448, 64) == 448 && oot_shadow_side(449, 64) == 512);
    CHECK(oot_shadow_side(777, 64) == 832 && oot_shadow_side(2400, 64) == 2432 && oot_shadow_side(1920, 64) == 1920);
    CHECK(oot_shadow_side(500, 0) == 500 && oot_shadow_side(500, 1) == 500 && oot_shadow_side(500, 256) == 512);
    CHECK(oot_shadow_side(0, 64) == 0 && oot_shadow_side(1, 64) == 64);
    int sizes = 0;
    uint32_t last = 0;
    for (uint32_t s = 384; s <= 1920; s++) {
        const uint32_t r = oot_shadow_side(s, 64);
        CHECK(r >= s && r - s <= 63 && r % 64 == 0);
        CHECK((s <= 768) == (r <= 768));        /* (no map crosses the renderer's line at 768) */
        if (r != last) sizes++, last = r;
    }
    CHECK(sizes == 25);
    /* the switch */
    CHECK(oot_shadow_step(NULL) == 64 && oot_shadow_step("") == 64 && oot_shadow_step("abc") == 64 && oot_shadow_step("64x") == 64);
    CHECK(oot_shadow_step("0") == 1 && oot_shadow_step("1") == 1);
    CHECK(oot_shadow_step("2") == 2 && oot_shadow_step("32") == 32 && oot_shadow_step("128") == 128 && oot_shadow_step("256") == 256);
    CHECK(oot_shadow_step("48") == 64 && oot_shadow_step("512") == 64 && oot_shadow_step("99999999") == 64);
    return fails ? 1 : 0;
}
"""


def check_source():
    host = (ROOT / "host" / "oot_shadow_step.c").read_text(encoding="utf-8")
    side = block(host, "uint32_t hos_oot_shadow_side(uint32_t side) {")
    check('s = (int)oot_shadow_step(getenv("HOS_OOT_SHADOW_STEP"));' in side and "const uint32_t out = oot_shadow_side(side, (uint32_t)s);" in side and
          "return out;" in side, "the host's answer is not the rule's of the switch's step")
    check("__atomic_compare_exchange_n(&step, &unset, s," in side and 'hos_log("oot: shadow maps\' sides rounded up to a multiple of %d' in side,
          "the step is not kept once, or leaves no line")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_OOT_SHADOW_STEP=<n>`" in dev, "docs/development.md: HOS_OOT_SHADOW_STEP is not in the switches table")


def check_patch():
    import oot_patches as o
    head, mark, decl = o.SHADOW_STEP_HEAD, o.SHADOW_STEP_MARK, o.SHADOW_STEP_DECL
    check("f_802640a0" in head, "the function is not the one that sizes a shadow map")
    check(len(o.SHADOW_STEP_FORMS) == 2, "the two forms a register is written in are not both looked for")
    inc = '#include "a64.h"\n'
    for old, new in o.SHADOW_STEP_FORMS:
        check("+ 1256" in old and "recomp_load32(" in old and new.count("hos_oot_shadow_side(") == 1 and old.rstrip(";")[old.index("=") + 1:] in new,
              "the new text does not round the game's own read of the side at +0x4e8")
        other = "void f_80264300(Ctx *__restrict A64_NOESC c) {\n    " + old + "\n}\n"   # (the same read in another function)
        text = inc + head + "    c->x[21]=c->x[0];\n    " + old + "\n    c->x[11]=c->x[10];\n}\n" + other
        out, found = o.patch_shadow_step(text)
        check(found == 1 and out.count(new + mark) == 1 and out.count(old) == 1 and out.count(decl) == 1 and out.endswith(other),
              "patch_shadow_step: the read is not made through the host once, or another function's is")
        check(out.index(decl) < out.index(head), "patch_shadow_step: the host's function is not declared before its use")
        again, found = o.patch_shadow_step(out)
        check(found == 1 and again == out, "patch_shadow_step: a text patched before is patched again")
        for what, bad in (("without the function", inc + other),
                          ("with the read twice in the function", inc + head + "    " + old + "\n    " + old + "\n}\n"),
                          ("with another offset", inc + head + "    " + old.replace("1256", "1260") + "\n}\n"),
                          ("without the include to declare at", head + "    " + old + "\n}\n")):
            got, found = o.patch_shadow_step(bad)
            check(not found and got == bad, "patch_shadow_step: a text %s is touched" % what)
    src = (ROOT / "nx2" / "oot_patches.py").read_text(encoding="utf-8")
    apply = src[src.index("def apply(gen, *, protect_hearts=False, required=False):"):]
    at = 0
    for part in ("shadow_step_sites = 0", "if protect_hearts:   # (found by address: the supported build's functions)",
                 "stepped, found = patch_shadow_step(out)", "shadow_step_sites += found", "out = stepped", "if out != s:",
                 "if protect_hearts and shadow_step_sites != 1:"):
        found = apply.find(part, at)
        check(found >= 0, "oot_patches.py apply: %r is missing, or not after the part before it" % part)
        at = found + len(part)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    check_source()
    check_patch()
    with tempfile.TemporaryDirectory(prefix="oot-shadow-step-") as tmp:
        c, exe = Path(tmp) / "step.c", Path(tmp) / "step.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "host"), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: a shadow map's side is rounded up to a multiple of 64, through the host: 25 sizes from 384 to 1,920")


if __name__ == "__main__":
    main()
