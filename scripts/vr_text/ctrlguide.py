"""(Scout) read-only: UI/CtrlGuideSetTable as names. Its GuideType, Command and GuideKey values are murmur3 (seed 0) of
names: GuideKey of StaticMsg/GuideKeyIcon's labels, Command of LayoutMsg/CtrlGuide_00's, GuideType of the game's own
names (looked up among every string of the game's image and every message label).

    python ctrlguide.py <romfs> <image.bin>
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import byml_dump  # noqa: E402
import mals_dump  # noqa: E402


def murmur3(data, seed=0):
    c1, c2 = 0xcc9e2d51, 0x1b873593
    h, n = seed, len(data)
    r = n & 3
    for i in range(0, n - r, 4):
        k = struct.unpack_from("<I", data, i)[0]
        k = (k * c1) & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        h ^= (k * c2) & 0xffffffff
        h = ((h << 13) | (h >> 19)) & 0xffffffff
        h = (h * 5 + 0xe6546b64) & 0xffffffff
    k, t = 0, data[n - r:]
    if r == 3:
        k ^= t[2] << 16
    if r >= 2:
        k ^= t[1] << 8
    if r >= 1:
        k ^= t[0]
        k = (k * c1) & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        h ^= (k * c2) & 0xffffffff
    h ^= n
    h ^= h >> 16
    h = (h * 0x85ebca6b) & 0xffffffff
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & 0xffffffff
    return h ^ (h >> 16)


def main(romfs, image):
    names = set(re.findall(rb"[A-Za-z0-9_]{1,64}", open(image, "rb").read()))
    d = mals_dump.zs_dicts(romfs)
    sarc = mals_dump.unzs(os.path.join(romfs, "Mals", "USen.Product.110.sarc.zs"), d["zs.zsdic"])
    files = mals_dump.sarc_files(sarc)
    texts = {}
    for f, (s, e) in files.items():
        if sarc[s:s + 8] != b"MsgStdBn":
            continue
        enc, _, labels, tx, _ = mals_dump.msbt(sarc[s:e])
        for i, lab in labels.items():
            names.add(lab.encode())
            if f in ("LayoutMsg/CtrlGuide_00.msbt", "StaticMsg/GuideKeyIcon.msbt"):
                texts[(f, lab)] = mals_dump.render(tx[i], enc, __import__("collections").defaultdict(lambda: [0, ""]), "")
    table = {}
    for n in names:
        table.setdefault(murmur3(n), n.decode())
    b = open(os.path.join(romfs, "UI", "CtrlGuideSetTable", "CtrlGuideSetTable.game__ui__CtrlGuideSetTable.bgyml"), "rb").read()
    root = byml_dump.parse(b)
    unknown = 0
    for i, gs in enumerate(root["GuideSetArray"]):
        gt = gs.get("GuideType")
        gname = table.get(gt, "?%d" % gt) if gt is not None else "(none)"
        steps = []
        for g in gs.get("GuideArray", []):
            c, k = g.get("Command"), g.get("GuideKey")
            cn = table.get(c, "?%d" % c) if c is not None else "-"
            kn = table.get(k, "?%d" % k) if k is not None else "-"
            unknown += cn.startswith("?") + kn.startswith("?")
            shown = texts.get(("LayoutMsg/CtrlGuide_00.msbt", cn), "")
            steps.append("[%s] %s (\"%s\")" % (kn, cn, shown))
            extra = {kk: vv for kk, vv in g.items() if kk not in ("Command", "GuideKey")}
            if extra:
                steps[-1] += " %r" % extra
        other = {kk: vv for kk, vv in gs.items() if kk not in ("GuideType", "GuideArray")}
        print("%2d %-28s %s%s" % (i, gname, "  ".join(steps), (" %r" % other) if other else ""))
    print("unresolved values:", unknown)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
