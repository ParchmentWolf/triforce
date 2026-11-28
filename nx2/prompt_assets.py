"""(hookshot) The button prompts of other controllers: the game's button-icon font redrawn per controller face, from the user's RomFS
and Kenney's Input Prompts (CC0, third_party/kenney_input).

    python -I nx2/prompt_assets.py --romfs <dir> --out <game folder>/prompts

Writes <out>/<face>/External.bfotf for each face (switch, xbox, ps4, ps5, steamdeck, keyboard). Every text in the game draws its button icons
from Font2/Scalable/External.*.bfotf (dialogue, the control hints, menus): A B X Y at U+E040..E043, L R ZL ZR at E044..E047, Plus
and Minus at E04B and E04C, the stick presses at E056 and E057, the d-pad at E060..E063. Each written font has one icon per pad
input at U+F700 + HOS_PAD_* (gpu/vk/vk_api.h), and each of those Switch buttons' code points in a cmap segment of its own: the
game (host/prompts.c) points each one at the icon of the pad input bound to that button when it serves the font, so the icons
follow the controls, changed ones too. (Triforce) Each controller face's font also has every controller face's icons
(faces_font: FACE_BASE, BIND_BASE), the same glyphs in each, so the game points the font it has at another face or new
controls while it runs (host/prompts.c's live part). The keyboard face (the keyboard and mouse; nx2/prompt_keys.py draws it, from
nothing but a font of the repository's) has an icon per key that can be bound instead, at U+F700 + its key code, and what is
said of a pad input below is a key code's there.

The textures with button icons (the ocarina's notes, the letters on black, the controller in the pause menu) the same way, with
Pillow, astc_encoder and texture2ddecoder: <out>/Common.bntx is the game's UI/Layout2Archive/Common bntx decompressed, and
<face>/textures.bin the encoded blocks to write over it for each Switch button on each pad input, which the game picks by the
controls when it serves the file. The Talk ring's buttons and the ocarina hint's icons (the layouts of UI/Layout2Archive/Common,
<out>/Common.blarc) the same way: <out>/ring.bin and <face>/hint.bin say what to write over them for the controls.

Each face's images (the notes, the letters, the controller picture drawn by nx2/prompt_draw.py, the leader lines) are made as
layers first: --dump <dir> writes them as PNG, and a PNG of the same name in nx2/prompt_faces/<face>/ takes a layer's place, to
rework one by hand (nx2/prompt_faces/README.md).

The faces' fonts are larger than the game's, and the game drops a file larger than its entry in the resource size table: <out>/
rsizetable.zs is the game's table with the font's entry raised to fit the largest, served in its place.

(Triforce) The title screen's Options entry ("Options / ZELDA NOTES Setting") the same way: <out>/mals/<language>.product.110
.sarc.zs is each language's messages with that entry made the game's word for Options, its separator and TITLE_TEXT, and the
host serves the one of the language the game runs in (title_messages). The same file has the texts that name the
console in the PC's words (PC_TEXTS: the ocarina's microphone hint says your microphone, not the console's), at the same size.

A .bfotf is an OpenType font behind an 8-byte header and XORed per little-endian word: the header is the magic 0x18029a7f and the
font's size (big-endian), each XORed with the same key as the font. The .zs files are zstd frames made with the dictionary zs.zsdic
of Pack/ZsDic.pack.zs.
"""
import argparse
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # (python -I leaves the script folder off)
from prompt_faces import FACES, override, parts   # noqa: E402 (the faces: their icons, drawings and their parts)
KENNEY = os.path.join(os.path.dirname(HERE), "third_party", "kenney_input")
FONT = "Font2/Scalable/External.Nin_Ounce_NVN2.bfotf.zs"
MAGIC = 0x18029A7F
PAD_BASE = 0xF700
WIDE = 1.6   # (how much wider than the game's icon a wide Kenney icon may be)
# the HOS_PAD_* inputs (gpu/vk/vk_api.h), in order
PADS = ["south", "east", "west", "north", "back", "guide", "start", "lstick", "rstick", "lshoulder", "rshoulder", "up", "down", "left",
        "right", "ltrigger", "rtrigger"]
# the Switch buttons' code points, in HOS_SW_* order (A B X Y LS RS L R ZL ZR Plus Minus Left Up Right Down), and hookshot's
# default controls for them (host/nn_hid.c pad_default: by position, A the right face button)
SWITCH = [0xE040, 0xE041, 0xE042, 0xE043, 0xE056, 0xE057, 0xE044, 0xE045, 0xE046, 0xE047, 0xE04B, 0xE04C, 0xE062, 0xE060, 0xE063,
          0xE061]
DEFAULT = ["east", "south", "north", "west", "lstick", "rstick", "lshoulder", "rshoulder", "ltrigger", "rtrigger", "start", "back",
           "left", "up", "right", "down"]
# the game's own icon for each pad input: what the Switch face shows
SWITCH_ICON = {"south": 0xE041, "east": 0xE040, "west": 0xE043, "north": 0xE042, "back": 0xE04C, "guide": 0xE04A, "start": 0xE04B,
               "lstick": 0xE056, "rstick": 0xE057, "lshoulder": 0xE044, "rshoulder": 0xE045, "up": 0xE060, "down": 0xE061,
               "left": 0xE062, "right": 0xE063, "ltrigger": 0xE046, "rtrigger": 0xE047}
# the icons that do not follow the controls, by the Kenney glyph's name after the face's prefix: the whole d-pad (the sticks keep the
# game's icons, an L or R cap with its arrows: right for any controller, where Kenney's are drawn in perspective)
STATIC = {0xE049: "dpad", 0xE064: "dpad_vertical_outline", 0xE065: "dpad_horizontal_outline"}


def zs_dictionary(romfs, which=b"zs.zsdic"):
    """zs.zsdic (or another of its dictionaries: pack.zsdic for the packs), out of Pack/ZsDic.pack.zs (a SARC, itself zstd
    without a dictionary)"""
    import zstandard
    with open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb") as f:
        b = zstandard.ZstdDecompressor().decompressobj().decompress(f.read())
    data, = struct.unpack_from("<I", b, 12)
    hl, = struct.unpack_from("<H", b, 4)
    n, = struct.unpack_from("<H", b, hl + 6)
    names = hl + 12 + 16 * n + 8
    for i in range(n):
        attr, start, end = struct.unpack_from("<III", b, hl + 12 + 16 * i + 4)
        o = names + (attr & 0xFFFFFF) * 4
        if b[o:b.index(b"\0", o)] == which:
            return b[data + start:data + end]
    raise SystemExit("prompts: no %s in Pack/ZsDic.pack.zs" % which.decode())


def read_zs(romfs, rel, dictionary):
    """(Triforce, as NX2navi's tools/pad_prompts.py unpack) The file goes to the decompressor a piece at a time and the
    pieces' outputs are joined once. Given the whole file in one call the library grows one bytes object by copying as the
    output comes, and the textures (69 MB packed, 244 MB unpacked) took 20 s of this tool's 80 that way"""
    import zstandard
    d = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(dictionary)).decompressobj()
    with open(os.path.join(romfs, rel), "rb") as f:
        raw = f.read()
    parts = []
    for at in range(0, len(raw), 1 << 16):
        parts.append(d.decompress(raw[at:at + (1 << 16)]))
        if d.eof:
            break
    return b"".join(parts)


def size_table(romfs, dictionary, game_size, font_size):
    """the game's resource size table (System/Resource/ResourceSizeTable.*.rsizetable.zs: "RESTBL", u32 version, u32 name length,
    u32 hashed entries, u32 named entries; the hashed ones u32 CRC-32 of the path, u32 size, by hash) with the External font's
    entry raised from the game's font (game_size bytes) to fit one of font_size: the game drops a file larger than its entry. None
    when it fits already"""
    import zlib
    name, b = read_size_table(romfs, dictionary)
    hashed, = struct.unpack_from("<I", b, 14)
    want = zlib.crc32(FONT[:-3].encode())
    for i in range(hashed):
        at = 22 + 8 * i
        h, size = struct.unpack_from("<II", b, at)
        if h == want:
            fit = font_size + size - game_size   # (the entry's allowance over the file kept: 288 bytes)
            if fit <= size:
                return None
            struct.pack_into("<I", b, at + 4, fit)
            return bytes(b)
    raise SystemExit(f"prompts: {name} has no entry for {FONT[:-3]}")


def unwrap(blob):
    key = struct.unpack_from("<I", blob, 0)[0] ^ MAGIC
    size = struct.unpack(">I", struct.pack("<I", struct.unpack_from("<I", blob, 4)[0] ^ key))[0]
    body = b"".join(struct.pack("<I", w ^ key) for w in struct.unpack_from(f"<{(len(blob) - 8) // 4}I", blob, 8))
    return key, body[:size]


def wrap(key, otf):
    otf += b"\0" * (-len(otf) % 4)
    head = struct.pack("<II", MAGIC ^ key, struct.unpack("<I", struct.pack(">I", len(otf)))[0] ^ key)
    return head + b"".join(struct.pack("<I", w ^ key) for w in struct.unpack(f"<{len(otf) // 4}I", otf))


