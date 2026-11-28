"""(Scout) read-only: the values a BFEVFL event flow passes for given parameter names (e.g. ActionGuideType), by
finding each parameter container (type 1, a dictionary of names) that has the name and reading its item.

    python evfl_params.py <romfs> <param> <flow> [<flow> ...]      (flow: the name under Event/EventFlow/)

Pointers in a BFEVFL are u64 offsets from the file's start. A dictionary ("DIC "): u32 magic, u32 count, then count+1
entries of 16 bytes (u32 bit, u16 left, u16 right, u64 name -> u16 length, the name). A container: u8 type, u8, u16
items, u32, u64 dictionary, then the items (type 1: u64 each -> a child container; 2 int: s32 each; 3 bool; 4 float;
5 string: u64 each -> u16 length, the text; 7 int array ...).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inspect_romfs as ir  # noqa: E402


def name_at(b, p):
    if p <= 0 or p + 2 > len(b):
        return None
    n, = struct.unpack_from("<H", b, p)
    s = b[p + 2:p + 2 + n]
    try:
        return s.decode("utf-8")
    except UnicodeDecodeError:
        return None


def dic_names(b, at):
    if b[at:at + 4] != b"DIC ":
        return None
    count, = struct.unpack_from("<I", b, at + 4)
    if count > 4096:
        return None
    names = []
    for i in range(1, count + 1):   # (entry 0 is the root)
        e = at + 8 + 16 * i
        if e + 16 > len(b):
            return None
        p, = struct.unpack_from("<Q", b, e + 8)
        names.append(name_at(b, p))
    return names


def item_value(b, p):
    if p <= 0 or p + 16 > len(b):
        return "?"
    t, n = b[p], struct.unpack_from("<H", b, p + 2)[0]
    d = p + 16
    if t == 2:
        return list(struct.unpack_from("<%di" % n, b, d)) if n != 1 else struct.unpack_from("<i", b, d)[0]
    if t == 3:
        return [bool(x) for x in struct.unpack_from("<%dI" % n, b, d)]
    if t == 4:
        return list(struct.unpack_from("<%df" % n, b, d))
    if t in (5, 6, 10, 11, 0):
        return [name_at(b, struct.unpack_from("<Q", b, d + 8 * i)[0]) for i in range(max(n, 1))]
    if t == 7:
        return list(struct.unpack_from("<%di" % n, b, d))
    return "type %d, %d items" % (t, n)


def main(romfs, param, flows):
    for flow in flows:
        b = ir.read(romfs, "Event/EventFlow/%s.bfevfl.zs" % flow)
        dics = {}
        at = b.find(b"DIC ")
        while at >= 0:
            names = dic_names(b, at)
            if names and param in names:
                dics[at] = names
            at = b.find(b"DIC ", at + 4)
        found = []
        for p in range(0, len(b) - 16, 8):
            if b[p] != 1:
                continue
            d, = struct.unpack_from("<Q", b, p + 8)
            if d not in dics:
                continue
            names = dics[d]
            n, = struct.unpack_from("<H", b, p + 2)
            if n != len(names):
                continue
            vals = {}
            for i, nm in enumerate(names):
                c, = struct.unpack_from("<Q", b, p + 16 + 8 * i)
                vals[nm] = item_value(b, c)
            found.append(vals)
        print("== %s: %d" % (flow, len(found)))
        for v in found:
            print("   ", v)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
