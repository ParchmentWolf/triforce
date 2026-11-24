"""The HUD on a picture wider than 16:9 (host/oot_wide_hud.h, host/oot_wide_hud.c, nx2/prompt_assets.py HUD_SIDE_PANES).

Screen edges moves the side-anchored HUD panes and animation states. Middle keeps the HUD in the middle 16:9. The rules checked here,
without the game:

- A layout in the middle: its projection times the squeeze, nothing moved. A kept one (a fade, a menu's background):
  untouched. A 16:9 picture (squeeze 1) or no squeeze: untouched.
- A layout at an edge (the lab's switch): a point at the 16:9 grid's right edge lands on the picture's right edge, one
  at its left edge on the picture's left edge, and the layout keeps its shape.
- A pane moved in a layout goes as far as a whole layout moved by its
  projection: a corner pane lands on the picture's corner through the middle projection.
- prompts/wide.bin: one entry per pane and copy of each layout, and one per bound x key at an edge, with the endpoint delta
  adjusted where needed. A changed layout is skipped independently.

python -I -B tests/test_wide_hud.py
"""
from contextlib import redirect_stderr
from io import StringIO
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import prompt_assets  # noqa: E402

FIXTURE = r'''
#include <math.h>
#include <stdio.h>
#include "oot_wide_hud.h"

static int fails;
#define CHECK(cond, what) do { if (!(cond)) { fails++; printf("FAIL line %d: %s\n", __LINE__, what); } } while (0)
static int near(float a, float b) { return fabsf(a - b) < 1e-4f; }

/* clip x of the layout's point x through the projection (first column's m00, the move m03) */
static float clip(const float first[4], float move, float x) { return first[0] * x + move; }

int main(void) {
    const float m00 = 2.0f / 3840.0f;
    const float q = (16.0f / 9.0f) / (21.0f / 9.0f);   /* a 21:9 picture */
    float first[4], move;

    /* the middle */
    first[0] = m00, first[1] = first[2] = first[3] = 0, move = 0;
    oot_hud_row(first, &move, q, 0, OOT_HUD_MIDDLE);
    CHECK(near(clip(first, move, 1920.0f), q) && near(clip(first, move, -1920.0f), -q) && move == 0.0f, "the middle 16:9");

    /* kept, and a 16:9 picture */
    first[0] = m00, move = 0;
    oot_hud_row(first, &move, q, 1, OOT_HUD_RIGHT);
    CHECK(first[0] == m00 && move == 0.0f, "a kept layout is untouched");
    oot_hud_row(first, &move, 1.0f, 0, OOT_HUD_RIGHT);
    CHECK(first[0] == m00 && move == 0.0f, "a 16:9 picture is untouched");
    oot_hud_row(first, &move, 0.0f, 0, OOT_HUD_LEFT);
    CHECK(first[0] == m00 && move == 0.0f, "no squeeze: untouched");

    /* the edges */
    first[0] = m00, move = 0;
    oot_hud_row(first, &move, q, 0, OOT_HUD_RIGHT);
    CHECK(near(clip(first, move, 1920.0f), 1.0f), "the grid's right edge on the picture's right edge");
    CHECK(near(clip(first, move, 1920.0f) - clip(first, move, -1920.0f), 2.0f * q), "its shape kept");
    first[0] = m00, move = 0;
    oot_hud_row(first, &move, q, 0, OOT_HUD_LEFT);
    CHECK(near(clip(first, move, -1920.0f), -1.0f), "the grid's left edge on the picture's left edge");

    /* a pane moved in the layout: as far as the projection would move it */
    const float out = oot_hud_out(q);
    first[0] = m00, move = 0;
    oot_hud_row(first, &move, q, 0, OOT_HUD_MIDDLE);
    CHECK(near(clip(first, move, 1920.0f + out), 1.0f), "the right corner pane on the picture's corner");
    CHECK(near(clip(first, move, -1920.0f - out), -1.0f), "the left corner pane on the picture's corner");
    CHECK(near(clip(first, move, 1626.0f + out) - 1.0f, clip(first, move, 1626.0f) - q), "a pane beside it keeps its distance to the edge");
    CHECK(oot_hud_out(1.0f) == 0.0f && oot_hud_out(0.0f) == 0.0f && oot_hud_out(1.5f) == 0.0f, "nothing on a 16:9 or narrower picture");
    CHECK(near(oot_hud_out((16.0f / 9.0f) / (32.0f / 9.0f)), 1920.0f), "32:9: a whole half grid further out");

    /* the classes */
    CHECK(oot_hud_keep_bit(0x84c04fb0ULL) == 2u && oot_hud_keep_bit(0x84c08300ULL) == 0u, "the menus' background is kept, the map's screen is not");

    printf(fails ? "wide hud: FAILED\n" : "wide hud: all checks passed\n");
    return fails != 0;
}
'''


