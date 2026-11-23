"""Exercise the lifted movie and viewport sites with open movie handles and synthetic presents.

And the menu sides beside the filled title movie (host/oot_title_movie.h, host/rx_backend.c host_wide_menus): none while
the movie alone shows; the picture's own margin while a menu opened over it runs (the file select, the file's box, the
Options, the system menus' backdrop: host/oot_menu.c tells each menu screen's class every frame it runs), and for
OOT_MENU_PRESENTS presents after its last update; none again after that. The title's own list is a menu screen too and is
no menu over the title. In play (no filled movie) the margin is the picture's whatever runs.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_wide

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

SOURCE = r"""
#include <cassert>
#include <cstring>
#include <cstdlib>
#include <initializer_list>
#include <thread>
extern "C" {
#include "oot_title_movie.h"
volatile int64_t hos_present_count;
int logs;
void hos_log(const char *, ...) { ++logs; }
}
volatile float hos_wide_ratio = 2.4f;
volatile float hos_wide_margin = (1 - (16.f / 9) / 2.4f) / 2;
struct Ctx { uint64_t x[32]; };
uint32_t recomp_load32(Ctx *, uintptr_t p) { uint32_t v; memcpy(&v, (void *)p, 4); return v; }
void recomp_store32(Ctx *, uintptr_t p, uint32_t v) { memcpy((void *)p, &v, 4); }
void movie(Ctx *c) { MOVIE_SITE }
void viewport(Ctx *c) { VIEWPORT_SITE }
void playback() {
    Ctx c{};
    float bounds[10]{};
    c.x[29] = (uintptr_t)bounds + 40;
    auto draw = [&](bool cover) {
        bounds[2] = 0;
        bounds[4] = 3840;
        movie(&c);
        if (cover) assert(bounds[2] == 0 && bounds[4] == 3840);
        else assert(bounds[2] > 0 && bounds[4] < 3840);
        c.x[2] = 0;
        c.x[4] = 1600;
        std::thread other([&] { viewport(&c); });
        other.join();
        assert(c.x[2] == 0 && c.x[4] == 1600);
        viewport(&c);
        assert((int32_t)c.x[2] == (cover ? -280 : 0));
        assert(c.x[4] == (cover ? 2160 : 1600));
        c.x[2] = 0;
        c.x[4] = 1600;
        viewport(&c);
        assert(c.x[2] == 0 && c.x[4] == 1600);
    };
    auto title = oot_movie_file("rom:/Event/Movie/Dm_Title_0005.webm");
    auto story = oot_movie_file("rom:/Event/Movie/Dm_Story_0010.WEBM");
    assert(title == OOT_MOVIE_TITLE && story == OOT_MOVIE_OTHER);
    assert(oot_movie_file("rom:/Else/Dm_Title_0005.webm") == OOT_MOVIE_OTHER);
    assert(oot_movie_file("rom:/Event/Movie/Dm_Title_0005.webm.bak") == OOT_MOVIE_NONE);
    draw(false);
    oot_movie_file_change(title, 1);
    oot_movie_file_change(title, 1);
    assert(!oot_movie_cover_recent() && logs == 0);
    draw(true);
    assert(oot_movie_cover_recent() && logs == 1);
    oot_movie_file_change(story, 1);
    draw(false);
    hos_present_count = 2;
    assert(oot_movie_cover_recent() && logs == 1);
    hos_present_count = 3;
    assert(!oot_movie_cover_recent() && logs == 2);
    oot_movie_file_change(title, -1);
    draw(false);
    oot_movie_file_change(story, -1);
    hos_wide_ratio = 32.f / 9;
    draw(false);
    hos_wide_ratio = 2.4f;
    draw(true);
    oot_movie_file_change(title, -1);
    draw(false);
}
// The menu sides' margin as host/rx_backend.c host_wide_menus gives it to the renderer
volatile uint32_t hos_wide_keep_mask;
static int mods_mode;
enum { HOS_OPT_MODS_MUSIC = 161 };
int rx_option(int id, int otherwise) { return id == HOS_OPT_MODS_MUSIC ? mods_mode : otherwise; }
BACKEND_SITES
static float margin_now() { return host_wide_menus(0xd); }
void menus() {
    const uint64_t title_list = 0x84c106e8, files = 0x84c0eba0, file_box = 0x84c0f840, options = 0x84c0f108,
                   backdrop = 0x84c04fb0, pause = 0x84c0baa8, hud = 0x84c08300;
    const float margin = hos_wide_margin;
    assert(margin > 0.1f);
    assert(!oot_title_menu_class(title_list) && !oot_title_menu_class(pause) && !oot_title_menu_class(hud) && !oot_title_menu_class(0));
    for (uint64_t c : {files, file_box, options, backdrop}) assert(oot_title_menu_class(c));
    Ctx c{};
    float bounds[10]{};
    c.x[29] = (uintptr_t)bounds + 40;
    auto frame = [&](bool title_movie, std::initializer_list<uint64_t> screens) {   // (one frame of the game: its screens, its draw, its present)
        for (uint64_t s : screens) oot_menu_screen_tick(s);
        if (title_movie) {
            bounds[2] = 0, bounds[4] = 3840;
            movie(&c);
            c.x[2] = 0, c.x[4] = 1600;
            viewport(&c);
            assert(c.x[4] == 2160);   // (the movie still fills the picture under a menu: the sides blur it)
        }
        hos_present_count = hos_present_count + 1;
    };
    hos_present_count = 100;
    auto title = oot_movie_file("rom:/Event/Movie/Dm_Title_0005.webm");
    oot_movie_file_change(title, 1);
    // the title alone, its own list running: no sides, and no menu's backdrop for the renderer
    for (int i = 0; i < 10; i++) frame(true, {title_list}), assert(margin_now() == 0.0f && !oot_menu_backdrop_runs());
    // 0.7's renderer-owned Mods page has no guest class. The title list alone does not request sides.
    mods_mode = 1;
    assert(margin_now() == 0.0f && !host_wide_backdrop());
    mods_mode = 2;
    for (int i = 0; i < 10; i++) frame(true, {title_list}), assert(margin_now() == margin && host_wide_backdrop());
    mods_mode = 1;
    assert(margin_now() == 0.0f && !host_wide_backdrop());
    mods_mode = 0;
    // the file select opened over it, with the backdrop or without, the title's list still running or not: the row's sides
    for (int i = 0; i < 10; i++) frame(true, {title_list, files}), assert(margin_now() == margin && oot_menu_backdrop_runs());
    for (int i = 0; i < 5; i++) frame(true, {files, file_box}), assert(margin_now() == margin);
    for (int i = 0; i < 5; i++) frame(true, {backdrop}), assert(margin_now() == margin);
    for (int i = 0; i < 5; i++) frame(true, {title_list, options}), assert(margin_now() == margin);
    // closed: the menu's last pictures keep the sides, then the title alone has none again
    for (int i = 0; i < OOT_MENU_PRESENTS - 1; i++) frame(true, {title_list}), assert(margin_now() == margin);
    assert(oot_menu_backdrop_runs());
    frame(true, {title_list});
    assert(margin_now() == 0.0f && !oot_menu_backdrop_runs());
    for (int i = 0; i < 10; i++) frame(true, {title_list}), assert(margin_now() == 0.0f);
    // screens that are no menu over the title change nothing there
    frame(true, {title_list, pause, hud}), assert(margin_now() == 0.0f);
    // in play, no filled movie: the picture's margin with a menu and without
    oot_movie_file_change(title, -1);
    for (int i = 0; i < 6; i++) frame(false, {hud});
    assert(margin_now() == margin && !oot_menu_backdrop_runs());   // (play, the item wheel's too: its blur is the wheel's)
    frame(false, {pause, backdrop}), assert(margin_now() == margin);
    assert(oot_wide_menu_margin(0.25f, 0, 0) == 0.25f && oot_wide_menu_margin(0.25f, 0, 1) == 0.25f);
    assert(oot_wide_menu_margin(0.25f, 1, 0) == 0.0f && oot_wide_menu_margin(0.25f, 1, 1) == 0.25f);
    assert(oot_menu_recent(10, 7) && !oot_menu_recent(10, 6) && !oot_menu_recent(10, -1));
}
int main() {
    playback();
    menus();
    int32_t y = 0, height = 1600;
    assert(oot_title_movie_cover(3840.f / 1600, &y, &height));
    assert(y == -280 && height == 2160);
    // Offset viewport, with an odd number of cropped rows.
    y = 13;
    height = 1440;
    assert(oot_title_movie_cover(3440.f / 1440, &y, &height));
    assert(height == 1935 && y == 13 - 247);
    // Near 12:5, rounding to a multiple of eight can land on either side.
    for (float ratio : {872.f/362, 864.f/361, 3848.f/1603}) {
        y = 0;
        height = 1080;
        assert(oot_title_movie_cover(ratio, &y, &height) && y < 0 && height > 1080);
    }
    for (float ratio : {16.f/10, 16.f/9, 2.425f, 32.f/9}) {
        y = 7;
        height = 1080;
        assert(!oot_title_movie_cover(ratio, &y, &height));
        assert(y == 7 && height == 1080);
    }
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", required=True)
    args = parser.parse_args()
    # the renderer's margin is the header's rule, and every menu screen's update tells its class, in both halves of
    # host/oot_menu.c (the Windows one with the mouse, the other without)
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    sites = backend[backend.index("static float host_wide_menus("):backend.index("int hos_mouse_pointer(")]
    menu = (ROOT / "host/oot_menu.c").read_text(encoding="utf-8")
    windows, other = menu.split("#else\n/* Not Windows:", 1)
    assert "oot_menu_screen_tick(peek64(screen));" in windows and "oot_menu_screen_tick(vt);" in other, \
        "host/oot_menu.c: a half does not tell the menu screens' classes"
    for name, value in (("OPTIONS_SCREEN_VTABLE", "0x84c0f108ULL"),):
        assert f"#define {name} {value}" in menu, "host/oot_menu.c: the Options screen's class is another"
    bench = (ROOT / "host/hos_bench.c").read_text(encoding="utf-8")
    assert "#define FILES_VT 0x84c0eba0ULL" in bench and "#define FILE_BOX_VT 0x84c0f840ULL" in bench and \
        "#define TITLE_VT 0x84c106e8ULL" in bench, "host/hos_bench.c: the start's screens' classes are others"
    assert "    0x84c04fb0ULL,   /* the pause and system menus' background */" in (ROOT / "host/oot_wide_hud.h").read_text(encoding="utf-8"), \
        "host/oot_wide_hud.h: the system menus' backdrop's class is another"
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp, "geometry.cpp")
        source.write_text(SOURCE.replace("MOVIE_SITE", oot_wide.MOVIE).replace("VIEWPORT_SITE", oot_wide.THUMB).replace("BACKEND_SITES", sites))
        exe = Path(tmp, "geometry.exe")
        host = ROOT / "host"
        obj = Path(tmp, "movie.o")
        includes = [] if os.name == "nt" else ["-I", str(host / "posix")]
        subprocess.run([args.cxx, "-x", "c", *includes, "-c", str(host / "oot_title_movie.c"),
                        "-o", str(obj)], check=True)
        subprocess.run([args.cxx, "-I", str(host), str(source), str(obj), "-pthread", "-o", str(exe)], check=True)
        env = os.environ.copy()
        env.pop("HOS_WIDE_KEEP", None)
        subprocess.run([str(exe)], env=env, check=True)


if __name__ == "__main__":
    main()
