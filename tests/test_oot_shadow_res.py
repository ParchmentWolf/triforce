"""The Graphics tab's Detail rows leave the game as shipped by default (no game).

((Triforce) 11-24) Shadow resolution (host/oot_shadow.c, host/oot_shadow_fit.c, nx2/oot_patches.py patch_shadow_res and
patch_shadow_fit) and Grass distance (gpu/vk/vk_draw.cpp grass_reach, gpu/vk/grass_distance.h).

1. The lift's patches: each site gets its call once, a text patched before is left as it is, a text without the function
   or with its code otherwise is not touched.
2. The defaults: both rows start at Game's; Game's is the host's size as the game rounded it, and the steady fit runs only
   from 3072 texels (Highest) unless HOS_SHADOW_STABLE=1; Grass distance's Game's is a reach of 1, which changes no copy.

    python -I -B tests/test_oot_shadow_res.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches as P  # noqa: E402


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


INC = '#include "a64.h"\n'
RES = (P.SHADOW_RES_HEAD + "    c->x[1]=0;\nL_804929ec:;\n"
       "    { uint64_t _a=c->x[9], _b=7ULL; uint64_t _r=_a+_b; _r&=0xFFFFFFFFULL; c->x[8]=_r; }\n"
       "    { uint64_t _r = c->x[8] & 0xfffffff8ULL; _r &= 0xFFFFFFFFULL; c->x[23] = _r; }\n"
       "    recomp_store64(c,c->x[19] + 224,c->x[9]);\n}\n")
BASIS = (P.SHADOW_BASIS_HEAD + "c->x[30] = 0x8073318cULL; f_80733620(c);\nL_8073318c:;\n    c->x[0]=1;\n}\n")
BOX = (P.SHADOW_BOX_HEAD + "L_80733efc:;\n    { uint64_t _b=c->x[21]; int64_t _o=0; { uint64_t _p0,_p1; recomp_ldp32(c,(_b+_o),&_p0,&_p1); "
       "a64_vset64(c->vreg[7],_p0); a64_vset64(c->vreg[6],_p1); }}\n    c->x[0]=1;\n" + P.SHADOW_BOX_REJOIN
       + "{ A64_POLL(c); goto L_80733efc; }\n}\n")


def main():
    s, n = P.patch_shadow_res(INC + RES)
    check(n == 1 and s.count("hos_oot_shadow_size(c, c->x[19], c->x[23]);") == 1 and s.count(P.SHADOW_RES_DECL) == 1,
          "the cascades' size is not sent through the host once")
    check(s.index("c->x[23] = _r; }") < s.index("= hos_oot_shadow_size(") < s.index("recomp_store64"),
          "the host is not asked between the rounding and the store")
    check(P.patch_shadow_res(s) == (s, 1), "a patched text is patched again")
    check(P.patch_shadow_res(INC + RES.replace("_b=7ULL", "_b=15ULL")) == (INC + RES.replace("_b=7ULL", "_b=15ULL"), 0),
          "other code is patched")
    t, n = P.patch_shadow_fit(INC + BASIS + BOX)
    check(n == 2 and t.count("hos_shadow_fit_basis(c, c->x[19]);") == 1 and t.count("hos_shadow_fit_box(c, c->x[20], _b)") == 1,
          "the nearest cascade's fit is not hooked at its two sites")
    check(P.patch_shadow_fit(t) == (t, 2), "a fitted text is patched again")
    nobox = INC + BASIS + BOX.replace(P.SHADOW_BOX_REJOIN, "")
    check(P.patch_shadow_fit(nobox)[1] == 1, "the box is hooked without the other mode's way back to it")
    check(P.patch_shadow_fit(INC + "void f_80000000(Ctx *__restrict A64_NOESC c) {\n}\n")[1] == 0, "a text without them is patched")

    host = (ROOT / "host" / "oot_shadow.c").read_text(encoding="utf-8")
    check("if (choice < 1 || choice > 2 || !shadow) return rounded;" in host, "Game's does not leave the game's size")
    fit = (ROOT / "host" / "oot_shadow_fit.c").read_text(encoding="utf-8")
    check("#define FIT_MIN_SIZE 3072" in fit and "return fit_mode() == 2 || size >= FIT_MIN_SIZE ? size : 0;" in fit,
          "the steady fit runs below Highest by default")
    h = (ROOT / "gpu" / "vk" / "vk_menu.h").read_text(encoding="utf-8")
    check(re.search(r"\bint shadow_res = 0;", h) and re.search(r"\bint grass_distance = 0;", h), "a Detail row's default is not Game's")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    check('static const char* const t[] = {"Game\'s", "High", "Highest"};' in menu and
          'static const char* const t[] = {"Game\'s", "2x", "3x", "4x"};' in menu, "the rows' first value is not Game's")
    draw = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    check("static const float times[] = {1.0f, 2.0f, 3.0f, 4.0f};" in draw and "if (nw && reach != 1.0f && stream_reserve(n, align)) {" in draw,
          "Grass distance's Game's changes the copy")
    print("ok: shadow resolution and grass distance patches, defaults as shipped")


if __name__ == "__main__":
    main()
