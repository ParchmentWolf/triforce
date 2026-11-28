"""Fills the empty [VR icon] [VR] [VR2 icon] [VR2] of the HUD hints and tutorial pop-ups with the VR controls
(VR: Full Gesture, VR2: Simplified). A field already written is never changed. None given: left empty (the game's;
for VR2, the VR one)."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "work", "prompts")   # (vr_text.py open makes work/; save takes it into edits/)
N = None
# HUD hint steps by file and command: (VR icon, VR word, VR2 icon, VR2 word)
HUD = {
    "01_SwingSword": {"SwingSword": ("Swing", N, N, N)},
    "02_ReleaseHand": {"ReleaseHand": ("B", N, N, N)},
    "03_OpenPouch": {"OpenPouch": ("X", N, N, N)},
    "04_Dive": {"Accelerate": ("RS_Click", N, N, N)},
    "05_DekuStick": {"Swing": ("Swing", N, N, N), "PutAway": ("R_Grip", N, "B", N)},
    "06_DekuNut": {"Throw": ("R_Grip", N, "Swing", N)},
    "07_Bomb": {"Throw": ("Swing", N, N, N), "PutAway": ("B", N, N, N)},
    "08_Bombchu": {"FireBombchu": ("R_Grip", "Let Go", "Swing", "Release"), "PutAway": ("B", N, N, N)},
    "09_Use": {"Use": ("R_Grip", N, N, N)},
    "10_TakeOut": {"TakeOut": ("R_Grip", "Reach Back", N, "Take Out")},
    "11_Drink": {"Drink": ("R_Grip", N, "Swing", N)},
    "12_Read": {"Read": ("R_Grip", N, N, N)},
    "13_Jump": {"Jump": ("RS_Click", N, N, N)},
    "14_Throw": {"Throw": ("Swing", N, N, N)},
    "16_SlingShot": {"ShootSeed": ("L_Grip", "Pull String", "R_Grip", "Shoot Seed")},
    "17_Bow": {"ShootArrow": ("L_Grip", "Pull String", "R_Grip", "Shoot Arrow")},
    "18_Boomerang": {"Throw": ("R_Trigger", N, "R_Grip", N)},
    "19_Hookshot": {"Fire": ("R_Trigger", N, "R_Grip", N)},
    "20_Hammer": {"Hit": ("Swing", N, N, N)},
    "22_ThrowLure": {"ThrowLure": ("R_Grip", N, N, N)},
    "23_MoveLure_RollUp": {"RollUp": ("R_Grip", N, N, N)},
    "24_MoveFishingRod_RollUp": {"RollUp": ("R_Grip", N, N, N)},
    "25_LockOn": {"LockOnAndCamerraReset": ("-", "Shield to Chest", "L_Trigger", "Target")},
    "26_Navi": {"Navi": ("-", "Hands Cover Ears", "R_Trigger", "Hold + Right")},
    "28_InWater": {"Accelerate": ("RS_Click", N, N, N)},
    "29_Brake": {"Brake": ("R_Grip", N, N, N)},
    "30_Hook": {"Hook": ("R_Grip", N, N, N)},
    "33_ReleaseHand_Jump": {"ReleaseHand": ("B", N, N, N), "Jump": ("RS_Click", N, N, N)},
    "34_RollUp": {"RollUp": ("R_Grip", N, N, N)},
    "36_Throw_Put": {"Throw": ("Swing", N, N, N)},
    "37_MoveShield": {"MoveShield": ("-", "Move Hand", N, N)},
}
TARGET = ("-", "Grip to Chest", "L_Trigger", "Target")
PULL = ("R_Grip", "Reach Back & Pull", "R_Grip", "Use")
AIM_STRING = ("L_Grip", "Pull String, Let Go", "R_Grip", "Hold & Release")
AIM_TRIGGER = ("R_Trigger", "Hold, Let Go", "R_Grip", "Hold & Release")
JUMP = ("RS_Click", N, N, N)
# tutorial pop-ups by label: Guide_ (icon, word, VR2 icon, VR2 word); Msg_/Title_ (None, text, None, VR2 text)
POP = {
    "Guide_AgonyStone_00": ("X", "Tap", N, N),
    "Guide_AlarmCucco_00": PULL,
    "Guide_Backflip_00": TARGET, "Guide_Backflip_02": JUMP,
    "Guide_Bombchu_00": ("R_Grip", "Reach Back & Pull", "R_Trigger", "Choose"),
    "Guide_Bombchu_01": ("R_Grip", "Let Go", "Swing", "Swing"),
    "Guide_Bomb_00": ("R_Grip", "Reach Back & Pull", "R_Trigger", "Choose"),
    "Guide_Bomb_01": ("Swing", "Swing", N, N),
    "Guide_Boomerang_00": ("R_Trigger", "Hold, Throw, Let Go", "R_Grip", "Hold & Release"),
    "Guide_BootShortcut_00": ("-", "Shake Both Arms Up", "R_Trigger", "Hold + Down"),
    "Guide_Bottle_00": ("R_Grip", "Pull Out, Swing to Scoop", "Swing", "Swing"),
    "Guide_Bow_00": AIM_STRING,
    "Guide_DekuNut_00": ("R_Grip", "Reach Back & Throw", "Swing", "Swing"),
    "Guide_DekuStick_00": ("Swing", N, N, N),
    "Guide_DinFire_00": PULL,
    "Guide_EquipmentMenuForBoot_00": ("X", "Tap", N, N),
    "Guide_EquipmentMenuForHeadArmor_00": ("X", "Tap", N, N),
    "Guide_EquipmentMenu_00": ("X", "Tap", N, N),
    "Guide_FaroreWind_00": PULL,
    "Guide_FireArrow_00": AIM_STRING,
    "Guide_FishingRod_00": ("R_Grip", "Hold & Release", N, N),
    "Guide_Hammer_00": ("Swing", "Swing Down", N, N),
    "Guide_HeadShortcut_00": ("-", "Grip on Top of Head", "R_Trigger", "Hold + Up"),
    "Guide_Hookshot_00": AIM_TRIGGER,
    "Guide_HorizontalSlash_00": ("Swing", "Swing Sideways", N, N),
    "Guide_IceArrow_00": AIM_STRING,
    "Guide_ItemMenu_00": ("X", "Tap", N, N),
    "Guide_ItemShortcut_00": ("L_Trigger", "Hold", "R_Trigger", "Hold"),
    "Guide_JumpSlash_00": TARGET, "Guide_JumpSlash_01": JUMP,
    "Guide_JumpSlash_02": ("Swing", "Swing Down", N, N),
    "Guide_Legacy_Backflip_00": TARGET, "Guide_Legacy_Backflip_02": JUMP,
    "Guide_Legacy_JumpSlash_00": TARGET, "Guide_Legacy_JumpSlash_02": ("Swing", "Swing Down", N, N),
    "Guide_Legacy_SideJump_00": TARGET, "Guide_Legacy_SideJump_02": JUMP,
    "Guide_LightArrow_00": AIM_STRING,
    "Guide_LockOnShield_00": ("-", "Shield to Chest", N, N),
    "Guide_LockOnSideMove_00": TARGET,
    "Guide_LockOn_Switch_00": TARGET,
    "Guide_LockOn_00": ("-", "Grip to Chest", "L_Trigger", "<game>"),
    "Guide_Longshot_00": AIM_TRIGGER,
    "Guide_MagicBean_00": PULL,
    "Guide_Navi_00": ("-", "Hands Cover Ears", "R_Trigger", "Hold + Right"),
    "Guide_NayruLove_00": PULL,
    "Guide_Ocarina_00": ("-", "Hands Together at Mouth", "R_Grip", "<game>"),
    "Guide_RotarySlash_00": ("Swing", "Swing Out, Hold, Bring In", "Y", "<game>"),
    "Guide_Save_00": ("X", "Tap", N, N),
    "Guide_ScrubBusinessSeed_00": PULL,
    "Guide_SideJump_00": TARGET, "Guide_SideJump_02": JUMP,
    "Guide_SlingShot_00": AIM_STRING,
    "Guide_SystemMinus_00": ("X", "Hold", N, N),
    "Guide_Thrust_00": TARGET, "Guide_Thrust_02": ("Swing", "Stab Forward", N, N),
    "Guide_TimeTrail_00": ("X", "Hold", N, N),
    "Guide_VerticalSlash_01": ("Swing", "Swing Down", N, N),
    "Guide_Weapon_Shield_Mirror_00": ("-", "Shield to Chest", N, N),
    "Guide_Weapon_Shield_Mirror_01": ("-", "Move Hand", N, N),
}
BLOCK = re.compile(r"(?m)^(?==== .+ ===$)")
# the pause menu's controls page (ui/PlusMenu_00.txt): label (after Pa_System_00-Pa_SystemController_00-) -> (VR, VR2).
# Its icons are the VR icons' own codes (nx2/prompt_vr.py ICON_BASE: LT RT LG RG Swing Menu A B X Y LS-press RS-press blank)
V = {k: "[U+%04X]" % (0xF6C0 + i) for i, k in enumerate(
    ["LT", "RT", "LG", "RG", "Swing", "Menu", "A", "B", "X", "Y", "LS_Push", "RS_Push", "Blank"])}
PAGE = {
    "Pa_BtnZL_00-T_IconL_00": (V["Blank"], V["LT"]), "Pa_BtnZL_00-T_GuideL_00": ("Target: Shield to Chest", "Target"),
    "Pa_BtnZR_00-T_IconR_00": (V["RG"], V["RG"]), "Pa_BtnZR_00-T_GuideR_00": ("Item: Reach Back & Pull", "Use Item"),
    "Pa_BtnL_00-T_IconL_00": (V["LT"], V["LS_Push"]), "Pa_BtnL_00-T_GuideL_00": (N, "Sprint (Toggle)"),
    "Pa_BtnR_00-T_IconR_00": (V["RT"], V["RT"]), "Pa_BtnR_00-T_GuideR_00": (N, "Item Panel (Hold)"),
    "Pa_BtnMinus_00-T_IconL_00": (V["X"], N), "Pa_BtnMinus_00-T_GuideL_00": ("Open Map (Hold)", N),
    "Pa_BtnPlus_00-T_IconR_00": (V["X"], N), "Pa_BtnPlus_00-T_GuideR_00": ("Open Menu (Tap)", N),
    "Pa_BtnA_00-T_IconR_00": (V["A"], N), "Pa_BtnB_00-T_IconR_00": (V["B"], N),
    "Pa_BtnX_00-T_IconR_00": (V["LG"], V["Blank"]),
    "Pa_BtnY_00-T_IconR_00": (V["Swing"], N), "Pa_BtnY_00-T_GuideR_00": ("Attack: Swing Sword", "Attack: Swing or Y"),
    "T_GuideBtnRStick_00": ("Jump (Press)", N),
    "Pa_BtnUp_00-T_IconL_00": (V["Blank"], V["RT"]), "Pa_BtnUp_00-T_GuideL_00": ("Mask: Grip Head, Lens: Nod", "RT + Up: Accessory"),
    "Pa_BtnLeft_00-T_IconL_00": (V["Blank"], V["RT"]), "Pa_BtnLeft_00-T_GuideL_00": ("Ocarina: Hands at Mouth", "RT + Left: Ocarina"),
    "Pa_BtnRight_00-T_IconL_00": (V["Blank"], V["RT"]), "Pa_BtnRight_00-T_GuideL_00": ("Navi: Hands Cover Ears", "RT + Right: Navi"),
    "Pa_BtnDown_00-T_IconL_00": (V["Blank"], V["RT"]), "Pa_BtnDown_00-T_GuideL_00": ("Boots: Shake Arms Up", "RT + Down: Boots"),
}
PAGE_OWN = {"Jump": ("Draw: Grips Behind Head", "Shield to Chest")}   # (the X button's label on the page)


def set_inline(b, tag, val):
    """'[tag] value' on one line: filled when empty"""
    if val is None: return b, 0
    m = re.search(r"(?m)^\[%s\][ \t]*(.*)$" % re.escape(tag), b)
    if not m:
        return b, 0
    if m.group(1).strip(): return b, 0
    return b[:m.start()] + "[%s] %s" % (tag, val) + b[m.end():], 1


def set_block(b, tag, val):
    """'[tag]' then the text on the lines under it, up to the next tag: filled when empty"""
    if val is None: return b, 0
    m = re.search(r"(?ms)^\[%s\][ \t]*\n(.*?)(?=^\[(?:Original|VR|VR2|VR icon|VR2 icon)\]|\Z)" % re.escape(tag), b)
    if not m or m.group(1).strip(): return b, 0
    return b[:m.start(1)] + val + "\n\n" + b[m.end(1):].lstrip("\n") if m.end(1) < len(b) else b[:m.start(1)] + val + "\n\n\n", 1


n = 0
# the HUD hints: [VR2 icon] and [VR2] lines added under [VR], then filled
d = os.path.join(P, "hud_hints")
for fn in sorted(os.listdir(d)):
    p = os.path.join(d, fn); t = open(p, encoding="utf-8").read()
    if "[VR2]" not in t:
        t = t.replace("# Write the icon you want under [VR icon] (an icon file's name from your folder) and the word under [VR].",
                      "# Write the icon you want under [VR icon] (an icon file's name from your folder) and the word under [VR].\n"
                      "# [VR2 icon] / [VR2]: the Simplified controls' (empty: [VR icon] / [VR] there too).")
        t = re.sub(r"(?m)^(\[VR\][^\n]*)$", r"\1\n[VR2 icon] \n[VR2] ", t)
    want = HUD.get(fn[:-4], {})
    parts = BLOCK.split(t); out = [parts[0]]
    for b in parts[1:]:
        cmd = re.match(r"=== Step \d+: (.+?) ===", b).group(1)
        if cmd in want:
            vi, vw, v2i, v2w = want[cmd]
            for tag, val in (("VR icon", vi), ("VR", vw), ("VR2 icon", v2i), ("VR2", v2w)):
                b, k = set_inline(b, tag, val); n += k
        out.append(b)
    open(p, "w", encoding="utf-8").write("".join(out))
# the tutorial pop-ups
d = os.path.join(P, "tutorial_popups")
seen = set()
for fn in sorted(os.listdir(d)):
    p = os.path.join(d, fn); t = open(p, encoding="utf-8").read()
    parts = BLOCK.split(t); out = [parts[0]]
    for b in parts[1:]:
        lab = re.match(r"=== (.+?) ===", b).group(1)
        if lab in POP:
            seen.add(lab)
            vi, vw, v2i, v2w = POP[lab]
            b, k = set_inline(b, "VR icon", vi); n += k
            b, k = set_inline(b, "VR2 icon", v2i); n += k
            b, k = set_block(b, "VR", vw); n += k
            b, k = set_block(b, "VR2", v2w); n += k
        out.append(b)
    open(p, "w", encoding="utf-8").write("".join(out))
# the controls page
p = os.path.join(HERE, "work", "ui", "PlusMenu_00.txt"); t = open(p, encoding="utf-8").read()
parts = BLOCK.split(t); out = [parts[0]]
want = {"Pa_System_00-Pa_SystemController_00-" + k: v for k, v in PAGE.items()}
want.update(PAGE_OWN)
for b in parts[1:]:
    lab = re.match(r"=== (.+?) ===", b).group(1)
    if lab in want:
        seen.add(lab)
        vr, vr2 = want[lab]
        b, k = set_block(b, "VR", vr); n += k
        b, k = set_block(b, "VR2", vr2); n += k
    out.append(b)
open(p, "w", encoding="utf-8").write("".join(out))
missing = (set(POP) | set(want)) - seen
print("filled %d field(s)%s" % (n, "; labels not found: %s" % sorted(missing) if missing else ""))
