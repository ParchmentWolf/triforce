"""(Triforce VR) Builds VR's texts into a game: every [VR] written in edits/ (dialogue, ui, items, other, the tutorial
pop-ups, the HUD hints' words and icons) through mals_edit.py, from that game's own files.

    python vr_build.py <game folder> [--scheme gesture|simplified] [--from edits|work] [--lang USen] [--dry]

Writes <game>/vr_text/gesture/romfs and <game>/vr_text/simplified/romfs (both schemes unless --scheme): the game takes the
Control Scheme's while VR is on, and none in flat-screen play (host/mods.c vr_text_scan).

--scheme simplified takes each label's [VR2] (the Simplified controls' text), its [VR] where [VR2] is empty.
A text replaces the game's (<game>: the game's own is kept), except in ActorMsg/PouchContent: there it is added under the game's own (a blank line between);
a [VR] that starts with the [Original] lines has them once, not twice.
--dry writes vr_edits.tsv beside this script and stops (to look at what would go in).
"""
import argparse
import collections
import os
import re
import struct
import subprocess
import sys
import zlib

import zstandard

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK = re.compile(r"(?m)^(?==== .+ ===$)")
ADDED_TO = {"ActorMsg/PouchContent.msbt"}   # (these files' texts go under the game's own, not in its place)
sys.path.insert(0, HERE)
import mals_dump  # noqa: E402
from mals_edit import encode  # noqa: E402


def section(b, tag):
    m = re.search(r"^\[%s\]\n(.*?)(?=^\[(?:Original|VR|VR2|VR icon|VR2 icon)\]|\Z)" % tag, b, re.S | re.M)
    return m.group(1).strip("\n") if m else ""


LEFT_OUT = set()   # (files left out unless --with-pouch: none now)


def text_files(root, with_pouch=False):
    """(file, its MSBT) for each text file: the four folders' (the MSBT on their first line) and the tutorial pop-ups'"""
    for grp in ("dialogue", "ui", "items", "other"):
        d = os.path.join(root, grp)
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if fn.endswith(".txt") and (with_pouch or os.path.join(grp, fn) not in LEFT_OUT):
                p = os.path.join(d, fn)
                yield p, open(p, encoding="utf-8").readline()[2:].strip()
    d = os.path.join(root, "prompts", "tutorial_popups")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if fn.endswith(".txt"):
            yield os.path.join(d, fn), "LayoutMsg/ActionGuide_00.msbt"


def flat(t):
    return " ".join(t.split())


def hud_words(root, scheme):
    """the HUD hints' words: each step's [VR] ([VR2] for Simplified, else its [VR]) as its command's label in CtrlGuide_00"""
    d = os.path.join(root, "prompts", "hud_hints")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.endswith(".txt"):
            continue
        path = os.path.join(d, fn)
        for b in BLOCK.split(open(path, encoding="utf-8").read())[1:]:
            cmd = re.match(r"=== Step \d+: (.+?) ===", b).group(1)
            line = lambda tag: (re.search(r"(?m)^\[%s\][ \t]*(.*)$" % re.escape(tag), b) or [None, ""])[1].strip()
            word = line("VR2") if scheme == "simplified" and line("VR2") else line("VR")
            if word and word != "<game>" and cmd != "(no word)":   # (<game>: the game's own word)
                yield path, "LayoutMsg/CtrlGuide_00.msbt", cmd, word


