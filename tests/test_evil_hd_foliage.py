"""Evil HD, the Graphics tab's row, and its first part: the foliage drawn farther (host/evil_hd.h, host/evil_hd.c, host/nn_vi.c,
the menu's row; HOS_EVIL_HD, HOS_EVIL_HD_DIST; no game).

(Triforce, Evil HD.) The game's grass, undergrowth, flowers, stones and the low trees of the distance stop at the distances
of its foliage LOD settings; the areas that do not set their own take eight defaults the game's parameter code reads by
address (main+0x3eefd38) when an area loads. With Evil HD on the host writes them times a factor (4); off, as shipped,
nothing of the game is written.

1. The rule, host/evil_hd.h compiled alone: the row and HOS_EVIL_HD over it; HOS_EVIL_HD_DIST's factor and its range; the
   eight distances times the factor (the factor 1: the game's own exactly); which bytes are known (the game's, or the game's
   times a factor this rule can write) and which are left alone (another version's, one value changed, a factor past 4).
2. The host (source): the factor is the rule's of the row and the two switches; nothing is written while it is the one
   the defaults hold (1 at the start: Evil HD off writes nothing); the bytes are checked before the write; the log says so.
   The row reaches it each frame: host/nn_vi.c calls it with option HOS_OPT_EVIL_HD, which the renderer answers from
   opts.evil_hd, the Graphics tab's Evil HD row (Off by default, saved as evil_hd).
3. The development guide and the readme have the switches and the row.
4. With the game's exefs on this PC (OOT_EXEFS, OOT_DUMP or work/dump.txt; skipped without it): the eight floats at the
   defaults' place are the game's, and the code that passes each one's address is the foliage LOD settings' reader.

    python -I -B tests/test_evil_hd_foliage.py [--cc clang]
"""
import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "clang"]