def cmap4(mapping, single):
    """a cmap table of one format 4 subtable (for Unicode BMP, platforms 0 and 3) from {code: glyph id}: runs of codes with
    consecutive glyphs share a segment, and each code of `single` has one of its own; every segment by idDelta alone"""
    segs = []
    for c in sorted(mapping):
        g = mapping[c]
        if segs and c not in single and segs[-1][1] == c - 1 and segs[-1][1] not in single and \
                (segs[-1][2] + c) & 0xFFFF == g:
            segs[-1][1] = c
        else:
            segs.append([c, c, (g - c) & 0xFFFF])
    segs.append([0xFFFF, 0xFFFF, 1])
    n = len(segs)
    search = 2 * (1 << (n.bit_length() - 1))
    sub = struct.pack(">HHHHHHH", 4, 16 + 8 * n, 0, 2 * n, search, (search // 2).bit_length() - 1, 2 * n - search)
    sub += b"".join(struct.pack(">H", s[1]) for s in segs) + b"\0\0"
    sub += b"".join(struct.pack(">H", s[0]) for s in segs)
    sub += b"".join(struct.pack(">H", s[2]) for s in segs)
    sub += b"\0\0" * n
    return struct.pack(">HHHHIHHI", 0, 2, 0, 3, 20, 3, 1, 20) + sub


# ((Triforce) the button prompts changed while the game runs, host/prompts.c's live part) Every controller face's font has every
# controller face's icons (LIVE_FACES, HOS_PROMPT_*'s order up to the keyboard's), so a new face or new controls are a change of
# the cmap of the font the game has (the same glyphs, the same size): face n's icon of pad input i at FACE_BASE + FACE_CODES x n
# + i, its d-pad icons (STATIC) at FACE_BASE + FACE_CODES x n + STATIC_AT.., and a code of its own for each Switch button b on
# each pad input i of each face at BIND_BASE + (n x 16 + b) x 17 + i, which a text's button codes are rewritten to (the game
# keeps a code's glyph once drawn: a new icon gets a code never drawn with another). All in the Private Use Area the game's font
# leaves free (checked: face_font)
LIVE_FACES = ["switch"] + [f for f in FACES if not FACES[f].get("keys")]
FACE_BASE = 0xF800
FACE_CODES = 32
STATIC_AT = 24
BIND_BASE = 0xF000
_FACES_CACHE = {}


def faces_font(otf, letters=None):
    """(Triforce) the game's font (decrypted) with every controller face's icons added (LIVE_FACES), and ((Triforce VR) the hand
    controllers' (nx2/prompt_vr.py; letters: the game's font its T and G are cut from), once for each game font:
    (the font's bytes, {code: glyph name} of the codes added, {face: [its glyph per pad input]}, {face: {STATIC code: glyph}})"""
    key = hash(otf)
    if key in _FACES_CACHE:
        return _FACES_CACHE[key]
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    game = TTFont(io.BytesIO(otf))
    gset, cmap = game.getGlyphSet(), dict(game.getBestCmap())
    top = game["CFF "].cff.topDictIndex[0]
    chars = top.CharStrings
    order = list(game.getGlyphOrder())
    hmtx = game["hmtx"]

    def bounds(glyphset, name):
        p = BoundsPen(glyphset)
        glyphset[name].draw(p)
        return p.bounds

    def add(name, charstring, width):
        chars.charStringsIndex.append(charstring)
        chars.charStrings[name] = len(chars.charStringsIndex) - 1
        top.charset.append(name)
        order.append(name)
        hmtx.metrics[name] = (width, 0)
        return name

    def copy(name, target):
        src = chars[target]
        src.decompile()
        return add(name, src, hmtx[target][0])

    assert BIND_BASE + len(LIVE_FACES) * len(SWITCH) * len(PADS) <= PAD_BASE
    assert FACE_BASE + FACE_CODES * len(LIVE_FACES) <= 0x10000 and len(PADS) <= STATIC_AT and STATIC_AT + len(STATIC) <= FACE_CODES
    placed, pads, statics = {}, {}, {}
    for n, face in enumerate(LIVE_FACES):
        base = FACE_BASE + FACE_CODES * n
        if face == "switch":   # (the game's own icons, a glyph of their own each as the other faces' are)
            pads[face] = [copy(f"pad_{face}_{p}", cmap[SWITCH_ICON[p]]) for p in PADS]
            statics[face] = {c: cmap[c] for c in STATIC if c in cmap}
        else:
            f = FACES[face]
            prefix, names = f["prefix"], f["icons"]
            kenney = TTFont(os.path.join(KENNEY, f["font"]))
            kset = kenney.getGlyphSet()

            def kname(s):
                return s[1:] if s.startswith("/") else prefix + s

            def draw(target, kn):
                """the Kenney glyph scaled into the box of the game's glyph `target` (as a square around its centre); a wide one
                (the Menu and View pills on the square Plus and Minus) as high as the box, up to WIDE times as wide, the glyph
                widened"""
                gb, kb = bounds(gset, target), bounds(kset, kn)
                side = max(gb[2] - gb[0], gb[3] - gb[1])
                s = min(side * WIDE / (kb[2] - kb[0]), side / (kb[3] - kb[1]))
                over = max(0, s * (kb[2] - kb[0]) - side)
                dx = (gb[0] + gb[2] + over) / 2 - s * (kb[0] + kb[2]) / 2
                dy = (gb[1] + gb[3]) / 2 - s * (kb[1] + kb[3]) / 2
                width = hmtx[target][0] + round(over)
                pen = T2CharStringPen(width, gset)
                kset[kn].draw(TransformPen(pen, (s, 0, 0, s, dx, dy)))
                cs = chars[target]
                return pen.getCharString(private=cs.private, globalSubrs=cs.globalSubrs), width

            pads[face] = []
            for p in PADS:
                kn = kname(names[p]) if p in names else None
                target = cmap[SWITCH_ICON[p]]
                # (no such button on this face, the PlayStation's PS button: the game's own icon)
                pads[face].append(add(f"pad_{face}_{p}", *draw(target, kn)) if kn in kset else
                                  copy(f"pad_{face}_{p}", target))
            statics[face] = {}
            for c, s in STATIC.items():
                kn = prefix + s
                if c in cmap:
                    statics[face][c] = add(f"static_{face}_{c:04x}", *draw(cmap[c], kn)) if kn in kset else cmap[c]
        for i in range(len(PADS)):
            placed[base + i] = pads[face][i]
        for k, c in enumerate(STATIC):
            if c in statics[face]:
                placed[base + STATIC_AT + k] = statics[face][c]
        for b in range(len(SWITCH)):
            for i in range(len(PADS)):
                placed[BIND_BASE + (n * len(SWITCH) + b) * len(PADS) + i] = pads[face][i]
    try:   # ((Triforce VR) the hand controllers' icons, for host/prompts.c while a VR session plays)
        import prompt_vr
        placed.update(prompt_vr.add_icons(gset, cmap, chars, hmtx, add, copy, letters))
    except ImportError:
        pass
    taken = sorted(c for c in placed if c in cmap)
    if taken:
        raise SystemExit("prompts: the game's font already has code points %s: no room for the faces' icons" %
                         ", ".join("U+%04X" % c for c in taken[:4]))
    game.setGlyphOrder(order)
    out = io.BytesIO()
    game.save(out)
    _FACES_CACHE[key] = got = (out.getvalue(), placed, pads, statics)
    return got


def face_font(otf, face, letters=None):
    """the game's font (decrypted) with every controller face's icons (faces_font) and this face's on the codes the game and the
    overlay read: a pad icon per input at PAD_BASE + its number, the Switch buttons' code points on the default controls' icons,
    the d-pad's (STATIC) on the face's. (the font, the glyph of each pad input's icon: write_hint's names)"""
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables.DefaultTable import DefaultTable

    plain, placed, pads, statics = faces_font(otf, letters)
    game = TTFont(io.BytesIO(plain))
    gid = {n: i for i, n in enumerate(game.getGlyphOrder())}
    mapping = {c: gid[n] for c, n in TTFont(io.BytesIO(otf)).getBestCmap().items() if c <= 0xFFFF}
    mapping.update({c: gid[n] for c, n in placed.items()})
    own = pads[face]
    for i in range(len(PADS)):
        mapping[PAD_BASE + i] = gid[own[i]]
    for c, p in zip(SWITCH, DEFAULT):
        mapping[c] = gid[own[PADS.index(p)]]
    for c, n in statics[face].items():
        mapping[c] = gid[n]
    t = DefaultTable("cmap")
    t.data = cmap4(mapping, set(SWITCH) | set(STATIC))   # (each a segment of its own: host/prompts.c points them anew)
    game["cmap"] = t
    out = io.BytesIO()
    game.save(out)
    return out.getvalue(), own


# ---- the textures with button icons (UI/Layout2Archive/Common.*.bntx: 878 textures, ASTC 4x4 and BC4, the Switch 2's block-linear
# layout). prompts/Common.bntx is the game's file, decompressed; prompts/<face>/textures.bin the blocks to write over it, for each
# Switch button and each pad input it can be bound to (host/prompts.c writes those of the controls in use):
#     "HPTX", u32 count, then count times: u8 Switch button (HOS_SW_*), u8 pad input (HOS_PAD_*), u16 0, u32 runs,
#     runs times: u32 offset in the file, u32 length, the bytes
# Each face's images are made first, as layers (face_layers), then encoded: --dump writes the layers as PNG, and a PNG of the same
# name in nx2/prompt_faces/<face>/ takes a layer's place (prompt_faces.override). A layer's name: the texture's, then for a Switch
# button's image on a pad input ".<pad input>" (the notes, the letters; the leader lines ".<Switch button>.<pad input>": only the
# line, drawn over the texture's lines that stay), ".png".
TEXTURES = "UI/Layout2Archive/Common.Product.100.Nin_Ounce_NVN2.bntx.zs"
SW = {n: i for i, n in enumerate(["a", "b", "x", "y", "ls", "rs", "l", "r", "zl", "zr", "plus", "minus", "left", "up", "right", "down"])}
# the ocarina's notes (white icons, dark letters) and the white letters on black (KeyTexFont, BC4)
NOTES = {"OcarinaButtonA_00": "a", "OcarinaButtonB_00": "b", "OcarinaButtonX_00": "x", "OcarinaButtonY_00": "y",
         "OcarinaButtonL_00": "l", "OcarinaButtonR_00": "r"}
LETTERS = {"KeyTexFontA_00": "a", "KeyTexFontB_00": "b", "KeyTexFontX_00": "x", "KeyTexFontY_00": "y"}
# the Pro Controller in the pause menu's controls page (System): the picture, the page's copy of it (tinted: PICTURE_TINT) and its
# shadow (PICTURE_SHADOW); a face's own picture (nx2/prompt_faces.py) takes their place, else the face buttons' discs (centre,
# radius in pixels) by the pad input there get the face's labels (a picture of the controller: its own labels, whatever the controls)
PICTURES = ("Controller_Pro", "Controller_Pro1")
PICTURE_TINT, PICTURE_SHADOW = "Controller_Pro1", "ControllerSh_Pro1"
PICTURE_BUTTONS = {"east": (869, 227, 31), "south": (800, 286, 31), "north": (800, 168, 31), "west": (732, 227, 31)}
# the page's leader lines (BC4, white on black, drawn over the picture: GUIDE_SCALE and GUIDE_AT take its pixels to theirs), from
# the labels' bars (BARS: the left ones' right edge, the right ones' left edge, kept from the game's) to the picture's parts
# (nx2/prompt_faces.py): each line's texture, bar (0 left, 1 right), row (its top; 6 pixels thick) and end: a Switch button (the
# part of the pad input bound to it: one line per pad input, chosen by the controls; a face button or the d-pad: a frame round the
# group, as the game's round its face buttons, the label's icon telling which) or a pad input (fixed: the sticks).
# (Triforce) The page has three more of them, drawn with the two first: _02 ZR's line, _03 the D-pad's frame round the Pro's d-pad
# and _04 L's and R's lines. Left the game's, on a face's picture they pointed at the Pro's places: on the PlayStation pads, whose
# left stick is where the Pro's d-pad is, the D-pad's frame went round the left stick (the ticket "Put d-pad arrows in the right
# place"). Now made for each face as the others are; the D-pad's label follows Switch Up's pad input
GUIDES = ("ControllerGuide_Pro_00", "ControllerGuide_Pro_01", "ControllerGuide_Pro_02", "ControllerGuide_Pro_03",
          "ControllerGuide_Pro_04")
GUIDE_SCALE, GUIDE_AT, BARS = 1.1136, (131.3, 462.6), (147, 1407)
GUIDE_LINES = [(0, 0, 333, "zl"), (1, 0, 561, "minus"), (0, 0, 667, "lstick"), (0, 1, 558, "plus"), (0, 1, 713, "a"),
               (0, 1, 1225, "rstick"), (2, 1, 333, "zr"), (3, 0, 1015, "up"), (4, 0, 447, "l"), (4, 1, 446, "r")]


def bntx_textures(b):
    """{name: (BRTI offset, format, width, height, GOBs per block, data offset)} of a Switch 2 BNTX (platform "Ounc")"""
    count, = struct.unpack_from("<I", b, 0x24)
    info, = struct.unpack_from("<Q", b, 0x28)
    out = {}
    for i in range(count):
        p, = struct.unpack_from("<Q", b, info + 8 * i)
        no, = struct.unpack_from("<Q", b, p + 0x60)
        nl, = struct.unpack_from("<H", b, no)
        fmt, = struct.unpack_from("<I", b, p + 0x1C)
        w, h = struct.unpack_from("<II", b, p + 0x24)
        bh, = struct.unpack_from("<I", b, p + 0x34)
        mips, = struct.unpack_from("<Q", b, p + 0x70)
        data, = struct.unpack_from("<Q", b, mips)
        out[b[no + 2:no + 2 + nl].decode()] = (p, fmt, w, h, 1 << bh, data)
    return out


def gob_offset(x, y, gobs, pitch):
    """a byte's place in a block-linear texture (x in bytes, y in rows of blocks): the Switch 2's GOB, the Tegra X1's with
    offset bits 5 and 6 swapped (gpu/render/rx_nvn.cpp bl_offset)"""
    a = (y // (8 * gobs)) * 512 * gobs * pitch + (x // 64) * 512 * gobs + (y % (8 * gobs) // 8) * 512
    return a + (((x & 63) >> 5) << 8 | ((y & 7) >> 2) << 7 | ((x & 31) >> 4) << 6 | ((y >> 1) & 1) << 5 | (y & 1) << 4 | (x & 15))


def decode(b, t):
    """a texture as a PIL image (RGBA, or L for BC4)"""
    import texture2ddecoder
    from PIL import Image
    _, fmt, w, h, gobs, data = t
    bpe = 16 if fmt >> 8 == 0x2D else 8
    bw, bh = (w + 3) // 4, (h + 3) // 4
    pitch = (bw * bpe + 63) // 64
    lin = b"".join(b[data + o:data + o + bpe] for o in (gob_offset(x * bpe, y, gobs, pitch) for y in range(bh) for x in range(bw)))
    if bpe == 16:
        return Image.frombytes("RGBA", (bw * 4, bh * 4), texture2ddecoder.decode_astc(lin, bw * 4, bh * 4, 4, 4), "raw",
                               "BGRA").crop((0, 0, w, h))
    return Image.frombytes("L", (bw * 4, bh * 4), lin, "bcn", 4).crop((0, 0, w, h))


def encode_bc4(im):
    """BC4 by each block's darkest and lightest, the 6 levels between"""
    import numpy as np
    v = np.asarray(im, dtype=np.int32)
    v = v.reshape(im.height // 4, 4, im.width // 4, 4).transpose(0, 2, 1, 3).reshape(-1, 16)
    hi, lo = v.max(1), v.min(1)
    span = np.maximum(hi - lo, 1)[:, None]
    t = np.where((hi > lo)[:, None], np.rint((v - lo[:, None]) * 7 / span), 7).astype(np.uint64)
    code = np.where(t == 7, 0, np.where(t == 0, 1, 8 - t)).astype(np.uint64)   # (0 the lightest, 1 the darkest, 2..7 between)
    idx = (code << (np.arange(16, dtype=np.uint64) * 3)).sum(1, dtype=np.uint64)
    out = np.zeros((len(v), 8), np.uint8)
    out[:, 0], out[:, 1] = hi, lo
    out[:, 2:] = idx.astype("<u8").view(np.uint8).reshape(-1, 8)[:, :6]
    return out.tobytes()


def encode_astc(im, srgb):
    import astc_encoder as A
    ctx = A.ASTCContext(A.ASTCConfig(A.ASTCProfile.LDR_SRGB if srgb else A.ASTCProfile.LDR, 4, 4, 1, A.ASTCQualityPreset.THOROUGH))
    return ctx.compress(A.ASTCImage(A.ASTCType.U8, im.width, im.height, 1, im.tobytes()), A.ASTCSwizzle.from_str("RGBA"))


def runs(t, im, box=None, mask=None):
    """the file's bytes for the blocks of im (the whole texture's size) inside box (pixels; all of it by default), or those with
    any of mask (L, im's size) in them, as (offset, bytes) runs"""
    from PIL import Image
    _, fmt, w, h, gobs, data = t
    bpe = 16 if fmt >> 8 == 0x2D else 8
    bw, bh = (w + 3) // 4, (h + 3) // 4
    x0, y0, x1, y1 = box or (mask and mask.getbbox()) or (0, 0, w, h)
    bx0, by0, bx1, by1 = max(0, x0 // 4), max(0, y0 // 4), min(bw, (x1 + 3) // 4), min(bh, (y1 + 3) // 4)
    part = Image.new(im.mode, (bw * 4, bh * 4))   # (only the box's blocks are encoded)
    part.paste(im, (0, 0))
    part = part.crop((bx0 * 4, by0 * 4, bx1 * 4, by1 * 4))
    blocks = encode_astc(part.convert("RGBA"), (fmt & 0xFF) == 6) if bpe == 16 else encode_bc4(part.convert("L"))
    pw = bx1 - bx0
    pitch = (bw * bpe + 63) // 64
    if mask:   # (the blocks with any of the mask)
        import numpy as np
        m = np.zeros((bh * 4, bw * 4), bool)
        m[:h, :w] = np.asarray(mask) > 0
        cover = m.reshape(bh, 4, bw, 4).any((1, 3))
    pieces = sorted((data + gob_offset(x * bpe, y, gobs, pitch),
                     blocks[((y - by0) * pw + x - bx0) * bpe:((y - by0) * pw + x - bx0 + 1) * bpe])
                    for y in range(by0, by1) for x in range(bx0, bx1) if not mask or cover[y, x])
    out = []
    for off, piece in pieces:   # (blocks next to each other in the file: one run)
        if out and out[-1][0] + len(out[-1][1]) == off:
            out[-1][1] += piece
        else:
            out.append([off, bytearray(piece)])
    return out


class Icons:
    """a face's icon for each pad input, drawn from a font (the game's own for the Switch face, else Kenney's)"""

    def __init__(self, face, otf):
        from fontTools.ttLib import TTFont
        if face == "switch":
            self.path, self.code = io.BytesIO(otf), {p: SWITCH_ICON[p] for p in PADS}
        else:
            f = FACES[face]
            prefix, names = f["prefix"], f["icons"]
            self.path = os.path.join(KENNEY, f["font"])
            rev = {n: c for c, n in TTFont(self.path).getBestCmap().items()}
            self.code = {}
            for p in PADS:
                n = names.get(p)
                n = n and (n[1:] if n.startswith("/") else prefix + n)
                if n in rev:
                    self.code[p] = rev[n]

    def masks(self, pad, size):
        """(the icon, its silhouette with the holes filled, the holes) as L masks of size x size, the icon centred in it"""
        from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
        if isinstance(self.path, io.BytesIO):
            self.path.seek(0)
        f = ImageFont.truetype(self.path, size * 4)
        g = Image.new("L", (size * 8, size * 8), 0)
        ImageDraw.Draw(g).text((size * 2, size * 2), chr(self.code[pad]), font=f, fill=255)
        g = g.crop(g.getbbox())
        s = size / max(g.size)
        g = g.resize((max(1, round(g.width * s)), max(1, round(g.height * s))), Image.LANCZOS)
        icon = Image.new("L", (size, size), 0)
        icon.paste(g, ((size - g.width) // 2, (size - g.height) // 2))
        outside = Image.new("L", (size + 4, size + 4), 255)   # (a margin: every side's outside joins the corner's)
        outside.paste(ImageChops.invert(icon.point(lambda v: 255 if v > 127 else 0)), (2, 2))
        ImageDraw.floodfill(outside, (0, 0), 128)   # (what the corner reaches: the outside)
        shape = outside.crop((2, 2, size + 2, size + 2)).point(lambda v: 0 if v == 128 else 255)
        inner = shape.filter(ImageFilter.MinFilter(5))   # (the soft rim of the icon is not a hole)
        holes = ImageChops.multiply(inner, ImageChops.invert(icon))
        return icon, shape, holes


class Layer:
    """an image of a texture's: written whole, or its box (pixels) of it, or (over: a layer's name) drawn over that layer where
    it has any of itself; for a Switch button (0xff: always) on a pad input"""

    def __init__(self, name, texture, sw, pad, im, box=None, over=None):
        self.name, self.texture, self.sw, self.pad, self.im, self.box, self.over = name, texture, sw, pad, im, box, over


def face_layers(b, tex, face, otf):
    """this face's images, as layers (in textures.bin's order), each a hand-made one if nx2/prompt_faces/<face>/ has it"""
    from PIL import Image, ImageDraw
    import prompt_draw
    keys = bool(FACES.get(face, {}).get("keys"))   # ((Triforce) the keyboard and mouse: an icon per key code, no controller)
    if keys:
        import prompt_keys
    icons = prompt_keys.Icons() if keys else Icons(face, otf)
    # (what a Switch button can be on: its name in icons, its number in textures.bin, its name in a layer's)
    inputs = [(vk, vk, "key%d" % vk) for vk in sorted(icons.code)] if keys else [(p, i, p) for i, p in enumerate(PADS)]
    layers = []
    made = {}   # ((Triforce) an input's image is the same on every texture of one size: made once, and encoded once)

    def keep(sw, pad):   # (the Switch face's default controls: the game's own textures)
        return pad in icons.code and not (face == "switch" and DEFAULT[SW[sw]] == pad)

    def note(pad, w, h):
        if ("note", pad, w, h) not in made:
            icon, shape, holes = icons.masks(pad, int(min(w, h) * 0.9))
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            o = ((w - icon.width) // 2, (h - icon.height) // 2)
            im.paste(Image.new("RGBA", icon.size, (255, 255, 255, 255)), o, shape)
            im.paste(Image.new("RGBA", icon.size, (0, 0, 0, 255)), o, holes)
            made["note", pad, w, h] = im
        return made["note", pad, w, h]

    def letter_of(pad, w, h):
        if ("letter", pad, w, h) not in made:
            icon, shape, holes = icons.masks(pad, int(min(w, h) * 0.9))
            # (an icon with no letter in it: its shape; a mouse's: the mouse, not what its outline leaves)
            letter = holes if holes.getbbox() and pad not in getattr(icons, "plain", ()) else icon
            im = Image.new("L", (w, h), 0)
            im.paste(letter, ((w - letter.width) // 2, (h - letter.height) // 2))
            made["letter", pad, w, h] = im
        return made["letter", pad, w, h]

    for name, sw in NOTES.items():
        t = tex[name]
        for pad, at, label in inputs:
            if keep(sw, pad):
                layers.append(Layer(f"{name}.{label}.png", name, SW[sw], at, note(pad, t[2], t[3])))
    for name, sw in LETTERS.items():
        t = tex[name]
        for pad, at, label in inputs:
            if keep(sw, pad):
                layers.append(Layer(f"{name}.{label}.png", name, SW[sw], at, letter_of(pad, t[2], t[3])))
    own = None
    if face != "switch" and not keys:   # ((Triforce) the keyboard has no picture: the page keeps the game's controller)
        hand = override(face, PICTURES[0] + ".png")
        own = Image.open(hand).convert("RGBA") if hand else prompt_draw.picture(
            face, decode(b, tex[PICTURES[0]]).convert("RGBA"), Icons("switch", otf))
    if own:
        layers += picture_layers(b, tex, own)
    for name in PICTURES if face != "switch" and not own and not keys else ():
        t = tex[name]
        im = decode(b, t)
        px = im.load()
        for pad, (cx, cy, r) in PICTURE_BUTTONS.items():
            fill, ink = px[cx + r - 6, cy], (205, 205, 205, 255)
            ImageDraw.Draw(im).ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
            size = int(2 * r * 0.92)
            icon, shape, holes = icons.masks(pad, size)
            disc = sum(i * n for i, n in enumerate(shape.histogram())) / 255 / size / size > 0.7   # (a disc with a letter in it: the letter)
            mark = holes if disc else icons.masks(pad, int(size * 0.7))[0]
            im.paste(Image.new("RGBA", mark.size, ink), (cx - mark.width // 2, cy - mark.height // 2), mark)
        xs, ys = [c[0] for c in PICTURE_BUTTONS.values()], [c[1] for c in PICTURE_BUTTONS.values()]
        r = max(c[2] for c in PICTURE_BUTTONS.values())
        layers.append(Layer(name + ".png", name, 0xFF, 0, im, (min(xs) - r, min(ys) - r, max(xs) + r + 1, max(ys) + r + 1)))
    layers += guide_layers_of(b, tex, face)
    for layer in layers:
        hand = override(face, layer.name)
        if hand:
            im = Image.open(hand).convert(layer.im.mode)
            if im.size != layer.im.size:
                raise SystemExit(f"prompts: {hand} is {im.size[0]}x{im.size[1]}, the texture {layer.im.size[0]}x{layer.im.size[1]}")
            layer.im = im
    return layers


def face_textures(b, tex, layers):
    """textures.bin's entries for these layers: [(Switch button, pad input, runs)], Switch button 0xff for those always written"""
    from PIL import ImageChops
    entries, made, encoded = [], {}, {}
    for layer in layers:
        t, im = tex[layer.texture], layer.im
        made[layer.name] = im
        if layer.over:
            entries.append((layer.sw, layer.pad, runs(t, ImageChops.lighter(made[layer.over], im), mask=im)))
        elif layer.box:
            x0, y0, x1, y1 = layer.box
            if im.getbbox():   # (a hand-made image may reach further)
                bx0, by0, bx1, by1 = im.getbbox()
                x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
            entries.append((layer.sw, layer.pad, runs(t, im, (x0, y0, x1, y1))))
        else:
            # ((Triforce) the same image on another texture of that size and format, a note or a letter on another Switch
            # button: the same blocks, at that texture's place. The notes were encoded six times over, the letters four)
            same = (id(im), t[1], t[2], t[3], t[4])
            if same not in encoded:
                encoded[same] = (t[5], runs(t, im))
            data, rs = encoded[same]
            entries.append((layer.sw, layer.pad, [[off - data + t[5], piece] for off, piece in rs]))
    return entries


# the groups a line frames, ending on the frame, when its pad input is one of them; the face buttons' labels (Switch A's line, under
# one bar with B, X and Y's) always frame one: the d-pad when A is on it, else the face buttons
GUIDE_GROUPS = (("north", "west", "east", "south"), ("up", "left", "right", "down"))
GUIDE_FACE = "a"
# the lines' router: a grid of GUIDE_GRID pixels; a bend costs GUIDE_BEND pixels of length, crossing a line that stays GUIDE_CROSS,
# coming to a part other than from above GUIDE_SIDE; a line keeps GUIDE_CLEAR pixels off the other parts (the sticks GUIDE_CLEAR / 2)
GUIDE_GRID, GUIDE_BEND, GUIDE_CROSS, GUIDE_SIDE, GUIDE_CLEAR = 8, 64, 40, 48, 16


def guide_at(part):
    """a part (picture pixels: x, y, r) in the lines' pixels"""
    return part[0] * GUIDE_SCALE + GUIDE_AT[0], part[1] * GUIDE_SCALE + GUIDE_AT[1], part[2] * GUIDE_SCALE


def guide_frame_at(where, group):
    """a group's frame: its centre and its corners' distance from it (the lines' pixels)"""
    pts = [guide_at(where[p]) for p in group]
    cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
    return cx, cy, max(max(abs(x - cx), abs(y - cy)) + r for x, y, r in pts) + 8   # (from the centre to a corner, as the game's)


# (Triforce, 11-22, the performance audit's IO-42, after Source A's) The lines that stay, widened (a 9 by 9 maximum, what a
# route pays to cross), kept for the last image asked: every route of one line is given the same image (guide_layers: the
# frames and each pad input's line), and each widened it again, 37 times for one face where 5 images differ. One entry,
# by the image's id, holding the image itself: the entry is used only when it is that very object, so an id given again
# to another image misses, and no step here changes an image in place. HOOKSHOT_PROMPTS_WIDEN_EACH=1 (read once):
# widened at every route, as before.
_WIDENED = {}
WIDEN_EACH = os.environ.get("HOOKSHOT_PROMPTS_WIDEN_EACH", "0") not in ("", "0")


def guide_widened(stays):
    """the lines that stay (L) with every lit pixel grown to 9 by 9, as an array: _WIDENED above"""
    import numpy as np
    from PIL import ImageFilter
    held = None if WIDEN_EACH else _WIDENED.get(id(stays))
    if held is not None and held[0] is stays:
        return held[1]
    st = np.asarray(stays.filter(ImageFilter.MaxFilter(9)))
    _WIDENED.clear()
    if not WIDEN_EACH:
        _WIDENED[id(stays)] = (stays, st)
    return st


def guide_route(size, bar, row, where, pad, stays, frame=None):
    """the way (points, the lines' pixels) of a line from a bar's row to the pad input's part, round the picture's other parts and
    with the fewest bends, crossing the lines that stay (L) as little as it can: it comes to a stick's centre, to a part's edge
    (from above best), or to a frame's corner (frame: centre, corners' distance)"""
    import heapq
    import math
    import numpy as np
    g = GUIDE_GRID
    x0, y0 = BARS[0] if bar == 0 else BARS[1], row + 3
    ilo, ihi = (0, (BARS[1] - x0) // g) if bar == 0 else (-((x0 - BARS[0]) // g), 0)
    jlo, jhi = -((y0 - 250) // g), (min(size[1] - 20, 1420) - y0) // g
    xs, ys = x0 + g * np.arange(ilo, ihi + 1), y0 + g * np.arange(jlo, jhi + 1)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    blocked = np.zeros(X.shape, bool)
    own = set(next((grp for grp in GUIDE_GROUPS if pad in grp), ())) if frame else {pad}
    for p, part in where.items():
        if len(part) == 4:   # (a box to keep off)
            (bx0, by0, _), (bx1, by1, _) = guide_at(part[:2] + (0,)), guide_at(part[2:] + (0,))
            m = GUIDE_CLEAR / 2
            blocked |= (X > bx0 - m) & (X < bx1 + m) & (Y > by0 - m) & (Y < by1 + m)
            continue
        x, y, r = guide_at(part)
        if p in own:
            continue
        clear = GUIDE_CLEAR / 2 if p in ("lstick", "rstick") else GUIDE_CLEAR
        blocked |= (X - x) ** 2 + (Y - y) ** 2 < (r + clear) ** 2
    for grp in GUIDE_GROUPS:   # (a group: inside its frame, which another line may draw, its own inside it)
        if all(p in where for p in grp):
            cx, cy, e = guide_frame_at(where, grp)
            if frame and pad in grp:
                blocked |= (X - cx) ** 2 + (Y - cy) ** 2 < (e - 8) ** 2
            else:   # (the frame: a square on its corner, its sides 1.15 corners' distance off in x + y)
                blocked |= np.abs(X - cx) + np.abs(Y - cy) < 1.15 * e + GUIDE_CLEAR
    blocked |= ((np.abs(X - BARS[0]) < 14) | (np.abs(X - BARS[1]) < 14)) & (Y != y0)   # (off the bars but on its own row)
    st = guide_widened(stays)   # ((Triforce, 11-22, IO-42) once per image, not once per route)
    pen = np.where(st[np.clip(Y, 0, size[1] - 1), np.clip(X, 0, size[0] - 1)] > 0, GUIDE_CROSS, 0)
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    goals = {}   # ((i, j, dir): (the end, extra cost)): the cell two before the end, coming the way it ends

    def goal(ex, ey, d, extra):
        i, j = round((ex - x0) / g) - 2 * dirs[d][0], round((ey - y0) / g) - 2 * dirs[d][1]
        cells = [(i + k * dirs[d][0], j + k * dirs[d][1]) for k in range(3)]
        if all(ilo <= ci <= ihi and jlo <= cj <= jhi and not blocked[ci - ilo, cj - jlo] for ci, cj in cells[:2]):
            goals[(i, j, d)] = ((ex, ey), extra)

    x, y, r = guide_at(where[pad])
    if frame:   # (a corner, or beside it on the grid's nearest line, along the frame's side)
        cx, cy, e = frame
        for k in (0, 1):
            sy, sx = y0 + g * (math.floor((cy - y0) / g) + k) - cy, x0 + g * (math.floor((cx - x0) / g) + k) - cx
            for (ex, ey), d, extra in (((cx + e - abs(sy), cy + sy), 1, 0), ((cx + sx, cy - e + abs(sx)), 2, GUIDE_SIDE),
                                       ((cx - e + abs(sy), cy + sy), 0, GUIDE_SIDE),
                                       ((cx + sx, cy + e - abs(sx)), 3, GUIDE_SIDE)):
                goal(ex, ey, d, extra)
    elif pad in ("lstick", "rstick"):
        for d in range(4):
            goal(x, y, d, 0)
    else:   # (on its edge, as the game's own lines end: 2 pixels into it)
        e = max(r - 2, 0)
        for (ex, ey), d, extra in (((x, y - e), 2, 0), ((x, y + e), 3, GUIDE_SIDE), ((x - e, y), 0, GUIDE_SIDE),
                                   ((x + e, y), 1, GUIDE_SIDE)):
            if r or d >= 2:
                goal(ex, ey, d, extra)
    start = (0, 0, 0 if bar == 0 else 1)
    best, came, heap = {start: 0}, {}, [(0, start)]
    while heap:
        c, (i, j, d) = heapq.heappop(heap)
        if c > best.get((i, j, d), 1e18):
            continue
        if (i, j, d) in goals:
            (ex, ey), _ = goals[(i, j, d)]
            way, k = [], (i, j, d)
            while k:
                way.append(k)
                k = came.get(k)
            way.reverse()
            pts = [(x0 + g * way[0][0], y0 + g * way[0][1])]
            for p0, p1 in zip(way, way[1:]):
                if p0[2] != p1[2]:
                    pts.append((x0 + g * p0[0], y0 + g * p0[1]))
            pts.append((ex, ey) if len(pts) > 1 or abs(ey - y0) > g else (ex, y0))   # (one leg: on its row)
            if len(pts) > 2:   # (the last leg's corner moved onto the end's line: its leg before only longer or shorter)
                cx_, cy_ = pts[-2]
                pts[-2] = (cx_, ey) if dirs[d][0] else (ex, cy_)
            return _square(pts)
        for nd in range(4):
            if nd == d ^ 1 or (nd != d and j == 0 and abs(i) < 5):   # (no turning back; the label's stub first)
                continue
            ni, nj = i + dirs[nd][0], j + dirs[nd][1]
            if not (ilo <= ni <= ihi and jlo <= nj <= jhi) or blocked[ni - ilo, nj - jlo]:
                continue
            nc = c + g + pen[ni - ilo, nj - jlo] + (GUIDE_BEND if nd != d else 0) + goals.get((ni, nj, nd), (0, 0))[1]
            if nc < best.get((ni, nj, nd), 1e18):
                best[(ni, nj, nd)], came[(ni, nj, nd)] = nc, (i, j, d)
                heapq.heappush(heap, (nc, (ni, nj, nd)))
    return None


def _square(pts):
    """a way's points with every leg level or upright (each point shares x or y with the one before)"""
    out = [pts[0]]
    for x, y in pts[1:]:
        px, py = out[-1]
        if (x, y) == (px, py):
            continue
        if x != px and y != py:
            out.append((px, y) if len(out) > 1 and out[-2][0] == px else (x, py))
        out.append((x, y))
    return out


def guide_draw(size, way, dot):
    """a line along its way (6 pixels thick, square corners), ending on a dot"""
    from PIL import Image, ImageDraw
    im = Image.new("L", size, 0)
    d = ImageDraw.Draw(im)
    for (x0, y0), (x1, y1) in zip(way, way[1:]):
        x0, x1, y0, y1 = round(min(x0, x1)), round(max(x0, x1)), round(min(y0, y1)), round(max(y0, y1))
        d.rectangle((x0 - 3, y0 - 3, x1 + 2, y1 + 2), fill=255)
    if dot:
        d.regular_polygon((round(way[-1][0]), round(way[-1][1]), 11), 5, rotation=18, fill=255)
    return im


def guide_line(size, bar, row, where, pad, stays):
    """a leader line (L, size) from a bar's row to the pad input's part (where: the picture's parts), ending on a dot"""
    way = guide_route(size, bar, row, where, pad, stays)
    if not way:   # (no way round: straight along the row, then up or down to the part's edge, as guide_route ends)
        x, y, r = guide_at(where[pad])
        e = 0 if pad in ("lstick", "rstick") else max(r - 2, 0)
        y += -e if row < y else e
        way = [(BARS[0] if bar == 0 else BARS[1], row + 3), (x, row + 3), (x, y)]
    return guide_draw(size, way, True)


def guide_frame(size, bar, row, where, group, stays):
    """a group's frame (L, size; a square on its corner, rounded, round its parts) and its line from a bar's row"""
    import math
    from PIL import Image, ImageChops, ImageDraw
    cx, cy, e = guide_frame_at(where, group)
    ss, round_ = 4, 0.36 * e
    a = (e + (math.sqrt(2) - 1) * round_) / math.sqrt(2)
    n = int(2 * a * ss) + 8
    sq = Image.new("L", (n, n), 0)
    ImageDraw.Draw(sq).rounded_rectangle((4, 4, n - 4, n - 4), radius=round_ * ss, outline=255, width=6 * ss)
    sq = sq.rotate(45, Image.BICUBIC, expand=True)
    sq = sq.resize((sq.width // ss, sq.height // ss), Image.LANCZOS)
    im = Image.new("L", size, 0)
    im.paste(sq, (round(cx - sq.width / 2), round(cy - sq.height / 2)))
    way = guide_route(size, bar, row, where, group[0], stays, (cx, cy, e - 3)) or \
        [(BARS[0] if bar == 0 else BARS[1], row + 3), (cx + e - 3 if bar else cx - e + 3, row + 3)]
    return ImageChops.lighter(im, guide_draw(size, way, False))


def game_line(im, bar, row):
    """where the game's line from bar (0 left, 1 right) at row is drawn in im (L, a guide texture): the shape it makes between
    the bars, as it is (the router's route to the same part runs elsewhere: taking that out left pieces of the game's line), a
    little wider for its soft edge. The whole shape the line's pixels touch: a game line touching another between the bars
    would be taken with it (the game's do not touch). None found near the label: an empty mask, said on stderr"""
    from PIL import Image, ImageDraw, ImageFilter
    x0, x1 = BARS[0] + 3, BARS[1] - 3   # (off the bars: they join the lines of one side)
    lit = im.point(lambda v: 255 if v > 24 else 0)
    inner = Image.new("L", im.size, 0)
    inner.paste(lit.crop((x0, 0, x1, im.height)), (x0, 0))
    x = x0 + 2 if bar == 0 else x1 - 3
    y = min((y for y in range(row - 12, row + 13) if 0 <= y < im.height and inner.getpixel((x, y))), key=lambda y: abs(y - row),
            default=None)
    out = Image.new("L", im.size, 0)
    if y is None:
        print(f"prompts: no game line from bar {bar} at row {row}: nothing taken out there", file=sys.stderr)
        return out
    ImageDraw.floodfill(inner, (x, y), 128)
    out.paste(inner.point(lambda v: 255 if v == 128 else 0).filter(ImageFilter.MaxFilter(7)).crop((BARS[0] + 1, 0, BARS[1], im.height)),
              (BARS[0] + 1, 0))
    return out


def guide_layers(game, face):
    """the page's leader lines for this face's picture, from the game's (L images, GUIDES): each texture's lines that stay (the
    Switch face: the game's), and {texture: [(Switch button, {pad input: its line})]}"""
    from PIL import Image, ImageChops
    where, size = parts(face), game[0].size
    keep = []   # (the game's bars, or on the Switch face all the game's but the lines that move)
    for im in game:
        k = Image.new("L", size, 0)
        if face == "switch":
            k.paste(im)
        else:
            k.paste(im.crop((0, 0, BARS[0], size[1])), (0, 0))
            k.paste(im.crop((BARS[1], 0, size[0], size[1])), (BARS[1], 0))
        keep.append(k)
    for tx, bar, row, end in GUIDE_LINES:   # (the lines that stay first: those that move keep off them)
        if end not in SW and face != "switch":
            keep[tx] = ImageChops.lighter(keep[tx], guide_line(size, bar, row, where, end, keep[tx]))
    moving = {}
    for tx, bar, row, end in GUIDE_LINES:
        if end not in SW:
            continue
        stays, frames = keep[tx], {}
        for group in GUIDE_GROUPS:
            if all(p in where for p in group):
                im = guide_frame(size, bar, row, where, group, stays)
                frames.update((p, im) for p in group)
        lines = {pad: frames.get(pad) or (frames["south"] if end == GUIDE_FACE and "south" in frames else
                                          guide_line(size, bar, row, where, pad, stays)) for pad in PADS if pad in where}
        if face == "switch":   # (the game's own line where the pad input's is hookshot's default's: taken out of what stays)
            own = lines[DEFAULT[SW[end]]]
            around = game_line(game[tx], bar, row)
            game_own = ImageChops.multiply(game[tx], around)
            for pad, im in lines.items():
                if im is own:
                    lines[pad] = game_own
            keep[tx] = ImageChops.subtract(keep[tx], around)
        moving.setdefault(tx, []).append((end, lines))
    return keep, moving


def guide_layers_of(b, tex, face):
    """the layers of the page's leader lines: each texture's lines that stay (0xff), then each Switch button's line for each pad
    input, drawn over them (host/prompts.c writes the entries in order)"""
    from PIL import Image, ImageChops
    if not parts(face):
        return []
    game = [decode(b, tex[n]) for n in GUIDES]
    keep, moving = guide_layers(game, face)
    layers = []
    for tx, name in enumerate(GUIDES):
        box = Image.new("L", game[tx].size, 0)   # (every place a line is or may be)
        for im in [game[tx], keep[tx]] + [im for _, lines in moving.get(tx, []) for im in lines.values()]:
            box = ImageChops.lighter(box, im)
        layers.append(Layer(name + ".png", name, 0xFF, 0, keep[tx], box.getbbox()))
        for end, lines in moving.get(tx, []):
            for pad, im in lines.items():
                layers.append(Layer(f"{name}.{end}.{pad}.png", name, SW[end], PADS.index(pad), im, over=name + ".png"))
    return layers


def picture_layers(b, tex, im):
    """the layers putting a face's controller picture (1160x680 RGBA, drawn in grey like Controller_Pro) in place of the Pro
    Controller: the picture, the page's tinted copy (each grey the colour the game's own pair gives it) and the shadow (the
    outline's left part squeezed into ControllerSh_Pro1 and blurred, fitted on the game's). ((Triforce) 11-24) The game's tint
    is no straight line of the grey: its black outlines turn a brown lighter than the #333333 body, which turns almost black,
    so a line fitted through the pair crushed a hand-drawn picture's outlines, lit its body and dimmed its buttons"""
    import numpy as np
    from PIL import Image, ImageFilter
    plain, tinted = (np.asarray(decode(b, tex[n]).convert("RGBA")).astype(float) for n in (PICTURES[0], PICTURE_TINT))
    solid = (plain[..., 3] > 250) & (tinted[..., 3] > 250)
    grey, colour = np.rint(plain[solid][:, :3].mean(1)).astype(int), tinted[solid][:, :3]
    levels, counts = np.unique(grey, return_counts=True)
    levels = levels[counts >= 20]   # (the greys the game drew enough of: not a few blended edge pixels)
    if not len(levels):
        raise SystemExit(f"prompts: no grey of the game's {PICTURES[0]} has its colour in {PICTURE_TINT}: not the pair known")
    table = np.array([np.median(colour[grey == v], 0) for v in levels])
    px = np.asarray(im).astype(float)
    level = px[..., :3].mean(2)
    tint = np.dstack([np.interp(level, levels, table[:, c]) for c in range(3)] + [px[..., 3]])
    sh = tex[PICTURE_SHADOW]
    shadow = im.getchannel("A").crop((40, 0, 480, 680)).resize((sh[2], sh[3])).filter(ImageFilter.GaussianBlur(24))
    shadow = shadow.point(lambda v: round(v * 0.7))
    return [Layer(PICTURES[0] + ".png", PICTURES[0], 0xFF, 0, im),
            Layer(PICTURE_TINT + ".png", PICTURE_TINT, 0xFF, 0, Image.fromarray(np.rint(tint).astype("uint8"))),
            Layer(PICTURE_SHADOW + ".png", PICTURE_SHADOW, 0xFF, 0, shadow)]


def write_textures(path, entries):
    with open(path, "wb") as f:
        f.write(b"HPTX" + struct.pack("<I", len(entries)))
        for sw, pad, rs in entries:
            f.write(struct.pack("<BBHI", sw, pad, 0, len(rs)))
            for off, data in rs:
                f.write(struct.pack("<II", off, len(data)) + bytes(data))


# ---- the Talk ring (DoCommand_00 in UI/Layout2Archive/Common.*.blarc, a BFFH layout, four copies): one group per Switch button
# an action can be on, N_A/B/X/Y_00, each its base, its big button and the three others' letters (KeyTexFont) at the Switch's
# places. prompts/Common.blarc is the game's file decompressed, prompts/ring.bin what to write over it to put each one where its
# pad input is (host/prompts.c picks the places by the controls): "HPRG", u32 count, then count times: u8 group (HOS_SW_A..Y),
# u8 the Switch button placed (the group's own: its big button and base), u8 place (RING_PLACES), u8 0, u32 runs, the runs
# (u32 offset, u32 length, the bytes)
LAYOUTS = "UI/Layout2Archive/Common.Product.100.Nin_Ounce_NVN2.blarc.zs"
RING_PLACES = {"east": (80.0, 0.0), "south": (0.0, -80.0), "north": (0.0, 80.0), "west": (-80.0, 0.0)}
# each group's panes (in the layout's order): its base, the others' letters, its big button (then its five children); the group
# whose big button is at each place gives the base's look (CrossBase_A or _B, mirrored or not) and the button's banner
RING_GROUPS = {"a": (5, {"b": 6, "x": 7, "y": 8}, 9), "b": (16, {"a": 17, "x": 18, "y": 19}, 20),
               "x": (27, {"a": 28, "b": 29, "y": 30}, 31), "y": (38, {"a": 39, "b": 40, "x": 41}, 42)}
RING_AT = {"east": "a", "south": "b", "north": "x", "west": "y"}


def layout_copies(blarc, name):
    """the (start, end) of each BFFH layout in the archive that is the layout `name`"""
    starts, at = [], 0
    while (at := blarc.find(b"BFFH", at)) >= 0:
        starts.append(at)
        at += 4
    return [(a, z) for a, z in zip(starts, starts[1:] + [len(blarc)]) if blarc.find(b"\0" + name.encode() + b"\0RootPane\0", a, z) > 0]


def ring_entries(blarc):
    """ring.bin's entries: [(group, Switch button placed, place, runs)], or None when the layout is not the one known"""
    def pane(k):   # (a pane's record: its transform (rotation, scale, translation) first, then parent, size, material)
        return 0x968 + k * 0x44 - 0x28

    copies = [a for a, _ in layout_copies(blarc, "DoCommand_00")]
    if not copies:
        return None
    lay = blarc[copies[0]:copies[0] + 0x2000]
    if any(struct.unpack_from("<2f", lay, pane(base) + 0x2c) != (320.0, 320.0) for base, _, _ in RING_GROUPS.values()):
        return None
    out = []
    for group, (base, small, btn) in RING_GROUPS.items():
        for place, xy in RING_PLACES.items():
            tb, _, tbtn = RING_GROUPS[RING_AT[place]]
            parts = [(pane(base) + 0x10, lay[pane(tb) + 0x10:pane(tb) + 0x18]),   # (the base's scale, its material)
                     (pane(base) + 0x3c, lay[pane(tb) + 0x3c:pane(tb) + 0x40]),
                     (pane(btn) + 0x1c, lay[pane(tbtn) + 0x1c:pane(tbtn) + 0x24])]   # (the button, its banner and text)
            parts += [(pane(btn + c), lay[pane(tbtn + c):pane(tbtn + c) + 0x24]) for c in range(1, 6)]
            out.append((SW[group], SW[group], list(RING_PLACES).index(place),
                        [[c + o, bytearray(v)] for c in copies for o, v in parts]))
            for other, k in small.items():
                out.append((SW[group], SW[other], list(RING_PLACES).index(place),
                            [[c + pane(k) + 0x1c, bytearray(struct.pack("<2f", *xy))] for c in copies]))
    return out


def write_ring(path, entries):
    with open(path, "wb") as f:
        f.write(b"HPRG" + struct.pack("<I", len(entries)))
        for group, placed, place, rs in entries:
            f.write(struct.pack("<BBBBI", group, placed, place, 0, len(rs)))
            for off, data in rs:
                f.write(struct.pack("<II", off, len(data)) + bytes(data))


# ---- the ocarina's hints ("Play a note" and the notes' icons: PaGuideKeyOcarinaInput_00 and _01, and PaGuideKeyCapture_00 while a
# song is taught to the scarecrow, in the same archive, four copies each): each icon a text pane of its own, drawn from its left,
# 90 apart, room for the game's icons. A wider one (the Xbox's LB and RB pills) runs into the next, so host/prompts.c moves each
# icon on by the extra width of the icons bound before it: the last one stays, the others and the text move left. prompts/<face>/hint.bin: "HPHN", u32 count of PADS, each pad input's icon's extra width (f32, layout units), u32
# panes, then each: u32 offset (its x in prompts/Common.blarc), u8 slot (0-4 the notes' icons in the hint's order, 5 the text),
# u8 0 x3, f32 its x
HINTS = ("PaGuideKeyOcarinaInput_00", "PaGuideKeyOcarinaInput_01", "PaGuideKeyCapture_00")
HINT_PANES = ["T_Icon_00", "T_Icon_01", "T_Icon_02", "T_Icon_03", "T_Icon_04", "T_Guide_00"]
HINT_FITS = 720   # (the widest advance the game's spacing holds: its own shoulder icons; font units)
HINT_SCALE = 0.1   # (layout units per font unit: the icons' panes draw the font at 100 per 1000 em)


def layout_panes(lay, *, unique=False):
    """a BFFH layout's panes: {name: its record's offset} (the record: rotation, scale at +0x10, translation at +0x1c, size at
    +0x2c); the header gives the offsets of the names' table (+0x118), the records' table (+0x120) and the count (+0x130)"""
    names, recs = struct.unpack_from("<QQ", lay, 0x118)
    n = struct.unpack_from("<I", lay, 0x130)[0]
    out = {}
    for k in range(n):
        name = struct.unpack_from("<Q", lay, names + 8 * k)[0]
        out[lay[name:lay.index(b"\0", name)].decode()] = struct.unpack_from("<Q", lay, recs + 8 * k)[0]
    return {} if unique and len(out) != n else out


def hint_panes(blarc):
    """the hint's panes in every copy: [(offset of an x, slot, x)], or None when the layouts are not the ones known. Each pane's
    x, and the keys of its x in the layout's animation (its "Type" sets the text's and the first two icons' x, the same in every
    state): a curve's values are an array (u64 offset of the floats, u32 count, u32 4, the floats) of (value, slope) pairs, taken
    when every value is a pane's x and every slope 0"""
    out = []
    for name in HINTS:
        for a, z in layout_copies(blarc, name):
            lay = blarc[a:z]
            panes = layout_panes(lay)
            if any(p not in panes for p in HINT_PANES):
                return None
            xs = {}
            for slot, p in enumerate(HINT_PANES):
                x = struct.unpack_from("<f", lay, panes[p] + 0x1c)[0]
                xs.setdefault(x, slot)
                out.append((a + panes[p] + 0x1c, slot, x))
            for o in range(0, len(lay) - 16, 8):
                at, n, size = struct.unpack_from("<QII", lay, o)
                if at != o + 16 or size != 4 or not 2 <= n <= 64 or n % 2 or o + 16 + 4 * n > len(lay):
                    continue
                v = struct.unpack_from(f"<{n}f", lay, at)
                if v[0] in xs and all(k == v[0] for k in v[::2]) and not any(v[1::2]):
                    out += [(a + at + 8 * k, xs[v[0]], v[0]) for k in range(n // 2)]
    return out or None


def write_hint(path, otf, panes, names=None):
    """(names: the glyph of each input's icon, in the inputs' order, None for a number that is no input: the pad inputs',
    or the keyboard face's 256 key codes')"""
    from fontTools.ttLib import TTFont
    hmtx = TTFont(io.BytesIO(otf))["hmtx"]
    names = names or [f"pad_{p}" for p in PADS]
    with open(path, "wb") as f:
        f.write(b"HPHN" + struct.pack("<I", len(names)))
        f.write(b"".join(struct.pack("<f", round(max(0, hmtx[n][0] - HINT_FITS) * HINT_SCALE) if n else 0.0) for n in names))
        f.write(struct.pack("<I", len(panes)) + b"".join(struct.pack("<IB3xf", at, slot, x) for at, slot, x in panes))


def dump(out, face, b, tex, layers):
    """the face's layers as PNG, and the game's textures they go into (once)"""
    os.makedirs(os.path.join(out, face), exist_ok=True)
    os.makedirs(os.path.join(out, "game"), exist_ok=True)
    for layer in layers:
        layer.im.save(os.path.join(out, face, layer.name))
        game = os.path.join(out, "game", layer.texture + ".png")
        if not os.path.exists(game):
            decode(b, tex[layer.texture]).save(game)


# ---- the edge-anchored HUD on a picture wider than 16:9 (in the same archive, four copies of each
# layout). With the Insert menu's Ultrawide HUD row on Screen edges host/prompts.c moves these panes out to the picture's
# sides (host/oot_wide_hud.h has the rule). They are moved in the layouts because a layout's projection cannot do it:
# - PlayerStatus_00 hangs the hearts, the magic bar and the D-pad's shortcuts on a pane at the 16:9 grid's top left corner and
#   the item slot on one at its top right: two sides in one layout;
# - MapMenu_00 is the small map in the corner and the menu's whole-screen map in one layout, and the game sets a layout's
#   projection once, not as the menu opens. The small map's own panes go out; its icons' layers (N_MapIcon_00,
#   N_PatternDungeonMini_01) are put at the small map's place by an animation's keys, which go out with them (hud_track_keys).
# prompts/wide.bin: "HPWD", u32 count, then each: u32 offset, i8 displacement multiplier (-1 left, +1 right,
# or the difference of endpoint multipliers for an animation delta),
# u8 0 x3, f32 the x
HUD_SIDE_PANES = {
    "ActionGuideTips_00": {"N_Guide_00": -1},
    "Location_00": {"N_SmallDisplay_00": -1},  # the large location card is centred
    "EventSkip_00": {"W_GuideBg_00": 1, "Pa_Skip_00": 1},
    # The challenge group is at +660. N_Guide_00 stays at +74; its only children, T_Guide_00 and T_Icon_00, move right.
    "ChallengeAttention_00": {"N_Challenge_00": 1, "T_Guide_00": 1, "T_Icon_00": 1},
    # The numeric HUD uses two instances of the same counter and a separate bottle marker group.
    "NumDisplay_00": {"Pa_Parts_00": 1, "Pa_Parts_01": 1, "A_Bottle_00": 1},
    "DoCommand_00": {},  # only the right-hand PosType state moves
    "SaveLoadIcon_00": {"N_InOut_00": -1},
    "PlayerStatus_00": {"N_ScaleL_00": -1, "N_ScaleR_00": 1, "N_VRS_00": 1, "N_SubItemBaseFishing_00": 1},
    "MapMenu_00": {"N_VRS_00": 1, "N_MiniMapCap_00": 1, "N_Field_01": 1, "N_Dungeon_01": 1, "N_MiniMapReplace_00": 1,
                   "P_MiniMapFrame_00": 1, "S_Floor_00": 1, "P_CapDungeon_00": 1},
}
HUD_CORNERS = {"N_ScaleL_00": -1920.0, "N_ScaleR_00": 1920.0}   # (the grid's corners: half its width out)


# The BFFH target tokens for pane translations encode the pane's index in the low four bits of
# the third byte and the high four bits (shifted by three) of the second. Attribute 14 is a curve.
def hud_translation_path(index):
    return 0x0160077f + ((index & 15) << 11) + ((index >> 4) << 16)


HUD_COUNTER_INSTANCES = {"Pa_Parts_00", "Pa_Parts_01"}
HUD_X_TRACKS = {
    "DoCommand_00": [("N_PosType_00", "PosType", 2, {234: 0, 724: 1, 466: 0})],
    "MapMenu_00": [("N_MapIcon_00", "MapType", 2, {1490: 1}),
                   ("N_PatternDungeonMini_01", "DungeonMiniMapPattern", 2, {1536: 1})],
    "SaveLoadIcon_00": [("N_InOut_00", "EnableText", 1, {-1720: -1, 1740: 1})],
}


# The dungeon pattern inherits MapType. Both sets of offsets shipped in the original minimap.
HUD_NESTED_TRACKS = {("MapMenu_00", "N_PatternDungeonMini_01", "DungeonMiniMapPattern"):
                     ("N_MapIcon_00", "MapType")}


def hud_track_keys(lay, animation, path, places, channels):
    """Follow the animation's target descriptor to its indexed curve. Reject missing or ambiguous bindings."""
    name = lay.find(b"\0" + animation.encode() + b"\0") + 1
    if not name:
        return None
    found = []
    for rec in range(0, len(lay) - 39, 8):
        if struct.unpack_from("<Q", lay, rec)[0] != name:
            continue
        targets, n, stride, curves, nc, cstride = struct.unpack_from("<QIIQII", lay, rec + 8)
        if stride != 8 or cstride != 8 or targets + 8 * n > len(lay) or curves + 8 * nc > len(lay):
            continue
        for i in range(n):
            desc, = struct.unpack_from("<Q", lay, targets + i * 8)
            if desc + 16 > len(lay):
                return None
            token, index, sentinel, count, attr = struct.unpack_from("<Q4H", lay, desc)
            if attr != 14 or lay[token:token + 6] != path.to_bytes(6, "little"):
                continue
            # The map's first curve reaches 1490 or 1536, the minimap's horizontal positions outside the grid's vertical range.
            # These authored translation tracks put x at the first curve index and y (if present)
            # immediately after it. The token binds the vector, not its axis. Check the descriptor
            # shape and the expected x positions before accepting channel zero.
            if sentinel != 65535 or count != channels or index + count > nc:
                return None
            curve, = struct.unpack_from("<Q", lay, curves + index * 8)
            if curve + 16 > len(lay):
                return None
            values, = struct.unpack_from("<Q", lay, curve + 8)
            if values + 24 > len(lay):
                return None
            at, size, step = struct.unpack_from("<QII", lay, values + 8)
            if step != 4 or not size or size % 2 or at + size * 4 > len(lay):
                return None
            offsets = range(at, at + size * 4, 8)
            keys = {}
            previous = None
            for off in offsets:
                x, slope = struct.unpack_from("<ff", lay, off)
                side = places.get(x, 0)
                if previous and previous[0] != side and (previous[1] or slope):
                    return None
                previous = side, slope
                if x in places:
                    keys[off] = (places[x], x)
                elif x != 0:
                    return None
            first, = struct.unpack_from("<f", lay, offsets[0])
            last, = struct.unpack_from("<f", lay, offsets[-1])
            delta, = struct.unpack_from("<f", lay, values)
            if delta != last - first:
                return None
            shift = places.get(last, 0) - places.get(first, 0)
            if shift:
                keys[values] = (shift, delta)
            if not set(places).issubset(x for _, x in keys.values()):
                return None
            found.append({off: item for off, item in keys.items() if item[0]})
    return found[0] if len(found) == 1 else None


def hud_grid_x(lay, records, pane, moving=()):
    """Translate a local anchor up to the grid. Only unrotated, unit-scale parents preserve our x offset."""
    x, = struct.unpack_from("<f", lay, pane + 0x1c)
    parent, = struct.unpack_from("<i", lay, pane + 0x28)
    seen = set()
    while parent != -1:
        if not 0 <= parent < len(records) or parent in seen:
            return None
        seen.add(parent)
        rec = records[parent]
        if rec in moving or struct.unpack_from("<5f", lay, rec) != (0., 0., 0., 0., 1.):
            return None
        x += struct.unpack_from("<f", lay, rec + 0x1c)[0]
        parent, = struct.unpack_from("<i", lay, rec + 0x28)
    return x


def wide_layout(blarc, name, sides):
    """Collect all copies together so a changed layout can keep its original placement."""
    out = []
    copies = layout_copies(blarc, name)
    if not copies:
        return None
    for a, z in copies:
        lay = blarc[a:z]
        panes = layout_panes(lay, unique=True)
        tracks = HUD_X_TRACKS.get(name, ())
        track_names = {p for p, _, _, _ in tracks}
        moving_names = set(sides) | track_names
        if not moving_names.issubset(panes):
            return None
        side_of, at = {}, {}
        records = list(panes.values())
        moving = {panes[p] for p in moving_names}
        for p, side in sides.items():
            if p not in track_names and hud_translation_path(records.index(panes[p])).to_bytes(6, "little") in lay:
                return None
            x = struct.unpack_from("<f", lay, panes[p] + 0x1c)[0]
            grid = hud_grid_x(lay, records, panes[p], moving)
            if name == "NumDisplay_00" and p in HUD_COUNTER_INSTANCES:
                # These instances have a central origin. Their contents, checked below, sit on the right.
                if grid != 0:
                    return None
                at[panes[p] + 0x1c] = (side, x)
                continue
            if grid is None or side * grid <= 640:  # only the outer thirds of the 3840-wide grid
                return None
            if x == 0.0 or HUD_CORNERS.get(p, x) != x or side_of.setdefault(x, side) != side:
                return None
            at[panes[p] + 0x1c] = (side, x)
        for pane, animation, channels, places in tracks:
            exception = HUD_NESTED_TRACKS.get((name, pane, animation))
            allowed = {panes[p] for p, anim, _, _ in tracks if (p, anim) == exception and p not in sides}
            grid = hud_grid_x(lay, records, panes[pane], moving - allowed)
            local, = struct.unpack_from("<f", lay, panes[pane] + 0x1c)
            if grid != local:  # these animated places are already grid coordinates
                return None
            keys = hud_track_keys(lay, animation, hud_translation_path(records.index(panes[pane])), places, channels)
            if keys is None:
                return None
            side_of.update({x: side for x, side in places.items() if side})
            at.update(keys)
        widths = {v + 0x2c for v in panes.values()}  # widths can equal a position, but never move
        for x in side_of:
            pat = struct.pack("<f", x)
            if any(lay[o:o + 4] == pat and o not in at and o not in widths for o in range(0, len(lay) - 3, 4)):
                return None
        out += [(a + o, side, x) for o, (side, x) in sorted(at.items())]
    return out or None


def wide_panes(blarc, ring=()):
    ring_bytes = {i for *_, runs in ring or () for off, data in runs for i in range(off, off + len(data))}
    out = []
    for name, sides in HUD_SIDE_PANES.items():
        entries = wide_layout(blarc, name, sides)
        if entries and any(i in ring_bytes for off, _, _ in entries for i in range(off, off + 4)):
            print(f"prompts: {name}: HUD edge position overlaps a Talk ring run, keeping its original placement", file=sys.stderr)
            continue
        if entries and name == "NumDisplay_00":
            # Only the owning HUD's two instances move. Check the visible part's grid on every copy.
            copies = layout_copies(blarc, "PaNumDisplay_00")
            if not copies:
                entries = None
            for a, z in copies:
                lay = blarc[a:z]
                panes = layout_panes(lay, unique=True)
                for child in ("P_NumBase_00", "A_Num_00", "N_PlusMinus_00"):
                    grid = hud_grid_x(lay, list(panes.values()), panes[child]) if child in panes else None
                    if grid is None or grid <= 640:
                        entries = None
        if entries:
            print(f"prompts: {name}: {len(entries)} HUD edge entries", file=sys.stderr)
            out.extend(entries)
        else:
            print(f"prompts: {name}: unknown HUD layout, keeping its original placement", file=sys.stderr)
    return out or None


def write_wide(path, panes):
    with open(path, "wb") as f:
        f.write(b"HPWD" + struct.pack("<I", len(panes)))
        for off, side, x in panes:
            f.write(struct.pack("<Ib3xf", off, side, x))


# ---- the camera's speed (the Insert menu's Camera speed row, host/prompts.c build_camera; NX2navi's camera speed setting, done
# with the files the prompts already use). The game's Options offer five camera sensitivities; their turn rates are the array
# StickSensitivity of Component/PlayerCameraParam/PlayerCamera.game__component__PlayerCameraParam.bgyml in
# Pack/Actor/PlayerCamera.pack.zs (a SARC, zstd with pack.zsdic). A BYML array keeps its floats in the array itself, so the
# host writes each times the row's factor over the old one and nothing else moves. prompts/PlayerCamera.pack is the game's
# pack decompressed; prompts/camera.bin: "HPCM", u32 count, then each: u32 offset (a value in the pack), f32 the game's value
CAMERA = "Pack/Actor/PlayerCamera.pack.zs"
CAMERA_MEMBER = "Component/PlayerCameraParam/PlayerCamera.game__component__PlayerCameraParam.bgyml"
CAMERA_KEY = "StickSensitivity"


def sarc_member(b, name):
    """(start, end) of the file `name` in the SARC b, or None"""
    if b[:4] != b"SARC" or len(b) < 0x20:
        return None
    hl, = struct.unpack_from("<H", b, 4)
    data, = struct.unpack_from("<I", b, 12)
    n, = struct.unpack_from("<H", b, hl + 6)
    names = hl + 12 + 16 * n + 8
    for i in range(n):
        attr, start, end = struct.unpack_from("<III", b, hl + 12 + 16 * i + 4)
        o = names + (attr & 0xFFFFFF) * 4
        if 0 <= o < len(b) and b[o:b.find(b"\0", o)] == name.encode():
            return (data + start, data + end) if data + end <= len(b) and start <= end else None
    return None


def byml_floats(d, key):
    """[(offset, value)] of the floats of the array `key` in the root dictionary of the BYML d (little-endian: "YB", u16
    version, u32 keys' table, u32 strings' table, u32 root; a dictionary: 0xc1, u24 count, then (u24 key, u8 type, u32 value)
    each; an array: 0xc0, u24 count, a type byte each, padded to 4, then the values; 0xd2 a float), or None"""
    try:
        if d[:2] != b"YB":
            return None
        keys, root = struct.unpack_from("<I", d, 4)[0], struct.unpack_from("<I", d, 12)[0]
        kh, rh = struct.unpack_from("<I", d, keys)[0], struct.unpack_from("<I", d, root)[0]
        if kh & 0xff != 0xc2 or rh & 0xff != 0xc1:
            return None
        for i in range(rh >> 8):
            e, value = struct.unpack_from("<II", d, root + 4 + 8 * i)
            if (e & 0xffffff) >= kh >> 8:
                return None
            at = keys + struct.unpack_from("<I", d, keys + 4 + 4 * (e & 0xffffff))[0]
            if d[at:d.index(b"\0", at)] != key.encode():
                continue
            ah = struct.unpack_from("<I", d, value)[0]
            count = ah >> 8
            if e >> 24 != 0xc0 or ah & 0xff != 0xc0 or not 1 <= count <= 8 or set(d[value + 4:value + 4 + count]) != {0xd2}:
                return None
            vals = value + 4 + ((count + 3) & ~3)
            return [(vals + 4 * j, struct.unpack_from("<f", d, vals + 4 * j)[0]) for j in range(count)]
    except (struct.error, ValueError):
        pass
    return None


def camera_speeds(pack):
    """the camera's turn rates in the pack: [(offset in the pack, value)], or None when the pack is not the one known (no such
    file or array in it, or a rate that is no speed)"""
    at = sarc_member(pack, CAMERA_MEMBER)
    floats = byml_floats(pack[at[0]:at[1]], CAMERA_KEY) if at else None
    if not floats or any(not 0.05 <= v <= 50.0 for _, v in floats):
        return None
    return [(at[0] + o, v) for o, v in floats]


def write_camera(path, speeds):
    with open(path, "wb") as f:
        f.write(b"HPCM" + struct.pack("<I", len(speeds)))
        for off, v in speeds:
            f.write(struct.pack("<If", off, v))


# ---- (Triforce) the title screen's third entry, "Options / ZELDA NOTES Setting" in US English: it opens the game's Options,
# where Triforce's own tabs are, so it reads "Options / Triforce". The text is label 0002 of LayoutMsg/Title_00.msbt in each
# language's messages, Mals/<language>.Product.110.sarc.zs (a SARC, zstd with zs.zsdic): the game's word for Options, a size
# tag (the rest is drawn smaller), then the rest. Everything up to the end of that tag is kept, the rest becomes the game's
# own separator and TITLE_TEXT. prompts/mals/<language>.product.110.sarc.zs (the file's name in lower case, as host/prompts.c
# asks for it) is each language's archive with that one file rewritten, as a zstd frame without the dictionary; the host
# serves the one of the language the game runs in, where no mod has that file
TITLE_TEXT = "Triforce"   # (what the entry says after the game's word for Options and its separator)
TITLE_MSBT, TITLE_LABEL = "LayoutMsg/Title_00.msbt", "0002"
TITLE_SEPARATORS = "/／|"   # (the game's own between the two parts, kept with its spaces: "/", the full-width one, "|")
TITLE_SEPARATOR = " / "   # (where the game has none: the rest in brackets, "Optionen (inkl. ZELDA NOTES-Einstellungen)")
MALS = "Mals"
SARC_ALIGN = 0x2000   # (the largest alignment a file in an archive is given: textures and models)


def msbt_sections(m):
    """an MSBT's sections, [(magic, the 8 bytes after its size, body, the padding after it)], or None when m is not one (only
    the little-endian kind: "MsgStdBn", the mark ff fe, the text's encoding at +0xc (0 UTF-8, 1 UTF-16), the count of
    sections at +0xe, the file's size at +0x12, sections from +0x20, each a magic, u32 its body's size, 8 bytes, the body,
    padded to 16)"""
    if len(m) < 0x20 or m[:8] != b"MsgStdBn" or m[8:10] != b"\xff\xfe" or m[0xc] not in (0, 1):
        return None
    count, = struct.unpack_from("<H", m, 0xe)
    if struct.unpack_from("<I", m, 0x12)[0] != len(m):
        return None
    out, at = [], 0x20
    for _ in range(count):
        if at + 16 > len(m):
            return None
        n, = struct.unpack_from("<I", m, at + 4)
        end = at + 16 + n
        pad = end + (-end % 16)
        if pad > len(m):
            return None
        out.append((bytes(m[at:at + 4]), bytes(m[at + 8:at + 16]), bytes(m[at + 16:end]), bytes(m[end:pad])))
        at = pad
    return out if at == len(m) else None


def msbt_build(m, sections):
    """the MSBT m (its header) with these sections (msbt_sections' form): a body of another size gets its padding (the byte
    the section had, else 0xab) and the file its size"""
    out = bytearray(m[:0x20])
    for magic, rest, body, pad in sections:
        need = -(16 + len(body)) % 16
        out += magic + struct.pack("<I", len(body)) + rest + body
        out += pad if len(pad) == need else (pad[:1] or b"\xab") * need
    struct.pack_into("<I", out, 0x12, len(out))
    return bytes(out)


def msbt_labels(body):
    """{label: its text's number} of a LBL1 body: u32 slots, each u32 count and u32 offset; at an offset that many labels, each
    u8 length, the name, u32 number"""
    slots, = struct.unpack_from("<I", body, 0)
    out = {}
    for i in range(slots):
        count, at = struct.unpack_from("<II", body, 4 + 8 * i)
        for _ in range(count):
            n = body[at]
            out[body[at + 1:at + 1 + n].decode("ascii")] = struct.unpack_from("<I", body, at + 1 + n)[0]
            at += 5 + n
    return out


def txt2_strings(body):
    """a TXT2 body's texts (u32 count, u32 offset each from the body's start, the texts with their ends), or None"""
    count, = struct.unpack_from("<I", body, 0)
    offs = list(struct.unpack_from(f"<{count}I", body, 4)) + [len(body)]
    if offs[0] != 4 + 4 * count or offs != sorted(offs):
        return None
    return [body[a:z] for a, z in zip(offs, offs[1:])]


def txt2_build(strings):
    at = 4 + 4 * len(strings)
    offs = []
    for s in strings:
        offs.append(at)
        at += len(s)
    return struct.pack(f"<I{len(strings)}I", len(strings), *offs) + b"".join(strings)


def title_text(s, encoding, text=TITLE_TEXT):
    """label 0002's text with its rest after the size tag (a tag: 0x0e, u16 group, u16 type, u16 its parameters' size, the
    parameters; group 0 type 2 the size) the separator and text, or None when it has no size tag before its end"""
    w, codec = (1, "utf-8") if encoding == 0 else (2, "utf-16-le")
    at = 0
    while at + w <= len(s):
        c = int.from_bytes(s[at:at + w], "little")
        if c == 0:
            return None
        if c == 0x0f:   # (a tag's end: u16 group, u16 type)
            at += w + 4
            continue
        if c != 0x0e:
            at += w
            continue
        if at + w + 6 > len(s):
            return None
        group, kind, n = struct.unpack_from("<HHH", s, at + w)
        at += w + 6 + n
        if group == 0 and kind == 2:
            break
    else:
        return None
    rest = bytearray()   # (the rest's text, up to its first tag or its end)
    for k in range(at, len(s) - w + 1, w):
        if int.from_bytes(s[k:k + w], "little") in (0, 0x0e, 0x0f):
            break
        rest += s[k:k + w]
    words = rest.decode(codec, "replace")
    sep = words[:len(words) - len(words.lstrip())]
    if words.lstrip()[:1] and words.lstrip()[0] in TITLE_SEPARATORS:
        after = words.lstrip()[1:]
        sep += words.lstrip()[0] + after[:len(after) - len(after.lstrip())]
    else:
        sep = TITLE_SEPARATOR
    return s[:at] + (sep + text).encode(codec) + b"\0" * w


def title_msbt(m, text=TITLE_TEXT):
    """the MSBT m with label 0002's rest made text (title_text), every other byte as it was, or None when m is not the
    title's (no LBL1 or TXT2, no label 0002, or a text with no size tag)"""
    sections = msbt_sections(m)
    if not sections:
        return None
    try:
        by = {magic: i for i, (magic, _, _, _) in enumerate(sections)}
        if b"LBL1" not in by or b"TXT2" not in by:
            return None
        k = msbt_labels(sections[by[b"LBL1"]][2]).get(TITLE_LABEL)
        magic, rest, body, pad = sections[by[b"TXT2"]]
        strings = txt2_strings(body)
        if strings is None or k is None or k >= len(strings):
            return None
        new = title_text(strings[k], m[0xc], text)
    except (struct.error, IndexError, UnicodeDecodeError):
        return None
    if new is None:
        return None
    strings[k] = new
    sections[by[b"TXT2"]] = (magic, rest, txt2_build(strings), pad)
    return msbt_build(m, sections)


def sarc_replace(b, name, data):
    """the SARC b with the file `name` made data: the files before it as they were, those after it moved on together by a
    multiple of every alignment they may need (an archive does not say which: each one's place's, up to SARC_ALIGN), so
    each keeps its own, the bytes between them as they were and a gap of zeros after the new file; the nodes' offsets and
    the archive's size made to agree. A file shorter by less than that moves nothing. None when b is no little-endian
    SARC, has no such file, or files that overlap it"""
    if len(b) < 0x20 or b[:4] != b"SARC":
        return None
    hl, bom = struct.unpack_from("<HH", b, 4)
    total, data_at = struct.unpack_from("<II", b, 8)
    if bom != 0xfeff or total != len(b) or b[hl:hl + 4] != b"SFAT":
        return None
    n, = struct.unpack_from("<H", b, hl + 6)
    nodes = hl + 12
    at = sarc_member(b, name)
    if not at:
        return None
    start, end = at[0] - data_at, at[1] - data_at
    entries = [struct.unpack_from("<IIII", b, nodes + 16 * i) for i in range(n)]
    k = next(i for i, e in enumerate(entries) if (e[2], e[3]) == (start, end))
    later = [i for i, e in enumerate(entries) if i != k and e[2] >= end]
    after = set(later)
    if any(i != k and i not in after and e[3] > start for i, e in enumerate(entries)):
        return None
    grow = len(data) - (end - start)
    if later:
        first = min(entries[i][2] for i in later)
        align = max([1] + [min((data_at + entries[i][2]) & -(data_at + entries[i][2]), SARC_ALIGN) for i in later])
        move = -(-grow // align) * align   # (at least grow, the least multiple of the alignment)
        out = bytearray(b[:data_at + start]) + data + bytes(first + move - start - len(data)) + b[data_at + first:]
    else:
        move = grow
        out = bytearray(b[:data_at + start]) + data + b[data_at + end:]
    struct.pack_into("<I", out, nodes + 16 * k + 12, start + len(data))
    for i in later:
        struct.pack_into("<II", out, nodes + 16 * i + 8, entries[i][2] + move, entries[i][3] + move)
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


def title_sarc(sarc, text=TITLE_TEXT):
    """a language's messages (Mals/*.sarc, decompressed) with the title's Options entry saying text, or None when they are
    not the ones known"""
    at = sarc_member(sarc, TITLE_MSBT)
    m = title_msbt(sarc[at[0]:at[1]], text) if at else None
    return sarc_replace(sarc, TITLE_MSBT, m) if m else None


def read_size_table(romfs, dictionary):
    """(its name, the game's resource size table decompressed: size_table says its form)"""
    folder = os.path.join(romfs, "System", "Resource")
    name = next((n for n in sorted(os.listdir(folder)) if n.startswith("ResourceSizeTable.") and n.endswith(".rsizetable.zs")),
                None)
    if not name:
        raise SystemExit("prompts: no System/Resource/ResourceSizeTable.*.rsizetable.zs")
    b = bytearray(read_zs(romfs, f"System/Resource/{name}", dictionary))
    if b[:6] != b"RESTBL":
        raise SystemExit(f"prompts: {name} is not a RESTBL table")
    return name, b


def size_entry(table, path):
    """a file's entry in a resource size table (path without .zs), None when it has none: a named entry (u32 name length
    after the version, then after the hashed entries each the name in that many bytes and u32 size) over a hashed one"""
    import zlib
    room, hashed, named = struct.unpack_from("<III", table, 10)
    at = 22 + 8 * hashed
    for i in range(named):
        e = at + (room + 4) * i
        if table[e:e + room].split(b"\0")[0] == path.encode():
            return struct.unpack_from("<I", table, e + room)[0]
    want = zlib.crc32(path.encode())
    for i in range(hashed):
        h, size = struct.unpack_from("<II", table, 22 + 8 * i)
        if h == want:
            return size
    return None


# ---- (Triforce) the game's texts that name the console, in the PC's words. One does: the hint for playing the ocarina by
# microphone ("Ocarina Audio Input") says to use the console's built-in one; on a PC the game listens to the microphone the
# Insert menu's Microphone row chooses. It is reworded in the same messages archive as the title's entry (title_messages
# writes the one file a language), in the string's own room: the string's bytes from start to end become the replacement,
# the rest (the other sentences, the tags, the reading aids over the kanji) stays the game's, and what is left of its room is
# filled with NULs, so no offset moves and the archive keeps its size. A wording is known by its fingerprint (no game text in
# this file); a string that is not one of them (another version, a mod's text) is left as it is and said
# [(msbt, label, {a wording's fingerprint: (start, end, replacement)})]
PC_TEXTS = [
    # the "Ocarina Audio Input" hint: the console's built-in microphone -> your microphone (the languages that have that wording)
    ("LayoutMsg/ActionGuide_00.msbt", "Pa_ActionGuide_01-T_Description_00", {
        "b816b30394a86b8a": (4, 38, "your microphone"),       # USen, EUen
        "9925b429328b1fd2": (21, 69, "votre microphone\n"),   # USfr, EUfr
        "e4bd22fcea2f8529": (16, 60, "un micrófono"),         # USes, EUes
        "0dd1fb25d15aec84": (4, 46, "o seu microfone"),       # USpt
        "3179003a18de9124": (9, 64, "dein Mikrofon"),         # EUde
        "7fa2434137fc436c": (11, 54, "il tuo microfono"),     # EUit
        "7f5339bb84e3bb77": (8, 56, "je microfoon"),          # EUnl
        "21bce07f220b2409": (8, 57, "mikrofonowi"),           # EUpl
        "54935b14b603297c": (0, 55, "Микрофон"),              # EUru
        "ed6bdf6d1550bdad": (0, 50, ""),                      # JPja: "the console's" goes, the microphone stays
        "01467ba53d125ec9": (0, 28, ""),                      # KRko: the same
        "cd07456de7b137ad": (6, 32, ""),                      # CNzh: the same
        "c52f433f130e10eb": (6, 32, ""),                      # TWzh: the same
    }),
]


def text_fingerprint(text):
    """a wording's name in PC_TEXTS: of the string's whole room, its terminator too"""
    import hashlib
    return hashlib.sha1(bytes(text)).hexdigest()[:16]


def msbt_rooms(m):
    """an MSBT's strings by label: {label: (start, end)}, each string's room in m (its bytes, tags and terminator, up to the
    next string's start); None when it is not a UTF-8 MSBT with labels and texts"""
    if len(m) < 0x20 or m[:8] != b"MsgStdBn" or m[8:10] != b"\xff\xfe" or m[12] != 0:   # (little-endian, UTF-8)
        return None
    at, sections = 0x20, {}
    while at + 16 <= len(m):
        size = struct.unpack_from("<I", m, at + 4)[0]
        sections[bytes(m[at:at + 4])] = (at + 16, size)
        at = (at + 16 + size + 15) & ~15
    if b"LBL1" not in sections or b"TXT2" not in sections:
        return None
    lbl, _ = sections[b"LBL1"]
    txt, txt_size = sections[b"TXT2"]
    count = struct.unpack_from("<I", m, txt)[0]
    starts = list(struct.unpack_from("<%dI" % count, m, txt + 4)) + [txt_size]
    out = {}
    for slot in range(struct.unpack_from("<I", m, lbl)[0]):
        n, at = struct.unpack_from("<II", m, lbl + 4 + 8 * slot)
        at += lbl
        for _ in range(n):
            length = m[at]
            index = struct.unpack_from("<I", m, at + 1 + length)[0]
            if index < count:
                out[bytes(m[at + 1:at + 1 + length]).decode("utf-8")] = (txt + starts[index], txt + starts[index + 1])
            at += 5 + length
    return out


def pc_texts(sarc, strings=None):
    """a language's messages (Mals/*.sarc, decompressed) with PC_TEXTS' edits made: (the new bytes, the same length; the
    labels reworded; the labels left as they are, each with why)"""
    out, done, left = bytearray(sarc), [], []
    for msbt, label, edits in PC_TEXTS if strings is None else strings:
        at = sarc_member(out, msbt)
        if not at:
            left.append((label, "no %s" % msbt))
            continue
        base, end = at
        rooms = msbt_rooms(out[base:end])
        if rooms is None or label not in rooms:
            left.append((label, "no such string"))
            continue
        a, b = (base + x for x in rooms[label])
        text = bytes(out[a:b])
        if text_fingerprint(text) not in edits:
            left.append((label, "its text is not one this was written for"))
            continue
        start, stop, new = edits[text_fingerprint(text)]
        new = new.encode("utf-8")
        if not 0 <= start <= stop < len(text) or len(new) > stop - start:
            raise ValueError("%s: the replacement does not fit what it replaces" % label)
        text = text[:start] + new + text[stop:]
        out[a:b] = text + b"\0" * (b - a - len(text))   # (in its own room: nothing after it moves)
        done.append(label)
    return bytes(out), done, left


def title_messages(romfs, dictionary, out, text=TITLE_TEXT):
    """writes <out>/mals/<language>.product.110.sarc.zs for each language whose messages are the ones known and whose
    rewritten archive is no larger than the game's file (and within its entry in the size table, where it has one); the
    languages written. The entry is the file's size plus an allowance the game keeps over it (336 bytes for every Mals
    archive), as size_table keeps the font's: an archive growing into that allowance is past what the entry holds for it
    and the game drops a file larger than its entry, so a TITLE_TEXT longer than a language's rest leaves that language as
    the game has it (the build says so) rather than raising the entry"""
    import zstandard
    _, table = read_size_table(romfs, dictionary)
    done, worded_in = [], []
    for name in sorted(os.listdir(os.path.join(romfs, MALS))):
        if not name.endswith(".sarc.zs"):
            continue
        game = read_zs(romfs, f"{MALS}/{name}", dictionary)
        new = title_sarc(game, text)
        if not new:
            print(f"prompts: {MALS}/{name}: the title keeps its text (its messages are not the ones known)", file=sys.stderr)
        entry = size_entry(table, f"{MALS}/{name[:-3]}")
        fits = len(game) if entry is None else min(len(game), entry)   # (the entry's allowance over the file kept)
        if new and len(new) > fits:
            print(f"prompts: {MALS}/{name}: the title keeps its text ({len(new)} bytes; the game's file is {len(game)}, "
                  f"its size table entry {entry}: a shorter TITLE_TEXT fits)", file=sys.stderr)
            new = None
        # ((Triforce) the texts that name the console, in the PC's words, in the same file: they keep its size)
        worded, said, left = pc_texts(new or game)
        for label, why in left:
            print(f"prompts: {MALS}/{name}: {label} left as it is ({why})", file=sys.stderr)
        if not new and not said:
            continue
        os.makedirs(os.path.join(out, "mals"), exist_ok=True)
        with open(os.path.join(out, "mals", name.lower()), "wb") as f:
            f.write(zstandard.ZstdCompressor(level=3).compress(worded))
        if new:
            done.append(name.split(".")[0])
        if said:
            worded_in.append(name.split(".")[0])
    if worded_in:
        print("prompts: the ocarina's microphone hint says your microphone in " + " ".join(worded_in), file=sys.stderr)
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--romfs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--faces", default=",".join(["switch"] + list(FACES)))
    ap.add_argument("--no-textures", action="store_true")
    ap.add_argument("--dump", help="also write every face's images as PNG into <dir>/<face>/ (the names nx2/prompt_faces/<face>/ "
                    "takes in their place), and the game's textures they go into into <dir>/game/")
    a = ap.parse_args()
    dictionary = zs_dictionary(a.romfs)
    game_font = read_zs(a.romfs, FONT, dictionary)
    key, otf = unwrap(game_font)
    letters = None
    try:   # ((Triforce VR) the letters of the hand controllers' trigger and grip icons, nx2/prompt_vr.py)
        import prompt_vr
        letters = unwrap(read_zs(a.romfs, prompt_vr.LETTERS, dictionary))[1]
    except (Exception, SystemExit) as e:
        print(f"prompts: the VR trigger and grip icons keep the game's letters ({e})", file=sys.stderr)
    textures = None
    if not a.no_textures:
        try:
            import astc_encoder  # noqa: F401
            import PIL  # noqa: F401
            import texture2ddecoder  # noqa: F401
            textures = read_zs(a.romfs, TEXTURES, dictionary)
        except ImportError as e:   # (the module that is missing: a package's own dependency too, astc_encoder's archspec)
            print(f"prompts: the textures keep the Switch's icons (no {e.name or e})", file=sys.stderr)
    if textures:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "Common.bntx"), "wb") as f:
            f.write(textures)
        tex = bntx_textures(textures)
    blarc = read_zs(a.romfs, LAYOUTS, dictionary)
    hint = hint_panes(blarc)
    if not hint:
        print("prompts: the ocarina's hint keeps the game's spacing (its layout is not the one known)", file=sys.stderr)
    largest = 0
    for face in a.faces.split(","):
        d = os.path.join(a.out, face)
        os.makedirs(d, exist_ok=True)
        names = None
        if FACES.get(face, {}).get("keys"):   # ((Triforce) the keyboard and mouse: its icons are drawn, nx2/prompt_keys.py)
            try:
                import prompt_keys
                plain, binds = prompt_keys.game_font(otf)
            except (Exception, SystemExit) as e:   # (tools without the labels' font, a game font it cannot take: the
                # controllers' faces are made all the same, and the game shows its own icons for the keyboard)
                print(f"prompts: {face} was not made ({e})", file=sys.stderr)
                os.rmdir(d)
                continue
            prompt_keys.write_binds(os.path.join(d, "keys.bin"), binds)
            names = prompt_keys.hint_names()
        else:
            plain, names = face_font(otf, face, letters)
        font = wrap(key, plain)
        if hint:
            write_hint(os.path.join(d, "hint.bin"), plain, hint, names)
        largest = max(largest, len(font))
        with open(os.path.join(d, "External.bfotf"), "wb") as f:
            f.write(font)
        if textures:
            layers = face_layers(textures, tex, face, otf)
            write_textures(os.path.join(d, "textures.bin"), face_textures(textures, tex, layers))
            if a.dump:
                dump(a.dump, face, textures, tex, layers)
        print(f"prompts: {face}", file=sys.stderr)
    ring = ring_entries(blarc)
    wide = wide_panes(blarc, ring)
    if ring or hint or wide:
        with open(os.path.join(a.out, "Common.blarc"), "wb") as f:
            f.write(blarc)
    if wide:
        write_wide(os.path.join(a.out, "wide.bin"), wide)
    else:
        print("prompts: no known HUD edge positions in the layouts",
              file=sys.stderr)
    speeds = None
    try:
        pack = read_zs(a.romfs, CAMERA, zs_dictionary(a.romfs, b"pack.zsdic"))
        speeds = camera_speeds(pack)
    except (Exception, SystemExit) as e:   # (a romfs without the pack, or one that does not decompress)
        print(f"prompts: the camera's pack was not read ({e})", file=sys.stderr)
    if speeds:
        with open(os.path.join(a.out, "PlayerCamera.pack"), "wb") as f:
            f.write(pack)
        write_camera(os.path.join(a.out, "camera.bin"), speeds)
        print("prompts: the camera's speeds " + " ".join("%.2f" % v for _, v in speeds), file=sys.stderr)
    else:
        print("prompts: the camera keeps the game's speed (its pack is not the one known)", file=sys.stderr)
    try:
        titles = title_messages(a.romfs, dictionary, a.out)
    except (Exception, SystemExit) as e:   # (a romfs without the messages, or one that does not decompress)
        titles = []
        print(f"prompts: the title's messages were not read ({e})", file=sys.stderr)
    if titles:
        print(f"prompts: the title's Options entry says {TITLE_TEXT} in " + " ".join(titles), file=sys.stderr)
    if ring:
        write_ring(os.path.join(a.out, "ring.bin"), ring)
        print("prompts: the Talk ring", file=sys.stderr)
    else:
        print("prompts: the Talk ring keeps the Switch's places (its layout is not the one known)", file=sys.stderr)
    table, path = size_table(a.romfs, dictionary, len(game_font), largest), os.path.join(a.out, "rsizetable.zs")
    if table:
        import zstandard
        with open(path, "wb") as f:
            f.write(zstandard.ZstdCompressor(level=3).compress(table))
        print(f"prompts: the size table lets the font have {largest} bytes", file=sys.stderr)
    elif os.path.exists(path):
        os.remove(path)


if __name__ == "__main__":
    main()
