"""(Scout) Override any of the game's texts: writes a language's message archive with your texts in place of the game's,
as a RomFS mod Triforce loads (or as a plain file).

    python mals_edit.py --game <game folder> --lang USen --edits my-texts.tsv --mod 50-my-texts
    python mals_edit.py --romfs <romfs> --lang USen --edits my-texts.tsv --out USen.Product.110.sarc.zs

--game takes the archive Triforce's own build made (<game>/prompts/mals/<lang>.product.110.sarc.zs: the game's texts plus
Triforce's two edits, the title's "Options / Triforce" entry and the PC's microphone wording) when there is one, else the
game's (<game>/romfs/Mals). A mod's archive takes the place of that one, so starting from it keeps Triforce's edits. The
result goes to <game>/mods/<mod>/romfs/Mals/<Lang>.Product.110.sarc.zs. Triforce gives a mod's file room to load in
whatever its size (host/mods.c hos_mods_table_size), so a text may be longer than the game's.

The edits file: one text a line, tab-separated: the MSBT (as mals_dump.py names it), the label, the new text. Lines that
start with # and empty lines are skipped. The text is written as mals_dump.py shows texts:
    {g.t:hex}    a tag (group g, type t, its parameters' bytes in hex), e.g. {0.3:0000} red, {0.3:ffff} back to the
                 default colour, {0.4:} a new box (the A press), {5.1:} a pause, {0.2:7d00} large
    {/g.t}       a tag's end
    [A] [B] [X] [Y] [L] [R] [ZL] [ZR] [Plus] [Minus] [LS] [RS] [Up] [Down] [Left] [Right] (the d-pad's)
    [LS_Up] [LS_Down] [LS_Left] [LS_Right] [LS_LeftRight] [RS_UpDown] [RS_LeftRight]
                 a button's icon in running text: the game's icon tag {1.4:NN} (BUTTON_TAGS below). Triforce draws it as
                 the button prompt of the controller in use, and of the key bound with the keyboard
    [U+E046]     a code point as it is (also [U+E046 ZL], as mals_dump.py writes it). An icon's code point shows only in
                 the panes drawn with the icon font (StaticMsg/GuideKeyIcon's texts, the T_Key*/T_Icon* panes); in
                 running text it is an empty box: use the button's name (the tag) there
    \\n          a new line
A label the MSBT does not have stops the tool (the game finds texts by label: a new one would never be shown).
"""
import argparse
import os
import re
import struct
import sys

import zstandard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mals_dump  # noqa: E402

# the icon tag's value for each button (group 1, type 4, one byte), as the game draws them with its own options (seen on
# screen, Switch face): 0b and 0e draw A and ZL too, 11-13 and 27 B, 25 26 28 X (variants that may follow the control
# options, such as the jump button's); 19-20 are arrows (right, left, up, down, up-right, up-left, down-left, down-right),
# 24 the console, 2d the ZELDA NOTES logo
BUTTON_TAGS = {"ls_up": 0x00, "ls_down": 0x01, "ls_left": 0x02, "ls_right": 0x03, "rs_updown": 0x04, "rs_leftright": 0x05,
               "up": 0x06, "down": 0x07, "left": 0x08, "right": 0x09, "a": 0x0a, "x": 0x0c, "y": 0x0d, "zl": 0x0f,
               "b": 0x10, "l": 0x14, "r": 0x15, "zr": 0x16, "plus": 0x17, "minus": 0x18, "ls": 0x21, "rs": 0x22,
               "ls_leftright": 0x23}
ALIGN_MAX = 0x2000


