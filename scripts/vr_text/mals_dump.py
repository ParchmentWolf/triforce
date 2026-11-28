"""(Scout) read-only: a language's messages (romfs Mals/<lang>.Product.110.sarc.zs) as text, every MSBT and label.

    python mals_dump.py <romfs> <out dir> [<lang> ...]      (default USen)

Writes <out>/<lang>.tsv (msbt, label, index, attribute bytes as hex, text), <out>/<lang>-files.txt (each MSBT: its
size, encoding, sections, labels) and <out>/<lang>-tags.txt (every tag seen, how often, an example). In the text a tag
is {g.t:params} (0x0e, u16 group, u16 type, u16 size, params), an end tag {/g.t}, a private-use code point [U+XXXX
name] (the External font's button icons), a newline \\n.
"""
import collections
import os
import struct
import sys

import zstandard

ICONS = {0xE040: "A", 0xE041: "B", 0xE042: "X", 0xE043: "Y", 0xE044: "L", 0xE045: "R", 0xE046: "ZL", 0xE047: "ZR",
         0xE049: "Dpad", 0xE04A: "Home", 0xE04B: "Plus", 0xE04C: "Minus", 0xE056: "LS", 0xE057: "RS", 0xE060: "Up",
         0xE061: "Down", 0xE062: "Left", 0xE063: "Right", 0xE064: "DpadUD", 0xE065: "DpadLR"}


def sarc_files(b):
    assert b[:4] == b"SARC", b[:4]
    hl, bom = struct.unpack_from("<HH", b, 4)
    assert bom == 0xFEFF
    data_at, = struct.unpack_from("<I", b, 12)
    n, = struct.unpack_from("<H", b, hl + 6)
    nodes = hl + 12
    names = nodes + 16 * n + 8
    out = {}
    for i in range(n):
        _, attr, start, end = struct.unpack_from("<IIII", b, nodes + 16 * i)
        o = names + (attr & 0xFFFFFF) * 4
        out[b[o:b.index(b"\0", o)].decode()] = (data_at + start, data_at + end)
    return out


def zs_dicts(romfs):
    raw = open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb").read()
    b = zstandard.ZstdDecompressor().decompressobj().decompress(raw)
    return {k: b[s:e] for k, (s, e) in sarc_files(b).items()}


def unzs(path, dic):
    d = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(dic)).decompressobj()
    raw = open(path, "rb").read()
    parts = []
    for at in range(0, len(raw), 1 << 16):
        parts.append(d.decompress(raw[at:at + (1 << 16)]))
        if d.eof:
            break
    return b"".join(parts)


def msbt(m):
    assert m[:8] == b"MsgStdBn" and m[8:10] == b"\xff\xfe", m[:10]
    enc = m[0xc]
    count, = struct.unpack_from("<H", m, 0xe)
    at, sec = 0x20, {}
    for _ in range(count):
        magic = bytes(m[at:at + 4])
        size, = struct.unpack_from("<I", m, at + 4)
        sec[magic] = m[at + 16:at + 16 + size]
        at = (at + 16 + size + 15) & ~15
    labels = {}
    if b"LBL1" in sec:
        body = sec[b"LBL1"]
        slots, = struct.unpack_from("<I", body, 0)
        for i in range(slots):
            c, o = struct.unpack_from("<II", body, 4 + 8 * i)
            for _ in range(c):
                ln = body[o]
                labels[struct.unpack_from("<I", body, o + 1 + ln)[0]] = body[o + 1:o + 1 + ln].decode("ascii", "replace")
                o += 5 + ln
    texts = []
    if b"TXT2" in sec:
        body = sec[b"TXT2"]
        c, = struct.unpack_from("<I", body, 0)
        offs = list(struct.unpack_from("<%dI" % c, body, 4)) + [len(body)]
        texts = [body[offs[i]:offs[i + 1]] for i in range(c)]
    attrs = []
    if b"ATR1" in sec:
        body = sec[b"ATR1"]
        c, size = struct.unpack_from("<II", body, 0)
        attrs = [bytes(body[8 + size * i:8 + size * (i + 1)]) for i in range(c)]
    return enc, sec, labels, texts, attrs


def render(s, enc, tags, where):
    w = 1 if enc == 0 else 2
    out, run, at = [], bytearray(), 0
    codec = "utf-8" if enc == 0 else "utf-16-le"

    def flush():
        if run:
            for ch in run.decode(codec, "replace"):
                o = ord(ch)
                if 0xE000 <= o <= 0xF8FF:
                    out.append("[U+%04X %s]" % (o, ICONS.get(o, "?")))
                elif ch == "\n":
                    out.append("\\n")
                elif ch == "\t":
                    out.append("\\t")
                else:
                    out.append(ch)
            run.clear()
    while at + w <= len(s):
        c = int.from_bytes(s[at:at + w], "little")
        if c == 0:
            break
        if c == 0x0E and at + w + 6 <= len(s):
            flush()
            g, t, n = struct.unpack_from("<HHH", s, at + w)
            p = bytes(s[at + w + 6:at + w + 6 + n])
            out.append("{%d.%d:%s}" % (g, t, p.hex()))
            k = (g, t)
            tags[k][0] += 1
            if not tags[k][1]:
                tags[k][1] = "%s %s" % (where, p.hex())
            at += w + 6 + n
            continue
        if c == 0x0F and at + w + 4 <= len(s):
            flush()
            g, t = struct.unpack_from("<HH", s, at + w)
            out.append("{/%d.%d}" % (g, t))
            at += w + 4
            continue
        run += s[at:at + w]
        at += w
    flush()
    return "".join(out)


def main(romfs, outdir, langs):
    dicts = zs_dicts(romfs)
    os.makedirs(outdir, exist_ok=True)
    for lang in langs:
        name = next(n for n in os.listdir(os.path.join(romfs, "Mals")) if n.lower().startswith(lang.lower() + "."))
        sarc = unzs(os.path.join(romfs, "Mals", name), dicts["zs.zsdic"])
        files = sarc_files(sarc)
        tags = collections.defaultdict(lambda: [0, ""])
        with open(os.path.join(outdir, lang + ".tsv"), "w", encoding="utf-8") as t, \
                open(os.path.join(outdir, lang + "-files.txt"), "w", encoding="utf-8") as fl:
            fl.write("%s: %d bytes unpacked, %d files\n" % (name, len(sarc), len(files)))
            for f in sorted(files):
                s, e = files[f]
                m = sarc[s:e]
                if m[:8] != b"MsgStdBn":
                    fl.write("%s\t%d\tnot an MSBT (%r)\n" % (f, e - s, bytes(m[:8])))
                    continue
                enc, sec, labels, texts, attrs = msbt(m)
                fl.write("%s\t%d\tenc %d\t%s\t%d texts\n" % (f, e - s, enc, ",".join(k.decode() for k in sec), len(texts)))
                for i, s2 in enumerate(texts):
                    lab = labels.get(i, "#%d" % i)
                    a = attrs[i].hex() if i < len(attrs) else ""
                    t.write("%s\t%s\t%d\t%s\t%s\n" % (f, lab, i, a, render(s2, enc, tags, f + ":" + lab)))
        with open(os.path.join(outdir, lang + "-tags.txt"), "w", encoding="utf-8") as tg:
            for (g, ty), (n, ex) in sorted(tags.items()):
                tg.write("%d.%d\t%d\t%s\n" % (g, ty, n, ex))
        print(lang, name, len(files), "files")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:] or ["USen"])
