"""(Scout) read-only helpers over the game's romfs: read a file (unpacked as its kind wants), BYML as text, strings.

    python inspect_romfs.py <romfs> byml <rel> [<max lines>]
    python inspect_romfs.py <romfs> strings <rel> [<min len>]
    python inspect_romfs.py <romfs> img <image.bin> <needle> [<needle> ...]
"""
import os
import re
import struct
import sys

import zstandard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import byml_dump  # noqa: E402


def sarc_files(b):
    hl, = struct.unpack_from("<H", b, 4)
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


def dicts(romfs):
    raw = open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb").read()
    b = zstandard.ZstdDecompressor().decompressobj().decompress(raw)
    return {k: b[s:e] for k, (s, e) in sarc_files(b).items()}


def read(romfs, rel):
    raw = open(os.path.join(romfs, rel), "rb").read()
    if not rel.endswith(".zs"):
        return raw
    d = dicts(romfs)
    k = "pack.zsdic" if rel.endswith(".pack.zs") else "bcett.byml.zsdic" if rel.endswith(".bcett.byml.zs") else "zs.zsdic"
    out = []
    dec = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(d[k])).decompressobj()
    for at in range(0, len(raw), 1 << 16):
        out.append(dec.decompress(raw[at:at + (1 << 16)]))
        if dec.eof:
            break
    return b"".join(out)


def show(v, ind=0, out=None):
    pad = "  " * ind
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, (dict, list)):
                out.append("%s%s:" % (pad, k))
                show(x, ind + 1, out)
            else:
                out.append("%s%s: %r" % (pad, k, x))
    elif isinstance(v, list):
        for x in v:
            if isinstance(x, (dict, list)):
                out.append("%s-" % pad)
                show(x, ind + 1, out)
            else:
                out.append("%s- %r" % (pad, x))
    else:
        out.append("%s%r" % (pad, v))


def main():
    romfs, what = sys.argv[1], sys.argv[2]
    if what == "byml":
        b = read(romfs, sys.argv[3])
        lines = []
        show(byml_dump.parse(b), 0, lines)
        cap = int(sys.argv[4]) if len(sys.argv) > 4 else 400
        print("\n".join(lines[:cap]))
        if len(lines) > cap:
            print("... %d lines more" % (len(lines) - cap))
    elif what == "strings":
        b = read(romfs, sys.argv[3])
        m = int(sys.argv[4]) if len(sys.argv) > 4 else 4
        for s in re.findall(rb"[\x20-\x7e]{%d,}" % m, b):
            print(s.decode())
    elif what == "img":
        b = open(sys.argv[3], "rb").read()
        for w in sys.argv[4:]:
            hits = [x.start() for x in re.finditer(re.escape(w.encode()), b)]
            print("%s: %d %s" % (w, len(hits), [hex(h) for h in hits[:8]]))
            for h in hits[:4]:
                seg = b[max(0, h - 160):h + 200]
                print("    " + "|".join(s.decode("ascii", "replace") for s in seg.split(b"\0") if s))


if __name__ == "__main__":
    main()
