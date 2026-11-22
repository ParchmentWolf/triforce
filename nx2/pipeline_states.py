"""The pipeline state lists (gpu/vk/vk_draw.cpp: triforce_pipeline_states.bin, written as the game is played): show one, or merge
several into the list a release ships (work/pipeline_states.bin, copied by nx2/make_game.py beside the game as
triforce_pipeline_states_shipped.bin, whose pipelines the first start's shader preparation builds before the title).

    python -I nx2/pipeline_states.py <list>...                    what they hold
    python -I nx2/pipeline_states.py --out work/pipeline_states.bin <list>...   merged, each pipeline once
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

    <list>: "HKSTATE1", u32 record size (528), then the records:
            u64 code[4] (vertex or mesh, fragment, task, the header-only stage), u64 variant,
            u32 mesh, topology, targets, samples, depth format, has depth, u32 color formats[8], u8 color types[8],
            u64 blend[8], u32 vertex attributes[16], u32 attribute count, u32 strides[16], u32 divisors[16],
            u32 blend enables, channel mask, polygon mode, depth clamp, alpha to coverage, pad,
            u32 answers, u32 questions, u32 answers[24] (stage, descriptor, image, type), u8 questions[32] (each answer as asked)
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


def read(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != MAGIC or struct.unpack_from("<I", data, 8)[0] != SIZE:
        raise SystemExit("%s: not a pipeline state list" % path)
    body = data[12:]
    return [body[i:i + SIZE] for i in range(0, len(body) - SIZE + 1, SIZE)]


# ---- (Triforce, 11-22, PIPE-11) checking a list

TOPOLOGY_MOST = 10     # (VK_PRIMITIVE_TOPOLOGY_PATCH_LIST)
POINT_LIST = 0         # (VK_PRIMITIVE_TOPOLOGY_POINT_LIST)


def record_faults(r):
    """What is wrong with one record, as words (none: sound). Its counts within their arrays, a first stage, flags 0 or 1"""
    faults = []
    code0 = struct.unpack_from("<Q", r, 0)[0]
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
    return struct.unpack_from("<I", r, 44)[0] == POINT_LIST


def check_bytes(data, name="list"):
    """(records, faults, points): the records of a list's bytes, what is wrong with it (empty: sound), and how many records
    draw point lists"""
    if data[:8] != MAGIC:
        return [], ["%s: not a pipeline state list (no %s head)" % (name, MAGIC.decode())], 0
    if len(data) < 12 or struct.unpack_from("<I", data, 8)[0] != SIZE:
        return [], ["%s: record size %s, not %d" % (name, struct.unpack_from("<I", data, 8)[0] if len(data) >= 12 else "?", SIZE)], 0
    body = data[12:]
    faults = []
    if len(body) % SIZE:
        faults.append("%s: %d bytes past its last whole record (cut short)" % (name, len(body) % SIZE))
    recs = [body[i:i + SIZE] for i in range(0, len(body) - SIZE + 1, SIZE)]
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


def read_any(path):
    """A list's bytes, plain or xz-packed (.xz)"""
    with open(path, "rb") as f:
        data = f.read()
    return lzma.decompress(data) if path.endswith(".xz") else data


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


def merge_sources(sources, keep_points=False):
    """sources: (name, bytes, note) in order. The merged records (each once, in the order first met) and a report line a
    source: its records, what it added, its repeats, the point-list records left out, or why it was left out whole"""
    merged, seen, report = [], set(), []
    for name, data, note in sources:
        recs, faults, points = check_bytes(data, name)
        if faults:
            report.append("%s: left out: %s" % (name, "; ".join(faults)))
            continue
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
        report.append("%s: %d pipelines, %d added, %d already in, %d point-list records left out%s" %
                      (name, len(recs), added, repeats, dropped, (" (" + note + ")") if note else ""))
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
    report.write("record size %d, %s\n" % (SIZE, MAGIC.decode()))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("triforce_pipeline_states.bin.xz", lzma.compress(data))
        z.writestr("report.txt", report.getvalue())
    return True


def describe(recs):
    programs = collections.Counter()
    kinds = collections.Counter()
    for r in recs:
        code = struct.unpack_from("<4Q", r, 0)
        mesh = struct.unpack_from("<I", r, 40)[0]
        programs[(code, mesh)] += 1
        kinds["mesh" if mesh else "graphics"] += 1
    return "%d pipelines (%s) of %d programs" % (len(recs), ", ".join("%s %d" % kv for kv in sorted(kinds.items())), len(programs))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("lists", nargs="*")
    p.add_argument("--out")
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
        merged, report = merge_sources(sources, a.keep_points)
        for line in report:
            print(line)
        if a.out:
            with open(a.out, "wb") as f:
                f.write(MAGIC + struct.pack("<I", SIZE) + b"".join(merged))
            print("%s: %s" % (a.out, describe(merged)))
        return 0
    if not a.lists:
        p.error("no list")
    merged, seen = [], set()
    for path in a.lists:
        recs = read(path)
        print("%s: %s" % (path, describe(recs)))
        for r in recs:
            if r not in seen:
                seen.add(r)
                merged.append(r)
    if a.out:
        with open(a.out, "wb") as f:
            f.write(MAGIC + struct.pack("<I", SIZE) + b"".join(merged))
        print("%s: %s" % (a.out, describe(merged)))


if __name__ == "__main__":
    sys.exit(main())