def layout(name, panes, curves=()):
    """a made-up layout as nx2/prompt_assets.py reads one: "BFFH", the names' and the records' tables' offsets at +0x118 and
    +0x120, the count at +0x130, the name before "RootPane" among the texts; panes: [(name, x)]; curves: [(value past the
    last key, [(value, slope)])], each an array as layout_keys reads one, 8-aligned, the first value 8 bytes before it"""
    names = ["RootPane"] + [n for n, _ in panes]
    xs = [0.0] + [x for _, x in panes]
    n = len(names)
    head = 0x140
    names_at, recs_at = head, head + 8 * n
    rec0 = recs_at + 8 * n
    texts_at = rec0 + 0x44 * n
    texts = b"\0" + name.encode() + b"\0"
    offs = []
    for t in names:
        offs.append(texts_at + len(texts))
        texts += t.encode() + b"\0"
    b = bytearray(texts_at) + texts
    b[0:4] = b"BFFH"
    struct.pack_into("<QQ", b, 0x118, names_at, recs_at)
    struct.pack_into("<I", b, 0x130, n)
    for k in range(n):
        struct.pack_into("<Q", b, names_at + 8 * k, offs[k])
        struct.pack_into("<Q", b, recs_at + 8 * k, rec0 + 0x44 * k)
        struct.pack_into("<f", b, rec0 + 0x44 * k + 0x10, 1.)
        struct.pack_into("<i", b, rec0 + 0x44 * k + 0x28, 0 if k else -1)
        struct.pack_into("<f", b, rec0 + 0x44 * k + 0x1c, xs[k])
    bindings = {"DoCommand_00": [("PosType", 0x01600f7f)], "MapMenu_00": [("MapType", 0x0165177f), ("DungeonMiniMapPattern", 0x0165377f)],
                "SaveLoadIcon_00": [("EnableText", 0x01600f7f)]}
    for i, (last, keys) in enumerate(curves):
        b += bytes(-len(b) % 8)
        values = len(b)
        b += struct.pack("<ff", last, 0.0)
        b += struct.pack("<QII", len(b) + 16, 2 * len(keys), 4)
        for value, slope in keys:
            b += struct.pack("<ff", value, slope)
        if i < len(bindings.get(name, [])):
            anim, path = bindings[name][i]
            if name == "MapMenu_00":
                path = 0x01605f7f if anim == "MapType" else 0x0160677f
            b += b"\0"
            text = len(b)
            b += anim.encode() + b"\0"
            token = len(b)
            b += path.to_bytes(6, "little")
            b += bytes(-len(b) % 8)
            desc = len(b)
            channels = 1 if name == "SaveLoadIcon_00" else 2
            b += struct.pack("<Q4H", token, 0, 65535, channels, 14)
            curve = len(b)
            b += struct.pack("<QQ", 0, values)
            curves_at = [curve]
            if channels == 2:
                y_curve = len(b)
                b += struct.pack("<QQ", 0, y_curve + 16)
                b += struct.pack("<ffQIIff", 0, 0, y_curve + 40, 2, 4, -690, 0)
                curves_at.append(y_curve)
            tables = len(b)
            b += struct.pack("<Q", desc) + struct.pack(f"<{channels}Q", *curves_at)
            b += struct.pack("<QQIIQII", text, tables, 1, 8, tables+8, channels, 8)
    return bytes(b)


