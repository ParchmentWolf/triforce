"""(Triforce VR) scripts/vr_text/edits: the team's VR wording alone, none of the game's text (CONTRIBUTING.md): no
[Original] or [Shared with] lines, and every label in the shape vr_build.py reads (its [VR] fields). Needs no game files.

    python -I tests/test_vr_text_edits.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITS = os.path.join(ROOT, "scripts", "vr_text", "edits")


def main():
    files = [os.path.join(d, f) for d, _, fs in os.walk(EDITS) for f in fs]
    assert files, "scripts/vr_text/edits is empty"
    labels = 0
    for p in files:
        rel = os.path.relpath(p, EDITS)
        assert p.endswith(".txt"), "%s: edits/ holds the .txt files alone" % rel
        text = open(p, encoding="utf-8").read()
        for bad in ("Original", "Shared with"):   # (as fields: the files' head comments name them)
            assert not re.search(r"(?m)^\[%s\]" % bad, text), \
                "%s has [%s]: the game's text is never committed (vr_text.py save drops it)" % (rel, bad)
        blocks = re.split(r"(?m)^(?==== .+ ===$)", text)[1:]
        assert blocks, "%s has no label" % rel
        for b in blocks:
            assert re.search(r"(?m)^\[VR\]", b), "%s: %s has no [VR]" % (rel, b.splitlines()[0])
            labels += 1
    print("PASS: %d label(s) in %d file(s), no game text" % (labels, len(files)))


if __name__ == "__main__":
    main()
