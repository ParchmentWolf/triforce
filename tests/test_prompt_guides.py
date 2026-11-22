"""The pause menu controls page's leader lines on each face's controller picture (nx2/prompt_assets.py guide_layers), with no
game file: the game's line textures stand in as black images of their size.

- Every ControllerGuide_Pro texture the page draws lines on over the Pro Controller is made again for the faces (GUIDES):
  ZL, Minus, the sticks, Plus and the face buttons on _00 and _01, ZR on _02, the D-pad's frame on _03, L and R on _04. Left
  the game's, a face's picture had them at the Pro's places: on the PlayStation pads, whose left stick is where the Pro's
  d-pad is, the D-pad's frame went round the left stick ("Put d-pad arrows in the right place").
- For each drawn face (PS4, PS5, Xbox, Steam Deck): the D-pad's label (Switch Up, on the d-pad) is a frame round that
  face's own d-pad, clear of its left stick; L, R and ZR's lines end at that face's shoulder and trigger.

    python -I -B tests/test_prompt_guides.py
"""
import sys
from pathlib import Path

RUN_ALL_MODULES = ["PIL", "numpy"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import prompt_assets as P  # noqa: E402
from prompt_faces import FACES  # noqa: E402

# the textures with the page's lines over the Pro Controller (UI/Layout2Archive/Common's bntx), and their size
PRO_GUIDES = ["ControllerGuide_Pro_0%d" % i for i in range(5)]
SIZE = (1555, 1511)


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def ink_box(im):
    box = im.point(lambda v: 255 if v > 127 else 0).getbbox()
    check(box is not None, "a line with no ink")
    return box


def main():
    from PIL import Image
    for name in PRO_GUIDES:
        check(name in P.GUIDES, f"{name} is not made for the faces: its lines point at the Pro Controller's places")
    tex = {name: i for i, name in enumerate(P.GUIDES)}
    game = [Image.new("L", SIZE, 0) for _ in P.GUIDES]
    faces = [f for f in FACES if P.parts(f)]
    check({"ps4", "ps5", "xbox", "steamdeck"} <= set(faces), "a drawn face missing: " + ", ".join(faces))
    for face in faces:
        where = P.parts(face)
        keep, moving = P.guide_layers(game, face)
        by = {(tx, end): lines for tx, entries in moving.items() for end, lines in entries}
        dpad = by.get((tex["ControllerGuide_Pro_03"], "up"))
        check(dpad is not None, f"{face}: no D-pad label on ControllerGuide_Pro_03")
        cx, cy, e = P.guide_frame_at(where, ("up", "left", "right", "down"))
        x0, y0, x1, y1 = ink_box(dpad["up"])
        # (the frame's right and top corners: the box's far side from the label's bar, at the left, and its top, the line
        # coming from the bar's row below)
        check(abs(x1 - (cx + e)) < 12 and abs(y0 - (cy - e)) < 12,
              f"{face}: the D-pad's frame reaches x {x1} and y {y0}; the face's d-pad is at ({cx:.0f}, {cy:.0f}), corners "
              f"{e:.0f} off")
        sx, sy, sr = P.guide_at(where["lstick"])
        check(dpad["up"].getpixel((round(sx), round(sy))) == 0, f"{face}: the D-pad's frame is over the left stick")
        check(dpad["down"] is dpad["up"], f"{face}: the d-pad's arms have frames of their own")
        for tx, end, pad in ((tex["ControllerGuide_Pro_04"], "l", "lshoulder"), (tex["ControllerGuide_Pro_04"], "r", "rshoulder"),
                             (tex["ControllerGuide_Pro_02"], "zr", "rtrigger")):
            lines = by.get((tx, end))
            check(lines is not None, f"{face}: no {end} label on {P.GUIDES[tx]}")
            x, y, _ = P.guide_at(where[pad])
            im = lines[pad]
            near = im.crop((round(x) - 20, round(y) - 30, round(x) + 21, round(y) + 11))
            check(near.getbbox() is not None, f"{face}: {end}'s line does not reach the {pad} at ({x:.0f}, {y:.0f})")
        print(f"{face}: the D-pad's frame round ({cx:.0f}, {cy:.0f}), L, R and ZR at its shoulders")
    print("ok")


if __name__ == "__main__":
    main()