def encode(text, enc):
    """the notation above as the MSBT's bytes (enc 0 UTF-8, 1 UTF-16), with the terminator"""
    w, codec = (1, "utf-8") if enc == 0 else (2, "utf-16-le")
    out = bytearray()
    i = 0
    tok = re.compile(r"\{(/?)(\d+)\.(\d+)(?::([0-9a-fA-F]*))?\}|\[(?:U\+([0-9A-Fa-f]{4,5})(?: [^\]]*)?|([A-Za-z_]+))\]|\\n|\\t")
    while i < len(text):
        m = tok.match(text, i)
        if not m:
            out += text[i].encode(codec)
            i += 1
            continue
        s = m.group(0)
        if s == "\\n":
            out += "\n".encode(codec)
        elif s == "\\t":
            out += "\t".encode(codec)
        elif m.group(2) is not None:
            g, t = int(m.group(2)), int(m.group(3))
            if m.group(1):
                out += (0x0F).to_bytes(w, "little") + struct.pack("<HH", g, t)
            else:
                p = bytes.fromhex(m.group(4) or "")
                out += (0x0E).to_bytes(w, "little") + struct.pack("<HHH", g, t, len(p)) + p
        elif m.group(5):
            out += chr(int(m.group(5), 16)).encode(codec)
        else:
            name = m.group(6).lower()
            if name not in BUTTON_TAGS:
                out += s.encode(codec)   # (not a button's name: the text as written)
            else:
                out += (0x0E).to_bytes(w, "little") + struct.pack("<HHHB", 1, 4, 1, BUTTON_TAGS[name])
        i = m.end()
    return bytes(out) + b"\0" * w


def msbt_replace(m, edits):
    """the MSBT m with these labels' texts ({label: text in the notation}); every other byte as it was"""
    enc = m[0xc]
    count, = struct.unpack_from("<H", m, 0xe)
    at, sections = 0x20, []
    for _ in range(count):
        magic = bytes(m[at:at + 4])
        size, = struct.unpack_from("<I", m, at + 4)
        end = at + 16 + size
        pad = end + (-end % 16)
        sections.append([magic, bytes(m[at + 8:at + 16]), bytes(m[at + 16:end]), bytes(m[end:pad])])
        at = pad
    _, _, labels, texts, _ = mals_dump.msbt(m)
    by_name = {v: k for k, v in labels.items()}
    for label, text in edits.items():
        if label not in by_name:
            raise SystemExit("mals_edit: no label %s (its labels: %s ...)" % (label, ", ".join(sorted(by_name)[:8])))
        texts[by_name[label]] = encode(text, enc)
    offs, at = [], 4 + 4 * len(texts)
    for t in texts:
        offs.append(at)
        at += len(t)
    body = struct.pack("<I%dI" % len(texts), len(texts), *offs) + b"".join(bytes(t) for t in texts)
    for s in sections:
        if s[0] == b"TXT2":
            s[2] = body
    out = bytearray(m[:0x20])
    for magic, rest, body, pad in sections:
        need = -(16 + len(body)) % 16
        out += magic + struct.pack("<I", len(body)) + rest + body + (pad[:1] or b"\xab") * need
    struct.pack_into("<I", out, 0x12, len(out))
    return bytes(out)


def sarc_rebuild(b, new):
    """the SARC b with some files' bytes replaced ({name: bytes}); every file keeps its order and its alignment (the
    largest power of two, up to 0x2000, its place had), the header's and the nodes' offsets made to agree"""
    hl, = struct.unpack_from("<H", b, 4)
    data_at, = struct.unpack_from("<I", b, 12)
    n, = struct.unpack_from("<H", b, hl + 6)
    nodes = hl + 12
    names = nodes + 16 * n + 8
    entries = []
    for i in range(n):
        h, attr, start, end = struct.unpack_from("<IIII", b, nodes + 16 * i)
        o = names + (attr & 0xFFFFFF) * 4
        entries.append((i, b[o:b.index(b"\0", o)].decode(), start, end))
    missing = set(new) - {e[1] for e in entries}
    if missing:
        raise SystemExit("mals_edit: the archive has no %s" % ", ".join(sorted(missing)))
    out = bytearray(b[:data_at])
    for i, name, start, end in sorted(entries, key=lambda e: e[2]):
        place = data_at + start
        align = min(place & -place, ALIGN_MAX) if place else ALIGN_MAX
        data = new.get(name, b[data_at + start:data_at + end])
        out += b"\0" * (-len(out) % align)
        s = len(out) - data_at
        out += data
        struct.pack_into("<II", out, nodes + 16 * i + 8, s, s + len(data))
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