def edits(root, scheme, originals, with_pouch=False):
    out, where = [], {}
    for path, msbt, label, new in hud_words(root, scheme):
        try:
            originals(msbt, label)
        except KeyError:   # (a step whose word is no label of the file: the game shows its icon alone)
            print("vr_build: %s: %s has no word of its own in the game: its [VR] is left out" % (os.path.relpath(path, root), label))
            continue
        key = (msbt, label)
        if key in where and where[key][1] != new:
            raise SystemExit("vr_build: the HUD word %s is written differently in %s and %s (one word for every hint showing it)"
                             % (label, os.path.relpath(where[key][0], root), os.path.relpath(path, root)))
        if key not in where:
            where[key] = (path, new)
            out.append((msbt, label, new))
    for path, msbt in text_files(root, with_pouch):
        text = open(path, encoding="utf-8").read()
        for b in BLOCK.split(text)[1:]:
            label = re.match(r"=== (.+?) ===", b).group(1).strip()
            vr, vr2 = section(b, "VR"), section(b, "VR2")
            mine = vr2 if scheme == "simplified" and vr2.strip() else vr
            if not mine.strip() or mine.strip() == "<game>":   # (<game>: the game's own text)
                continue
            if msbt in ADDED_TO:
                orig = section(b, "Original")
                lines = mine.split("\n")
                for k in range(len(lines) + 1):   # (the [Original] lines at its start: left out, the game's go first)
                    if flat("\n".join(lines[:k])) == flat(orig) and flat(orig):
                        lines = lines[k:]
                        break
                while lines and not lines[0].strip():
                    lines = lines[1:]
                if not lines:
                    continue
                new = originals(msbt, label) + "\\n\\n" + join_lines(lines)
            else:
                new = join_lines(mine.split("\n"))
            key = (msbt, label)
            if key in where:
                if where[key][1] != new:
                    raise SystemExit("vr_build: %s %s is written differently in %s and %s: keep it in one"
                                     % (msbt, label, os.path.relpath(where[key][0], root), os.path.relpath(path, root)))
                continue
            where[key] = (path, new)
            out.append((msbt, label, new))
    return out


def join_lines(lines):
    return "\\n".join(line.rstrip() for line in lines)


GAME_ROMFS = [None]   # (the game's romfs: <game>/romfs, or --romfs)


def game_romfs(game):
    return GAME_ROMFS[0] or os.path.join(game, "romfs")


def game_texts(game, lang):
    """(msbt, label) -> the game's text as mals_edit.py writes it, from the archive mals_edit.py starts from"""
    romfs = game_romfs(game)
    name = next(n for n in os.listdir(os.path.join(romfs, "Mals")) if n.lower().startswith(lang.lower() + "."))
    built = os.path.join(game, "prompts", "mals", name.lower())
    if os.path.exists(built):
        base = zstandard.ZstdDecompressor().decompressobj().decompress(open(built, "rb").read())
    else:
        base = mals_dump.unzs(os.path.join(romfs, "Mals", name), mals_dump.zs_dicts(romfs)["zs.zsdic"])
    files = mals_dump.sarc_files(base)
    cache = {}

    def get(msbt, label):
        if msbt not in cache:
            s, e = files[msbt]
            enc, _, labels, tx, _ = mals_dump.msbt(base[s:e])
            tags = collections.defaultdict(lambda: [0, ""])
            cache[msbt] = {}
            for i, t in enumerate(tx):
                cache[msbt][labels.get(i, "#%d" % i)] = (mals_dump.render(t, enc, tags, msbt), bytes(t), enc)
        r, raw, enc = cache[msbt][label]
        assert encode(r, enc) == raw, (msbt, label)   # (written back, the game's own bytes)
        return r
    return get


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("--lang", default="USen")
    ap.add_argument("--romfs", help="the game's romfs (default: <game folder>/romfs)")
    ap.add_argument("--scheme", choices=("gesture", "simplified"), help="one scheme alone (default: both)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--from", dest="source", choices=("edits", "work"), default="edits", help="edits/ (default) or work/")
    ap.add_argument("--with-pouch", action="store_true", help="(kept for old commands: PouchContent is built anyway)")
    a = ap.parse_args()
    GAME_ROMFS[0] = a.romfs
    originals = game_texts(a.game, a.lang)
    for scheme in [a.scheme] if a.scheme else ["gesture", "simplified"]:
        build(a, scheme, originals)


SOURCE = [os.path.join(HERE, "edits")]


