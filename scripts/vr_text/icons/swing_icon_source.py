"""(Triforce VR) The swing icon: a Meta Quest 3 style controller on its side with swing lines, in the button-icon font's units
(1000 an em, the box of the game's icons). Run with skia-pathops, fontTools and Pillow:

    python swing_icon_source.py            writes Swing.png (256 x 256) beside this file
    python swing_icon_source.py --data     prints the outline as nx2/prompt_vr.py's SWING (paste it there)
"""
import math, os, sys
import pathops
from PIL import Image, ImageDraw, ImageFont
OUT = os.path.dirname(os.path.abspath(__file__))

def hull(pts):
    pts = sorted(set(pts))
    def cross(o, a, b): return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0: lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0: hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]
def circ_pts(cx, cy, r, n=72):
    return [(round(cx + r*math.cos(2*math.pi*i/n), 2), round(cy + r*math.sin(2*math.pi*i/n), 2)) for i in range(n)]
def poly(pts):
    p = pathops.Path(); p.moveTo(*pts[0])
    for q in pts[1:]: p.lineTo(*q)
    p.close(); return p
def blob(circles):   # the rounded hull of circles (x, y, r)
    pts = []
    for c in circles: pts += circ_pts(*c)
    return poly(hull(pts))
def U(*ps):
    out = ps[0]
    for p in ps[1:]: out = pathops.op(out, p, pathops.PathOp.UNION)
    return out
def D(a, b): return pathops.op(a, b, pathops.PathOp.DIFFERENCE)

def xf(c, ang, s, tx, ty):
    x, y = c[0], c[1]; ca, sa = math.cos(ang), math.sin(ang)
    return (tx + s*(x*ca - y*sa), ty + s*(x*sa + y*ca)) + tuple(s*v for v in c[2:])

def controller(P):
    a, s, tx, ty = math.radians(P['tilt']), P['scale'], P['tx'], P['ty']
    T = lambda c: xf(c, a, s, tx, ty)
    head = [T(c) for c in P['head']]
    handle = [T(c) for c in P['handle']]
    body = U(blob(head), blob(handle))
    face = blob([(x, y, r - P['wall']*s) for x, y, r in head])
    shape = D(body, face)
    parts = [shape] + [blob([T(c)]) for c in P['dots']]
    return U(*parts)

def lines(P):
    return [blob([l[:2] + (l[4],), l[2:4] + (l[4],)]) for l in P['lines']]

P = dict(
    tilt=12, scale=0.95, tx=470, ty=290,
    head=[(95, 95, 112), (95, -95, 112), (-85, 0, 125)],
    handle=[(-110, -15, 92), (-430, -55, 74)],
    wall=44,
    dots=[(-10, 0, 60), (110, 80, 30), (118, -30, 30)],
    lines=[(70, 600, 175, 505, 24), (30, 500, 185, 360, 24), (165, 625, 245, 553, 24)],
)
path = U(controller(P), *lines(P))


def contours(path):
    from fontTools.pens.recordingPen import RecordingPen
    rp = RecordingPen()
    path.draw(rp)
    out, cur = [], []
    for op, args in rp.value:
        if op == "moveTo":
            cur = [tuple(round(v) for v in args[0])]
        elif op == "lineTo":
            cur.append(tuple(round(v) for v in args[0]))
        elif op in ("closePath", "endPath"):
            if len(cur) > 2:
                out.append(cur)
            cur = []
    return out


cs = contours(path)
if "--data" in sys.argv:
    print("SWING = (720, %r)" % (cs,))
else:
    def area(c):
        return sum(c[i][0] * c[(i + 1) % len(c)][1] - c[(i + 1) % len(c)][0] * c[i][1] for i in range(len(c))) / 2
    big = 4
    im = Image.new("L", (256 * big, 256 * big), 0)
    d = ImageDraw.Draw(im)
    fill = 1 if area(max(cs, key=lambda c: abs(area(c)))) > 0 else -1
    T = lambda pt: ((pt[0] - 360 + 128 / 0.2) * 0.2 * big, (1000 * 0.8 - pt[1] - 470 + 128 / 0.2) * 0.2 * big)
    for c in sorted(cs, key=lambda c: -abs(area(c))):
        d.polygon([T(pt) for pt in c], fill=255 if area(c) * fill > 0 else 0)
    alpha = im.resize((256, 256), Image.LANCZOS)
    out = Image.new("RGBA", (256, 256), (255, 255, 255, 0))
    out.putalpha(alpha)
    out.save(os.path.join(OUT, "Swing.png"))
    print("Swing.png")