def read_edits(path):
    edits = {}
    with open(path, encoding="utf-8-sig") as f:
        for k, line in enumerate(f, 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                raise SystemExit("mals_edit: %s line %d: want MSBT, label and text, tab-separated" % (path, k))
            edits.setdefault(parts[0], {})[parts[1]] = parts[2]
    return edits


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game", help="the game folder (romfs/, prompts/, mods/)")
    ap.add_argument("--romfs", help="the game's romfs (with --out)")
    ap.add_argument("--lang", default="USen", help="USen, EUen, USfr, EUfr, USes, EUes, USpt, EUde, EUit, EUnl, EUpl, EUru, "
                    "JPja, KRko, CNzh, TWzh (the game's language: Triforce's language.txt / HOS_LANGUAGE)")
    ap.add_argument("--edits", required=True)
    ap.add_argument("--mod", help="with --game: the mod's folder name under <game>/mods")
    ap.add_argument("--out", help="write the archive here instead")
    a = ap.parse_args()
    romfs = a.romfs or (os.path.join(a.game, "romfs") if a.game else None)
    if not romfs or not (a.out or (a.game and a.mod)):
        ap.error("give --game with --mod, or --romfs/--game with --out")
    name = next((n for n in os.listdir(os.path.join(romfs, "Mals")) if n.lower().startswith(a.lang.lower() + ".")), None)
    if not name:
        raise SystemExit("mals_edit: no Mals/%s.*.sarc.zs in %s" % (a.lang, romfs))
    built = os.path.join(a.game, "prompts", "mals", name.lower()) if a.game else None
    if built and os.path.exists(built):
        base, came = zstandard.ZstdDecompressor().decompressobj().decompress(open(built, "rb").read()), built
    else:
        base = mals_dump.unzs(os.path.join(romfs, "Mals", name), mals_dump.zs_dicts(romfs)["zs.zsdic"])
        came = os.path.join(romfs, "Mals", name)
    files = mals_dump.sarc_files(base)
    new = {}
    for msbt, labels in read_edits(a.edits).items():
        if msbt not in files:
            raise SystemExit("mals_edit: the archive has no %s" % msbt)
        s, e = files[msbt]
        new[msbt] = msbt_replace(base[s:e], labels)
    out = sarc_rebuild(base, new)
    # (checked: the texts read back as written, and every other file's bytes as they were)
    files2 = mals_dump.sarc_files(out)
    assert set(files2) == set(files)
    for f, (s, e) in files.items():
        s2, e2 = files2[f]
        if f not in new:
            assert out[s2:e2] == base[s:e], f
    for msbt, labels in read_edits(a.edits).items():
        s2, e2 = files2[msbt]
        enc, _, lab, texts, _ = mals_dump.msbt(out[s2:e2])
        idx = {v: k for k, v in lab.items()}
        for label, text in labels.items():
            assert bytes(texts[idx[label]]) == encode(text, enc), (msbt, label)
    packed = zstandard.ZstdCompressor(level=19, write_content_size=True).compress(out)
    dest = a.out or os.path.join(a.game, "mods", a.mod, "romfs", "Mals", name)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(packed)
    n = sum(len(v) for v in read_edits(a.edits).values())
    print("mals_edit: %d text(s) in %d MSBT(s) from %s" % (n, len(new), came))
    print("mals_edit: %s: %d bytes (%d unpacked; the base %d unpacked)" % (dest, len(packed), len(out), len(base)))


if __name__ == "__main__":
    main()
