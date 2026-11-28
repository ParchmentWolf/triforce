"""Writes vr_text/: every game text as a file to reword for VR, and the button prompts.

    python gen_vr_text.py <romfs> <image.bin> [<out dir>]      (out: vr_text beside this script)

An existing file is never overwritten (your [VR] lines are kept); delete a file to make it again.
"""
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import byml_dump  # noqa: E402
import ctrlguide  # noqa: E402
import mals_dump  # noqa: E402

# the icon tag's values ({1.4:NN}) by button name, as mals_edit.py writes them, and the variants that draw the same button
ICON_NAMES = {0x00: "LS_Up", 0x01: "LS_Down", 0x02: "LS_Left", 0x03: "LS_Right", 0x04: "RS_UpDown", 0x05: "RS_LeftRight",
              0x06: "Up", 0x07: "Down", 0x08: "Left", 0x09: "Right", 0x0a: "A", 0x0b: "A", 0x0c: "X", 0x0d: "Y",
              0x0e: "ZL", 0x0f: "ZL", 0x10: "B", 0x11: "B", 0x12: "B", 0x13: "B", 0x14: "L", 0x15: "R", 0x16: "ZR",
              0x17: "Plus", 0x18: "Minus", 0x21: "LS", 0x22: "RS", 0x23: "LS_LeftRight", 0x25: "X", 0x26: "X",
              0x27: "B", 0x28: "X"}
TAG = re.compile(r"\{1\.4:([0-9a-f]{2})\}")


def readable(text):
    """the dump's text with button icons by name ([A]) and real line breaks"""
    def icon(m):
        v = int(m.group(1), 16)
        return "[%s]" % ICON_NAMES[v] if v in ICON_NAMES else m.group(0)
    return TAG.sub(icon, text).replace("\\n", "\n")


def icons_of(text):
    return [ICON_NAMES.get(int(v, 16), "{1.4:%s}" % v) for v in TAG.findall(text)]


def write_new(path, body):
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return True


def group_of(msbt):
    top = msbt.split("/")[0]
    return {"EventFlowMsg": "dialogue", "LayoutMsg": "ui", "ActorMsg": "items"}.get(top, "other")


