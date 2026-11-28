"""Minimal BYML (v2-v7) reader: python byml_dump.py <file.bgyml> ... prints each file as indented YAML-ish text."""
import struct
import sys


def parse(b):
    e = "<" if b[:2] == b"YB" else ">"
    u32 = lambda o: struct.unpack_from(e + "I", b, o)[0]
    u16 = lambda o: struct.unpack_from(e + "H", b, o)[0]
    keys_off, strs_off, root_off = u32(4), u32(8), u32(12)

    def strtab(off):
        if not off:
            return []
        n = u32(off) >> 8
        out = []
        for i in range(n):
            s = u32(off + 4 + i * 4) + off
            out.append(b[s:b.index(b"\0", s)].decode("utf-8", "replace"))
        return out

    keys, strs = strtab(keys_off), strtab(strs_off)

    def value(t, raw):
        if t == 0xA0:
            return strs[raw]
        if t == 0xD0:
            return bool(raw)
        if t == 0xD1:
            return struct.unpack("<i", struct.pack("<I", raw))[0]
        if t == 0xD2:
            return round(struct.unpack("<f", struct.pack("<I", raw))[0], 6)
        if t == 0xD3:
            return raw
        if t in (0xD4, 0xD5, 0xD6):
            v = struct.unpack_from(e + ("q" if t == 0xD4 else "Q" if t == 0xD5 else "d"), b, raw)[0]
            return v
        if t == 0xFF:
            return None
        if t in (0xC0, 0xC1, 0x20, 0x21):
            return node(raw)
        return "<type %#x %#x>" % (t, raw)

    def node(off):
        t = b[off]
        n = u32(off) >> 8
        if t == 0xC0:
            types = b[off + 4: off + 4 + n]
            vals = off + 4 + ((n + 3) & ~3)
            return [value(types[i], u32(vals + i * 4)) for i in range(n)]
        if t == 0xC1:
            out = {}
            for i in range(n):
                p = off + 4 + i * 8
                k = u32(p) & 0xFFFFFF if e == "<" else u32(p) >> 8
                kt = b[p + 3] if e == "<" else b[p + 3]
                out[keys[k]] = value(kt, u32(p + 4))
            return out
        return "<node %#x>" % t

    return node(root_off) if root_off else None


def show(v, ind=0):
    pad = "  " * ind
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, (dict, list)) and x:
                print("%s%s:" % (pad, k))
                show(x, ind + 1)
            else:
                print("%s%s: %r" % (pad, k, x))
    elif isinstance(v, list):
        for x in v:
            if isinstance(x, (dict, list)) and x:
                print("%s-" % pad)
                show(x, ind + 1)
            else:
                print("%s- %r" % (pad, x))
    else:
        print(pad + repr(v))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print("=== " + p.replace("\\", "/").split("/")[-1])
        try:
            show(parse(open(p, "rb").read()))
        except Exception as ex:
            print("  (not read: %s)" % ex)