ROOT = Path(__file__).resolve().parents[1]


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
#include <stdio.h>
#include "evil_hd.h"
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static int same(const float *a, const float *b, float f) {
    for (int i = 0; i < EVIL_HD_FOLIAGE_COUNT; i++) if (a[i] != b[i] * f) return 0;
    return 1;
}
int main(void) {
    /* the row, and HOS_EVIL_HD over it */
    CHECK(!evil_hd_on(0, NULL) && evil_hd_on(1, NULL) && !evil_hd_on(0, "") && evil_hd_on(1, ""));
    CHECK(evil_hd_on(0, "1") && !evil_hd_on(1, "0") && !evil_hd_on(0, "2") && evil_hd_on(1, "yes") && evil_hd_on(1, "10"));
    /* HOS_EVIL_HD_DIST */
    CHECK(evil_hd_dist_factor(NULL) == 4.0f && evil_hd_dist_factor("") == 4.0f && evil_hd_dist_factor("abc") == 4.0f);
    CHECK(evil_hd_dist_factor("1") == 1.0f && evil_hd_dist_factor("3") == 3.0f && evil_hd_dist_factor("4") == 4.0f);
    CHECK(evil_hd_dist_factor("2.5") == 2.5f && evil_hd_dist_factor("1.") == 1.0f && evil_hd_dist_factor("1.5") == 1.5f);
    CHECK(evil_hd_dist_factor("0.5") == 4.0f && evil_hd_dist_factor("0") == 4.0f && evil_hd_dist_factor("4.5") == 4.0f);
    CHECK(evil_hd_dist_factor("2x") == 4.0f && evil_hd_dist_factor("-2") == 4.0f && evil_hd_dist_factor("1.2.3") == 4.0f);
    CHECK(evil_hd_dist_factor("99999999") == 4.0f);
    /* the factor now: 1 with Evil HD off whatever the distance switch says */
    CHECK(evil_hd_factor(0, NULL, NULL) == 1.0f && evil_hd_factor(0, NULL, "3") == 1.0f && evil_hd_factor(1, "0", "3") == 1.0f);
    CHECK(evil_hd_factor(1, NULL, NULL) == 4.0f && evil_hd_factor(0, "1", "3") == 3.0f && evil_hd_factor(1, NULL, "1") == 1.0f);
    /* the eight distances: the game's in order (main+0x3eefd38), times the factor */
    const float game[EVIL_HD_FOLIAGE_COUNT] = {40, 60, 35, 30, 40, 135, 10, 45};
    float out[EVIL_HD_FOLIAGE_COUNT];
    CHECK(same(evil_hd_foliage_game, game, 1.0f) && EVIL_HD_FOLIAGE_DEFAULTS == 0x83f0fd38ULL);
    evil_hd_foliage(1.0f, out);
    CHECK(same(out, game, 1.0f));
    evil_hd_foliage(2.5f, out);
    CHECK(out[0] == 80.0f && out[1] == 120.0f && out[5] == 337.5f && out[4] == 100.0f && out[7] == 112.5f);
    CHECK(out[2] == 75.0f && out[3] == 70.0f);   /* (the ornaments and shoot leaves kept to 75 and 70 m: 11-25 flicker) */
    evil_hd_foliage(4.0f, out);
    CHECK(out[0] == 80.0f && out[1] == 120.0f && out[5] == 540.0f && out[2] == 75.0f && out[3] == 70.0f);
    evil_hd_foliage(2.0f, out);
    CHECK(out[2] == 70.0f && out[3] == 60.0f);   /* (under their most: the factor's own) */
    CHECK(out[0] == 80.0f && out[1] == 120.0f);   /* (the undergrowth at its most: 11-26 child Kokiri Forest) */
    evil_hd_foliage(1.5f, out);
    CHECK(out[0] == 60.0f && out[1] == 90.0f);
    /* which bytes are known: the game's, or what a write of this left (a factor from 1 to 4) */
    CHECK(evil_hd_foliage_known(game));
    for (float f = 1.0f; f <= 4.0f; f += 0.25f) {
        evil_hd_foliage(f, out);
        CHECK(evil_hd_foliage_known(out));
    }
    evil_hd_foliage(2.5f, out);
    out[3] += 1.0f;
    CHECK(!evil_hd_foliage_known(out));   /* (one value not the rule's) */
    float other[EVIL_HD_FOLIAGE_COUNT] = {40, 60, 35, 30, 40, 150, 10, 45};
    CHECK(!evil_hd_foliage_known(other));
    for (int i = 0; i < EVIL_HD_FOLIAGE_COUNT; i++) other[i] = game[i] * 5.0f;
    CHECK(!evil_hd_foliage_known(other));   /* (past the most) */
    for (int i = 0; i < EVIL_HD_FOLIAGE_COUNT; i++) other[i] = game[i] * 0.5f;
    CHECK(!evil_hd_foliage_known(other));   /* (under the game's) */
    const float zero[EVIL_HD_FOLIAGE_COUNT] = {0};
    CHECK(!evil_hd_foliage_known(zero));
    return fails ? 1 : 0;
}
"""


def check_rule(cc):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "t.c"
        exe = Path(d) / ("t.exe" if os.name == "nt" else "t")
        src.write_text(PROGRAM, encoding="utf-8")
        r = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"), str(src), "-o", str(exe)],
                           capture_output=True, text=True)
        check(r.returncode == 0, "the rule does not compile alone:\n" + r.stdout + r.stderr)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the rule:\n" + r.stdout + r.stderr)


def check_source():
    host = (ROOT / "host" / "evil_hd.c").read_text(encoding="utf-8")
    tick = block(host, "void hos_evil_hd_tick(int row) {")
    check('mode = getenv("HOS_EVIL_HD");' in tick and 'dist = getenv("HOS_EVIL_HD_DIST");' in tick and
          "const float f = evil_hd_factor(row, mode, dist);" in tick, "the host's factor is not the rule's of the row and the switches")
    check("static float applied = 1.0f;" in tick, "the defaults the host starts from are not the game's own (factor 1)")
    guard = tick.index("if (f == applied || refused) return;")
    known = tick.index("if (!evil_hd_foliage_known(have)) {")
    write = tick.index("memcpy(GP(EVIL_HD_FOLIAGE_DEFAULTS), want, sizeof want);")
    check(guard < known < write and tick.count("memcpy(GP(") == 1,
          "the host writes the game's defaults with Evil HD off, or before checking they are the game's")
    check("evil_hd_foliage(f, want);" in tick and "applied = f;" in tick[write:] and 'hos_log("evil hd: %s' in tick[write:],
          "the host does not write the rule's distances, keep what it wrote, or say so")
    check("refused = 1;" in tick[known:write] and "left alone" in tick[known:write], "bytes not the game's are not left alone")
    check(re.search(r"^volatile float hos_evil_hd_factor = 1\.0f;", host, re.M), "the factor does not start at the game's own")
    vi = (ROOT / "host" / "nn_vi.c").read_text(encoding="utf-8")
    check("hos_evil_hd_tick(rx_option(HOS_OPT_EVIL_HD, 0));" in vi, "host/nn_vi.c does not give the row to the host each frame")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
    check("enum { HOS_OPT_EVIL_HD = 420 };" in api, "no option id for the row")
    ids = re.findall(r"HOS_OPT_\w+ = (\d+)", api)
    check(ids.count("420") == 1, "option id 420 is another option's too")
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    check("if (id == HOS_OPT_EVIL_HD) return evil_hd_now();" in replay, "the renderer does not answer with Evil HD as it is now (the row, F2)")
    menu_h = (ROOT / "gpu" / "vk" / "vk_menu.h").read_text(encoding="utf-8")
    check(re.search(r"^\s*int evil_hd = 0;", menu_h, re.M), "the row is not Off unless chosen")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    check('MENU_HEADING(TAB_GRAPHICS, "Evil HD"),' in menu and '{TAB_GRAPHICS, "Evil HD", &opts.evil_hd, 0, 1, 1, tx_onoff,' in menu,
          "the Graphics tab has no Evil HD row, Off and On (its key: evil_hd)")
    row = menu[menu.index('{TAB_GRAPHICS, "Evil HD", &opts.evil_hd'):]
    row = row[:row.index("},") + 2]
    # ((Triforce, 11-25) the row changes at once (F2 too): the foliage reaches the areas entered after; its help says so)
    check("hn_evil_hd, false, true}" in row and "4 times as far" in row, "the row's help does not tell of the render distance")


def check_docs():
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `HOS_EVIL_HD=0`, `=1`, `HOS_EVIL_HD_DIST=<1..4>` |" in dev, "the development guide has no row for the switches")
    check("| `evil_hd` | 0 Off" in dev, "the options file's table has no evil_hd")
    readme = (ROOT / "readme.md").read_text(encoding="utf-8")
    check("| Evil HD | Off, On" in readme and "has Evil HD, Upscaling, Anti-aliasing, N64 Classic, Frame generation" in readme, "the readme has no Evil HD row")


def check_game():
    """The defaults' place in the game's own main, when the exefs is on this PC (never in CI: no game there)"""
    sys.path.insert(0, str(ROOT / "nx2"))
    try:
        import kit
    except Exception:
        return "skipped (nx2/kit.py)"
    if not kit.EXEFS or not os.path.exists(os.path.join(kit.EXEFS, "main")):
        return "skipped (no exefs here)"
    try:
        import image as eden_image
        img = eden_image.EdenImage(kit.EXEFS)
    except Exception as e:
        return "skipped (%s)" % e
    have = [struct.unpack("<f", struct.pack("<I", img.word(0x83f0fd38 + 4 * i)))[0] for i in range(8)]
    check(have == [40.0, 60.0, 35.0, 30.0, 40.0, 135.0, 10.0, 45.0], "the game's main has other values there: %r" % have)
    # (each default's address made once, by adrp + add in the foliage LOD settings' reader, which names Dist_Undergrowth0)
    words = [img.word(a) for a in range(0x82c0d300, 0x82c0d6b0, 4)]
    adds = 0
    for i, w in enumerate(words[:-1]):
        if (w & 0x9f00001f) == 0x90000008 and (words[i + 1] & 0xffc003ff) == 0x91000108:   # adrp x8 / add x8, x8, #lo
            immlo, immhi = (w >> 29) & 3, (w >> 5) & 0x7ffff
            pc = 0x82c0d300 + 4 * i
            page = (pc & ~0xfff) + (((immhi << 2) | immlo) << 12)
            if page + ((words[i + 1] >> 10) & 0xfff) in [0x83f0fd38 + 4 * k for k in range(8)]:
                adds += 1
    check(adds == 8, "the foliage LOD settings' reader does not pass the eight defaults' addresses (%d found)" % adds)
    return "the game's eight defaults and their reader checked"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="clang")
    a = ap.parse_args()
    check_rule(a.cc)
    check_source()
    check_docs()
    print("test_evil_hd_foliage: ok (%s)" % check_game())


if __name__ == "__main__":
    main()
