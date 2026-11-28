"""(Triforce VR) VR's texts: your own wording kept in edits/ (in git: none of the game's text), and a work/ folder to write
in, with the game's text beside yours (made from your own game, never committed).

    python vr_text.py open --game <game folder> [--all]   work/ from your game's texts, with edits/ filled in
    python vr_text.py save                                edits/ from work/: the labels you wrote, without the game's text
    python vr_build.py <game folder>                      edits/ into your game (both control schemes)

open writes the files edits/ has (--all: every text file of the game, the tutorial pop-ups and the HUD hints, to find new
ones); a work/ folder already there is left alone (--fresh: made again, what it has that save did not take is lost).
save keeps a label only when one of its [VR] [VR2] [VR icon] [VR2 icon] is written, drops [Original] and [Shared with],
writes a text that is the game's own as <game>, and drops the game's lines at the start of a PouchContent text (the build
puts the game's own first there).
"""
import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EDITS, WORK = os.path.join(HERE, "edits"), os.path.join(HERE, "work")
BLOCK = re.compile(r"(?m)^(?==== .+ ===$)")
TAGS = r"(?:Original|VR|VR2|VR icon|VR2 icon|Icon|Shared with)"
FIELDS = ("VR icon", "VR", "VR2 icon", "VR2")
ADDED_TO = "items/PouchContent.txt"
HEAD_NOTE = "# Under each label: your text under [VR] (Full Gesture) and [VR2] (Simplified); empty or <game> keeps the game's.\n"


def hud(rel):
    return rel.replace("\\", "/").startswith("prompts/hud_hints/")


def fields(b, rel):
    """a label's VR fields as written: {tag: text}"""
    out = {}
    for tag in FIELDS:
        if hud(rel) or tag.endswith("icon"):
            m = re.search(r"(?m)^\[%s\][ \t]*(.*)$" % re.escape(tag), b)
            out[tag] = m.group(1).strip() if m else ""
        else:
            m = re.search(r"(?ms)^\[%s\][ \t]*\n(.*?)(?=^\[%s\]|\Z)" % (re.escape(tag), TAGS), b)
            out[tag] = m.group(1).strip("\n").rstrip() if m else ""
    return out


def original(b, rel):
    if hud(rel):
        m = re.search(r"(?m)^\[Original\][ \t]*(.*)$", b)
        return m.group(1).strip() if m else ""
    m = re.search(r"(?ms)^\[Original\][ \t]*\n(.*?)(?=^\[%s\]|\Z)" % TAGS, b)
    return m.group(1).strip("\n").rstrip() if m else ""


def flat(t):
    return " ".join(t.split())


def put(b, rel, tag, text):
    """a label's field written (as open fills a work file)"""
    if hud(rel) or tag.endswith("icon"):
        b, n = re.subn(r"(?m)^\[%s\][ \t]*.*$" % re.escape(tag), lambda m: "[%s] %s" % (tag, text), b, count=1)
        return b
    m = re.search(r"(?ms)^\[%s\][ \t]*\n(.*?)(?=^\[%s\]|\Z)" % (re.escape(tag), TAGS), b)
    if not m:
        return b
    return b[:m.start(1)] + text + "\n\n" + (b[m.end(1):].lstrip("\n") if m.end(1) < len(b) else "\n")


def text_files(root):
    for d, _, fns in os.walk(root):
        for fn in sorted(fns):
            if fn.endswith(".txt") and fn not in ("README.txt", "icons_in_text.txt"):
                yield os.path.relpath(os.path.join(d, fn), root)


