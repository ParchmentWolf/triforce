"""The camera's two near-plane clearance inputs retain the game's 16:9 shape.

On a picture wider (or narrower) than 16:9 the camera carries the picture's ratio, and the sphere it keeps clear of walls was
sized from it: at 32:9 too big for a crawl passage, so the camera stayed at the entrance while Link crawled away. Run the real
oot_wide.install and compile its generated after-load code with authored registers. Matching picture ratios become 16:9;
other values and every other register stay unchanged. No game image, lifted code or GPU is used.

python -I -B tests/test_oot_camera_clearance.py [--cc gcc]
"""
import argparse
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_wide  # noqa: E402


# Authored from Arm ARM LDR SIMD/FP unsigned-immediate fields: size=10,
# V=1, opc=01, imm12=0x51c/4, Rn=19, Rt=10 or 14.
def ldr_s(rt):
    return (2 << 30) | (0b111 << 27) | (1 << 26) | (1 << 24) | (1 << 22) | ((0x51c // 4) << 10) | (19 << 5) | rt


SITES = ((0x71a844, ldr_s(10), 10), (0x71b624, ldr_s(14), 14))


class Image:
    def __init__(self, words):
        self.words = words

    def word(self, pc):
        return self.words[pc]


def installed(words):
    lifter = SimpleNamespace(after={})
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        oot_wide.install(lifter, Image(words))
    return lifter.after, log.getvalue()


FIXTURE = r'''
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { uint64_t x[32], vreg[32][2]; } Ctx;
volatile float hos_wide_ratio;
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
static void a64_vset64(uint64_t v[2], uint64_t bits) { v[0] = bits; v[1] = 0; }
static void apply(Ctx *c, unsigned site) {
    (void)c;
    if (site == 0) { SITE_0 }
    else { SITE_1 }
}
static unsigned cases;
static void check(unsigned site, float picture, float input, int replace) {
    const unsigned reg = site ? 14 : 10;
    Ctx c, want;
    memset(&c, 0xa5, sizeof c);
    uint32_t bits;
    memcpy(&bits, &input, 4);
    a64_vset64(c.vreg[reg], bits); /* authored result of a scalar load */
    want = c;
    if (replace) {
        const float normal = 16.0f / 9.0f;
        memcpy(&bits, &normal, 4);
        a64_vset64(want.vreg[reg], bits);
    }
    hos_wide_ratio = picture;
    apply(&c, site);
    if (memcmp(&c, &want, sizeof c)) {
        float got;
        memcpy(&got, c.vreg[reg], 4);
        fprintf(stderr, "site %u, picture %.9g, input %.9g: got %.9g, replace %d\n",
                site, (double)picture, (double)input, (double)got, replace);
        CHECK(!memcmp(&c, &want, sizeof c));
    }
    CHECK(hos_wide_ratio == picture || (isnan(hos_wide_ratio) && isnan(picture)));
    cases++;
}
int main(void) {
    const float shapes[] = { 32.0f/9.0f, 64.0f/27.0f, 21.0f/9.0f, 48.0f/9.0f, 16.0f/10.0f, 4.0f/3.0f };
    for (unsigned site = 0; site < 2; site++) {
        for (unsigned i = 0; i < sizeof shapes / sizeof shapes[0]; i++) {
            float r = shapes[i];
            check(site, r, r, 1);
            check(site, r, r + .009f, 0);
            check(site, r, r - .009f, 0);
            check(site, r, r + .011f, 0);
            check(site, r, r - .011f, 0);
            check(site, r, 16.0f/9.0f, 0);
            check(site, r, 0, 0);
            check(site, r, NAN, 0);
            check(site, r, INFINITY, 0);
        }
        check(site, 2312.0f/1440.0f, 16.0f/10.0f, 0);
        check(site, 0, 32.0f/9.0f, 0); /* normal host value at 16:9 */
        check(site, 0, 0, 0);
        check(site, -1, -1, 0);
        check(site, 16.0f/9.0f, 16.0f/9.0f, 0);
        check(site, 16.0f/9.0f, 16.0f/9.0f + .009f, 0);
        check(site, 16.0f/9.0f, 16.0f/9.0f - .009f, 0);
        check(site, 16.0f/9.0f, 32.0f/9.0f, 0);
        check(site, NAN, 32.0f/9.0f, 0);
    }
    printf("PASS: %u whole-context camera-clearance cases at both loads\n", cases);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    words = {oot_wide.MAIN + off: word for off, word, _ in oot_wide.SITES}
    for off, word, _ in SITES:   # (the game's words, authored here: oot_wide.py's must be the same)
        assert words.get(oot_wide.MAIN + off) == word, "nx2/oot_wide.py has no site at main+%#x for the word %08x" % (off, word)
    after, _ = installed(words)
    creationflags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="camera-clearance-") as temporary:
        folder = Path(temporary)
        source, executable = folder / "fixture.c", folder / "fixture.exe"
        fixture = FIXTURE
        for i, (off, _, _) in enumerate(SITES):
            fixture = fixture.replace("SITE_%d" % i, after.get(oot_wide.MAIN + off, ""))
        source.write_text(fixture, encoding="utf-8")
        for command, cwd in (([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(executable)], None),
                             ([str(executable)], folder)):
            run = subprocess.run(command, cwd=cwd, creationflags=creationflags, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=30)
            print(run.stdout, end="")
            print(run.stderr, end="", file=sys.stderr)
            if run.returncode:
                raise SystemExit(run.returncode)
    for off, word, _ in SITES:
        pc = oot_wide.MAIN + off
        assert pc in after
        for missing in (False, True):
            changed = dict(words)
            if missing:
                del changed[pc]
            else:
                changed[pc] = word ^ 1
            guarded, warning = installed(changed)
            assert pc not in guarded, hex(pc)
            assert "main+%#x" % off in warning and "left out" in warning
            assert {k: v for k, v in after.items() if k != pc} == guarded
    print("PASS: both original words guarded; missing or changed words leave only that site original")


if __name__ == "__main__":
    main()
