"""A character's shadow map reserves the storage of the next step of sides up (host/shadow_slot.h, host/nvn_native.c
shadow_slot_layout and the builder's two storage answers, host/nn_applet.c hos_rt_pool_pinned; no game).

(Triforce, 11-21, the performance audit's TEX-85, after Source A's.) The game sizes each character's shadow map from the
camera's distance every frame and places a frame's render targets first fit in its target heap: a map a few pixels
larger moved every target made after it, and each moved one is a new image to the renderer.

This compiles shadow_slot.h alone and checks the rule: 385 reserves 768, 1277 reserves 1536, 1537 and 1920 reserve 1920;
384 and less, 1921 and more, a map that is not square, another format, two levels, a 3D texture and step 0 reserve their
own (0); the step is 384 when not set, 0 on a pinned heap, and the switch's value when set, on a pinned heap too.

And reads the source: both of the builder's answers take the larger of the texture's own and the slot's, after the
no-builder guard; the slot's layout is nvn_tex_layout of a copy at the slot's side, the builder untouched; the step asks
whether the heap is pinned and is not kept until the heap has been sized; the heap says pinned for HOS_RT_POOL_MB and
for the 5120-wide cap; the switch is in the switches table.

    python -I -B tests/test_shadow_slot.py [--cc clang]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"
RUN_ALL_ARGS = ["--cc", "clang"]


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
#include "shadow_slot.h"
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static uint32_t side(uint32_t w, uint32_t h) { return hos_shadow_slot_side(1, 0x34, 1, 1, w, h, 384); }
int main(void) {
    CHECK(side(385, 385) == 768 && side(397, 397) == 768 && side(439, 439) == 768 && side(768, 768) == 768);
    CHECK(side(769, 769) == 1152 && side(1277, 1277) == 1536 && side(1537, 1537) == 1920 && side(1920, 1920) == 1920);
    CHECK(side(384, 384) == 0 && side(256, 256) == 0 && side(1921, 1921) == 0 && side(4096, 4096) == 0);
    CHECK(side(500, 501) == 0);                                              /* (not square) */
    CHECK(hos_shadow_slot_side(1, 0x32, 1, 1, 500, 500, 384) == 0);          /* (another format) */
    CHECK(hos_shadow_slot_side(1, 0x34, 2, 1, 500, 500, 384) == 0);          /* (two levels) */
    CHECK(hos_shadow_slot_side(0, 0x34, 1, 1, 500, 500, 384) == 0);          /* (not two-dimensional) */
    CHECK(hos_shadow_slot_side(1, 0x34, 1, 2, 500, 500, 384) == 0);          /* (deep) */
    CHECK(hos_shadow_slot_side(1, 0x34, 1, 1, 500, 500, 0) == 0);            /* (the switch off) */
    CHECK(hos_shadow_slot_side(1, 0x34, 1, 0, 500, 500, 384) == 768);        /* (depth 0 or 1: a plain 2D texture) */
    CHECK(hos_shadow_slot_side(1, 0x34, 1, 1, 500, 500, 256) == 512 && hos_shadow_slot_side(1, 0x34, 1, 1, 1900, 1900, 512) == 1920);
    /* the step */
    CHECK(hos_shadow_slot_step(NULL, 0) == 384 && hos_shadow_slot_step(NULL, 1) == 0);
    CHECK(hos_shadow_slot_step("0", 0) == 0 && hos_shadow_slot_step("384", 1) == 384 && hos_shadow_slot_step("256", 0) == 256);
    CHECK(hos_shadow_slot_step("off", 0) == 0 && hos_shadow_slot_step("-1", 0) == 0 && hos_shadow_slot_step("", 1) == 384);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    nvn = (HOST / "nvn_native.c").read_text(encoding="utf-8")
    check('#include "shadow_slot.h"' in nvn, "nvn_native.c does not use the rule")
    slot = block(nvn, "static int shadow_slot_layout(const nvn_texdesc *d, nvn_texlayout *out) {")
    check('const char *e = getenv("HOS_SHADOW_BUCKET");' in slot and "const int pinned = hos_rt_pool_pinned();" in slot and
          "now = (int)hos_shadow_slot_step(e, pinned > 0);" in slot and "if (e || pinned >= 0) {" in slot,
          "the step is not the rule's of the switch and the pinned heap, or is kept before the heap has been sized")
    check("hos_shadow_slot_side(d->target == NVN_TEXTURE_TARGET_2D, d->format, d->levels, d->depth, d->width," in slot and
          "nvn_texdesc slot = *d;" in slot and "slot.width = slot.height = side;" in slot and "nvn_tex_layout(&slot, out);" in slot,
          "the slot's layout is not nvn_tex_layout of a copy at the slot's side")
    check("d->width =" not in slot and "d->height =" not in slot, "the texture's own description is changed")
    size = block(nvn, "NV(nvnTextureBuilderGetStorageSize) {")
    check(size.index('no_builder(c, "storage size")') < size.index("shadow_slot_layout(") and
          "if (L.bpb && shadow_slot_layout(&CTB(P(0))->d, &slot) && slot.size > L.size) L.size = slot.size;" in size,
          "the storage size is not the larger of the texture's own and its slot's, after the no-builder guard")
    align = block(nvn, "NV(nvnTextureBuilderGetStorageAlignment) {")
    check(align.index('no_builder(c, "storage alignment")') < align.index("shadow_slot_layout(") and
          "if (L.bpb && shadow_slot_layout(&CTB(P(0))->d, &slot) && slot.align > L.align) L.align = slot.align;" in align,
          "the storage alignment is not the larger of the texture's own and its slot's")
    applet = (HOST / "nn_applet.c").read_text(encoding="utf-8")
    pool = block(applet, "uint64_t hos_rt_pool_size(uint64_t game) {")
    check("__atomic_store_n(&rt_pool_pinned, e != NULL || v != asked || (is_five_k && scaled > five_k)," in pool and
          "static int rt_pool_pinned = -1;" in applet and "int hos_rt_pool_pinned(void) {" in applet,
          "the target heap does not say whether it is pinned (HOS_RT_POOL_MB, the 5120-wide cap), or not that it is not known yet")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`HOS_SHADOW_BUCKET=<step>`" in dev, "docs/development.md: HOS_SHADOW_BUCKET is not in the switches table")

    with tempfile.TemporaryDirectory(prefix="shadow-slot-") as tmp:
        c, exe = Path(tmp) / "slot.c", Path(tmp) / "slot.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(HOST), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, "the rule as made:\n" + r.stdout)
    print("PASS: a character's shadow map reserves the storage of the next step of sides up; its own layout is untouched")


if __name__ == "__main__":
    main()
