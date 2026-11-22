"""A lone Alt does not freeze the start-up screen (host/display.c keymenu_dropped, wndproc; no game, no window).

After Casual Gamer's #dev-fixes post. Pressed and let go alone, Alt has DefWindowProc enter the menu loop (WM_SYSCOMMAND with
SC_KEYMENU) on the window's thread, which during the start-up screen is the one waiting for the shaders: the screen froze
until a key was pressed. The window has no menu bar, so the command is answered 0 there.

Cuts keymenu_dropped out of display.c and runs it with stand-ins for the Windows types: a lone Alt's command (lp 0) and one
for a letter with Alt (lp the character) are dropped, Alt+Space's (the system menu) is not, nor are the other system commands
(SC_CLOSE: Alt+F4; SC_SCREENSAVE; SC_MAXIMIZE), whatever their low bits; HOS_ALT_MENU=1 drops none. Then the source: the
window procedure asks it first in WM_SYSCOMMAND and returns 0, and Alt+Enter and F10 are still WM_SYSKEYDOWN's; the switch is
in docs/development.md.

    python -I -B tests/test_alt_menu.py [--cxx g++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    if text.count(marker) != 1:
        raise SystemExit("FAIL: not found once in display.c: " + marker)
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <cstdio>
#include <cstdlib>
#include <cstdint>
typedef uintptr_t WPARAM;
typedef intptr_t LPARAM;
#define SC_KEYMENU 0xF100
#define SC_CLOSE 0xF060
#define SC_SCREENSAVE 0xF140
#define SC_MAXIMIZE 0xF030
@@DROPPED@@
#define CHECK(x) do { if (!(x)) { std::printf("line %d: %s\n", __LINE__, #x); return 1; } } while (0)
int main(int argc, char**) {
    if (argc > 1) {   // (HOS_ALT_MENU=1: as before)
        CHECK(!keymenu_dropped(SC_KEYMENU, 0) && !keymenu_dropped(SC_KEYMENU, 'f'));
        std::printf("alt menu: HOS_ALT_MENU=1 leaves the menu loop to Windows, as before\n");
        return 0;
    }
    CHECK(keymenu_dropped(SC_KEYMENU, 0));          // (a lone Alt, or F10 let through)
    CHECK(keymenu_dropped(SC_KEYMENU | 3, 0));      // (the low four bits are Windows' own)
    CHECK(keymenu_dropped(SC_KEYMENU, 'f'));        // (Alt and a letter: a menu's mnemonic, and there is no menu)
    CHECK(!keymenu_dropped(SC_KEYMENU, ' '));       // (Alt+Space: the system menu)
    CHECK(!keymenu_dropped(SC_CLOSE, 0) && !keymenu_dropped(SC_SCREENSAVE, 0) && !keymenu_dropped(SC_MAXIMIZE, 0));
    std::printf("alt menu: a lone Alt enters no menu loop\n");
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    display = (ROOT / "host/display.c").read_text(encoding="utf-8")
    fn = block(display, "static int keymenu_dropped(WPARAM wp, LPARAM lp) {")
    proc = block(display, "static LRESULT CALLBACK wndproc(HWND w, UINT msg, WPARAM wp, LPARAM lp) {")
    sys_cmd = proc[proc.index("case WM_SYSCOMMAND:"):]
    sys_cmd = sys_cmd[:sys_cmd.index("break;")]
    if "if (keymenu_dropped(wp, lp)) return 0;" not in sys_cmd or \
            sys_cmd.index("keymenu_dropped") > sys_cmd.index("SC_SCREENSAVE"):
        raise SystemExit("FAIL: the window procedure does not answer a lone Alt's menu command itself")
    sys_key = proc[proc.index("case WM_SYSKEYDOWN:"):]
    if "if ((wp == VK_RETURN && (lp & (1 << 29))) || wp == VK_F10) {" not in sys_key[:sys_key.index("break;")]:
        raise SystemExit("FAIL: Alt+Enter and F10 are no longer WM_SYSKEYDOWN's")
    if "`HOS_ALT_MENU=1`" not in (ROOT / "docs/development.md").read_text(encoding="utf-8"):
        raise SystemExit("FAIL: HOS_ALT_MENU is not in docs/development.md's switches")
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="alt-menu-") as tmp:
        src, exe = Path(tmp) / "alt.cpp", Path(tmp) / "alt.exe"
        src.write_text(FIXTURE.replace("@@DROPPED@@", fn), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], check=True)
        env = dict(os.environ)
        env.pop("HOS_ALT_MENU", None)
        ran = 0
        for argv, value in (([str(exe)], None), ([str(exe), "before"], "1")):
            if value is not None:
                env["HOS_ALT_MENU"] = value
            r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, creationflags=flags)
            print(r.stdout, end="")
            ran = ran or r.returncode
        if ran:
            raise SystemExit("FAIL: a lone Alt's menu command")
    print("PASS: a lone Alt enters no menu loop; Alt+Space, Alt+F4, Alt+Enter and F10 as they were")


if __name__ == "__main__":
    main()