def save(a):
    kept_files, kept_labels = 0, 0
    wrote = set()
    for rel in text_files(WORK):
        text = open(os.path.join(WORK, rel), encoding="utf-8").read()
        parts = BLOCK.split(text)
        head = "".join(HEAD_NOTE if "[Original]" in line else line for line in parts[0].splitlines(True) if line.startswith("#"))
        out = []
        for b in parts[1:]:
            label = b.splitlines()[0]
            f, orig = fields(b, rel), original(b, rel)
            if not any(f.values()):
                continue
            for tag in ("VR", "VR2"):
                t = f[tag]
                if not t or t == "<game>":
                    continue
                if orig and flat(t) == flat(orig):
                    f[tag] = "<game>"
                elif rel.replace("\\", "/") == ADDED_TO and orig:
                    lines = t.split("\n")
                    for k in range(len(lines), 0, -1):
                        if flat("\n".join(lines[:k])) == flat(orig):
                            f[tag] = "\n".join(lines[k:]).strip("\n")
                            break
            body = [label]
            if hud(rel):
                icon = re.search(r"(?m)^\[Icon\].*$", b)
                if icon:
                    body.append(icon.group(0))
                body += ["[%s] %s" % (tag, f[tag]) for tag in FIELDS]
                body.append("")
            else:
                for tag in FIELDS:
                    if tag.endswith("icon"):
                        if f[tag] or re.search(r"(?m)^\[%s\]" % re.escape(tag), b):
                            body.append("[%s] %s" % (tag, f[tag]))
                    else:
                        body += ["[%s]" % tag, f[tag], ""]
                body.append("")
            out.append("\n".join(body) + "\n")
            kept_labels += 1
        dest = os.path.join(EDITS, rel)
        if out:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "w", encoding="utf-8").write(head + "\n" + "".join(out))
            wrote.add(os.path.normpath(rel))
            kept_files += 1
    for rel in list(text_files(EDITS)) if os.path.isdir(EDITS) else []:
        if os.path.normpath(rel) not in wrote:   # (nothing written in it any more)
            os.remove(os.path.join(EDITS, rel))
            print("vr_text: %s has no VR text now: taken out of edits/" % rel)
    print("vr_text: edits/: %d label(s) in %d file(s)" % (kept_labels, kept_files))


def open_work(a):
    if os.path.isdir(WORK):
        if not a.fresh:
            raise SystemExit("vr_text: work/ is there already (--fresh to make it again: what save has not taken is lost)")
        shutil.rmtree(WORK)
    sys.path.insert(0, HERE)
    import gen_vr_text
    full = os.path.join(HERE, "work_all") if not a.all else WORK
    gen_vr_text.main(os.path.join(a.game, "romfs"), os.path.join(a.game, "image.bin"), full)
    if not a.all:   # (the files edits/ has, alone)
        for rel in text_files(EDITS):
            src = os.path.join(full, rel)
            if os.path.exists(src):
                os.makedirs(os.path.dirname(os.path.join(WORK, rel)), exist_ok=True)
                shutil.copy(src, os.path.join(WORK, rel))
            else:
                print("vr_text: %s is no file of the game's texts" % rel)
        shutil.rmtree(full)
    filled = 0
    for rel in text_files(EDITS):
        path = os.path.join(WORK, rel)
        if not os.path.exists(path):
            continue
        mine = {b.splitlines()[0]: fields(b, rel) for b in BLOCK.split(open(os.path.join(EDITS, rel), encoding="utf-8").read())[1:]}
        parts = BLOCK.split(open(path, encoding="utf-8").read())
        for i, b in enumerate(parts[1:], 1):
            f = mine.get(b.splitlines()[0])
            if not f:
                continue
            if not hud(rel):   # (a pop-up's step gets its icon fields where edits/ has them)
                for tag in ("VR2 icon", "VR icon"):
                    if f.get(tag) and not re.search(r"(?m)^\[%s\]" % re.escape(tag), b):
                        b = b.replace("[%s]\n" % tag[:-5], "[%s] \n[%s]\n" % (tag, tag[:-5]), 1)
            for tag in FIELDS:
                if f.get(tag):
                    b = put(b, rel, tag, f[tag])
            parts[i] = b
            filled += 1
        open(path, "w", encoding="utf-8").write("".join(parts))
    print("vr_text: work/: %d label(s) of yours filled in" % filled)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open")
    o.add_argument("--game", required=True, help="the game folder (romfs/, image.bin)")
    o.add_argument("--all", action="store_true", help="every text file of the game, not only the ones edits/ has")
    o.add_argument("--fresh", action="store_true", help="make work/ again")
    sub.add_parser("save")
    a = ap.parse_args()
    (open_work if a.cmd == "open" else save)(a)


if __name__ == "__main__":
    main()
