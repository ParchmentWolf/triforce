"""The five ocarina note controls (host/nn_hid.c, gpu/vk/vk_api.h): unset by default, their lines in the options file,
and the shared-binding rules. A row starts unset, meaning the Switch button's own binding plays the note; only a row the
player bound takes that button's bit for the wait. A note row's keys are never taken from it and it takes none from
others, so one key can be a note and the D-pad direction that opens the ocarina at once; a normal row's rebinding still
takes its key from the other normal rows, and its gamepad input still swaps among them. A note row takes no mouse
button, from the page or from the file. The MOVE/CAM rows take no gamepad input.
python -I -B tests/test_ocarina_note_bindings.py   (needs a C compiler)
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    while text[end] in ";\n":
        end += 1
        if text[end - 1] == "\n":
            break
    return text[start:end]


def between(text, first, last):
    """from the line that holds first to the end of the block or statement that starts at last"""
    start = text.rindex("\n", 0, text.index(first)) + 1
    return text[start:text.index(last)] + block(text, last)


PRELUDE = r"""
#define _CRT_SECURE_NO_WARNINGS
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "vk_api.h"
#include "../../host/hold_toggle.h"   /* (hold-to-toggle's latch, beside the bindings) */
typedef long LONG;
typedef unsigned long DWORD;
#define VK_LBUTTON 0x01
#define VK_RBUTTON 0x02
#define VK_MBUTTON 0x04
#define VK_TAB 0x09
#define VK_RETURN 0x0D
#define VK_SHIFT 0x10
#define VK_CONTROL 0x11
#define VK_MENU 0x12
#define VK_CAPITAL 0x14
#define VK_SPACE 0x20
#define VK_LEFT 0x25
#define VK_UP 0x26
#define VK_RIGHT 0x27
#define VK_DOWN 0x28
#define VK_NUMPAD4 0x64
#define MAX_PATH 260
static LONG InterlockedExchange(volatile LONG *p, LONG v) { LONG o = *p; *p = v; return o; }
static LONG InterlockedCompareExchange(volatile LONG *p, LONG v, LONG c) { LONG o = *p; if (o == c) *p = v; return o; }
static void Sleep(int ms) { (void)ms; }
static void hos_log(const char *f, ...) { (void)f; }
static const char *ini_dir;
#ifdef _WIN32
#define EXE_SEP "\\"
#else
#define EXE_SEP "/"
#endif
static DWORD GetModuleFileNameA(void *m, char *b, DWORD n) { (void)m; return (DWORD)snprintf(b, n, "%s" EXE_SEP "hookshot.exe", ini_dir); }
#define hos_game_path_a(b,n) GetModuleFileNameA(0,b,n)
"""

MAIN = r"""
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
int main(int argc, char **argv) {
    (void)argc;
    ini_dir = argv[1];
    binds_load();
    /* (a) defaults: the five note rows are unset, so the game's own buttons play until the player binds one */
    CHECK(hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_L, 0) == 0
          && hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_R, 0) == 0
          && hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_A, 0) == 0
          && hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_X, 0) == 0);   /* (note_y: this folder's file has its key) */
    CHECK(hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_L, 0) == -1
          && hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 0) == -1
          && hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_A, 0) == -1
          && hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_Y, 0) == -1);
    /* (b) a file with lines for other controls: they load, the note rows it leaves out stay unset
       (this folder's has key_move_up=90 and pad_a=5) */
    CHECK(hos_binding(HOS_BIND_KEY, HOS_KEY_MOVE_UP, 0) == 'Z');
    CHECK(hos_binding(HOS_BIND_PAD, HOS_SW_A, 0) == HOS_PAD_GUIDE);
    CHECK(hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_A, 1) == 0);
    /* (c) a key_ line and a pad_ line for a note row load; a mouse button in one is not taken */
    CHECK(hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_Y, 0) == 78 && hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_Y, 1) == 0);
    CHECK(hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_X, 0) == HOS_PAD_NORTH);
    CHECK(hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_X, 1) == -1);   /* (one gamepad input a control) */
    CHECK(hos_binding(HOS_BIND_PAD, HOS_SW_X, 0) == HOS_PAD_NORTH);   /* X's own input, shared, not moved */
    /* (d) sharing: a normal row taking a note row's key leaves the note row holding it too... */
    hos_bind(HOS_BIND_KEY, HOS_KEY_OC_NOTE_A, 0, VK_NUMPAD4);
    hos_bind(HOS_BIND_KEY, HOS_SW_DOWN, 0, VK_NUMPAD4);
    CHECK(hos_binding(HOS_BIND_KEY, HOS_SW_DOWN, 0) == VK_NUMPAD4
          && hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_A, 0) == VK_NUMPAD4);
    /* ...and a note row's own rebinding takes its key from nobody */
    hos_bind(HOS_BIND_KEY, HOS_SW_B, 0, 'V');
    hos_bind(HOS_BIND_KEY, HOS_KEY_OC_NOTE_A, 0, 'V');
    CHECK(hos_binding(HOS_BIND_KEY, HOS_SW_B, 0) == 'V' && hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_A, 0) == 'V');
    /* two note rows can even share a key (the page shows both) */
    hos_bind(HOS_BIND_KEY, HOS_KEY_OC_NOTE_L, 0, 'V');
    CHECK(hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_A, 0) == 'V' && hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_L, 0) == 'V');
    /* a normal row still takes its key from the other normal rows (not from note rows) */
    hos_bind(HOS_BIND_KEY, HOS_SW_ZR, 0, 'V');
    CHECK(hos_binding(HOS_BIND_KEY, HOS_SW_B, 0) == 0 && hos_binding(HOS_BIND_KEY, HOS_SW_ZR, 0) == 'V'
          && hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_A, 0) == 'V');
    /* (e) pad inputs: a normal row's bind swaps among the Switch rows and leaves the note rows alone... */
    hos_bind(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 0, HOS_PAD_RSHOULDER);
    hos_bind(HOS_BIND_PAD, HOS_SW_B, 0, HOS_PAD_RSHOULDER);
    CHECK(hos_binding(HOS_BIND_PAD, HOS_SW_B, 0) == HOS_PAD_RSHOULDER
          && hos_binding(HOS_BIND_PAD, HOS_SW_R, 0) == HOS_PAD_SOUTH   /* r gives up RSHOULDER for B's old SOUTH */
          && hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 0) == HOS_PAD_RSHOULDER);   /* the note row is untouched */
    /* ...and a note row can hold the same pad input as a Switch row, with no swap */
    hos_bind(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 0, HOS_PAD_EAST);
    CHECK(hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 0) == HOS_PAD_EAST
          && hos_binding(HOS_BIND_PAD, HOS_SW_B, 0) == HOS_PAD_RSHOULDER && hos_binding(HOS_BIND_PAD, HOS_SW_R, 0) == HOS_PAD_SOUTH);
    hos_bind(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 0, -1);   /* (Delete in the page: unset again) */
    CHECK(hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 0) == -1);
    hos_bind(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 1, HOS_PAD_EAST);   /* (no second gamepad input) */
    CHECK(hos_binding(HOS_BIND_PAD, HOS_KEY_OC_NOTE_R, 0) == -1);
    /* the MOVE/CAM rows take no gamepad input */
    hos_bind(HOS_BIND_PAD, HOS_KEY_CAM_UP, 0, HOS_PAD_WEST);
    CHECK(hos_binding(HOS_BIND_PAD, HOS_KEY_CAM_UP, 0) == -1 && hos_binding(HOS_BIND_PAD, HOS_SW_Y, 0) == HOS_PAD_WEST);
    /* a note row takes no mouse button; a row past the table is nobody's */
    hos_bind(HOS_BIND_KEY, HOS_KEY_OC_NOTE_L, 1, VK_RBUTTON);
    CHECK(hos_binding(HOS_BIND_KEY, HOS_KEY_OC_NOTE_L, 1) == 0 && hos_binding(HOS_BIND_KEY, HOS_SW_ZL, 1) == VK_RBUTTON);
    hos_bind(HOS_BIND_PAD, HOS_KEY_N, 0, HOS_PAD_WEST), hos_bind(HOS_BIND_KEY, HOS_KEY_N, 0, 'P');
    CHECK(hos_binding(HOS_BIND_PAD, HOS_KEY_N, 0) == -1 && hos_binding(HOS_BIND_KEY, HOS_KEY_N, 0) == 0);
    /* Reset to defaults: the note rows come back unset */
    hos_bind(HOS_BIND_KEY, -1, 0, 0);
    for (int i = HOS_KEY_OC_NOTE_L; i <= HOS_KEY_OC_NOTE_X; i++)
        CHECK(hos_binding(HOS_BIND_KEY, i, 0) == 0 && hos_binding(HOS_BIND_KEY, i, 1) == 0 && hos_binding(HOS_BIND_PAD, i, 0) == -1);
    CHECK(hos_binding(HOS_BIND_PAD, HOS_SW_A, 0) == HOS_PAD_EAST && hos_binding(HOS_BIND_KEY, HOS_SW_A, 0) == 'E');
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


