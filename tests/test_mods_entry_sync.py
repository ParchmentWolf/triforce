"""The Mods entry comes and goes with the game's own buttons, by the game's own amount each frame (gpu/vk/
mods_entry_anim.h Anim::step, vk_menu.cpp mods_list_shown, draw_title_mods, draw_mods_row and menu_option_set, host/
oot_menu.c mods_list_tick, vk_api.h HOS_OPT_MODS_ALPHA; no game).

(Triforce, 11-20) The owner: "fix the mods button it should be synced with the timing of the other button ui so it
seamlessly moves and disappears with them". The entry under a game list's last button was drawn by a clock of the
renderer's own: 15 frames from the first frame the list ran, and gone 150 ms and a fade after the list's last report. A
probe of the title's list showed the game's own buttons' alpha in each button's box (+0x78, a float): 0 for the 1.5 s
the list runs before it shows, a rise over a second as the title opens, 1 to 0 in one frame as Options is chosen, and
15 frames as the list comes back. So the entry stood there a second and a half before the game's buttons and stayed
after them. The host tells that amount each frame now, and the entry shows as much.

This compiles mods_entry_anim.h alone and checks: with the game's amount told, the entry shows exactly that while the
list is there (nothing while the game shows nothing, however long the list has run; the rise as it is; all of it), it
does not lag behind a rise by a clock of its own, and a list whose reports stop goes as before (150 ms, then the
UnSelect's fade from where it was); not told (an older host), the list's In by the renderer's clock as before.

And reads the source: the host reads the amount from the last button's box, takes only a number from 0 to 1, tells it
before the frame's HOS_OPT_MODS_LIST, says at once that the list is not the entry's any more when another screen has
the cursor and the game's buttons are hidden, and leaves an entry not shown yet out of the mouse's reach; the renderer
keeps the amount, takes a list report without HOS_MODS_LIST_SHOWN as gone now, gives the title's entry the amount and
fades the System page's Mods and Quit by it.

    python -I -B tests/test_mods_entry_sync.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


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
#include <cmath>
#include <cstdio>
#include "mods_entry_anim.h"
using namespace mods_entry;
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static bool near(float a, float b, float tol = 1e-4f) { return std::fabs(a - b) <= tol; }
int main() {
    const int64_t t0 = 7000000000LL, ms = 1000000;
    {   // the title's opening: the list runs 1.5 s at nothing, then the game's own rise over a second
        Anim a;
        for (int k = 0; k < 90; k++) {   // (1.5 s of frames: the game shows nothing of its buttons)
            a.step(t0 + k * kFrameNs, false, 0, 0.0f);
            CHECK(a.shown == 0.0f);   // (the renderer's own clock had it whole after 15 frames)
        }
        float last = 0;
        for (int k = 0; k <= 60; k++) {   // (the game's rise: the entry's, frame for frame)
            const float game = (float)(k * k) / 3600.0f;
            a.step(t0 + (90 + k) * kFrameNs, false, 0, game);
            CHECK(near(a.shown, game) && a.shown >= last);
            last = a.shown;
        }
        CHECK(near(a.shown, 1.0f));
        a.step(t0 + 200 * kFrameNs, false, 0, 1.0f);
        CHECK(near(a.shown, 1.0f));
        // Options chosen: the game's buttons at nothing on that frame, the entry too
        a.step(t0 + 201 * kFrameNs, false, 0, 0.0f);
        CHECK(a.shown == 0.0f);
        // the list back: 15 frames by the game's amount, not that times a rise of the entry's own
        for (int k = 1; k <= 15; k++) {
            const float game = curve(kListIn, (float)k);
            a.step(t0 + (300 + k) * kFrameNs, false, 0, game);
            CHECK(near(a.shown, game));
        }
    }
    {   // a list whose reports stop (its screen went): there for 150 ms, then the UnSelect's fade from where it was
        Anim a;
        a.step(t0, false, 0, 0.8f);
        CHECK(near(a.shown, 0.8f));
        a.step(t0 + 100 * ms, false, 100 * ms, 0.8f);   // (within the 150 ms: still the list's)
        CHECK(near(a.shown, 0.8f));
        a.step(t0 + 150 * ms + 4 * kFrameNs, false, kListGoneNs + 4 * kFrameNs, 0.8f);
        CHECK(near(a.shown, 0.8f * curve(kUnSelect, 4.0f)) && a.shown < 0.8f && a.shown > 0.0f);
        a.step(t0 + 500 * ms, false, kListShownNs, 0.8f);
        CHECK(a.shown == 0.0f);
    }
    {   // gone at once: a list said to be the entry's no longer has no age to speak of (INT64_MAX, cut to kListShownNs)
        Anim a;
        a.step(t0, false, 0, 1.0f);
        a.step(t0 + kFrameNs, false, kListShownNs, 1.0f);
        CHECK(a.shown == 0.0f);
    }
    {   // not told (an older host): the list's In by the renderer's clock, as before
        Anim a;
        a.step(t0, false, 0);
        CHECK(near(a.shown, 0.0f));
        a.step(t0 + 15 * kFrameNs, false, 0);
        CHECK(near(a.shown, 1.0f));
        Anim b;
        b.step(t0, false, 0, -1.0f);
        b.step(t0 + 8 * kFrameNs, false, 0, -1.0f);
        CHECK(near(b.shown, curve(kListIn, 8.0f)));
    }
    {   // the amount the overlay draws the game's alpha with: itself in linear light, a^(1/2.2) in code values
        CHECK(list_amount(0.0f, false) == 0.0f && near(list_amount(1.0f, false), 1.0f) && near(list_amount(1.0f, true), 1.0f));
        CHECK(near(list_amount(0.25f, true), 0.25f) && near(list_amount(0.25f, false), 0.5325f, 1e-3f));
        CHECK(near(list_amount(0.5f, false), 0.7297f, 1e-3f) && list_amount(-1.0f, false) == 0.0f && near(list_amount(3.0f, false), 1.0f));
        float last = 0;
        for (int k = 0; k <= 100; k++) {
            const float v = list_amount((float)k / 100.0f, false);
            CHECK(v >= last && v >= (float)k / 100.0f - 1e-6f);   // (never back, never dimmer than the game's alpha)
            last = v;
        }
    }
    {   // the cursor's own animation is not the list's: focused at once, whatever the list shows
        Anim a;
        a.step(t0, true, 0, 0.5f);
        a.step(t0 + 2 * kFrameNs, true, 0, 0.5f);
        CHECK(near(a.focus, 1.0f) && near(a.shown, 0.5f));
    }
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()

    api = (VK / "vk_api.h").read_text(encoding="utf-8")
    check("enum { HOS_OPT_MODS_ALPHA = 162 };" in api, "HOS_OPT_MODS_ALPHA is not an option of its own number")

    host = (ROOT / "host" / "oot_menu.c").read_text(encoding="utf-8")
    tick = block(host, "static void mods_list_tick(uint64_t screen, int title, ModsCall *call) {")
    read = "if (!peek(peek64(l.b[last] + 0x58) + 0x78, &alpha, 4) || !(alpha >= 0.0f && alpha <= 1.0f)) alpha = 1.0f;"
    check(read in tick, "the host does not read the last button's alpha from its box, or takes anything for it")
    tell, report = "rx_option_set(HOS_OPT_MODS_ALPHA, (int)(alpha * 1000.0f + 0.5f));", "rx_option_set(HOS_OPT_MODS_LIST, HOS_MODS_LIST_SHOWN"
    check(tell in tick and tick.index(read) < tick.index(tell) < tick.index(report),
          "the amount is not told before the frame's list report")
    gone = "if (alpha <= 0.0f) rx_option_set(HOS_OPT_MODS_LIST, 0);"
    cursor = "if (!mods_cursor_button(screen, &pend) && !mods_held.button) {"
    check(cursor in tick and gone in tick and tick.index(read) < tick.index(cursor) < tick.index(gone) < tick.index(tell),
          "a list hidden under another screen is not said to be gone at once")
    check("if (alpha >= 0.5f) InterlockedExchange64(&mods_entry_ns, (LONG64)now);" in tick,
          "an entry the game does not show yet is within the mouse's reach")

    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    check("std::atomic<int> mods_list_alpha{-1};" in menu, "the renderer does not keep the game's amount (not told: -1)")
    shown = block(menu, "float mods_list_shown() {")
    check("return a < 0 ? -1.0f : mods_entry::list_amount((float)a / 1000.0f, dev.hdr);" in shown,
          "mods_list_shown is not the host's thousandths as the overlay has to draw them, or -1 while not told")
    setter = block(menu, "void menu_option_set(int id, int value) {")
    check("if (id == HOS_OPT_MODS_ALPHA) {" in setter and "mods_list_alpha.store(std::clamp(value, 0, 1000), std::memory_order_relaxed);" in setter,
          "the renderer does not take HOS_OPT_MODS_ALPHA")
    at = setter.index("if (id == HOS_OPT_MODS_LIST) {")
    listed = setter[at:setter.index("if (id == HOS_OPT_MODS_ENTER) {")]
    check("if (!(value & HOS_MODS_LIST_SHOWN)) {" in listed and "mods_list_ns.store(0, std::memory_order_release);" in listed and
          listed.index("mods_list_ns.store(0,") < listed.index("mods_list_bits.store(value,"),
          "a list report without HOS_MODS_LIST_SHOWN is not gone at once, or changes what kind of list it was")
    title = block(menu, "void draw_title_mods(ui::Ctx& c, bool sel, float cx, float cy, float k, float pitch) {")
    check("title_anim.step(now, sel, std::min<int64_t>(age, mods_entry::kListShownNs), mods_list_shown());" in title,
          "the title's entry is not given the game's amount")
    row = block(menu, "void draw_mods_row(ui::Ctx& c, bool sel) {")
    check("const int vtx_row = c.d->VtxBuffer.Size;" in row and "if (const float list = mods_list_shown(); list >= 0 && list < 1)" in row and
          "c.d->VtxBuffer[v].col = ui::alpha(c.d->VtxBuffer[v].col, list);" in row and
          row.index("const int vtx_row") < row.index("ui::button(c, a, b, names[i], mods_focus[i].shown);") < row.index("list >= 0 && list < 1"),
          "the System page's Mods and Quit are not faded by the game's amount")

    with tempfile.TemporaryDirectory(prefix="mods-entry-sync-") as tmp:
        src, exe = Path(tmp) / "sync.cpp", Path(tmp) / "sync.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the entry by the game's amount:\n" + r.stdout)
    print("PASS: the Mods entry shows as much as the game's own buttons, frame for frame, and goes when they do")


if __name__ == "__main__":
    main()
