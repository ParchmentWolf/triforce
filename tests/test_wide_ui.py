"""The HUD's pane planner (host/hos_wide_ui.c: ozwaldorf's planner for "Extended" ultrawide menus, NotRexed/Hookshot pull
request 2843) as Triforce uses it: the Display tab's HUD position row keeps its values, 0 Middle and 1 Screen edges.

- Middle, the default: nothing is planned and nothing moves, at 16:9 or wider: the game's layouts as before, and the
  projection site keeps its own squeeze (hos_ui_qx stays 0).
- Screen edges on a wider screen: a HUD layout's side panes move out by the screen's extra half width, its children keep the
  move they were made with, a pane spanning the canvas is drawn the screen's width, and a menu's layout is not moved; the
  row changes at once, back to Middle too.
- A narrower screen (4:3): nothing runs, whatever the row (this game's options over the game's screens take the layouts there
  to span the whole picture, gpu/vk/game_grid.h).
- Menu sides at Extended: a menu's side panes move out too, the HUD stays in the middle with HUD position at Middle.
- HOS_WIDE_UI=0: nothing runs, and host/oot_wide_hud.c moves the HUD's panes as the layouts load, as before this file.
- The wiring: nx2/oot_wide.py's pane sites, the renderer's two options, the hos_wide_hud_out gate.

python -I -B tests/test_wide_ui.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_wide  # noqa: E402

HEAD = '#include "%s"\n' % (ROOT / "gpu/vk/vk_api.h").as_posix() + r'''#include <math.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; } Ctx;
#define BASE 0x10000000ull
static unsigned char mem[0x40000];
volatile float hos_wide_squeeze, hos_wide_ratio;
volatile uint32_t hos_wide_keep_mask = 0xf;
static uint64_t recomp_load8(Ctx *c, uint64_t a) { (void)c; if (a < BASE || a >= BASE + sizeof mem) return 0; return mem[a - BASE]; }
static uint64_t recomp_load32(Ctx *c, uint64_t a) { uint32_t v; (void)c; if (a < BASE || a + 4 > BASE + sizeof mem) return 0; memcpy(&v, mem + (a - BASE), 4); return v; }
static uint64_t recomp_load64(Ctx *c, uint64_t a) { uint64_t v; (void)c; if (a < BASE || a + 8 > BASE + sizeof mem) return 0; memcpy(&v, mem + (a - BASE), 8); return v; }
static void recomp_store32(Ctx *c, uint64_t a, uint32_t v) { (void)c; memcpy(mem + (a - BASE), &v, 4); }
static void recomp_store64(Ctx *c, uint64_t a, uint64_t v) { (void)c; memcpy(mem + (a - BASE), &v, 8); }
typedef void (*A64Fn)(Ctx *);
A64Fn a64_lookup(uint64_t addr) { (void)addr; return NULL; }
static void hos_log(const char *f, ...) { (void)f; }
static int64_t hos_now_ns(void) { return 0; }
static int row_position, row_menus, row_placement;   /* (the renderer's answers: HUD position, Menu sides, HUD placement) */
static int row_health = HOS_HUD_DEFAULT_PLACEMENT;
int rx_option(int id, int otherwise) {
    if (id == HOS_OPT_HUD_POSITION) return row_position;
    if (id == HOS_OPT_MENU_SIDES) return row_menus;
    if (id == HOS_OPT_HUD_PLACEMENT) return row_placement;
    if (id == HOS_OPT_HUD_HEALTH) return row_health;
    return otherwise;
}
'''

MAIN = r'''
static void putf(uint64_t a, float v) { memcpy(mem + (a - BASE), &v, 4); }
static void put32(uint64_t a, uint32_t v) { memcpy(mem + (a - BASE), &v, 4); }
static void put64(uint64_t a, uint64_t v) { memcpy(mem + (a - BASE), &v, 8); }
static float getf(uint64_t a) { float v; memcpy(&v, mem + (a - BASE), 4); return v; }
static int near(float a, float b) { return a > b - 0.01f && a < b + 0.01f; }
static Ctx c;
#define HUD (BASE + 0x100)
#define MENU (BASE + 0x300)
#define STATUS (BASE + 0x500)
#define PANES (BASE + 0x1000)
#define NAMES (BASE + 0x8000)
#define STRINGS (BASE + 0x9000)
static uint64_t text_at = STRINGS;
static uint64_t text(const char *s) { const uint64_t a = text_at; memcpy(mem + (a - BASE), s, strlen(s) + 1); text_at += 64; return a; }
static void layout_named(uint64_t l, const char *name) {
    const uint64_t res = l + 0x180;
    put64(l + 0x100, PANES), put32(l + 0x13c, 64), put64(l + 0xf8, res);
    put64(res + 0x18, text(name)), put64(res + 0x20, NAMES);
}
static uint64_t pane_in(uint64_t layout, int i, const char *name, float x, float w, unsigned origin, unsigned type) {
    const uint64_t p = PANES + (uint64_t)i * 0xb0;
    put64(p + 0x18, layout), put64(NAMES + (uint64_t)i * 8, text(name));
    putf(p + 0x28, 1.0f), putf(p + 0x4c, x), putf(p + 0x58, w);
    put32(p + 0xa8, ((origin + 3) << 11) | (type << 22) | 1);
    return p;
}
static float place(uint64_t p, uint64_t parent, float x) {
    putf(p + 0x4c, x);
    hos_wide_ui_parent(parent);
    hos_wide_ui_placed(&c, p);
    return getf(p + 0x4c);
}
static float drawn_width(uint64_t p) {
    const float w = getf(p + 0x58);
    memcpy(c.vreg[0], &w, 4);
    hos_wide_ui_size(&c, p);
    float out;
    memcpy(&out, c.vreg[0], 4);
    return out;
}
static uint64_t root, left, heart, right, back, mroot, mleft, sroot, gauge;
static void frame(void) {
    place(sroot, 0, 0); place(gauge, sroot, -1140);
    place(root, 0, 0);
    const float moved = place(left, root, -1920) + 1920;
    place(heart, left, -1140 + moved); place(right, root, 1626); place(back, root, 0);
    place(mroot, 0, 0); place(mleft, mroot, -1920);
}
/* two presents and two frames: noted on the first frame, planned at the present, moved on the next */
static void settle(void) { for (int i = 0; i < 3; i++) hos_wide_ui_tick(), frame(); }
static void shape(float w, float h) {
    hos_wide_ratio = fabsf(w / h - 16.0f / 9.0f) < 0.001f ? 0.0f : w / h;
    hos_wide_squeeze = hos_wide_ratio > 0.0f ? fminf(1.0f, (16.0f / 9.0f) / hos_wide_ratio) : 0.0f;
}
int main(int argc, char **argv) {
    layout_named(HUD, "Talk_00"), layout_named(MENU, "Test_Menu_00");
    root = pane_in(HUD, 0, "RootPane", 0, 0, 1, 0), left = pane_in(HUD, 1, "N_Left_00", -1920, 60, 1, 0);
    heart = pane_in(HUD, 2, "P_Heart_00", -1140, 300, 1, 1), right = pane_in(HUD, 3, "P_Right_00", 1626, 240, 1, 1);
    back = pane_in(HUD, 4, "P_Back_00", 0, 3840, 1, 1);
    mroot = pane_in(MENU, 10, "RootPane", 0, 0, 1, 0), mleft = pane_in(MENU, 11, "P_Column_00", -1920, 400, 0, 1);
    layout_named(STATUS, "PlayerStatus_00");
    sroot = pane_in(STATUS, 20, "RootPane", 0, 0, 1, 0), gauge = pane_in(STATUS, 22, "Pa_HeartGauge_00", -1140, 1300, 1, 6);
    if (argc > 1 && !strcmp(argv[1], "off")) {   /* HOS_WIDE_UI=0: nothing runs whatever the rows */
        shape(3440, 1440), row_position = 1, row_menus = HOS_MENU_SIDES_EXTENDED;
        settle();
        CHECK(hos_wide_ui_off() && hos_ui_qx == 0.0f && getf(left + 0x4c) == -1920 && getf(mleft + 0x4c) == -1920);
        CHECK(drawn_width(back) == 3840);
        puts("ok: HOS_WIDE_UI=0");
        return 0;
    }
    CHECK(!hos_wide_ui_off());
    shape(1920, 1080);   /* 16:9, Screen edges: nothing */
    row_position = 1;
    settle();
    CHECK(hos_ui_qx == 0.0f && getf(left + 0x4c) == -1920 && getf(right + 0x4c) == 1626 && drawn_width(back) == 3840);
    shape(3440, 1440);   /* 21:9, Middle (the default): nothing, the projection site's own squeeze */
    row_position = 0;
    settle();
    CHECK(hos_ui_qx == 0.0f && getf(left + 0x4c) == -1920 && getf(right + 0x4c) == 1626 && drawn_width(back) == 3840);
    const float extra = 1920.0f * (3440.0f / 1440.0f / (16.0f / 9.0f) - 1.0f);   /* (reach: 21:9 is under 12:5) */
    row_position = 1;   /* Screen edges, at once */
    settle();
    CHECK(near(hos_ui_qx, (16.0f / 9.0f) / (3440.0f / 1440.0f)) && hos_ui_qy == 1.0f);   /* (the same squeeze as before) */
    CHECK(near(getf(left + 0x4c), -1920 - extra));         /* (the HUD's left side out, at the left edge) */
    CHECK(near(getf(heart + 0x4c), -1140 - extra));        /* (made from it: moved once) */
    CHECK(near(getf(right + 0x4c), 1626 + extra));         /* (far out on the right: out) */
    CHECK(near(drawn_width(back), 3840.0f * (1.0f + extra / 1920.0f)) && drawn_width(right) == 240);   /* (spans: wider) */
    CHECK(getf(mleft + 0x4c) == -1920);                    /* (a menu's: not moved) */
    row_position = 0;   /* back to Middle, at once */
    settle();
    CHECK(hos_ui_qx == 0.0f && getf(left + 0x4c) == -1920 && getf(right + 0x4c) == 1626 && drawn_width(back) == 3840);
    row_menus = HOS_MENU_SIDES_EXTENDED;   /* Extended: the menus' sides out, the HUD in the middle */
    settle();
    CHECK(near(getf(mleft + 0x4c), -1920 - extra) && getf(left + 0x4c) == -1920);
    row_menus = 1, row_position = 0;
    shape(1920, 1080);   /* HUD placement Custom at 16:9: the hearts' group 10% of the width right, 384 units */
    row_placement = 1, row_health = (10 + 16) | (16 << 6) | (100 << 12);
    settle();
    CHECK(near(getf(gauge + 0x4c), -1140 + 384) && getf(left + 0x4c) == -1920);
    row_placement = 0;   /* back to the game's */
    settle();
    CHECK(getf(gauge + 0x4c) == -1140);
    row_menus = 1, row_position = 1, row_placement = 1;
    shape(1440, 1080);   /* 4:3: nothing, whatever the rows */
    settle();
    CHECK(hos_ui_qx == 0.0f && getf(left + 0x4c) == -1920 && getf(right + 0x4c) == 1626 && drawn_width(back) == 3840);
    puts("ok: Middle, Screen edges, Extended, 16:9 and 4:3");
    return 0;
}
'''


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    engine = (ROOT / "host/hos_wide_ui.c").read_text(encoding="utf-8")
    body = "\n".join(line for line in engine.splitlines() if not line.startswith("#include"))
    with tempfile.TemporaryDirectory(prefix="wide-ui-") as tmp:
        src, exe = Path(tmp) / "wide_ui.c", Path(tmp) / "wide_ui.exe"
        src.write_text(HEAD + body + MAIN, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-O1", str(src), "-o", str(exe), "-lm"], check=True)
        plain = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}
        subprocess.run([str(exe)], env=plain, check=True)
        subprocess.run([str(exe), "off"], env=dict(plain, HOS_WIDE_UI="0"), check=True)

    sites = {off for off, _, _ in oot_wide.SITES}
    check(all(off in sites for off, _, _ in oot_wide.UI_SITES) and len(oot_wide.UI_SITES) == 9,
          "nx2/oot_wide.py's SITES lack the planner's nine pane sites")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    check("if (id == HOS_OPT_HUD_POSITION) return opts.wide_hud;" in replay and
          "if (id == HOS_OPT_MENU_SIDES) return opts.wide_menus;" in replay, "the renderer does not answer the two rows")
    hud = (ROOT / "host/oot_wide_hud.c").read_text(encoding="utf-8")
    check("edges_on() && hos_wide_ui_off() ? oot_hud_out(hos_wide_squeeze) : 0.0f" in hud,
          "the layouts' load-time moves are not left to HOS_WIDE_UI=0 alone")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    check("hos_wide_ui_tick();" in backend, "the plan is not made at each present")
    framegen = (ROOT / "gpu/vk/vk_framegen.cpp").read_text(encoding="utf-8")
    check(re.search(r"const int centred = opts\.wide_menus == 1 \|\| opts\.wide_menus == 2 \? opts\.wide_menus : 0;", framegen),
          "Extended draws the centred modes' sides")
    # (HUD placement's Custom minimap: the map screen's update wrapped after the menus' tick hook, once)
    import oot_patches
    head = oot_patches.MENU_TICK_HEAD
    lifted = '#include "a64.h"\n' + head + "    c->x[1] = 2;\n    return;\n}\n\nvoid f_other(Ctx *c) {\n}\n"
    once = oot_patches.patch_gameplay_hud_screen(oot_patches.patch_menu_tick(lifted))
    check(once.count("hos_gameplay_hud_screen(c, gameplay_hud_update_game);") == 1 and
          once.index(head) < once.index("void gameplay_hud_update_game(Ctx *__restrict A64_NOESC c) {\n    hos_oot_menu_tick(c,") and
          "extern void hos_gameplay_hud_screen(Ctx *c, A64Fn update);" in once and "void f_other(Ctx *c) {" in once,
          "the map screen's update is not wrapped around the game's body with the menus' tick in it")
    check(oot_patches.patch_gameplay_hud_screen(once) == once, "the wrapper goes in twice")
    print("PASS: the HUD planner at Middle, Screen edges and Extended, HUD placement Custom, its sites and wiring")


if __name__ == "__main__":
    main()
