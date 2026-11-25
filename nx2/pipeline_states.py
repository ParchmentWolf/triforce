"""The pipeline state lists (gpu/vk/vk_draw.cpp: triforce_pipeline_states.bin, written as the game is played): show one, or merge
several into the list a release ships (work/pipeline_states.bin, copied by nx2/make_game.py beside the game as
triforce_pipeline_states_shipped.bin, whose pipelines the first start's shader preparation builds before the title).

    python -I nx2/pipeline_states.py <list>...                    what they hold
    python -I nx2/pipeline_states.py --out work/pipeline_states.bin <list>...   merged, each pipeline once
    python -I nx2/pipeline_states.py --v2 --out <file> <list>...  the same, version 1 lists converted to version 2
    python -I nx2/pipeline_states.py --check <list>...            each list checked (exit 1 when one is not sound)
    python -I nx2/pipeline_states.py --out work/pipeline_states.bin --contrib contrib <list>...
                                         and the players' lists in contrib/ (*.bin.xz, a note each), checked one by one,
                                         with what each source added
    python -I nx2/pipeline_states.py --export <list> <file.zip>   a player's list checked and packed with a report

(Triforce, 11-22, the performance audit's PIPE-11, after Source A's.) The shipped list grows from more than one PC's play:
--check says whether a list is sound (its head, its size, each record's counts and topology); --contrib merges the lists
players handed in, each checked first (a list that is not sound is left out whole, with why), in a fixed order (the
positional lists, then contrib/'s by name), and says for each source how many pipelines it added that the ones before
lacked; --export makes what a player hands in (the list as .bin.xz and a report of what it holds, nothing of the PC's).
Point-list records are counted as suspect: --check refuses them and --contrib leaves them out (Source A found 728 of its
734 wrong) unless --keep-points; the plain merge keeps every record, as before.

A list holds no game code: each record is a pipeline's stage code keys (hashes of the game's shaders, which the player's own
triforce_shaders.bin turns back into the shaders), the program variant's hash, and the formats and draw state baked into the pipeline.
Any list is read plain or xz-packed (told by its first bytes).

Version 2 (HKSTATE2, written by builds since it) holds what the game asked for, the same on every GPU and with any settings: the
targets' NVN formats, whether the draw was a mesh draw, the draw's own topology, and the program variant's texture answers with its
stages numbered without the mesh fallback's generated vertex stage. Each GPU's shader preparation maps them through the rules its
draws follow (the formats it makes of the NVN ones, its mesh shaders or the mesh fallback). Version 1 (HKSTATE1, older builds) held
the recording GPU's choices: the Vulkan formats it rendered in, and on a GPU with the mesh fallback the fallback's topology and
stage numbering; the game still reads it.

    <list>: "HKSTATE2", u32 record size (552), then the records:
            u64 code[4] (vertex or mesh, fragment, task, the header-only stage), u64 variant (of the answers below),
            u32 mesh, topology (a mesh draw's: triangle list), targets, samples, has depth, depth NVN format,
            u32 colour NVN texture formats[8] (0: none), u32 colour NVN view formats[8] (the format each is drawn in),
            u64 blend[8], u32 vertex attributes[16], u32 attribute count, u32 strides[16], u32 divisors[16],
            u32 blend enables, channel mask, polygon mode, depth clamp, alpha to coverage,
            u32 answers, u32 questions, u32 answers[24] (stage, descriptor, image, type), u8 questions[32], u32 kind, u32 pad
            (variant 0 with no answers and no questions: the variant nothing bound makes, each texture as its instruction
            declares it; lists converted from records without texture answers hold those)
            kind 0: a graphics or mesh pipeline, as above.
            kind 1 (COMPUTE): a compute program, code[0] its compute stage's code key and every other field 0 (the game
            writes one at a program's first dispatch; its pipelines' reader leaves them out, vk_draw.cpp state_list_computes
            reads them)
    <list>: "HKSTATE1", u32 record size (528), then the records:
            u64 code[4], u64 variant,
            u32 mesh, topology, targets, samples, depth format, has depth, u32 color formats[8] (Vulkan), u8 color types[8],
            u64 blend[8], u32 vertex attributes[16], u32 attribute count, u32 strides[16], u32 divisors[16],
            u32 blend enables, channel mask, polygon mode, depth clamp, alpha to coverage, pad,
            u32 answers, u32 questions, u32 answers[24] (stage, descriptor, image, type), u8 questions[32] (each answer as asked)

Lists of both versions merge into version 2 (version 1 alone stays version 1; --v2 converts it too). A version 1 record is
converted: each Vulkan format back to an NVN format every GPU renders in it (V1_NVN: no format a GPU chooses itself), a mesh record
made with the mesh fallback numbered as the native one. A record that cannot be (a format the table lacks, a fallback record whose
answers were left out) is left out, and counted.
"""
import argparse
import collections
import io
import lzma
import os
import struct
import sys
import zipfile

