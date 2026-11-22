"""The button prompts' guide lines widen the lines that stay once per image, not once per route (nx2/prompt_assets.py
guide_widened, guide_route).

(Triforce, 11-22, the performance audit's IO-42, after Source A's.) guide_route grew the "lines that stay" image by a 9
by 9 maximum at every call, and every route of one line (the groups' frames, each pad input's line) is given the same
image. guide_widened keeps the last image's array: one entry, used only when it holds that very image.
HOOKSHOT_PROMPTS_WIDEN_EACH=1 widens at every route, as before.

Game-free, on blank images of the guide's size (no game file is read):
  - through guide_layers for the xbox face, the 9 by 9 maximum is made once per route with the switch (as before) and at
    most 5 times by default, once for each image that differs;
  - what guide_layers returns is the same either way, byte for byte: the lines that stay and every pad input's line,
    for the xbox face and the Switch face;
  - asked twice for one image the second answer is the kept array, with no filter; an entry that holds another image
    under this image's id misses and is replaced; the cache never holds more than one image;
  - guide_route asks guide_widened, and the switches table has the switch.

    python -I -B tests/test_prompt_widen_cache.py
"""
import os
import sys
from pathlib import Path
from unittest import mock

RUN_ALL_MODULES = ["numpy", "PIL"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import prompt_assets  # noqa: E402

SIZE = (1552, 1440)   # (the bars at 147 and 1407, the rows down to 1225: prompt_assets.BARS, GUIDE_LINES)


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def layers(face, each):
    """guide_layers on blank game images: (what it returned as bytes, the 9 by 9 maxima made, the routes asked)"""
    from PIL import Image, ImageFilter
    game = [Image.new("L", SIZE, 0) for _ in prompt_assets.GUIDES]
    made, routes = [], []
    real_filter, real_route = ImageFilter.MaxFilter, prompt_assets.guide_route

    def counting(size=3):
        made.append(size)
        return real_filter(size)

    def route(*a, **k):
        routes.append(a[4])
        return real_route(*a, **k)

    prompt_assets._WIDENED.clear()
    with mock.patch.object(prompt_assets, "WIDEN_EACH", each), mock.patch.object(ImageFilter, "MaxFilter", counting), \
            mock.patch.object(prompt_assets, "guide_route", route):
        keep, moving = prompt_assets.guide_layers(game, face)
    out = {"keep": [im.tobytes() for im in keep]}
    for tx, ends in moving.items():
        for end, lines in ends:
            for pad, im in lines.items():
                out["%d %s %s" % (tx, end, pad)] = im.tobytes()
    return out, made.count(9), len(routes)


def main():
    import numpy as np
    from PIL import Image, ImageFilter

    # ---- through guide_layers: fewer maxima, the same layers
    for face in ("xbox", "switch"):
        before, widened_before, routes_before = layers(face, True)
        now, widened_now, routes_now = layers(face, False)
        check(routes_before == routes_now and routes_now > 20, "%s: %d and %d routes" % (face, routes_before, routes_now))
        check(widened_before == routes_before, "%s: with the switch %d maxima for %d routes, not one each"
              % (face, widened_before, routes_before))
        check(widened_now <= 5, "%s: %d maxima by default, more than the 5 images that differ" % (face, widened_now))
        check(sorted(before) == sorted(now), "%s: the layers' names differ" % face)
        differ = [name for name in before if before[name] != now[name]]
        check(not differ, "%s: layers differ from the ones widened at every route: %s" % (face, differ[:6]))
        check(any(any(layer) for name, layer in now.items() if name != "keep"), "%s: no line was drawn at all" % face)
        if face == "xbox":
            counts = (widened_before, widened_now)
    check(len(prompt_assets._WIDENED) <= 1, "the cache holds more than one image")

    # ---- the cache itself
    a, b = Image.new("L", (64, 48), 0), Image.new("L", (64, 48), 0)
    a.putpixel((10, 10), 255)
    b.putpixel((40, 30), 255)
    want_a, want_b = np.asarray(a.filter(ImageFilter.MaxFilter(9))), np.asarray(b.filter(ImageFilter.MaxFilter(9)))
    prompt_assets._WIDENED.clear()
    with mock.patch.object(prompt_assets, "WIDEN_EACH", False):
        first = prompt_assets.guide_widened(a)
        check(np.array_equal(first, want_a) and first[6:15, 6:15].all() and first.sum() == 81 * 255, "not a 9 by 9 maximum")
        with mock.patch.object(ImageFilter, "MaxFilter", side_effect=AssertionError("widened again")):
            check(prompt_assets.guide_widened(a) is first, "the same image was not answered from the cache")
        # an entry under b's id that holds another image: it must miss, and be replaced by b's own
        prompt_assets._WIDENED.clear()
        prompt_assets._WIDENED[id(b)] = (a, first)
        got = prompt_assets.guide_widened(b)
        check(np.array_equal(got, want_b) and not np.array_equal(got, first), "an entry holding another image was used")
        check(list(prompt_assets._WIDENED) == [id(b)] and prompt_assets._WIDENED[id(b)][0] is b, "the entry was not replaced")
        prompt_assets.guide_widened(a)
        check(list(prompt_assets._WIDENED) == [id(a)], "the cache keeps more than the last image")
    with mock.patch.object(prompt_assets, "WIDEN_EACH", True):
        prompt_assets._WIDENED.clear()
        one, two = prompt_assets.guide_widened(a), prompt_assets.guide_widened(a)
        check(one is not two and np.array_equal(one, two) and not prompt_assets._WIDENED, "the switch still keeps an array")

    # ---- the source and the docs
    source = (ROOT / "nx2" / "prompt_assets.py").read_text(encoding="utf-8")
    route = source[source.index("def guide_route("):source.index("def _square(")]
    check("st = guide_widened(stays)" in route and "MaxFilter" not in route, "guide_route widens the image itself again")
    check('WIDEN_EACH = os.environ.get("HOOKSHOT_PROMPTS_WIDEN_EACH", "0") not in ("", "0")' in source, "the switch is not read")
    check("if held is not None and held[0] is stays:" in source, "the cache is not checked by the image itself")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    rows = [line for line in docs.splitlines() if line.startswith("| `HOOKSHOT_PROMPTS_WIDEN_EACH=1` |")]
    check(len(rows) == 1 and "IO-42" in rows[0], "docs/development.md has no row for HOOKSHOT_PROMPTS_WIDEN_EACH")
    print("ok: the xbox face's lines that stay are widened %d times, not %d; the layers are the same bytes" % (counts[1], counts[0]))


if __name__ == "__main__":
    main()