GOOD = [("N_VRS_00", 1626.0), ("N_ScaleL_00", -1920.0), ("N_ScaleR_00", 1920.0), ("N_SubItemBaseFishing_00", 1270.0)]
MAP = [("N_VRS_00", 1536.0), ("N_MiniMapCap_00", 1470.0), ("N_LocalMap_00", 0.0), ("N_ItemIcon_00", 1666.0),
       ("N_Field_01", 1490.0), ("N_Dungeon_01", 1536.0), ("N_MiniMapReplace_00", 1470.0), ("P_MiniMapFrame_00", 1536.0),
       ("S_Floor_00", 1706.0), ("P_CapDungeon_00", 1536.0), ("N_MapIcon_00", 0.0), ("N_PatternDungeonMini_01", 0.0)]
# (the icons' layers: at 0 for the whole-screen map's patterns, at the small map's place for its own; then two curves that
# are not places: one with a slope, one with another value)
MAP_CURVES = [(0.0, [(0.0, 0.0), (0.0, 0.0), (1490.0, 0.0), (1490.0, 0.0), (0.0, 0.0)]),
              (1536.0, [(0.0, 0.0), (1536.0, 0.0), (1536.0, 0.0)]),
              (0.0, [(0.0, 0.0), (1.0, 0.5), (2.0, 0.0)]),
              (0.0, [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)])]


def archive(status=None, the_map=None):
    one = layout("PlayerStatus_00", GOOD) if status is None else status
    two = layout("MapMenu_00", MAP, MAP_CURVES) if the_map is None else the_map
    extra = (layout("ActionGuideTips_00", [("N_Guide_00", -1140)]) +
             layout("Location_00", [("N_SmallDisplay_00", -1720), ("N_Large_00", 0)]) +
             layout("EventSkip_00", [("W_GuideBg_00", 2110), ("Pa_Skip_00", 1796)]) +
             layout("ChallengeAttention_00", [("N_Challenge_00", 660), ("T_Guide_00", 1716), ("T_Icon_00", 1770)]) +
             layout("PaNumDisplay_00", [("P_NumBase_00", 1360), ("P_NumBaseLine_00", 1360), ("P_BaseDecide_00", 1360),
                                      ("N_IconPos_00", 1454), ("A_Num_00", 1482), ("N_PlusMinus_00", 1528)]) +
             layout("NumDisplay_00", [("Pa_Parts_00", 0), ("Pa_Parts_01", 0), ("A_Bottle_00", 1300)]) +
             layout("DoCommand_00", [("N_PosType_00", 234)], [(232, [(234, 0), (724, 0), (724, 0), (466, 0)])]) +
             layout("SaveLoadIcon_00", [("N_InOut_00", -1720)], [(-3460, [(1740, 0), (1740, 0), (-1720, 0)])]))
    return b"SARC" + bytes(60) + layout("Other_00", [("N_ScaleL_00", -1920.0)]) + one + two + extra + one + two + extra