MAGIC = b"HKSTATE1"
SIZE = 528
MAGIC2 = b"HKSTATE2"
SIZE2 = 552
XZ_MAGIC = b"\xfd7zXZ\x00"
TRIANGLE_LIST = 3   # (VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST: what a mesh draw is given, vk_draw.cpp kMeshDrawTopology)

# A version 1 record's Vulkan format -> an NVN format vk_format (gpu/vk/vk_formats.cpp) makes it on every GPU: the formats a
# target can be, ASTC and BC (no GPU renders into them) left out. tests/test_pipeline_states.py checks it against vk_formats.cpp,
# gpu/render/nvn_api.h and the Vulkan headers
V1_NVN = {
    4: 0x95, 5: 0x3c, 7: 0x3a, 8: 0x3b, 9: 0x01, 10: 0x02, 13: 0x03, 14: 0x04, 16: 0x0d, 17: 0x0e, 20: 0x0f, 21: 0x10,
    23: 0x19, 24: 0x1a, 27: 0x1b, 28: 0x1c, 37: 0x6d, 38: 0x6e, 41: 0x6f, 42: 0x70, 43: 0x37, 44: 0x99, 50: 0x9b,
    64: 0x3d, 68: 0x3e, 70: 0x06, 71: 0x07, 74: 0x08, 75: 0x09, 76: 0x05, 77: 0x12, 78: 0x13, 81: 0x14, 82: 0x15,
    83: 0x11, 91: 0x72, 92: 0x73, 95: 0x74, 96: 0x75, 97: 0x29, 98: 0x0b, 99: 0x0c, 100: 0x0a, 101: 0x17, 102: 0x18,
    103: 0x16, 106: 0x22, 107: 0x77, 108: 0x78, 109: 0x76, 122: 0x3f, 123: 0x40, 124: 0x32, 125: 0x33, 126: 0x34,
    127: 0x31, 129: 0x35, 130: 0x36, 1000340001: 0x39,
}

# the records as struct layouts (vk_draw.cpp StateRec, StateRec2)
_V1 = struct.Struct("<4QQ6I8I8s8Q16II16I16I6III24I32s4x")
_V2 = struct.Struct("<4QQ6I8I8I8Q16II16I16I5III24I32s2I")
assert _V1.size == SIZE and _V2.size == SIZE2
KIND_AT = SIZE2 - 8   # (a version 2 record's kind: vk_draw.cpp StateRec2::kind)
COMPUTE = 1           # (StateRec2::kCompute)
HEADS = {MAGIC: SIZE, MAGIC2: SIZE2}


def read_any(path):
    """A list's bytes, plain or xz-packed (told by its first bytes)"""
    with open(path, "rb") as f:
        data = f.read()
    return lzma.decompress(data) if data[:6] == XZ_MAGIC else data


def head_size(data):
    """The record size a list's head names, None when its head is not one of a version this reads"""
    if len(data) < 12 or HEADS.get(data[:8]) != struct.unpack_from("<I", data, 8)[0]:
        return None
    return HEADS[data[:8]]


def read(path):
    data = read_any(path)
    size = head_size(data)
    if not size:
        raise SystemExit("%s: not a pipeline state list (%s, %d-byte records, or %s, %d)" % (path, MAGIC2.decode(), SIZE2,
                                                                                         MAGIC.decode(), SIZE))
    body = data[12:]
    return [body[i:i + size] for i in range(0, len(body) - size + 1, size)]


def kind(r):
    """A record's kind: 0 a graphics or mesh pipeline (every version 1 record), COMPUTE a compute program"""
    return struct.unpack_from("<I", r, KIND_AT)[0] if len(r) == SIZE2 else 0