def main(romfs, image, out):
    d = mals_dump.zs_dicts(romfs)
    sarc = mals_dump.unzs(os.path.join(romfs, "Mals", "USen.Product.110.sarc.zs"), d["zs.zsdic"])
    files = mals_dump.sarc_files(sarc)
    tags = collections.defaultdict(lambda: [0, ""])
    texts = {}   # (msbt, label) -> dump notation
    order = collections.defaultdict(list)
    for f in sorted(files):
        s, e = files[f]
        if sarc[s:s + 8] != b"MsgStdBn":
            continue
        enc, _, labels, tx, _ = mals_dump.msbt(sarc[s:e])
        for i, t in enumerate(tx):
            lab = labels.get(i, "#%d" % i)
            texts[(f, lab)] = mals_dump.render(t, enc, tags, f)
            order[f].append(lab)
    made = 0
    icon_lines = []
    for f, labs in order.items():
        body = ["# %s" % f,
                "# Under each label: the game's text ([Original]); write yours under [VR], and under [VR2] the Simplified controls' "
                "(empty: [VR] there too). An empty [VR] keeps the game's.",
                "# Button icons: [A] [B] [X] [Y] [L] [R] [ZL] [ZR] [Plus] [Minus] [LS] [RS] [Up] [Down] [Left] [Right] ...",
                "# Keep the {..} tags you want (colours, pauses, a new box {0.4:}); see README.txt.", ""]
        for lab in labs:
            t = texts[(f, lab)]
            body += ["=== %s ===" % lab, "[Original]", readable(t), "", "[VR]", "", "[VR2]", "", ""]
            ic = icons_of(t)
            if ic:
                icon_lines.append("%s\t%s\t%s\t%s" % (", ".join(ic), f, lab, readable(t).replace("\n", " / ")))
        name = f.split("/")[-1].replace(".msbt", ".txt")
        made += write_new(os.path.join(out, group_of(f), name), "\n".join(body))
    write_new(os.path.join(out, "icons_in_text.txt"),
              "# Every text with a button icon: the icons, the file, the label, the text (line breaks as ' / ')\n" +
              "\n".join(sorted(icon_lines)) + "\n")

    # the HUD's control hints (UI/CtrlGuideSetTable): one file each, named by what shows it
    names = set(re.findall(rb"[A-Za-z0-9_]{1,64}", open(image, "rb").read()))
    for (f, lab) in texts:
        names.add(lab.encode())
    table = {}
    for n in names:
        table.setdefault(ctrlguide.murmur3(n), n.decode())
    root = byml_dump.parse(open(os.path.join(romfs, "UI", "CtrlGuideSetTable",
                                             "CtrlGuideSetTable.game__ui__CtrlGuideSetTable.bgyml"), "rb").read())
    uses = collections.defaultdict(list)   # a command's word -> the hint sets showing it
    sets = []
    for i, gs in enumerate(root["GuideSetArray"]):
        gt = gs.get("GuideType")
        gname = table.get(gt, "") if gt is not None else "Always"
        steps = []
        for g in gs.get("GuideArray", []):
            c, k = g.get("Command"), g.get("GuideKey")
            steps.append((table.get(c, "?") if c is not None else "", table.get(k, "?") if k is not None else ""))
        if not gname:   # (a type the game's strings do not name: by its commands)
            gname = "_".join(c for c, _ in steps if c) or "Set%d" % i
        sets.append((i, gname, steps))
        for c, _ in steps:
            if c:
                uses[c].append(gname)
    for i, gname, steps in sets:
        body = ["# HUD control hint set %d: %s" % (i, gname),
                "# Each step: the button icon shown, the word beside it (LayoutMsg/CtrlGuide_00, by its label).",
                "# Write the icon you want under [VR icon] (an icon file's name from your folder) and the word under [VR].",
                "# [VR2 icon] / [VR2]: the Simplified controls' (empty: [VR icon] / [VR] there too).",
                "# Note: a word is shared by every set that shows it (listed): changing it changes it in all of them.", ""]
        for n, (c, k) in enumerate(steps, 1):
            word = readable(texts.get(("LayoutMsg/CtrlGuide_00.msbt", c), "")) if c else ""
            shared = [s for s in uses.get(c, []) if s != gname]
            body += ["=== Step %d: %s ===" % (n, c or "(no word)"),
                     "[Icon] %s" % (k or "-"),
                     "[Original] %s" % word,
                     "[Shared with] %s" % (", ".join(sorted(set(shared))) or "-"),
                     "[VR icon] ",
                     "[VR] ",
                     "[VR2 icon] ",
                     "[VR2] ", ""]
        write_new(os.path.join(out, "prompts", "hud_hints", "%02d_%s.txt" % (i, gname)), "\n".join(body))

    # the tutorial pop-ups (LayoutMsg/ActionGuide_00): one file per guide type
    guide = collections.defaultdict(list)
    for (f, lab) in texts:
        if f != "LayoutMsg/ActionGuide_00.msbt":
            continue
        m = re.match(r"(Title|Msg|Guide|Guide_Legacy)_(.+?)(?:_(\d\d))?$", lab)
        key = m.group(2) if m else lab
        guide[key].append(lab)
    for key, labs in sorted(guide.items()):
        body = ["# Tutorial pop-up: %s (LayoutMsg/ActionGuide_00)" % key,
                "# Title_ is the heading, Msg_ its line, Guide_..._00/_01/_02 the words beside each step's button icon.",
                "# The icon beside a step is chosen by the game's code (not a text): write the one you want under [VR icon].",
                "# [VR2] / [VR2 icon]: the Simplified controls' (empty: [VR] / [VR icon] there too).",
                ""]
        for lab in sorted(labs):
            body += ["=== %s ===" % lab, "[Original]", readable(texts[("LayoutMsg/ActionGuide_00.msbt", lab)]), ""]
            if lab.startswith("Guide"):
                body += ["[VR icon] "]
            body += ["[VR]", "", ""]
            if lab.startswith("Guide"):
                body += ["[VR2 icon] "]
            body += ["[VR2]", "", ""]
        write_new(os.path.join(out, "prompts", "tutorial_popups", "%s.txt" % key), "\n".join(body))

    print("vr_text: %d text files; %d hint sets; %d tutorial pop-ups; %d texts with icons" %
          (made, len(sets), len(guide), len(icon_lines)))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else os.path.join(here, "work"))
