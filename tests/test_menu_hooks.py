"""The game's menus' mouse (host/oot_menu.c) hooks two functions of the lifted game at their heads: a menu screen's handler of
a pane getting the focus (f_802ed660: hos_oot_menu_focus) and a menu screen's update (f_802f1380: hos_oot_menu_tick).

nx2/oot_patches.py's patch_menu_focus and patch_menu_tick put each call first in its function, once, and declare it; a
file without the function is left alone, and a file patched before is given back as it is (a lift patched again). apply
makes them only in the supported build's lift (protect_hearts): those addresses are its functions.

python -I -B tests/test_menu_hooks.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

FOCUS = "    hos_oot_menu_focus(c, c->x[0], c->x[1], c->x[30]);"
TICK = "    hos_oot_menu_tick(c, c->x[0]);"
BODY = "    c->x[19]=c->x[0];\n    c->x[8]=recomp_load64(c,c->x[19] + 56);\nreturn;\n}\n"


def lifted(*heads):
    return '#include "a64.h"\n' + "".join(head + BODY for head in heads)


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def hooked(patch, head, call, decl):
    out = patch(lifted(head))
    check(out is not None and out.count(call) == 1, "the hook is not in its function once: %s" % call.strip())
    check(head + call in out, "the hook is not first in its function: %s" % call.strip())
    check(decl in out, "the lifted file does not declare the hook: %s" % decl)
    check(BODY in out, "the function's body was changed")
    check(patch(out) == out, "a file patched before was patched again: %s" % call.strip())
    check(patch(lifted(head.replace("f_802", "f_803"))) is None, "a file without the function was patched")
    return out


def applied(protect_hearts):
    with tempfile.TemporaryDirectory() as gen:
        path = os.path.join(gen, "code_000.c")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(lifted(oot_patches.MENU_FOCUS_HEAD, oot_patches.MENU_TICK_HEAD))
        stdout = sys.stdout
        sys.stdout = open(os.devnull, "w")
        try:
            oot_patches.apply(gen, protect_hearts=protect_hearts)
        finally:
            sys.stdout.close()
            sys.stdout = stdout
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()


def main():
    hooked(oot_patches.patch_menu_focus, oot_patches.MENU_FOCUS_HEAD, FOCUS,
           "extern void hos_oot_menu_focus(Ctx *c, uint64_t screen, uint64_t pane, uint64_t lr);")
    hooked(oot_patches.patch_menu_tick, oot_patches.MENU_TICK_HEAD, TICK,
           "extern void hos_oot_menu_tick(Ctx *c, uint64_t screen);")
    both = applied(True)
    check(both.count(FOCUS) == 1 and both.count(TICK) == 1, "the supported build's lift did not get both hooks once")
    plain = applied(False)
    check(FOCUS not in plain and TICK not in plain, "another build's lift got the menus' hooks")
    # ((Triforce) the button prompts' live part, host/prompts.c: a text box's draw and layout, FreeType's glyph render)
    prompts = ((oot_patches.patch_text_draw, oot_patches.TEXT_DRAW_HEAD, "    hos_prompts_text_draw(c->x[0]);",
                "extern void hos_prompts_text_draw(uint64_t box);"),
               (oot_patches.patch_text_layout, oot_patches.TEXT_LAYOUT_HEAD, "    hos_prompts_text_layout(c->x[0]);",
                "extern void hos_prompts_text_layout(uint64_t box);"),
               (oot_patches.patch_glyph, oot_patches.GLYPH_HEAD, "    hos_prompts_glyph(c->x[1]);",
                "extern void hos_prompts_glyph(uint64_t slot);"))
    for patch, head, call, decl in prompts:
        out = patch(lifted(head))
        check(out is not None and out.count(call) == 1 and head + call in out, "not first in its function once: %s" % call)
        check(decl in out and BODY in out and patch(out) == out, "declared, the body kept, once: %s" % call)
        check(patch(lifted(head.replace("void f_", "void g_"))) is None, "a file without the function was patched: %s" % call)
    with tempfile.TemporaryDirectory() as gen:
        path = os.path.join(gen, "code_000.c")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(lifted(*(head for _, head, _, _ in prompts)))
        stdout = sys.stdout
        sys.stdout = open(os.devnull, "w")
        try:
            oot_patches.apply(gen, protect_hearts=True)
        finally:
            sys.stdout.close()
            sys.stdout = stdout
        with open(path, encoding="utf-8", newline="") as f:
            got = f.read()
    check(all(got.count(call) == 1 for _, _, call, _ in prompts), "the supported build's lift did not get the prompts' hooks once")
    print("PASS: the menus' and the button prompts' hooks go first in their functions, once, only in the supported build's lift")


if __name__ == "__main__":
    main()