def compute_record(key):
    """The record of a compute program: its compute stage's code key and nothing else"""
    r = bytearray(SIZE2)
    struct.pack_into("<Q", r, 0, key)
    struct.pack_into("<I", r, KIND_AT, COMPUTE)
    return bytes(r)


# ---- version 1 records as version 2

def answers_hash(answers):
    """Program::variant of packed answers (vk_shader.cpp answers_hash)"""
    h = 0
    for a in answers:
        stage, desc, image, typ = a >> 28, a >> 12 & 0xFFFF, a >> 8 & 1, a & 0xFF
        h = ((h ^ (stage << 32 | desc << 16 | typ << 1 | image)) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def v1_to_v2(r):
    """A version 1 record as version 2, or None when it cannot be (vk_draw.cpp state_v1_portable does the same in the game)"""
    f = list(_V1.unpack(r))
    code, variant = f[0:4], f[4]
    mesh, topo, n, samples, depth_format, has_depth = f[5:11]
    colors = f[11:19]
    blend, vattr, nvattr = f[20:28], f[28:44], f[44]
    stride, divisor = f[45:61], f[61:77]
    blend_en, chmask, poly, clamp, a2c = f[77:82]
    nanswers, nquestions = f[83], f[84]
    answers, questions = list(f[85:109]), f[109]
    if nanswers > 24 or nquestions > 32 or n > 8:
        return None
    if mesh:   # (made with the mesh fallback: its generated vertex stage after (task,) mesh, and the fallback's topology)
        g = 2 if code[2] else 1
        fallback = topo != TRIANGLE_LIST or any(a >> 28 > g for a in answers[:nanswers])
        if fallback:
            if not nanswers:
                return None
            for i in range(nanswers):
                if answers[i] >> 28 > g:
                    answers[i] = (answers[i] & 0x0FFFFFFF) | ((answers[i] >> 28) - 1) << 28
            variant, topo = answers_hash(answers[:nanswers]), TRIANGLE_LIST
    nvn = []
    for k in range(8):
        if k >= n or not colors[k]:
            nvn.append(0)
        elif colors[k] in V1_NVN:
            nvn.append(V1_NVN[colors[k]])
        else:
            return None
    depth_nvn = 0
    if has_depth and depth_format:
        if depth_format not in V1_NVN:
            return None
        depth_nvn = V1_NVN[depth_format]
    return _V2.pack(*code, variant, mesh, topo, n, samples, has_depth, depth_nvn, *nvn, *nvn, *blend, *vattr, nvattr,
                    *stride, *divisor, blend_en, chmask, poly, clamp, a2c, nanswers, nquestions, *answers, questions, 0, 0)


def as_v2(lists, force=False):
    """Lists of records of one version: as they are when all are version 1 (and not force), else each version 1 record converted
    (those that cannot be left out). (lists, how many were left out from each)"""
    if not force and all(len(r) == SIZE for recs in lists for r in recs):
        return lists, [0] * len(lists)
    out, lost = [], []
    for recs in lists:
        conv, n = [], 0
        for r in recs:
            r = v1_to_v2(r) if len(r) == SIZE else r
            if r is None:
                n += 1
            else:
                conv.append(r)
        out.append(conv)
        lost.append(n)
    return out, lost


def pack(recs):
    """A list's bytes, unpacked: what the game reads. Version 2 when any record is (the version 1 ones converted)"""
    (recs,), lost = as_v2([recs])
    if lost[0]:
        print("%d version 1 pipelines could not be converted to version 2: left out" % lost[0], file=sys.stderr)
    if recs and len(recs[0]) == SIZE2:
        return MAGIC2 + struct.pack("<I", SIZE2) + b"".join(recs)
    return MAGIC + struct.pack("<I", SIZE) + b"".join(recs)


# ---- (Triforce, 11-22, PIPE-11) checking a list

TOPOLOGY_MOST = 10     # (VK_PRIMITIVE_TOPOLOGY_PATCH_LIST)
POINT_LIST = 0         # (VK_PRIMITIVE_TOPOLOGY_POINT_LIST)


def record_faults(r):
    """What is wrong with one record of either version, as words (none: sound). Its counts within their arrays, a first stage,
    flags 0 or 1; a version 2 record of a kind this knows (a compute program's: its key and nothing else)"""
    faults = []
    code0 = struct.unpack_from("<Q", r, 0)[0]
    if len(r) == SIZE2:
        k = kind(r)
        if k == COMPUTE:
            return [] if code0 and r == compute_record(code0) else ["a compute program's record holding more than its key, or none"]
        if k:
            return ["kind %d" % k]
        mesh, topo, n, samples, has_depth = struct.unpack_from("<5I", r, 40)
        nvattr = struct.unpack_from("<I", r, 256)[0]
        nanswers, nquestions = struct.unpack_from("<2I", r, 408)
    else:
        mesh, topo, n, samples, _depth, has_depth = struct.unpack_from("<6I", r, 40)
        nvattr = struct.unpack_from("<I", r, 232)[0]
        nanswers, nquestions = struct.unpack_from("<2I", r, 388)
    if not code0:
        faults.append("no vertex or mesh stage")
    if mesh > 1 or has_depth > 1:
        faults.append("a flag other than 0 or 1")
    if topo > TOPOLOGY_MOST:
        faults.append("topology %d" % topo)
    if n > 8:
        faults.append("%d colour targets" % n)
    if samples not in (1, 2, 4, 8, 16):
        faults.append("%d samples" % samples)
    if nvattr > 16:
        faults.append("%d vertex attributes" % nvattr)
    if nanswers > 24 or nquestions > 32:
        faults.append("%d answers, %d questions" % (nanswers, nquestions))
    return faults


def is_point(r):
    """A pipeline drawing point lists (the topology at the same place in both versions; a compute program is no pipeline)"""
    return kind(r) == 0 and struct.unpack_from("<I", r, 44)[0] == POINT_LIST


def check_bytes(data, name="list"):
    """(records, faults, points): the records of a list's bytes, what is wrong with it (empty: sound), and how many records
    draw point lists"""
    if data[:8] not in HEADS:
        return [], ["%s: not a pipeline state list (no %s or %s head)" % (name, MAGIC2.decode(), MAGIC.decode())], 0
    size = head_size(data)
    if not size:
        return [], ["%s: record size %s, not %d" % (name, struct.unpack_from("<I", data, 8)[0] if len(data) >= 12 else "?",
                                                     HEADS[data[:8]])], 0
    body = data[12:]
    faults = []
    if len(body) % size:
        faults.append("%s: %d bytes past its last whole record (cut short)" % (name, len(body) % size))
    recs = [body[i:i + size] for i in range(0, len(body) - size + 1, size)]
    bad = 0
    for k, r in enumerate(recs):
        f = record_faults(r)
        if f:
            bad += 1
            if bad <= 8:
                faults.append("%s: record %d: %s" % (name, k, ", ".join(f)))
    if bad > 8:
        faults.append("%s: %d records not sound in all" % (name, bad))
    return recs, faults, sum(1 for r in recs if is_point(r))


def contrib_sources(folder):
    """The players' lists in a folder: (name, path, note), by name; a list's note is <name>.note beside it ("" without)"""
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".bin.xz"):
            continue
        note_path = os.path.join(folder, name[:-len(".bin.xz")] + ".note")
        note = ""
        if os.path.exists(note_path):
            with open(note_path, encoding="utf-8", errors="replace") as f:
                note = f.read().strip()
        out.append((name, os.path.join(folder, name), note))
    return out