def source(a):
    """the texts built: edits/ (the default), or --from work (vr_text.py open's folder, before save)"""
    SOURCE[0] = os.path.join(HERE, a.source)
    return SOURCE[0]


def build(a, scheme, originals):
    """one scheme's texts, HUD hint table and size table into <game>/vr_text/<scheme>/romfs (host/mods.c: with VR on, that
    Control Scheme's, over the mods)"""
    e = edits(source(a), scheme, originals, a.with_pouch)
    tsv = os.path.join(HERE, "vr_edits.tsv")
    with open(tsv, "w", encoding="utf-8") as f:
        f.write("# made by vr_build.py from vr_text/: MSBT, label, text\n")
        for msbt, label, vr in e:
            f.write("%s\t%s\t%s\n" % (msbt, label, vr))
    print("vr_build: %s: %d text(s) -> %s" % (scheme, len(e), tsv))
    if a.dry or not e:
        return
    romfs = os.path.join(a.game, "vr_text", scheme, "romfs")
    name = next(n for n in os.listdir(os.path.join(game_romfs(a.game), "Mals")) if n.lower().startswith(a.lang.lower() + "."))
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "mals_edit.py"), "--game", a.game, "--romfs", game_romfs(a.game),
                    "--lang", a.lang,
                    "--edits", tsv, "--out", os.path.join(romfs, "Mals", name)], check=True)
    size_table(a.game, romfs, a.lang)
    hint_keys(a.game, romfs, scheme)


# the HUD hints' icons: each [VR icon] ([VR2 icon]) as a key of StaticMsg/GuideKeyIcon whose Switch button the game, in a VR
# session, shows as that control (nx2/prompt_vr.py MAP). "-" a key with no icon there
HINT_KEY = {
    "gesture": {"Swing": "Y", "R_Grip": "ZR", "L_Grip": "ZR", "R_Trigger": "R", "L_Trigger": "L", "A": "A", "B": "B",
                "X": "Plus", "RS_Click": "X_OptionB", "LS_Click": "X_OptionB", "-": "ZL"},
    "simplified": {"Swing": "Y", "R_Grip": "ZR", "L_Grip": "ZR", "R_Trigger": "R", "L_Trigger": "ZL", "A": "A", "B": "B",
                   "X": "Plus", "RS_Click": "X_OptionB", "LS_Click": "X_OptionB", "-": "L"},
}
HINT_TABLE = "UI/CtrlGuideSetTable/CtrlGuideSetTable.game__ui__CtrlGuideSetTable.bgyml"


def guide_key_offsets(b):
    """the hint table's steps: [[the offset of each step's GuideKey value, None without one] per hint set]"""
    e = "<" if b[:2] == b"YB" else ">"
    u32 = lambda o: struct.unpack_from(e + "I", b, o)[0]
    n = u32(4)
    keys = [b[u32(n + 4 + 4 * i) + n:b.index(b"\0", u32(n + 4 + 4 * i) + n)].decode() for i in range(u32(n) >> 8)]

    def entries(off):   # a dictionary's {key: (type, value, the value's offset)}
        out = {}
        for i in range(u32(off) >> 8):
            p = off + 4 + 8 * i
            k = u32(p) & 0xFFFFFF if e == "<" else u32(p) >> 8
            out[keys[k]] = (b[p + 3], u32(p + 4), p + 4)
        return out

    def array(off):
        cnt = u32(off) >> 8
        types, vals = b[off + 4:off + 4 + cnt], off + 4 + ((cnt + 3) & ~3)
        return [(types[i], u32(vals + 4 * i)) for i in range(cnt)]
    sets = []
    for t, v in array(entries(u32(12))["GuideSetArray"][1]):
        steps = []
        g = entries(v).get("GuideArray")
        for t2, v2 in array(g[1]) if g else []:
            k = entries(v2).get("GuideKey")
            steps.append(k[2] if k else None)
        sets.append(steps)
    return sets