class WideHudTest(unittest.TestCase):
    def test_rules(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory(prefix="widehud-") as d:
            tmp = Path(d)
            (tmp / "t.c").write_text(FIXTURE, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-O1", "-I", str(ROOT / "host"),
                                    str(tmp / "t.c"), "-o", str(binary), "-lm"], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("all checks passed", run.stdout)

    def test_table(self):
        blarc = archive()
        got = prompt_assets.wide_panes(blarc)
        # (the hearts' layout: four panes; the map's: eight panes, the two keys at 1490, the two at 1536 and that curve's
        # value past its last key; two copies of each)
        self.assertEqual(len(got), 2 * (4 + 8 + 2 + 2 + 1 + 17))
        for off, side, x in got:
            self.assertEqual(struct.unpack_from("<f", blarc, off)[0], x)

        self.assertEqual({x for _, side, x in got if side < 0}, {-1920.0, -1720.0, -1140.0, -3460})
        self.assertEqual({x for _, side, x in got if side > 0}, {1920.0, 1626.0, 1270.0, 1536.0, 1470.0, 1490.0, 1706.0, 2110, 1796, 660, 1716, 1770, 1740, 0, 724, 1300})
        first = blarc.index(layout("PlayerStatus_00", GOOD))
        self.assertTrue(all(off >= first for off, _, _ in got))        # (the other layout's pane of the same name: left)
        self.assertNotIn(1666.0, {x for _, _, x in got})                 # (the whole-screen map's own pane: left)
        self.assertEqual(len({off for off, _, _ in got}), len(got))
        with tempfile.TemporaryDirectory(prefix="widehud-") as d:
            path = Path(d) / "wide.bin"
            prompt_assets.write_wide(path, got)
            raw = path.read_bytes()
        self.assertEqual(raw[:4], b"HPWD")
        self.assertEqual(struct.unpack_from("<I", raw, 4)[0], len(got))
        self.assertEqual(len(raw), 8 + 12 * len(got))
        self.assertEqual(struct.unpack_from("<Ib3xf", raw, 8), got[0])

    def test_parent_grid(self):
        lay = bytearray(layout("HUD", [("Parent", 1520), ("Child", -130)]))
        records = list(prompt_assets.layout_panes(lay).values())
        struct.pack_into("<i", lay, records[2] + 0x28, 1)
        self.assertEqual(prompt_assets.hud_grid_x(lay, records, records[2]), 1390)
        self.assertIsNone(prompt_assets.hud_grid_x(lay, records, records[2], {records[1]}))
        struct.pack_into("<f", lay, records[1] + 0x10, 2.)
        self.assertIsNone(prompt_assets.hud_grid_x(lay, records, records[2]))

    def test_keys(self):
        lay = layout("MapMenu_00", MAP, MAP_CURVES)
        self.assertEqual(prompt_assets.hud_translation_path(82), 0x0165177f)
        self.assertEqual(prompt_assets.hud_translation_path(86), 0x0165377f)
        path = prompt_assets.hud_translation_path(list(prompt_assets.layout_panes(lay)).index("N_MapIcon_00"))
        keys = prompt_assets.hud_track_keys(lay, "MapType", path, {1490: 1}, 2)
        self.assertEqual(list(keys.values()), [(1, 1490)] * 2)
        self.assertIsNone(prompt_assets.hud_track_keys(lay, "MapType", 0x0165377f, {1490: 1}, 2))
        wrong_attr = lay.replace(struct.pack("<4H", 0, 65535, 2, 14), struct.pack("<4H", 0, 65535, 2, 15))
        self.assertIsNone(prompt_assets.hud_track_keys(wrong_attr, "MapType", path, {1490: 1}, 2))

    def test_track_guards(self):
        name = "MapMenu_00"
        sides = prompt_assets.HUD_SIDE_PANES[name]
        def rows(blob):
            return prompt_assets.wide_layout(blob, name, sides)
        def parent(child, ancestor):
            lay = bytearray(layout(name, MAP, MAP_CURVES))
            panes = prompt_assets.layout_panes(lay)
            struct.pack_into("<i", lay, panes[child] + 0x28, list(panes).index(ancestor))
            return lay
        self.assertTrue(rows(parent("N_PatternDungeonMini_01", "N_MapIcon_00")))
        self.assertIsNone(rows(parent("N_MapIcon_00", "N_PatternDungeonMini_01")))
        self.assertIsNone(rows(parent("N_Field_01", "N_MapIcon_00")))
        lay = layout(name, MAP, MAP_CURVES)
        for fields in [(0, 0, 2, 14), (0, 65535, 1, 14), (1, 65535, 2, 14)]:
            self.assertIsNone(rows(lay.replace(struct.pack("<4H", 0, 65535, 2, 14), struct.pack("<4H", *fields))))
        self.assertTrue(rows(layout(name, MAP, [(0, [(0, 0), (1490, 0), (0, 0)]), *MAP_CURVES[1:]])))
        for slopes in [(1, 0), (0, 1)]:
            ramp = [(0, slopes[0]), (1490, slopes[1]), (0, 0)]
            self.assertIsNone(rows(layout(name, MAP, [(0, ramp), *MAP_CURVES[1:]])))

    def test_static_guards(self):
        name = "ActionGuideTips_00"
        sides = prompt_assets.HUD_SIDE_PANES[name]
        def guide(x):
            return layout(name, [("N_Guide_00", x)])
        self.assertIsNone(prompt_assets.wide_layout(guide(-640), name, sides))
        self.assertTrue(prompt_assets.wide_layout(guide(-641), name, sides))
        self.assertIsNone(prompt_assets.wide_layout(guide(-641) + bytes.fromhex("7f0f60010000"), name, sides))
        duplicate = layout(name, [("N_Guide_00", -642), ("N_Guide_00", -641)])
        last = prompt_assets.layout_panes(duplicate)["N_Guide_00"]
        self.assertEqual(struct.unpack_from("<f", duplicate, last + 0x1c)[0], -641)
        self.assertIsNone(prompt_assets.wide_layout(duplicate, name, sides))
        good = archive()
        removed = prompt_assets.wide_layout(good, name, sides)
        expected = [entry for entry in prompt_assets.wide_panes(good) if entry not in removed]
        self.assertEqual(prompt_assets.wide_panes(good.replace(guide(-1140), guide(-640))), expected)

    def test_ring_clash_and_independent_layout_failure(self):
        good = archive()
        def entries(name):
            return set(prompt_assets.wide_layout(good, name, prompt_assets.HUD_SIDE_PANES[name]))
        action = entries("DoCommand_00")
        tips = entries("ActionGuideTips_00")
        all_entries = prompt_assets.wide_panes(good)
        off = min(action)[0]
        ring = [(0, 0, 0, [(off + 3, b"x")])]
        bad = good.replace(layout("ActionGuideTips_00", [("N_Guide_00", -1140)]),
                           layout("ActionGuideTips_00", [("N_Guide_00", -640)]))
        for blob, omitted in [(good, action), (bad, action | tips)]:
            log = StringIO()
            with redirect_stderr(log):
                self.assertEqual(prompt_assets.wide_panes(blob, ring), [e for e in all_entries if e not in omitted])
            self.assertIn("DoCommand_00: HUD edge position overlaps a Talk ring run", log.getvalue())
            self.assertEqual("ActionGuideTips_00: unknown HUD layout" in log.getvalue(), blob == bad)

    def test_unknown_layout(self):
        self.assertIsNone(prompt_assets.wide_panes(b"SARC" + bytes(60)))                                   # (no such layout)
        def status(blob):
            return prompt_assets.wide_layout(blob, "PlayerStatus_00", prompt_assets.HUD_SIDE_PANES["PlayerStatus_00"])
        def map_rows(blob):
            return prompt_assets.wide_layout(blob, "MapMenu_00", prompt_assets.HUD_SIDE_PANES["MapMenu_00"])
        self.assertTrue(prompt_assets.wide_panes(archive(the_map=b"")))  # other layouts survive a missing map
        self.assertIsNone(status(archive(status=layout("PlayerStatus_00", GOOD[:3]))))   # (a pane missing)
        moved = [(n, 1800.0 if n == "N_ScaleR_00" else x) for n, x in GOOD]
        self.assertIsNone(status(archive(status=layout("PlayerStatus_00", moved))))      # (not at the corner)
        twice = layout("PlayerStatus_00", GOOD + [("N_Other_00", 1270.0)])
        self.assertIsNone(status(archive(status=twice)))                                 # (a place held elsewhere)
        other = layout("MapMenu_00", MAP + [("N_Else_00", 1706.0)], MAP_CURVES)
        self.assertIsNone(map_rows(archive(the_map=other)))                                # (the same, the map's)
        ramp = layout("MapMenu_00", MAP, MAP_CURVES + [(0.0, [(0.0, 0.0), (1536.0, 3.0)])])
        self.assertIsNone(map_rows(archive(the_map=ramp)))                                 # (a key that moves there)
        self.assertIsNone(map_rows(archive(the_map=b"")))                                  # (no map layout)
        self.assertIsInstance(prompt_assets.WIDE, float)   # (the icons' own constant: a table of this file once took its name)

    def test_wired(self):
        host = (ROOT / "host/oot_wide_hud.c").read_text(encoding="utf-8")
        self.assertIn('hos_ini_option("ultrawide_hud", 0)', host)
        prompts = (ROOT / "host/prompts.c").read_text(encoding="utf-8")
        self.assertIn("hos_wide_hud_out()", prompts)
        wide = (ROOT / "nx2/oot_wide.py").read_text(encoding="utf-8")
        self.assertIn("hos_wide_hud_row(c, c->x[0] - 0x1b8, _row, &_tx);", wide)
        menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
        # ((Triforce, options_version 7) the Ultrawide group's HUD position, kept as ultrawide_hud=, which oot_wide_hud.c reads)
        self.assertIn('"HUD position", &opts.wide_hud, 0, 1, 1, tx_wide_hud,', menu)
        self.assertIn('{"HUD position", "ultrawide_hud"}', menu)


if __name__ == "__main__":
    unittest.main()