def merge_sources(sources, keep_points=False, force_v2=False):
    """sources: (name, bytes, note) in order. The merged records (each once, in the order first met) and a report line a
    source: its records, what it added, its repeats, the point-list records left out, or why it was left out whole. Version 2
    when any sound source is (or force_v2): each version 1 record converted first, those that cannot be counted"""
    checked, report = [], [None] * len(sources)
    for i, (name, data, note) in enumerate(sources):
        recs, faults, _points = check_bytes(data, name)
        if faults:
            report[i] = "%s: left out: %s" % (name, "; ".join(faults))
            continue
        checked.append((i, name, recs, note))
    lists, lost = as_v2([recs for _i, _name, recs, _note in checked], force_v2)
    merged, seen = [], set()
    for (i, name, given, note), recs, gone in zip(checked, lists, lost):
        added = repeats = dropped = 0
        for r in recs:
            if is_point(r) and not keep_points:
                dropped += 1
                continue
            if r in seen:
                repeats += 1
                continue
            seen.add(r)
            merged.append(r)
            added += 1
        report[i] = "%s: %d pipelines, %d added, %d already in, %d point-list records left out%s%s" % (
            name, len(given), added, repeats, dropped, (", %d not converted to version 2" % gone) if gone else "",
            (" (" + note + ")") if note else "")
    return merged, report