class OcarinaNoteBindingsTests(unittest.TestCase):
    def test_bindings(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
        api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
        # (the rows after the camera's, before HOS_KEY_N, in the order of the host's names; the API's version as it was:
        # no function is new and none changed its arguments)
        self.assertIn("HOS_KEY_CAM_RIGHT, HOS_KEY_OC_NOTE_L, HOS_KEY_OC_NOTE_R,\n       HOS_KEY_OC_NOTE_A, HOS_KEY_OC_NOTE_Y, "
                      "HOS_KEY_OC_NOTE_X,\n", api)
        self.assertIn('"cam_right", "note_l", "note_r", "note_a", "note_y", "note_x",\n', hid)
        code = between(hid, "static const char *const bind_names[HOS_KEY_N]",
                       "void hos_bind(int set, int button, int slot, int code) {")
        with tempfile.TemporaryDirectory(prefix="oc-note-bindings-") as tmp:
            tmp = Path(tmp)
            (tmp / "triforce_options.ini").write_text(
                "key_move_up=90,0\npad_a=5\nkey_note_y=78,1\npad_note_x=3\nkey_note_x=2,4\n", encoding="utf-8")
            (tmp / "t.c").write_text(PRELUDE + code + MAIN, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wno-unused-function", "-Wno-unused-variable",
                                    "-I", str(ROOT / "gpu" / "vk"), "-I", str(ROOT / "gpu"), str(tmp / "t.c"), "-o", str(binary)],
                                   text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), str(tmp)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