def hint_keys(game, romfs, scheme):
    """the hint table with each step's key as its [VR icon] ([VR2 icon]) asks, into the mod"""
    sys.path.insert(0, HERE)
    import ctrlguide
    d = os.path.join(SOURCE[0], "prompts", "hud_hints")
    b = bytearray(open(os.path.join(game_romfs(game), HINT_TABLE), "rb").read())
    sets = guide_key_offsets(bytes(b))
    e = "<" if b[:2] == b"YB" else ">"
    done = 0
    for fn in sorted(os.listdir(d)):
        m = re.match(r"(\d+)_", fn)
        if not m or not fn.endswith(".txt") or int(m.group(1)) >= len(sets):
            continue
        steps = sets[int(m.group(1))]
        for blk in BLOCK.split(open(os.path.join(d, fn), encoding="utf-8").read())[1:]:
            n = int(re.match(r"=== Step (\d+):", blk).group(1)) - 1
            line = lambda tag: (re.search(r"(?m)^\[%s\][ \t]*(.*)$" % re.escape(tag), blk) or [None, ""])[1].strip()
            icon = line("VR2 icon") if scheme == "simplified" and line("VR2 icon") else line("VR icon")
            key = HINT_KEY[scheme].get(icon)
            if icon and not key:
                print("vr_build: %s step %d: no key shows the icon %s" % (fn, n + 1, icon))
            if key and n < len(steps) and steps[n] is not None:
                struct.pack_into(e + "I", b, steps[n], ctrlguide.murmur3(key.encode()))
                done += 1
    dest = os.path.join(romfs, HINT_TABLE)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "wb").write(bytes(b))
    print("vr_build: the HUD hints' icons: %d step(s) -> %s" % (done, dest))


def size_table(game, romfs, lang):
    """the mod's own ResourceSizeTable: Triforce's (prompts/rsizetable.zs, the game's with room for the button prompts' font)
    with the text archive's entry raised to fit the mod's archive. The game loads the texts at its start, before Triforce's
    own per-file room (host/mods.c hos_mods_table_size) applies, so without this a larger archive does not fit"""
    mals = os.path.join(romfs, "Mals")
    name = next(n for n in os.listdir(mals) if n.lower().startswith(lang.lower() + "."))
    real = zstandard.ZstdDecompressor().decompressobj().decompress(open(os.path.join(mals, name), "rb").read())
    src = os.path.join(game, "prompts", "rsizetable.zs")
    if not os.path.exists(src):
        src = next(os.path.join(game_romfs(game), "System", "Resource", n)
                   for n in os.listdir(os.path.join(game_romfs(game), "System", "Resource")) if n.endswith(".rsizetable.zs"))
    b = bytearray(zstandard.ZstdDecompressor().decompressobj().decompress(open(src, "rb").read()))
    assert b[:6] == b"RESTBL", b[:6]
    _, strsz, ncrc, nname = struct.unpack_from("<IIII", b, 6)
    key = name[:-3].encode()   # (the table names the unpacked file: Mals/USen.Product.110.sarc)
    want = len(real) + (64 << 10)
    crc, at, done = zlib.crc32(b"Mals/" + key), 22, 0
    for i in range(ncrc):
        h, s = struct.unpack_from("<II", b, at + 8 * i)
        if h == crc:
            struct.pack_into("<I", b, at + 8 * i + 4, max(s, want))
            done = 1
            print("vr_build: size table: Mals/%s %d -> %d" % (key.decode(), s, max(s, want)))
    if not done:
        raise SystemExit("vr_build: the size table has no Mals/%s" % key.decode())
    game_name = next(n for n in os.listdir(os.path.join(game_romfs(game), "System", "Resource")) if n.endswith(".rsizetable.zs"))
    dest = os.path.join(romfs, "System", "Resource", game_name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(zstandard.ZstdCompressor(level=19, write_content_size=True).compress(bytes(b)))
    print("vr_build: %s" % dest)


if __name__ == "__main__":
    main()