def export_zip(list_path, zip_path):
    """A player's list checked and packed: the list as triforce_pipeline_states.bin.xz and report.txt (what it holds, and
    the check's words). Nothing of the PC's. False, with the faults printed, when the list is not sound"""
    data = read_any(list_path)
    recs, faults, points = check_bytes(data, os.path.basename(list_path))
    if faults:
        for f in faults:
            print(f)
        return False
    report = io.StringIO()
    report.write("Triforce pipeline state list, for the shipped list (hashes and draw state only, no game code)\n")
    report.write("%s\n" % describe(recs))
    report.write("point-list records: %d\n" % points)
    report.write("record size %d, %s\n" % (head_size(data), data[:8].decode()))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("triforce_pipeline_states.bin.xz", lzma.compress(data))
        z.writestr("report.txt", report.getvalue())
    return True


def describe(recs):
    versions = collections.Counter(1 if len(r) == SIZE else 2 for r in recs)
    programs = collections.Counter()
    kinds = collections.Counter()
    for r in recs:
        code = struct.unpack_from("<4Q", r, 0)
        mesh = struct.unpack_from("<I", r, 40)[0]
        compute = kind(r) == COMPUTE
        programs[(code, mesh, compute)] += 1
        kinds["compute" if compute else "mesh" if mesh else "graphics"] += 1
    return "%d pipelines (%s) of %d programs%s" % (len(recs), ", ".join("%s %d" % kv for kv in sorted(kinds.items())), len(programs),
                                                  "".join(", version %d" % v for v in sorted(versions)))


def write(path, recs):
    data = pack(recs)
    with open(path, "wb") as f:
        f.write(lzma.compress(data) if path.endswith(".xz") else data)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("lists", nargs="*")
    p.add_argument("--out")
    p.add_argument("--v2", action="store_true", help="version 2 out even from version 1 lists alone (converted)")
    p.add_argument("--check", action="store_true", help="check each list: exit 1 when one is not sound")
    p.add_argument("--contrib", help="a folder of players' lists (*.bin.xz, a .note each), checked and merged after the lists")
    p.add_argument("--keep-points", action="store_true", help="keep point-list records (refused by --check, left out by --contrib)")
    p.add_argument("--export", nargs=2, metavar=("LIST", "ZIP"), help="a list checked and packed with its report")
    a = p.parse_args()
    if a.export:
        return 0 if export_zip(*a.export) else 1
    if a.check:
        bad = False
        for path in a.lists:
            recs, faults, points = check_bytes(read_any(path), path)
            if points and not a.keep_points:
                faults.append("%s: %d point-list records (suspect: --keep-points to allow)" % (path, points))
            print("%s: %s" % (path, "; ".join(faults) if faults else "sound, " + describe(recs)))
            bad |= bool(faults)
        return 1 if bad else 0
    if a.contrib:
        sources = [(os.path.basename(x), read_any(x), "") for x in a.lists]
        sources += [(name, read_any(path), note) for name, path, note in contrib_sources(a.contrib)]
        merged, report = merge_sources(sources, a.keep_points, a.v2)
        for line in report:
            print(line)
        if a.out:
            write(a.out, merged)
            print("%s: %s" % (a.out, describe(merged)))
        return 0
    if not a.lists:
        p.error("no list")
    lists = []
    for path in a.lists:
        recs = read(path)
        print("%s: %s" % (path, describe(recs)))
        lists.append(recs)
    if a.out:
        lists, lost = as_v2(lists, force=a.v2)
        if sum(lost):
            print("%d version 1 pipelines not converted (a format no table entry has, or a mesh fallback record without its "
                  "answers): left out" % sum(lost))
        merged, seen = [], set()
        for recs in lists:
            for r in recs:
                if r not in seen:
                    seen.add(r)
                    merged.append(r)
        write(a.out, merged)
        print("%s: %s" % (a.out, describe(merged)))


if __name__ == "__main__":
    sys.exit(main())
