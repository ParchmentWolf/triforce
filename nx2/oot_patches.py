"""Changes to the lifted C for Ocarina of Time, applied by lift.py after it writes the code (and by hand: python -I nx2/oot_patches.py).

Each is a runtime switch where it can be, so the game's own path stays reachable.

- Dynamic resolution (Lichii's built-in "Max Resolution" patch, main+0x805BD0): the engine's config flag at +0x94 picks the path that
  follows the GPU-time controller; with hos_fixed_resolution set it takes the other path, the 3D at full scale. The controller made
  a new set of render targets at each size, ~11 images a frame at times, and held the GPU near its budget.
- Text speed (the Insert menu's "Text speed"): f_80b1e140 (main+0xafe140) steps a text pane's letter animation, the
  LetterAnimControl of the panes with "LetterAnimOn" user data (dialogue, Navi, signs). Its time argument (s0) moves the
  letters' clock (+0x60 += rate +0x4c * time, the rate from the message's speed tag) and the pauses' timer (+0x58 -= time);
  hos_text_scale multiplies it, 1.0 as shipped. The auto-advance timer (+0x5c, before) keeps the game's time. A huge
  scale shows a page at once (one frame per pause), as the game's own skip on A (+0x72 = 2, f_80794b00) without its flags.
- The fixed path's scale (hos_fixed_scale_bits: the Insert menu's Resolution) reaching the 3D, in the caller f_831f3200
  (main+0x31d3200). It recomputes the 3D's scale (+0xe5c = scale * +0xe58 / +0xe50) only while +0xe2c bit 3 is set. The dynamic
  path sets it on a level change; the fixed path's flag 1 calls f_831f41d0, whose bit 3 the apply block clears in the same frame,
  before any recompute. So the fixed path kept the dynamic path's last scale (0.75 docked: 1536x864 at every setting). Flag 1 now
  also asks for the recompute, and on the fixed path the flags +0xe20 bits 3/4 (a hardcoded 0.75 / 0.5 in place of the scale)
  are not looked at.
- The OptimizeChangeBank thread's allocations tried again when their heap is full (host/oot_heap_retry.c): f_804566e0's two
  calls of f_80522050, its GPU memory (GPU_ALLOC_SITES), and its two tryAllocs of CPU buffers (HEAP_ALLOC_SITES). They went on
  with a null pointer and crashed writing through it (issue 1697). The supported build only.
- ((Triforce) 11-19) The texture data compaction thread's step called through the host (host/oot_tex_compact.c): f_807da3f0's
  call of f_807da480. The host counts the cycles it starts and, with HOS_OOT_TEX_COMPACT_MS set, holds them to a pace; unset,
  the step runs as shipped. The supported build only.
- ((Triforce) 11-22) The texture data manager's ask for a compaction round (f_80797240) also asks the host, which lets one through
  at most once a second (host/oot_tex_compact.c hos_oot_tex_compact_due, HOS_OOT_TEX_ASK_MS; 0: as shipped). The supported
  build only.
- ((Triforce) 11-24) The neighbouring map the OptimizeChangeBank thread preloads, kept while the game's choice only flickers
  (host/oot_ocb_hold.h): the preload manager's update (f_832b9880) picks one of the map's neighbours each frame and a
  change cancels the one loading or loaded; a choice flickering between two (or in and out of a radius) reloaded them over
  and over with Link on one spot. Its choice goes through hos_oot_ocb_pick, which takes another neighbour only once it
  stays the choice HOS_OCB_HOLD_MS (0: the game's own at every frame). The supported build only.
- ((Triforce) 11-21, the performance audit's GAME-05) A character's or an object's shadow map's side through the host
  (host/oot_shadow_step.h): f_802640a0 reads it once before it asks for the texture; hos_oot_shadow_side rounds it up to a
  multiple of 64 (HOS_OOT_SHADOW_STEP), so the sides come round again and the render targets' pool serves them. The supported
  build only.
- ((Triforce) 11-24) The Graphics tab's Shadow resolution: the sun's cascades' size, rounded in f_80492370, through the host
  (host/oot_shadow.c hos_oot_shadow_size), which raises it to 2200 or 3072 for the sun's shadow object; and on Highest the
  nearest cascade's fit (f_80733120's light basis, f_80733be0's box) through the host, which keeps it still under the scene
  while the camera moves (host/oot_shadow_fit.c). Game's, the row's default, changes nothing. The supported build only.
- ((Triforce) 11-24) Ocarina note controls: the note-wait action's start (f_828a9190) and tick (f_828a9280) report the
  wait to the host (hos_oc_wait, hos_oc_last_kind, hos_oc_beat), which swaps the five notes for the Controls page's
  note rows while the game waits for a note button (host/nn_hid.c oc_notes); a tick whose gates refuse reports no wait,
  so a dialogue keeps its buttons. With no note row bound, as shipped, the game's buttons play as before.
- ((Triforce) 11-24) The game's job barriers waiting for their work (host/oot_barrier.h): three parallel-for jobs
  (f_800998a0, f_800738e0, f_8007e200) sleep 20 us and look again while the masks they poll are not full; the sleep is
  hos_oot_barrier_wait, which ends when a polled word moves (1 ms at most), and each OR into such a word wakes the waiters
  (hos_oot_barrier_wake). On by default; HOS_OOT_BARRIER_WAIT=0, the sleeps as lifted. The supported build only.
"""
import glob
import os
import re
import sys
import whole_write   # (rewrites written beside and moved over: issue 1197)

DECL = "extern volatile int hos_fixed_resolution;\nextern volatile int hos_dynres_runs;\nextern volatile uint32_t hos_fixed_scale_bits;\n"
OLD = "if (!((c->x[8] >> 0) & 1)) { goto L_8082640c; }"
NEW = "if (hos_fixed_resolution || !((c->x[8] >> 0) & 1)) { goto L_8082640c; }\n    hos_dynres_runs++;"
LABEL = "L_8082640c:;"
SCALE_OLD = "c->x[9] = 0x3f800000ULL;"
SCALE_NEW = "c->x[9] = hos_fixed_scale_bits;"   # (the fixed path's scale, 1.0 as shipped)
DECL2 = "extern volatile int hos_fixed_resolution;\nextern volatile uint64_t hos_res_module;\nextern volatile uint32_t hos_fixed_scale_bits;\n"
APPLY_OLD = "L_831f3efc:;\n    c->x[9]=recomp_load32(c,c->x[20] + 3628);"
APPLY_NEW = "L_831f3efc:;\n    if (hos_fixed_resolution) {   /* (only while +0xe5c is not the chosen scale: a recompute every frame remade the targets) */\n        union { uint32_t u; float f; } now = {(uint32_t)recomp_load32(c,c->x[20] + 3676)}, want = {hos_fixed_scale_bits},\n            e50 = {(uint32_t)recomp_load32(c,c->x[20] + 3664)}, e58 = {(uint32_t)recomp_load32(c,c->x[20] + 3672)};\n        const float d = now.f - (e50.f != 0 ? want.f * e58.f / e50.f : want.f);\n        if (d > 1e-4f || d < -1e-4f) c->x[8] |= 8;\n    }\n    c->x[9]=recomp_load32(c,c->x[20] + 3628);"
FLAGS_OLD = "L_831f3f08:;\n    c->x[8]=recomp_load64(c,c->x[20] + 3616);\n"
FLAGS_NEW = FLAGS_OLD + "    hos_res_module = c->x[20];\n    if (hos_fixed_resolution) c->x[8] &= ~0x18ULL;\n"


def fixed_scale(t):
    """The fixed path's scale reaching the 3D (the Resolution row). (t, 1) when applied here"""
    if APPLY_OLD not in t or FLAGS_OLD not in t:
        return t, 0
    t = t.replace(APPLY_OLD, APPLY_NEW, 1).replace(FLAGS_OLD, FLAGS_NEW, 1)
    return t.replace('#include "a64.h"\n', '#include "a64.h"\n' + DECL2, 1), 1

TEXT_DECL = "extern volatile float hos_text_scale;\n"
LIFE_BUILD_ID = "e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348"
LIFE_HEAD = "void f_804bd8c0(Ctx *__restrict A64_NOESC c) {\n"
MOVE_HEAD = "void f_82c415e0(Ctx *__restrict A64_NOESC c) {\n"
MOVE_ANCHOR = ("if (((c->x[8] >> 1) & 1)) { goto L_82c41748; }\n")
MOVE_MATRIX = "L_82c41778:;\n"
WARP_HEAD = "void f_806d2530(Ctx *__restrict A64_NOESC c) {\n"
WARP_ANCHOR = "{ uint64_t _t = c->x[8]; c->x[30] = 0x806d25c8ULL; A64_ICALL(c, _t); }\n"
VIEW_HEAD = "void f_804e48c0(Ctx *__restrict A64_NOESC c) {\n"
# (the head of the view's loop: a bare label, since nx2/poll.py puts the interrupt poll before each backward goto; with the
# poll after the label in C lifted before that)
VIEW_ANCHORS = ("L_804e5068:;\n", "L_804e5068:; A64_POLL(c);\n")
LIFE_CAS = ("{ uint64_t _a = c->x[13]; uint32_t _e = (uint32_t)c->x[11]; "
            "__atomic_compare_exchange_n((uint32_t *)A64_PTR(_a), &_e, (uint32_t)c->x[12], "
            "0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST); A64_MARK(_a, 4); c->x[11] = (uint64_t)_e; }")


def patch_life(source):
    start = source.find(LIFE_HEAD)
    if start < 0:
        return None
    end = source.find("\n}", start)
    if end < 0 or source[start:end].count(LIFE_CAS) != 2:
        return None
    if "hos_oot_hearts_enabled() &&" in source[start:end]:   # ((Triforce) made before: a lift patched again got the guard twice)
        return source
    # x19 is the actor. Confirm its type and life pointer before protecting this write.
    guard = ("    if ((uint32_t)c->x[12] < (uint32_t)c->x[11] && hos_oot_hearts_enabled() &&\n"
             "        hos_oot_is_player(c, c->x[19]) &&\n"
             "        c->x[13] == recomp_load64(c,c->x[19] + 7184) + 8)\n"
             "        c->x[12] = c->x[11];\n")
    body = source[start:end].replace(LIFE_CAS, guard + LIFE_CAS)
    return (source[:start] + body + source[end:]).replace(
        '#include "a64.h"\n', '#include "a64.h"\nextern int hos_oot_hearts_enabled(void);\n'
        'extern int hos_oot_is_player(Ctx *c, uint64_t actor);\n', 1)


def patch_movement(source):
    start = source.find(MOVE_HEAD)
    if start < 0:
        return None
    end = source.find("\n}", start)
    if end < 0 or source[start:end].count(MOVE_ANCHOR) != 1 or source[start:end].count(MOVE_MATRIX) != 1:
        return None
    bypass = ("    hos_oot_lift_player(c, c->x[19]);\n"
              + MOVE_ANCHOR)
    body = source[start:end].replace(MOVE_ANCHOR, bypass, 1).replace(
        MOVE_MATRIX, MOVE_MATRIX + "    hos_oot_flight_pose(c, c->x[19], c->x[25]);\n", 1)
    source = source[:start] + body + source[end:]
    return source.replace('#include "a64.h"\n', '#include "a64.h"\n'
                          'extern void hos_oot_lift_player(Ctx *c, uint64_t actor);\n'
                          'extern void hos_oot_flight_pose(Ctx *c, uint64_t actor, uint64_t matrix);\n', 1)


def patch_flight_rotation(source):
    start = source.find(WARP_HEAD)
    if start < 0:
        return None
    end = source.find("\n}", start)
    body = source[start:end]
    if end < 0 or body.count(WARP_ANCHOR) != 1:
        return None
    body = body.replace(WARP_ANCHOR, "    hos_oot_flight_rotation(c, c->x[0], c->x[1]);\n" + WARP_ANCHOR)
    return (source[:start] + body + source[end:]).replace(
        '#include "a64.h"\n', '#include "a64.h"\n'
        'extern void hos_oot_flight_rotation(Ctx *c, uint64_t controller, uint64_t matrix);\n', 1)


def patch_view(source):
    start = source.find(VIEW_HEAD)
    if start < 0:
        return None
    end = source.find("\n}", start)
    body = source[start:end]
    if end < 0:
        return None
    for anchor in VIEW_ANCHORS:
        if body.count(anchor) == 1:
            break
    else:
        return None
    body = body.replace(anchor, anchor + "    hos_oot_free_view(c, c->x[20]);\n")
    return (source[:start] + body + source[end:]).replace(
        '#include "a64.h"\n', '#include "a64.h"\nextern void hos_oot_free_view(Ctx *c, uint64_t view);\n', 1)

# Native mouse look (host/mouse_native.c): the player camera's update, f_80644c80 (a virtual method, the camera in x0), hands
# its camera to the host before anything else, on the game's thread, once a frame; with the menu's Mouse camera on the mouse's
# motion turns the camera's yaw (+0x1a4) and pitch (+0x18c) there, before the camera reads its input.
CAM_HEAD = "void f_80644c80(Ctx *__restrict A64_NOESC c) {\n"


def patch_mouse_camera(source):
    start = source.find(CAM_HEAD)
    if start < 0:
        return None
    if "hos_mouse_camera(c->x[0]);" in source:   # (made before: a lift patched again)
        return source
    at = start + len(CAM_HEAD)
    source = source[:at] + "    hos_mouse_camera(c->x[0]);   /* (nx2/oot_patches.py: native mouse look) */\n" + source[at:]
    return source.replace('#include "a64.h"\n', '#include "a64.h"\nextern void hos_mouse_camera(uint64_t camera);\n', 1)


MENU_FOCUS_HEAD = "void f_802ed660(Ctx *__restrict A64_NOESC c) {\n"


def patch_menu_focus(source):
    """f_802ed660, a menu screen's handler of a pane getting the focus (host/oot_menu.c), calls
    hos_oot_menu_focus first, with the screen, the pane and its caller's return address"""
    start = source.find(MENU_FOCUS_HEAD)
    if start < 0:
        return None
    if "hos_oot_menu_focus(c," in source:   # (made before: a lift patched again)
        return source
    at = start + len(MENU_FOCUS_HEAD)
    hook = "    hos_oot_menu_focus(c, c->x[0], c->x[1], c->x[30]);   /* (nx2/oot_patches.py: the menus' focus) */\n"
    return (source[:at] + hook + source[at:]).replace(
        '#include "a64.h"\n', '#include "a64.h"\nextern void hos_oot_menu_focus(Ctx *c, uint64_t screen, uint64_t pane, uint64_t lr);\n', 1)


MENU_TICK_HEAD = "void f_802f1380(Ctx *__restrict A64_NOESC c) {\n"


# ((Triforce) the button prompts changed while the game runs, host/prompts.c's live part) three hooks at the head of lifted
# functions: a text box's draw and its layout (its button codes rewritten), FreeType's glyph render (where the prompts' font is)
TEXT_DRAW_HEAD = "void f_8152b670(Ctx *__restrict A64_NOESC c) {\n"
TEXT_LAYOUT_HEAD = "void f_8152aec0(Ctx *__restrict A64_NOESC c) {\n"
GLYPH_HEAD = "void f_81680c60(Ctx *__restrict A64_NOESC c) {\n"


def _prompts_hook_head(source, head, call, decl):
    """call put first in the function that starts with head, once, and decl declared; None without the function"""
    start = source.find(head)
    if start < 0:
        return None
    if call.split("(")[0] + "(" in source:   # (made before: a lift patched again)
        return source
    at = start + len(head)
    return (source[:at] + call + source[at:]).replace('#include "a64.h"\n', '#include "a64.h"\n' + decl, 1)


def patch_text_draw(source):
    """f_8152b670, a text box's draw (x0 the box: each time the game shows it), calls hos_prompts_text_draw first with the box: the
    button prompts changed while the game runs, the box's codes for them rewritten and the box marked to be laid out again
    (host/prompts.c)"""
    return _prompts_hook_head(source, TEXT_DRAW_HEAD,
                              "    hos_prompts_text_draw(c->x[0]);   /* (nx2/oot_patches.py: the button prompts changed) */\n",
                              "extern void hos_prompts_text_draw(uint64_t box);\n")


def patch_text_layout(source):
    """f_8152aec0, a text box's layout (x0 the box: it lays its text out again when its status says so, at +8: bit 0x20000),
    calls hos_prompts_text_layout first with the box: the button prompts changed while the game runs, the box's codes for them
    rewritten and the box laid out again (host/prompts.c)"""
    return _prompts_hook_head(source, TEXT_LAYOUT_HEAD,
                              "    hos_prompts_text_layout(c->x[0]);   /* (nx2/oot_patches.py: the button prompts changed) */\n",
                              "extern void hos_prompts_text_layout(uint64_t box);\n")


def patch_glyph(source):
    """f_81680c60, FreeType's ft_smooth_render (x1 the glyph slot), calls hos_prompts_glyph first with the slot: where the game
    keeps the button prompts' font, for a change while it runs (host/prompts.c)"""
    return _prompts_hook_head(source, GLYPH_HEAD,
                              "    hos_prompts_glyph(c->x[1]);   /* (nx2/oot_patches.py: where the button prompts' font is) */\n",
                              "extern void hos_prompts_glyph(uint64_t slot);\n")


def patch_menu_tick(source):
    """f_802f1380, a menu screen's update (each frame, before the screen's UI controller: +56, its vtable's
    +16), calls hos_oot_menu_tick first with the screen: the game's menus' mouse (host/oot_menu.c)"""
    start = source.find(MENU_TICK_HEAD)
    if start < 0:
        return None
    if "hos_oot_menu_tick(c," in source:   # (made before: a lift patched again)
        return source
    at = start + len(MENU_TICK_HEAD)
    hook = "    hos_oot_menu_tick(c, c->x[0]);   /* (nx2/oot_patches.py: the menus' mouse) */\n"
    return (source[:at] + hook + source[at:]).replace(
        '#include "a64.h"\n', '#include "a64.h"\nextern void hos_oot_menu_tick(Ctx *c, uint64_t screen);\n', 1)


def patch_gameplay_hud_screen(source):
    """(Triforce) f_802f1380's body wrapped (after patch_menu_tick's hook) so host/hos_wide_ui.c hos_gameplay_hud_screen runs
    around each screen's update: the shared map's projection is scoped to the minimap's update there (HUD placement's
    Custom minimap), on every way out of it"""
    start = source.find(MENU_TICK_HEAD)
    if start < 0:
        return None
    if "hos_gameplay_hud_screen(c," in source:   # (made before: a lift patched again)
        return source
    end = source.find("\n}", start)
    if end < 0:
        return None
    end += 2
    # (the game's body beside its original entry, for the generated code's splitter and its guest local checks)
    body = source[start:end].replace(MENU_TICK_HEAD, "void gameplay_hud_update_game(Ctx *__restrict A64_NOESC c) {\n", 1)
    wrapper = (MENU_TICK_HEAD +
               "    void gameplay_hud_update_game(Ctx *__restrict A64_NOESC c);\n"
               "    hos_gameplay_hud_screen(c, gameplay_hud_update_game);\n}\n\n")
    return (source[:start] + wrapper + body + source[end:]).replace(
        '#include "a64.h"\n', '#include "a64.h"\nextern void hos_gameplay_hud_screen(Ctx *c, A64Fn update);\n', 1)


MOD_SIZE_CALL = "c->x[30] = 0x801b64e4ULL; f_836e3d30(c);\n"
MOD_SIZE_HOOK = ("    c->x[0] = hos_mods_table_size(c->x[0], recomp_load64(c, c->x[29] + 24));"
                 "   /* (nx2/oot_patches.py: room for the mods' files, host/mods.c) */\n")


def patch_mod_sizes(source):
    """((Triforce) 11-17) f_801b6340 asks the ResourceSizeTable (RESTBL, f_836e3d30: the CRC of the path, a binary search) how
    much memory a file's load needs; the file's resource heap is made that size (f_801b6840). A mod's file served instead of the
    game's (host/mods.c) can need more than the table gives it: a model with more materials and shapes than the original fails
    its gsys::ModelResource allocations, which the game does not check (the Dark Link mod's Deku Shield and Slingshot: a write
    to address 0 on loading a child save). The host raises the size for a mod's file to its real size and room beside it
    (hos_mods_table_size); the game's own files keep the table's"""
    if MOD_SIZE_CALL not in source:
        return source, 0
    if "hos_mods_table_size(" in source:   # (made before: a lift patched again)
        return source, 1
    out = source.replace(MOD_SIZE_CALL, MOD_SIZE_CALL + MOD_SIZE_HOOK, 1)
    out = out.replace('#include "a64.h"\n', '#include "a64.h"\nextern uint64_t hos_mods_table_size(uint64_t size, uint64_t path);\n', 1)
    return out, 1


TEXT_HEAD = "void f_80b1e140(Ctx *__restrict A64_NOESC c) {"
# (the letters' block: past the early returns, the auto-advance timer and the hidden / no-text checks; reached once a call)
TEXT_OLD = ("L_80b1e1b4:;\n"
            "    c->x[9]=recomp_load16(c,c->x[19] + 110);\n"
            "if ((uint32_t)c->x[9] == 0) { goto L_80b1e18c; }\n")
# (the same block in a build with interrupt polls: nx2/poll.py puts the poll before each backward goto, as a block)
TEXT_OLD_POLLED = TEXT_OLD.replace("{ goto L_80b1e18c; }", "{ { A64_POLL(c); goto L_80b1e18c; } }")
TEXT_ADD = ("    if (hos_text_scale != 1.0f) { float _t; uint32_t _u; memcpy(&_t,c->vreg[0],4); _t *= hos_text_scale; "
            "memcpy(&_u,&_t,4); a64_vset64(c->vreg[0],_u); }   /* (nx2/oot_patches.py: text speed) */\n")
TEXT_NEW = TEXT_OLD + TEXT_ADD


def patch_dynres(s):
    if OLD not in s:
        return None
    s = s.replace(OLD, NEW, 1)
    at = s.index(LABEL)
    scale = s.index(SCALE_OLD, at)
    s = s[:scale] + SCALE_NEW + s[scale + len(SCALE_OLD):]
    return s.replace('#include "a64.h"\n', '#include "a64.h"\n' + DECL, 1)


# The frame's real time in place of the nominal rate, for a Frame rate cap above 60 (host/nn_vi.c hos_frame_seconds_bits; 0, as
# at a cap of 60: the game's own divide, nothing changes). The engine has two places where its integer nominal rate (+0x2c8 of
# the graphics module) becomes a time step, both a float divide "base / nominal":
# - f_80706be0: the frame's step, base 60.0 (30.0 in the half-rate mode), added to the game clock (the double at
#   [x19+0xd58], in 1/60 s) and handed on as the frame's seconds;
# - f_83b6ea90: the global step (60.0 / nominal, a float in .data) the rest of the engine reads.
# The engine's own rate is 60 / <whole display intervals>, never above 60, and its controller puts 60 back over a higher value
# written from outside before either divide runs: above 60 fps every frame still stepped 1/60 s and the game ran fps / 60 times
# too fast. With the host's measured frame time the step is base * seconds, whatever the rate. hos_step_probe: f_80706be0's
# x19, which tells the host the hook is in this build and gives it the game clock for its log (HOS_FPS_LOG=1).
STEP_SITES = (("void f_80706be0(Ctx *__restrict A64_NOESC c) {\n", 8, "\n    hos_step_probe = c->x[19];"),
              ("void f_83b6ea90(Ctx *__restrict A64_NOESC c) {\n", 0, ""))
STEP_OLD = "    _v=a64_fpx_div32_div32(c,_a,_b);\n    a64_vset64(c->vreg[%d],_v);}"
STEP_HOOK = ("    _v=a64_fpx_div32_div32(c,_a,_b);\n"
             "    { const uint32_t _hs = hos_frame_seconds_bits; if (_hs) { float _base, _secs; uint32_t _w; memcpy(&_base,&_a,4); "
             "memcpy(&_secs,&_hs,4); _base *= _secs; memcpy(&_w,&_base,4); _v = _w; } }   /* (base * the frame's seconds: nx2/oot_patches.py) */\n"
             "    a64_vset64(c->vreg[%d],_v);}")
STEP_MARK = "hos_frame_seconds_bits; if (_hs)"   # (once per divide with the hook)
STEP_DECL = "extern volatile uint32_t hos_frame_seconds_bits;\nextern volatile uint64_t hos_step_probe;\n"


def patch_frame_seconds(s):
    """The host's frame time at the step divides of f_80706be0 and f_83b6ea90: (s, the sites patched here). A site whose
    function is not in the file, is patched already, or whose code differs (another game version) is left as it is."""
    done = 0
    for head_text, reg, extra in STEP_SITES:
        head = s.find(head_text)
        if head < 0:
            continue
        end = s.find("\nvoid f_", head + len(head_text))
        body = s[head:end if end >= 0 else len(s)]
        old, new = STEP_OLD % reg, STEP_HOOK % reg + extra
        if new in body or body.count(old) != 1 or body.count("a64_fpx_div32_div32") != 1:
            continue
        at = head + body.index(old)
        s = s[:at] + new + s[at + len(old):]
        done += 1
    if done and STEP_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + STEP_DECL, 1)
    return s, done


def unpatch_frame_seconds(s):
    """s without the hook, as the lift wrote it: for a lift where only one of the two divides was found (apply)"""
    for _, reg, extra in STEP_SITES:
        s = s.replace(STEP_HOOK % reg + extra, STEP_OLD % reg)
    return s if STEP_MARK in s else s.replace(STEP_DECL, "", 1)   # (a hook of another shape stays, with its declarations)


# A movie's frame count above a 60 cap. The game's movie player counts its updates while a movie plays (f_83b7c710: one more
# at +760 of the player each frame), and a cutscene that shows a movie takes that count as its timeline's frame (f_83b5ec10,
# f_83b5e9a0): the narration, the rumble and the cutscene's end are placed by it. The movie itself follows the clock, so above
# 60 fps those cues ran ahead of the picture, fps / 60 times too fast (issue 1742). The count now grows by the frames' time, as
# the game's clock does (hos_movie_frames, host/nn_vi.c: 1 as before while the host gives no frame time).
MOVIE_HEAD = "void f_83b7c710(Ctx *__restrict A64_NOESC c) {\n"
# (the load and the add alone: the store after them is rewritten by the page marks' pass, which runs after these edits)
MOVIE_OLD = ("    c->x[8]=recomp_load32(c,c->x[20] + 760);\n"
             "    { uint64_t _a=c->x[8], _b=1ULL; uint64_t _r=_a+_b; _r&=0xFFFFFFFFULL; c->x[8]=_r; }\n")
MOVIE_NEW = MOVIE_OLD.replace("_b=1ULL", "_b=hos_movie_frames(c->x[20])")
MOVIE_DECL = "uint32_t hos_movie_frames(uint64_t player);\n"


def patch_movie_frames(s):
    """The movie player's count by the frames' time; None when the file has no such function, s unchanged when the function is
    there but its code differs (another game version) or has the patch already."""
    head = s.find(MOVIE_HEAD)
    if head < 0:
        return None
    end = s.find("\nvoid f_", head + len(MOVIE_HEAD))
    body = s[head:end if end >= 0 else len(s)]
    if body.count(MOVIE_OLD) != 1:
        return s
    at = head + body.index(MOVIE_OLD)
    s = s[:at] + MOVIE_NEW + s[at + len(MOVIE_OLD):]
    return s if MOVIE_DECL in s else s.replace('#include "a64.h"\n', '#include "a64.h"\n' + MOVIE_DECL, 1)


# A looping animation one frame long (the frozen Zoras under the ice in adult Zora's Domain: start 0, end 1) is one pose. At the
# console's 60 fps the clock's step is 1 and each update lands on the same phase. Under a Frame rate cap above 60 the step is the
# frame's own time (0.36 at 165 fps), the phase moved by it each frame, and each frame drew another phase: the pose twitched.
# The time a skeleton is drawn at comes from two places, and both are patched to hos_loop_step / hos_loop_pose (host/loop_step.h):
# - f_802cfca0 advances the clock of each animation entry ([x20]: flags +0, time +4, speed +12, start +16, end +20) and copies it
#   to the skeleton's time. Its two advances multiply the step (vreg 8) by the definition's speed first: a loop of one frame or less
#   takes the step as whole frames, carried per entry; longer loops keep the fractional step.
# - f_80944aa0 writes the time the skeletons are drawn at (x22: the value +0, the range it is kept in +4, +8) from a clock of its
#   own that also moved by the fractional step: a range of one frame or less is drawn at its start, the phase of a clock that
#   moves in whole frames.
# A cap of 60 (hos_frame_seconds_bits 0) leaves both as the game has them.
LOOP_HEAD = "void f_802cfca0(Ctx *__restrict A64_NOESC c) {\n"
LOOP_MUL = ("    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[8],4);memcpy(&_b,c->vreg[%d],4);_z=(_a^_b)&0x80000000ULL;\n")
LOOP_SITES = (
    ("if (((c->x[9] >> 3) & 1)) { goto L_802d077c; }\n", 1),
    ("if (((c->x[9] >> 3) & 1)) { goto L_802d07f4; }\n", 0),
)
LOOP_MARK = "/* (nx2/oot_patches.py: a loop of one frame by whole frames) */"
LOOP_DECL = "extern uint32_t hos_loop_step(uint64_t at, uint32_t step_bits, uint32_t start_bits, uint32_t end_bits);\n"


def _loop_new(mul):
    return mul.replace("memcpy(&_a,c->vreg[8],4);",
                       "memcpy(&_a,c->vreg[8],4); _a=hos_loop_step(c->x[20], (uint32_t)_a, (uint32_t)recomp_load32(c,c->x[20] + 16), "
                       "(uint32_t)recomp_load32(c,c->x[20] + 20));   " + LOOP_MARK + "\n    ", 1)


def patch_loop_steps(s):
    """f_802cfca0's two clock advances take hos_loop_step's step: (s, how many of the two are in s with it, made now or before).
    A file without the function, or an advance whose code differs (another game version), is left as it is"""
    head = s.find(LOOP_HEAD)
    if head < 0:
        return s, 0
    end = s.find("\nvoid f_", head + len(LOOP_HEAD))
    end = end if end >= 0 else len(s)
    body = s[head:end]
    done = 0
    for before, reg in LOOP_SITES:
        old = before + LOOP_MUL % reg
        new = before + _loop_new(LOOP_MUL % reg)
        if body.count(new) == 1:
            done += 1
        elif body.count(old) == 1:
            body = body.replace(old, new, 1)
            done += 1
    s = s[:head] + body + s[end:]
    if done and LOOP_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + LOOP_DECL, 1)
    return s, done


POSE_HEAD = "void f_80944aa0(Ctx *__restrict A64_NOESC c) {\n"
POSE_OLD = "    { { uint64_t _v=0; memcpy(&_v,&c->vreg[0][0],4); recomp_store32(c,(c->x[22]+0ULL),_v); } }\n"
POSE_NEW = ("    { { uint64_t _v=0; memcpy(&_v,&c->vreg[0][0],4); _v=hos_loop_pose((uint32_t)_v, (uint32_t)recomp_load32(c,c->x[22] + 4), "
            "(uint32_t)recomp_load32(c,c->x[22] + 8));   /* (nx2/oot_patches.py: a loop of one frame by its start) */ "
            "recomp_store32(c,(c->x[22]+0ULL),_v); } }\n")
POSE_DECL = "extern uint32_t hos_loop_pose(uint32_t time_bits, uint32_t start_bits, uint32_t end_bits);\n"


def patch_loop_pose(s):
    """The one store f_80944aa0 makes of a skeleton's time (the call that wraps it into its range, then the store) through
    hos_loop_pose: (s, 1) when it is in s with it (made now or before); a file without the function, or one whose code
    differs, is left as it is"""
    head = s.find(POSE_HEAD)
    if head < 0:
        return s, 0
    end = s.find("\nvoid f_", head + len(POSE_HEAD))
    body = s[head:end if end >= 0 else len(s)]
    if body.count(POSE_NEW) == 1:
        return s, 1
    if body.count(POSE_OLD) != 1:
        return s, 0
    at = head + body.index(POSE_OLD)
    s = s[:at] + POSE_NEW + s[at + len(POSE_OLD):]
    if POSE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + POSE_DECL, 1)
    return s, 1


# Counters that add the frame step, or the step times a whole number, cut to whole frames (host/frame_whole.h). At 60 fps the step
# is 1; under a Frame rate cap above 60 it is the frame's own time, under 1 (0.42 at 144 fps), and the cut is 0 every frame:
# - f_80a87e50, the pick-up indicator above Link's head (a rupee, a Deku Stick): the count it shows (+864) moves toward the
#   wallet's (+860) by (int)(step * max(distance / 50, 1)) and the indicator fades when they meet. Cut to 0, it stayed at the old
#   count until a door or a talk replaced it (issue 1832).
# - f_800672e0, the water renderer: its ripple simulation runs (int)step times the water's substeps (+76 of the pass) each frame.
#   Cut to 0, the rings Link and the actors make in water stood still above 60 fps. Found by atk3001 for Lichii (zortos293/
#   Lichii#1152), as ported to Fritchii (Frizti/Fritchii d389685a4, 063dbb741): its remainder is kept per water object (x21).
#   Whole frames carried, a frame ran all its substeps or none (0 or 4 at 108 fps), and the rings stood still for a frame and
#   then jumped: the substeps are carried instead (WHOLE_TIMES), 2 or 3 every frame.
# - f_803edf70, the time of day: each frame it adds (int)(2 * step) game seconds (+60) to the seconds of the day (+40, a day of
#   86400, then the day count +44). Cut, it added 1 a frame below 120 fps (the day slower: 83% at 100) and 0 above 120, where
#   the clock stood still and the sun swung back and forth over the frozen hour.
# hos_frame_whole carries the fractions per counter while the frames' own time is the step, so each moves at the game's rate;
# otherwise it cuts as the game does. A site is added here once it is seen to misbehave in game. (A site's function, its code to
# replace, and the counter's address for its remainder.) A site of WHOLE_TIMES multiplies the whole frames by a whole number of
# substeps (the register it loaded them into): hos_frame_whole_times hands out the whole substeps and the register becomes 1.
WHOLE_SITES = (
    # (the cut alone, the function's one: the multiply before it is a64_fpx_hot_mul32_fma32 in a lift where the function is
    # among A64_HOT_FUNCS)
    ("void f_80a87e50(Ctx *__restrict A64_NOESC c) {@",
     "    c->x[12]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);@",
     "c->x[19] + 864"),
    # (the substeps' load and the cut, the function's one: x8 * x9 substeps follow)
    ("void f_800672e0(Ctx *__restrict A64_NOESC c) {@",
     "    c->x[8]=recomp_load32(c,c->x[19] + 76);@"
     "    c->x[9]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);@",
     "c->x[21]"),
    # (the cut with the store after it: the function cuts into x8 the same way once more, in the branch that sets
    #  the time from another source)
    ("void f_803edf70(Ctx *__restrict A64_NOESC c) {@",
     "    c->x[8]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);@"
     "    recomp_store32(c,c->x[19] + 60,c->x[8]);@",
     "c->x[19] + 60"),
)
WHOLE_SITES = tuple((h.replace("@", "\n"), o.replace("@", "\n"), k) for h, o, k in WHOLE_SITES)
WHOLE_MARK = "/* (the step's whole frames: nx2/oot_patches.py) */"
WHOLE_DECL = "extern uint32_t hos_frame_whole(uint64_t at, uint32_t amount_bits);\n"
WHOLE_TIMES_DECL = "extern uint32_t hos_frame_whole_times(uint64_t at, uint32_t amount_bits, uint32_t times);\n"
WHOLE_TIMES = {"void f_800672e0(Ctx *__restrict A64_NOESC c) {\n": "c->x[8]"}   # (the water's substeps)


def whole_new(old, key, times=None):
    """old with its cut to whole frames (the one recomp_fp_to_int) made hos_frame_whole's for the counter at key; with times
    (the register of the substeps it multiplies by), hos_frame_whole_times's whole substeps, and the register 1"""
    lines = old.split("\n")
    for i, line in enumerate(lines):
        if "recomp_fp_to_int(c->vreg[0][0]" in line:
            reg = line.split("=", 1)[0]
            if times:
                lines[i] = "%s=hos_frame_whole_times(%s, (uint32_t)c->vreg[0][0], (uint32_t)%s); %s=1;   %s" % (
                    reg, key, times.strip(), times.strip(), WHOLE_MARK)
            else:
                lines[i] = "%s=hos_frame_whole(%s, (uint32_t)c->vreg[0][0]);   %s" % (reg, key, WHOLE_MARK)
    return "\n".join(lines)


def patch_whole_frames(s):
    """The counters of WHOLE_SITES take hos_frame_whole's whole frames: (s, the sites patched here). A file without the function,
    one patched before, or one whose code differs (another game version) is left as it is. A site of WHOLE_TIMES that an earlier
    build patched with the whole frames alone (a work folder keeps its lift) takes the substeps now."""
    done = 0
    times_done = 0
    for head_text, old, key in WHOLE_SITES:
        head = s.find(head_text)
        if head < 0:
            continue
        end = s.find("\n}\n", head)
        body = s[head:end if end >= 0 else len(s)]
        times = WHOLE_TIMES.get(head_text)
        new = whole_new(old, key, times)
        if new in body:
            continue
        earlier = whole_new(old, key) if times else None
        if body.count(old) == 1:
            replaced = old
        elif earlier and body.count(earlier) == 1:
            replaced = earlier
        else:
            continue
        at = head + body.index(replaced)
        s = s[:at] + new + s[at + len(replaced):]
        done += 1
        times_done += bool(times)
    if done and WHOLE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + WHOLE_DECL, 1)
    if times_done and WHOLE_TIMES_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + WHOLE_TIMES_DECL, 1)
    return s, done


# Above a Frame rate cap of 60, three places that need whole 60 fps frames (host/oot_high_fps.h has why and the logic; at a cap of
# 60 the host hands back what the game computed):
# - the sound manager's job, f_80435300 (phase in w2; phase 0 loads the game step, [[slot]]+0x10, and hands it to the sound
#   engine): its head asks hos_oot_sound_gate whether to run now (60 Hz above 60 fps, the other phases following phase 0), and
#   the step it loads goes through hos_oot_sound_step (a whole one while the gate holds the job). After zortos293/Lichii PR #1289
#   (auz466), which does the same as a code patch for the emulator.
# - the music manager's update, f_83373400 (game::Bgm, run by that job, so at 60 Hz too): its own loads of the time object's step
#   (+16) and seconds (+24) go through hos_oot_sound_step and hos_oot_sound_seconds, so while the gate holds the job it counts a
#   whole step, not the frame's part of one (handed the part, its clock ran at 60 / fps of the real one). Its head takes the
#   change flags the gate held back (hos_oot_bgm_begin) and its four reads of the battle manager's change flags ([x26]+2200)
#   get them with the byte (hos_oot_bgm_flags): flags set for one frame the gate held are not lost (the battle music after a fight).
# - the physics solver's step count, set each update from the frame step in f_838ceb80 and f_838cfc10 (the same code in both):
#   hos_oot_solver_steps rounds it up instead of down, at least 1, so Link stays on moving platforms (issue 1798).
SOUND_HEAD = "void f_80435300(Ctx *__restrict A64_NOESC c) {\n"
SOUND_SLOT = "g_module_base + 0x80435000ULL + (int64_t)75927552"   # (the page of the step's pointer, whose +2192 holds it)
SOUND_OLD = ("    c->x[8]=" + SOUND_SLOT + ";\n"
             "    { uint64_t _r = ((uint64_t)0 | ((c->x[0]) << 0)); c->x[19] = _r; }\n"
             "    c->x[8]=recomp_load64(c,c->x[8] + 2192);\n"
             "    c->x[8]=recomp_load64(c,c->x[8] + 0);\n"
             "    { { uint64_t _v=recomp_load32(c,(c->x[8]+16ULL)); a64_vset64(c->vreg[0],_v); } }\n")
SOUND_NEW = SOUND_OLD.replace("uint64_t _v=recomp_load32(c,(c->x[8]+16ULL));",
                              "uint64_t _v=hos_oot_sound_step((uint32_t)recomp_load32(c,(c->x[8]+16ULL)));")
SOUND_GATE = ("    if (!hos_oot_sound_gate(c, (uint32_t)c->x[2], " + SOUND_SLOT + " + 2192)) return;"
              "   /* (nx2/oot_patches.py: the sound job at 60 Hz above 60 fps) */\n")
SOUND_DECL = "extern int hos_oot_sound_gate(Ctx *c, uint32_t phase, uint64_t slot);\nextern uint32_t hos_oot_sound_step(uint32_t step_bits);\n"
BGM_HEAD = "void f_83373400(Ctx *__restrict A64_NOESC c) {\n"
BGM_OLD = ("    { { uint64_t _v=recomp_load32(c,(c->x[8]+16ULL)); a64_vset64(c->vreg[8],_v); } }\n"
           "    { { uint64_t _v=recomp_load32(c,(c->x[8]+24ULL)); a64_vset64(c->vreg[9],_v); } }\n")
BGM_NEW = ("    { { uint64_t _v=hos_oot_sound_step((uint32_t)recomp_load32(c,(c->x[8]+16ULL))); a64_vset64(c->vreg[8],_v); } }"
           "   /* (nx2/oot_patches.py: the music manager's whole step above 60 fps) */\n"
           "    { { uint64_t _v=hos_oot_sound_seconds((uint32_t)recomp_load32(c,(c->x[8]+24ULL)), "
           "(uint32_t)recomp_load32(c,(c->x[8]+16ULL))); a64_vset64(c->vreg[9],_v); } }\n")
BGM_DECL = "extern uint32_t hos_oot_sound_step(uint32_t step_bits);\nextern uint32_t hos_oot_sound_seconds(uint32_t seconds_bits, uint32_t step_bits);\n"
BGM_FLAGS_OLD = "    c->x[8]=recomp_load8(c,c->x[26] + 2200);\n"   # (the update's four reads of the change flags)
BGM_FLAGS_NEW = ("    c->x[8]=hos_oot_bgm_flags(c->x[26] + 2200, recomp_load8(c,c->x[26] + 2200));"
                 "   /* (nx2/oot_patches.py: with the flags of frames the gate held) */\n")
BGM_FLAGS_HEAD = "    hos_oot_bgm_begin();   /* (nx2/oot_patches.py: the change flags held back since the last run) */\n"
BGM_FLAGS_DECL = "extern void hos_oot_bgm_begin(void);\nextern uint64_t hos_oot_bgm_flags(uint64_t at, uint64_t flags);\n"
SOLVER_HEADS = ("void f_838ceb80(Ctx *__restrict A64_NOESC c) {\n", "void f_838cfc10(Ctx *__restrict A64_NOESC c) {\n")
# (the cut of frame step * steps a frame + 0.001, then its store into the solver: vreg 0 the float cut, vreg 1 the steps a frame)
SOLVER_OLD = ("    c->x[1]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);\n"
              "    recomp_store32(c,c->x[0] + 712,c->x[1]);\n")
SOLVER_NEW = SOLVER_OLD.replace(
    "    recomp_store32(", "    c->x[1]=hos_oot_solver_steps((uint32_t)c->x[1], (uint32_t)c->vreg[0][0], (uint32_t)c->vreg[1][0]);"
    "   /* (nx2/oot_patches.py: solver steps rounded up above 60 fps) */\n    recomp_store32(", 1)
SOLVER_DECL = "extern uint32_t hos_oot_solver_steps(uint32_t game, uint32_t scaled_bits, uint32_t per_frame_bits);\n"
# A horse's jump state machine, f_82c59eb0 (s10 its step): while the horse gets ready to jump it sets the blend frames into its
# JumpReady animation each frame, and with a step under 1 (slow motion at 60 fps) it takes them from last frame's plus the step.
# Above 60 fps every step is under 1, the blend frames grew each frame, and Epona galloped through fences while her body went
# over them. Before the branch on its "step < 1" test (fcmp s10, 1.0; b.pl past the slow-motion branch), hos_oot_horse_whole_step
# sends a step that is the whole frame's (the time object's step, [[slot]]+0x10) past it too (host/oot_high_fps.h).
HORSE_HEAD = "void f_82c59eb0(Ctx *__restrict A64_NOESC c) {\n"
HORSE_TEST = "    a64_vset64(c->vreg[9],0x3f800000ULL);\n    { if (!a64_fcmp32(c,c->vreg[10],c->vreg[9])) "   # (its line goes on)
HORSE_BRANCH = "if (!c->n) { goto L_82c5ae48; }\n"
HORSE_SKIP = ("    if (hos_oot_horse_whole_step((uint32_t)c->vreg[10][0], " + SOUND_SLOT + " + 2192)) { goto L_82c5ae48; }"
              "   /* (nx2/oot_patches.py: a horse's jump blend above 60 fps) */\n")
HORSE_DECL = "extern int hos_oot_horse_whole_step(uint32_t step_bits, uint64_t slot);\n"
# A rigid body's update before the physics step, f_804f5030, on its path for a body driven to a target (x20 the controller, x23
# the body): the game sets the target (+0x3c) to the body's position plus this frame's move and asks for (target - position) /
# dt. Above 60 fps Havok's solve delivers only part of it (0.86 at 120 fps), the next target starts from where the body ended
# up, and Link's pull-up onto a ledge fell short: he slid back on the lip. Before the target is read,
# hos_oot_drive_target adds last update's shortfall to Link's (host/oot_high_fps.h). The path is in the function twice.
DRIVE_HEAD = "void f_804f5030(Ctx *__restrict A64_NOESC c) {\n"
# (two copies of that path, the body loaded into x23 or x24: the same type test, reached from different places)
DRIVE_REGS = (23, 24)
DRIVE_READ = ("    c->x[%d]=recomp_load64(c,c->x[20] + 240);\n"
              "    { uint64_t _b=c->x[20]; int64_t _o=60; { uint64_t _p0,_p1; recomp_ldp32(c,(_b+_o),&_p0,&_p1); "
              "a64_vset64(c->vreg[2],_p0); a64_vset64(c->vreg[1],_p1); }}\n"
              "    { { uint64_t _v=recomp_load32(c,(c->x[20]+68ULL)); a64_vset64(c->vreg[0],_v); } }\n")
DRIVE_CALL = ("    hos_oot_drive_target(c->x[20], c->x[%d], " + SOUND_SLOT + " + 2192);"
              "   /* (nx2/oot_patches.py: Link's driven body follows its target above 60 fps) */\n")
DRIVE_DECL = "extern void hos_oot_drive_target(uint64_t controller, uint64_t body, uint64_t slot);\n"
# A jump's takeoff speed (f_80b97d10: sqrt(2 g h) - g dt / 2 along the character's up, written to the vector its caller gave in x2,
# kept in x19): on a backflip Link's body gets it for one physics update, so above 60 fps his hop was lower (one shorter step of
# it) and a backflip down a slope took off twice. After its last store, hos_oot_jump_speed(the vector) keeps the speed for the
# takeoff's velocity (TAKEOFF_VELOCITY_* below; host/oot_high_fps.h oot_takeoff_rest_speed). x19 is c->x[19] where the lift
# keeps the function as the edits expect, x19_ in a lift with register locals.
TAKEOFF_HEAD = "void f_80b97d10(Ctx *__restrict A64_NOESC c) {\n"
TAKEOFF_STORE = "    {{ {{ uint64_t _v=0; memcpy(&_v,&c->vreg[2][0],4); recomp_store32(c,({x}+8ULL),_v); }} }}\n"
TAKEOFF_X19 = ("c->x[19]", "x19_")
TAKEOFF_CALL = "    hos_oot_jump_speed({x});   /* (nx2/oot_patches.py: a jump's takeoff above 60 fps) */\n"
TAKEOFF_DECL = "extern void hos_oot_jump_speed(uint64_t vec);\n"
# The takeoff's velocity: f_804f5030 hands Havok a body's velocity with the world's set-velocity call (its vtable +0x190, at
# 0x804f6694: x1 the body's id, x2 the linear velocity it reads, x19 the body's object), Link's takeoff speed on the takeoff's
# update. hos_oot_takeoff_velocity(the object, the velocity, the game's time object's slot) before the call gives a body the rest
# of a 60 fps takeoff step's rise on the next update when the game asks no vertical speed there (a backflip), above a 60 cap.
# f_804f5030 is kept as the edits expect (DRIVE_HEAD), so the call is written one way.
TAKEOFF_VELOCITY_SITE = "{ uint64_t _t = c->x[8]; c->x[30] = 0x804f6698ULL; A64_ICALL(c, _t); }\n"
TAKEOFF_VELOCITY_CALL = ("    hos_oot_takeoff_velocity(c->x[19], c->x[2], " + SOUND_SLOT + " + 2192);"
                         "   /* (nx2/oot_patches.py: a jump's takeoff above 60 fps) */\n")
TAKEOFF_VELOCITY_DECL = "extern void hos_oot_takeoff_velocity(uint64_t object, uint64_t velocity, uint64_t slot);\n"

# Below 60 fps, Havok cloth (Link's cap, romfs Phive/Cloth): the simulate operator's per-frame setup, f_81b3aa48, loads its step
# context's time (x22 + 8) and stores it with a substep's (+44, +48 of its frame data). The time is a 60th whatever the frame, so the
# cloth runs slow (0.3 of the clock at 18 fps: Link's cap swings out and settles slowly). hos_oot_cloth_seconds multiplies it by the
# game's frame step while that is over 1: the float f_83b6ea90 writes at 0x84d61fc8 (host/oot_high_fps.h).
CLOTH_HEAD = "void f_81b3aa48(Ctx *__restrict A64_NOESC c) {\n"
CLOTH_OLD = "    { { uint64_t _v=recomp_load64(c,(c->x[22]+8ULL)); a64_vset64(c->vreg[0],_v); } }\n"
CLOTH_NEW = ("    { { uint64_t _v=recomp_load64(c,(c->x[22]+8ULL)); _v=(_v&0xffffffff00000000ULL)|hos_oot_cloth_seconds((uint32_t)_v, "
             "(uint32_t)recomp_load32(c,g_module_base + 0x84d61fc8ULL)); a64_vset64(c->vreg[0],_v); } }"
             "   /* (nx2/oot_patches.py: the cloth's time below 60 fps) */\n")
CLOTH_DECL = "extern uint32_t hos_oot_cloth_seconds(uint32_t seconds_bits, uint32_t step_bits);\n"

# Above 60 fps (HOS_FPS_CLOTH_60=1), the cloth's solve job, f_81b47080 (run by the job runner f_8016b620, once a frame for each
# cloth near the camera), at most 60 times a second: hos_oot_cloth_solve says, from the game clock, whether this frame solves;
# a held frame returns at once with the job's own result (0), before its first line saves anything (host/oot_high_fps.h).
CLOTH_SOLVE_HEAD = "void f_81b47080(Ctx *__restrict A64_NOESC c) {\n"
CLOTH_SOLVE_OLD = ("    { uint64_t _b=c->x[31]; int64_t _o=-128; { uint64_t _v=0; memcpy(&_v,&c->vreg[10][0],8); "
                   "recomp_store64(c,(_b+_o),_v); } c->x[31]=_b+_o; }\n")
CLOTH_SOLVE_NEW = ("    if (!hos_oot_cloth_solve((uint32_t)recomp_load32(c,g_module_base + 0x84d61fc8ULL))) { c->x[0] = 0; return; }"
                   "   /* (nx2/oot_patches.py: the cloth's solves above 60 fps) */\n")
CLOTH_SOLVE_DECL = "extern int hos_oot_cloth_solve(uint32_t step_bits);\n"


# Three more places that go wrong with a frame step under one frame (host/oot_high_fps.h has why and the logic; at a cap of 60 the
# host hands back what the game computes). Found and fixed for this build by NX2navi (its recomp/patches-v111.txt, the sets
# ofollow, owater and orecord: main+0x13d704, +0x13a064, +0x389ac20; +0x3876014, +0x38827f8, +0x632cfc; +0x32926c8, +0x3293410,
# +0x3296b08, +0x3296da4; main is at 0x80020000 here), there as code words, here as hooks in the lifted C:
# - the character controller's three follow-surface updates compare the physics' inverse step with 100.0 and keep a tenth of
#   the floor's velocity above it: every update above 100 fps, so a moving platform slid out from under Link. The 100.0 comes
#   from hos_oot_floor_cut (100 / the frame's 60 fps frames while that is under one).
# - the two water managers and the interactive floors (the Deku Tree's ground webs) run seconds / (1/60 s), cut to whole,
#   fixed steps: none in an update shorter than 1/60 s, so the surfaces stood still above 60 fps. Before the cut the quotient
#   goes through hos_oot_sim_steps (x19 the object, each function's x0): the whole steps with the object's remainder kept.
# - the ocarina recorder's clock adds (unsigned)frame step at four places: 0 above 60 fps, so a recording lost its rests.
#   hos_oot_record_frames carries the fraction.
FLOOR_HEADS = ("void f_8015d490(Ctx *__restrict A64_NOESC c) {\n", "void f_80159dc0(Ctx *__restrict A64_NOESC c) {\n",
               "void f_838baa40(Ctx *__restrict A64_NOESC c) {\n")
# (mov w8, #0x42c80000; fmov s1, w8: the 100.0 of the compare that follows)
FLOOR_OLD = ("    c->x[8] = 0x42c80000ULL;\n    c->x[8] &= 0xFFFFFFFFULL;\n"
             "    { a64_vset64(c->vreg[1],0); memcpy(&c->vreg[1][0],&c->x[8],4); }\n")
FLOOR_NEW = FLOOR_OLD.replace("c->x[8] = 0x42c80000ULL;",
                              "c->x[8] = hos_oot_floor_cut();   /* (nx2/oot_patches.py: a floor's carry above 100 fps) */", 1)
FLOOR_DECL = "extern uint32_t hos_oot_floor_cut(void);\n"
# (a function and the register its cut goes to: fdiv s0, s8, s0 then fcvtzs w<n>, s0, the function's one cut of s0 into that register)
SIM_SITES = (("void f_83895f20(Ctx *__restrict A64_NOESC c) {\n", 8), ("void f_838a2660(Ctx *__restrict A64_NOESC c) {\n", 8),
             ("void f_80652cb0(Ctx *__restrict A64_NOESC c) {\n", 22))
SIM_OLD = "    c->x[%d]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);\n"
SIM_HOOK = ("    a64_vset64(c->vreg[0],hos_oot_sim_steps(c->x[19], (uint32_t)c->vreg[0][0]));"
            "   /* (nx2/oot_patches.py: fixed steps above 60 fps) */\n")
SIM_DECL = "extern uint32_t hos_oot_sim_steps(uint64_t object, uint32_t quotient_bits);\n"
# (a function and how many times it adds the step to the clock: fcvtzu w8, s0)
RECORD_SITES = (("void f_832b2690(Ctx *__restrict A64_NOESC c) {\n", 1), ("void f_832b32b0(Ctx *__restrict A64_NOESC c) {\n", 1),
                ("void f_832b6840(Ctx *__restrict A64_NOESC c) {\n", 2))
RECORD_OLD = "    c->x[8]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,0,3,c->fpcr,&c->fpsr);\n"
RECORD_NEW = ("    c->x[8]=hos_oot_record_frames((uint32_t)c->vreg[0][0]);"
              "   /* (nx2/oot_patches.py: the ocarina recorder's clock above 60 fps) */\n")
RECORD_DECL = "extern uint32_t hos_oot_record_frames(uint32_t step_bits);\n"
# ((Triforce, 11-18) #bug-tracker "Enemy Music not clearing in dungeon": above 60 fps the battle music kept playing after the last
# enemy was gone; at a cap of 60 it ended. Two places in Link's update f_804caa80 (x19 Link) take the time since one he keeps
# (the float [[x19+144]] less s0) times a constant of the game's (page +2952), cut to whole frames into x8, then step a small
# state of his by that count (against 8 and 4). Above 60 fps the time is under a frame every update, cut to 0, and the state
# never moved on, so the music that waits on it never ended. Found in the lab (a probe over every cut in the 40 functions that
# load the frame step: with all of them carried, then with these two alone, the music ended at 240 fps). A positive amount goes
# through hos_frame_whole (host/frame_whole.h: its fraction carried while the frames' own time is the step, the game's cut at a
# cap of 60), one remainder per place (the keys are ids, not fields: Link + 145 and + 147); a negative one keeps the game's cut.
# Each place is found by its own page constant, then the constant's load and the cut (a hot lift's multiply is
# a64_fpx_hot_*: any lines between).
BATTLE_HEAD = "void f_804caa80(Ctx *__restrict A64_NOESC c) {\n"
BATTLE_CUT = "    c->x[8]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);\n"
BATTLE_SITES = (("    c->x[8]=g_module_base + 0x804cb000ULL + (int64_t)60379136;\n", "c->x[19] + 145"),
                ("    c->x[8]=g_module_base + 0x804cd000ULL + (int64_t)60370944;\n", "c->x[19] + 147"))
BATTLE_LOAD = "    { { uint64_t _v=recomp_load32(c,(c->x[8]+2952ULL)); a64_vset64(c->vreg[1],_v); } }\n"
BATTLE_MARK = "/* (nx2/oot_patches.py: Link's state steps above 60 fps, the battle music's end) */"
BATTLE_NEW = ("    { const uint64_t _g=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);"
              " c->x[8]=((int32_t)(uint32_t)c->vreg[0][0] > 0) ? hos_frame_whole(%s, (uint32_t)c->vreg[0][0]) : _g; }   "
              + BATTLE_MARK + "\n")


def _function(s, head_text):
    """(start, end) of the function whose head is head_text, or None"""
    head = s.find(head_text)
    if head < 0:
        return None
    end = s.find("\nvoid f_", head + len(head_text))
    return head, end if end >= 0 else len(s)


def patch_sound_job(s):
    """The sound job's gate and step: (s, 1) when the job is in s with them (made now or before), (s, 0) when it is not here or
    its code differs (another game version: left as it is)"""
    at = _function(s, SOUND_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(SOUND_NEW) == 1 and body.count(SOUND_GATE) == 1:
        return s, 1
    if body.count(SOUND_OLD) != 1 or SOUND_GATE in body:
        return s, 0
    body = body.replace(SOUND_OLD, SOUND_NEW, 1)
    body = SOUND_HEAD + SOUND_GATE + body[len(SOUND_HEAD):]
    s = s[:head] + body + s[end:]
    if SOUND_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SOUND_DECL, 1)
    return s, 1


def patch_bgm_time(s):
    """The music manager's step and seconds through the host: (s, 1) when its update is in s with them (made now or before),
    (s, 0) when it is not here or its code differs (another game version: left as it is)"""
    at = _function(s, BGM_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(BGM_NEW) == 1:
        return s, 1
    if body.count(BGM_OLD) != 1:
        return s, 0
    s = s[:head] + body.replace(BGM_OLD, BGM_NEW, 1) + s[end:]
    if BGM_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + BGM_DECL, 1)
    return s, 1


def patch_bgm_flags(s):
    """The music manager's change flags with the ones the gate held back: (s, 1) when its update is in s with them (made now
    or before), (s, 0) when it is not here or its code differs (another game version: left as it is)"""
    at = _function(s, BGM_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(BGM_FLAGS_NEW) == 4 and body.count(BGM_FLAGS_HEAD) == 1:
        return s, 1
    if body.count(BGM_FLAGS_OLD) != 4 or BGM_FLAGS_HEAD in body:
        return s, 0
    body = BGM_HEAD + BGM_FLAGS_HEAD + body[len(BGM_HEAD):].replace(BGM_FLAGS_OLD, BGM_FLAGS_NEW)
    s = s[:head] + body + s[end:]
    if BGM_FLAGS_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + BGM_FLAGS_DECL, 1)
    return s, 1


def patch_solver_steps(s):
    """The solver step count's two places: (s, how many of them are in s with the hook, made now or before)"""
    done = 0
    for head_text in SOLVER_HEADS:
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        if body.count(SOLVER_NEW) == 1:
            done += 1
        elif body.count(SOLVER_OLD) == 1:
            s = s[:head] + body.replace(SOLVER_OLD, SOLVER_NEW, 1) + s[end:]
            done += 1
    if done and SOLVER_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SOLVER_DECL, 1)
    return s, done


def patch_horse_jump(s):
    """A horse's jump state machine's step test with the whole-frame one before it: (s, 1) when it is in s with it (made now or
    before), (s, 0) when it is not here or its code differs (another game version: left as it is)"""
    at = _function(s, HORSE_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(HORSE_SKIP + HORSE_BRANCH) == 1:
        return s, 1
    if body.count(HORSE_TEST) != 1 or HORSE_SKIP in body:
        return s, 0
    line_end = body.find("\n", body.index(HORSE_TEST) + len(HORSE_TEST))
    if line_end < 0 or not body.startswith(HORSE_BRANCH, line_end + 1):
        return s, 0
    body = body[:line_end + 1] + HORSE_SKIP + body[line_end + 1:]
    s = s[:head] + body + s[end:]
    if HORSE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + HORSE_DECL, 1)
    return s, 1


def patch_drive_target(s):
    """Link's driven body's target through the host before f_804f5030 reads it, at both copies of the path: (s, how many of them
    are in s with it, made now or before); a copy whose body load and target reads are not found once, as written, is left"""
    at = _function(s, DRIVE_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    done = 0
    for reg in DRIVE_REGS:
        read, call = DRIVE_READ % reg, DRIVE_CALL % reg
        load = read.index("    { uint64_t _b")
        if body.count(read[:load] + call + read[load:]) == 1:
            done += 1
            continue
        if body.count(read) != 1:
            continue
        i = body.index(read) + load
        body = body[:i] + call + body[i:]
        done += 1
    s = s[:head] + body + s[end:]
    if done and DRIVE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + DRIVE_DECL, 1)
    return s, done


def patch_jump_speed(s):
    """A jump's takeoff speed to the host after f_80b97d10's last store: (s, 1) when f_80b97d10 is in s with it (made now or
    before), (s, 0) when it is not here or its store of the vector's last part is not found once, as written"""
    at = _function(s, TAKEOFF_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    # ((Triforce) the store is the last of a group whose page marks are shared (a64_lift.mark_groups, made after these patches):
    # a finished lift, patched again by hand, spells it recomp_store32_sp, with the group's A64_MARK line after it)
    for x, marked in ((x, m) for x in TAKEOFF_X19 for m in (0, 1)):
        store = TAKEOFF_STORE.format(x=x)
        if marked:
            store = store.replace("recomp_store32(", "recomp_store32_sp(", 1)
        made = store + TAKEOFF_CALL.format(x=x)
        if body.count(made) == 1:
            return s, 1
        if body.count(store) != 1:
            continue
        s = s[:head] + body.replace(store, made, 1) + s[end:]
        if TAKEOFF_DECL not in s:
            s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + TAKEOFF_DECL, 1)
        return s, 1
    return s, 0


def patch_takeoff_velocity(s):
    """A body's velocity through the host before f_804f5030's set-velocity call: (s, 1) when f_804f5030 is in s with it (made now
    or before), (s, 0) when it is not here or the call is not found once, as written"""
    at = _function(s, DRIVE_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(TAKEOFF_VELOCITY_CALL + TAKEOFF_VELOCITY_SITE) == 1:
        return s, 1
    if body.count(TAKEOFF_VELOCITY_SITE) != 1 or TAKEOFF_VELOCITY_CALL in body:
        return s, 0
    s = s[:head] + body.replace(TAKEOFF_VELOCITY_SITE, TAKEOFF_VELOCITY_CALL + TAKEOFF_VELOCITY_SITE, 1) + s[end:]
    if TAKEOFF_VELOCITY_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + TAKEOFF_VELOCITY_DECL, 1)
    return s, 1


def patch_cloth_time(s):
    """The cloth setup's time through the host: (s, 1) when f_81b3aa48 is in s with it (made now or before), (s, 0) when it is
    not here or its code differs (another game version: left as it is)"""
    at = _function(s, CLOTH_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(CLOTH_NEW) == 1:
        return s, 1
    if body.count(CLOTH_OLD) != 1:
        return s, 0
    s = s[:head] + body.replace(CLOTH_OLD, CLOTH_NEW, 1) + s[end:]
    if CLOTH_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + CLOTH_DECL, 1)
    return s, 1


def patch_cloth_solve(s):
    """The cloth's solve job gated through the host: (s, 1) when f_81b47080 is in s with it (made now or before), (s, 0) when it
    is not here or its first line differs (another game version: left as it is)"""
    at = _function(s, CLOTH_SOLVE_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(CLOTH_SOLVE_NEW) == 1:
        return s, 1
    if body.count(CLOTH_SOLVE_OLD) != 1:
        return s, 0
    first = body.index(CLOTH_SOLVE_OLD)
    if body[:first].count("\n") > 2:   # (the first store is the job's own first line, after the head and a hint)
        return s, 0
    s = s[:head] + body[:first] + CLOTH_SOLVE_NEW + body[first:] + s[end:]
    if CLOTH_SOLVE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + CLOTH_SOLVE_DECL, 1)
    return s, 1


# f_8263e8e0, the steering update: after applying a turn it clamps the saved rate (+36) to the turn's magnitude times
# the step. The turn was already scaled by the step, so a rate-limited update keeps rate * step squared: above 60 fps
# Gohma can keep circling the ceiling without reaching her next point. Convert the turn back to a rate for
# both bounds when 0 < step < 1. At a step of 1 or more, and for invalid steps, keep the game's arithmetic unchanged.
TURN_RATE_HEAD = "void f_8263e8e0(Ctx *__restrict A64_NOESC c) {\n"
TURN_RATE_OLD = """    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[0],4);memcpy(&_b,c->vreg[1],4);_z=(_a^_b)&0x80000000ULL;
    _v=a64_fpx_mul32_fma32(c,_a,_b,_z);
    a64_vset64(c->vreg[1],_v);}
    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[0],4);memcpy(&_b,c->vreg[8],4);_z=(_a^_b)&0x80000000ULL;
    _v=a64_fpx_mul32_fma32(c,_a,_b,_z);
    a64_vset64(c->vreg[0],_v);}
"""
# v8 holds the positive step throughout both instructions. Its binary32 bits test the interval without a host FP
# comparison (or changing the guest's flags); division still uses the guest FP helper, as the original multiply does.
TURN_RATE_NEW = TURN_RATE_OLD.replace(
    "    _v=a64_fpx_mul32_fma32(c,_a,_b,_z);",
    "    if ((uint32_t)c->vreg[8][0] > 0 && (uint32_t)c->vreg[8][0] < 0x3f800000u)\n"
    "        _v=a64_fpx_div32_div32(c,_a,_b);\n"
    "    else _v=a64_fpx_mul32_fma32(c,_a,_b,_z);")


def patch_turn_rate(s):
    """The saved steering rate's two bounds: (s, 1) when both are patched, now or before; a changed anchor is left alone."""
    at = _function(s, TURN_RATE_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(TURN_RATE_NEW) == 1:
        return s, 1
    if body.count(TURN_RATE_OLD) != 1:
        return s, 0
    return s[:head] + body.replace(TURN_RATE_OLD, TURN_RATE_NEW, 1) + s[end:], 1


# A song's playback after the ocarina (the ocarina's state machine f_8019bad0 runs f_832b2af0 in state 5, the song just played,
# and f_832b2dc0 in state 6, its other melody playback): each update while the melody plays it calls f_832b7b50, whether the
# note flag the sound engine sets for one of its runs at each of the melody's notes is set, and goes on to the next note when
# it is. Above 60 fps the sound job runs at 60 Hz and the playback went on two or three notes at each (host/oot_high_fps.h has
# why and the rule). After each call its result goes through hos_oot_song_cue; the call carries its return address, so it is
# once in its function.
SONG_CUE_SITES = (("void f_832b2af0(Ctx *__restrict A64_NOESC c) {\n", "c->x[30] = 0x832b2c84ULL; f_832b7b50(c);\n"),
                  ("void f_832b2dc0(Ctx *__restrict A64_NOESC c) {\n", "c->x[30] = 0x832b2ed4ULL; f_832b7b50(c);\n"))
SONG_CUE_NEW = ("    c->x[0] = hos_oot_song_cue(%d, c->x[0]);"
                "   /* (nx2/oot_patches.py: the note flag once a note above 60 fps) */\n")
SONG_CUE_DECL = "extern uint64_t hos_oot_song_cue(uint32_t site, uint64_t game);\n"


def patch_song_cue(s):
    """The song playbacks' note flag through the host: (s, how many of the two calls are in s with it, made now or before);
    a call not found once in its function is left alone"""
    done = 0
    for site, (head_text, call) in enumerate(SONG_CUE_SITES):
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        new = call + SONG_CUE_NEW % site
        if body.count(new) == 1:
            done += 1
        elif body.count(call) == 1:
            s = s[:head] + body.replace(call, new, 1) + s[end:]
            done += 1
    if done and SONG_CUE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SONG_CUE_DECL, 1)
    return s, done


def patch_floor_carry(s):
    """The follow-surface updates' compare: (s, how many of the three are in s with the hook, made now or before)"""
    done = 0
    for head_text in FLOOR_HEADS:
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        if body.count(FLOOR_NEW) == 1:
            done += 1
        elif body.count(FLOOR_OLD) == 1:
            s = s[:head] + body.replace(FLOOR_OLD, FLOOR_NEW, 1) + s[end:]
            done += 1
    if done and FLOOR_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + FLOOR_DECL, 1)
    return s, done


def patch_sim_steps(s):
    """The height-field surfaces' fixed steps: (s, how many of the three places are in s with the hook, made now or before)"""
    done = 0
    for head_text, reg in SIM_SITES:
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        old = SIM_OLD % reg
        if body.count(SIM_HOOK + old) == 1:
            done += 1
        elif body.count(old) == 1 and SIM_HOOK not in body:
            s = s[:head] + body.replace(old, SIM_HOOK + old, 1) + s[end:]
            done += 1
    if done and SIM_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SIM_DECL, 1)
    return s, done


def patch_record_clock(s):
    """The ocarina recorder's clock: (s, how many of its four adds are in s with the hook, made now or before). A function
    whose adds are not as many as RECORD_SITES says (another game version) is left as it is."""
    done = 0
    for head_text, count in RECORD_SITES:
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        if body.count(RECORD_NEW) == count and RECORD_OLD not in body:
            done += count
        elif body.count(RECORD_OLD) == count and RECORD_NEW not in body:
            s = s[:head] + body.replace(RECORD_OLD, RECORD_NEW) + s[end:]
            done += count
    if done and RECORD_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + RECORD_DECL, 1)
    return s, done


def patch_battle_steps(s):
    """Link's two state steps of BATTLE_SITES with hos_frame_whole's whole frames: (s, how many are in s with it, made now or
    before). A place not found exactly once (another game version, or a lift with other code there) is left as it is."""
    at = _function(s, BATTLE_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    done = 0
    for anchor, key in BATTLE_SITES:
        new = BATTLE_NEW % key
        if new in body:
            done += 1
            continue
        found = [m for m in re.finditer(re.escape(anchor) + r"(?:[^\n]*\n){0,6}?" + re.escape(BATTLE_LOAD)
                                        + r"(?:[^\n]*\n){0,4}?" + re.escape(BATTLE_CUT), body)]
        if len(found) != 1:
            continue
        m = found[0]
        cut_at = m.end() - len(BATTLE_CUT)
        body = body[:cut_at] + new + body[m.end():]
        done += 1
    s = s[:head] + body + s[end:]
    if done and WHOLE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + WHOLE_DECL, 1)
    return s, done


# The sprint button (host/oot_sprint.h has the rules, host/oot_sprint.c the game's addresses; after NX2navi's set "sprint").
# Link sprints while his input flags hold the dash input (bit 4), which the game sets only out of a roll. Two functions load
# those flags and test the bit: his movement update f_804caa80 (to start the sprint and to keep it), and the update of his
# stance and camera f_80c225d0 (the low byte). After each load the host gets the flags and gives them back, with the bit
# while the button's sprint is on. With the Sprint button row off the call returns what it got.
SPRINT_LINK_HEAD = "void f_804caa80(Ctx *__restrict A64_NOESC c) {\n"
SPRINT_LINK_OLD = ("    c->x[10]=recomp_load64(c,c->x[19] + 80);\n"
                   "    c->x[9]=recomp_load32(c,c->x[19] + 44);\n"
                   "    c->x[10]=recomp_load64(c,c->x[10] + 0);\n")
SPRINT_LINK_ADD = "    c->x[10]=hos_oot_sprint_link(c,c->x[19],c->x[10]);   /* (nx2/oot_patches.py: the sprint button) */\n"
SPRINT_STANCE_HEAD = "void f_80c225d0(Ctx *__restrict A64_NOESC c) {\n"
SPRINT_STANCE_OLD = ("    c->x[8]=recomp_load64(c,c->x[19] + 80);\n"
                     "    c->x[8]=recomp_load8(c,c->x[8] + 0);\n"
                     "if (((c->x[8] >> 4) & 1)) { goto L_80c27f54; }\n")
SPRINT_STANCE_NEW = ("    c->x[8]=recomp_load64(c,c->x[19] + 80);\n"
                     "    c->x[8]=recomp_load8(c,c->x[8] + 0);\n"
                     "    c->x[8]=hos_oot_sprint_stance(c,c->x[19],c->x[8]);   /* (nx2/oot_patches.py: the sprint button) */\n"
                     "if (((c->x[8] >> 4) & 1)) { goto L_80c27f54; }\n")
SPRINT_DECL = ("extern uint64_t hos_oot_sprint_link(Ctx *c, uint64_t link, uint64_t flags);\n"
               "extern uint64_t hos_oot_sprint_stance(Ctx *c, uint64_t link, uint64_t flags);\n")


def patch_sprint(s):
    """The sprint button's two calls: (s, how many of the two are in s, made now or before). A function whose code differs
    (another game version) is left as it is."""
    done = 0
    for head_text, old, new in ((SPRINT_LINK_HEAD, SPRINT_LINK_OLD, SPRINT_LINK_OLD + SPRINT_LINK_ADD),
                                (SPRINT_STANCE_HEAD, SPRINT_STANCE_OLD, SPRINT_STANCE_NEW)):
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        if body.count(new) == 1:
            done += 1
        elif body.count(old) == 1:
            s = s[:head] + body.replace(old, new) + s[end:]
            done += 1
    if done and SPRINT_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SPRINT_DECL, 1)
    return s, done


# (Triforce) The host's zstd decoder (host/host_zstd.h has what the two functions are and the rules; HOS_HOST_ZSTD, off unless
# set). The game's own zstd, linked into main: f_8010b380 (main+0xeb380) is ZSTD_decompressMultiFrame, f_80115c80 (main+0xf5c80)
# the stream feed its loading threads decode through. At the head of each the host is asked first: it answers the call (x0 the
# result, the function returns) or says 0 and the game's code runs as it is. hos_host_zstd is 0 once the switch was read as off,
# and the call is no longer made. A switch at run time, so that it takes no new translation to turn on or off.
# Only the supported build's: the heads are found by address, and by lines only these two functions have (their shape below), so
# a function of that name with other code (another game version, a changed lift) is left as it is.
# (Triforce) The shapes are matched with the store marks' spellings taken out (_unmarked, below). The page marks of a group of
# stores (a64_lift.mark_groups) are made after these patches (nx2/chunks.py edit_c): a store of a group becomes
# recomp_storeN_sp( and an A64_MARK line follows the group. The lift as it stands on disk has them, these patches see the text
# before them. The stream feed's begin stores (+48 and +0 through x19) are such a group: its shape, read from the lift on disk,
# was never in the text the patch saw, and every build said "found at 1 of 2 places" (the stream feed left out). The lines are
# written as the text is before the marks, the text the patch sees (tests/test_host_zstd.py holds them to that).
ZSTD_SITES = (
    ("void f_8010b380(Ctx *__restrict A64_NOESC c) {\n", "hos_zstd_multiframe",
     # (the eighth argument kept and tested, and the dictionary read from a DDict's +8 and +16)
     ("    recomp_store64_sp(c,c->x[31] + 104,c->x[7]);\nif (c->x[7] != 0) { goto L_8010fd78; }\n",
      "L_8010fd78:;\n    c->x[8]=recomp_load64(c,c->x[31] + 104);\n"
      "    { uint64_t _b=c->x[8]; int64_t _o=8; { uint64_t _p0,_p1; recomp_ldp64(c,(_b+_o),&_p0,&_p1); c->x[5]=_p0; c->x[6]=_p1; } }\n")),
    ("void f_80115c80(Ctx *__restrict A64_NOESC c) {\n", "hos_zstd_stream",
     # (the phase read from the state, the "done" result, the error code asked of zstd, and the stores of a begin. (Triforce)
     # And every field host/host_zstd.h reads or writes, at its offset: the output and its room (+8, +16) read in phase 2, the
     # DCtx's "bytes expected next" (HZ_DCTX_EXPECTED, 28776) read first there, the workspace (+24) read at the begin before
     # the content size goes to +20; the DCtx to +48 and the phase to +0 at its end)
     ("    c->x[8]=recomp_load8(c,c->x[0] + 0);\n",
      "    c->x[0] = 0xfffffffdULL;\n",
      "c->x[30] = 0x8011629cULL; f_80d5ba00(c);\n",
      "    c->x[22]=recomp_load64(c,c->x[21] + 28776);\n",
      "    c->x[23]=recomp_load64(c,c->x[19] + 8);\n"
      "    { uint64_t _r = (uint64_t)(int64_t)(int32_t)recomp_load32(c,c->x[19] + 16); c->x[2] = _r; }\n",
      "    c->x[21]=recomp_load64(c,c->x[19] + 24);\n    recomp_store32(c,c->x[19] + 20,c->x[8]);\n",
      "    recomp_store64(c,c->x[19] + 48,c->x[21]);\n    recomp_store8(c,c->x[19] + 0,c->x[8]);\n")),
)
ZSTD_HOOK = "    if (hos_host_zstd && %s(c)) return;   /* (nx2/oot_patches.py: the host's zstd decoder, HOS_HOST_ZSTD) */\n"
ZSTD_DECL = ("extern volatile int hos_host_zstd;\nextern int hos_zstd_multiframe(Ctx *c);\n"
             "extern int hos_zstd_stream(Ctx *c);\n")
# (a64_lift.MG_MARK's line, and the _sp spelling of a marked store: mark_groups_lines, stack_stores, frame_stores)
MARK_LINE = re.compile(r"^    A64_MARK\(\(c->x\[\d+\] \+ \(uint64_t\)\(int64_t\)\(-?\d+\)\), \d+\);\n", re.M)
MARK_SP = re.compile(r"\brecomp_(store8|store16|store32|store64|stp32|stp64)_sp\(")


def _unmarked(text):
    """(Triforce) text without the store marks' spellings: a group's A64_MARK lines out, recomp_storeN_sp( as recomp_storeN(.
    The code's shape alone, the same before a64_lift.mark_groups and after it (a second run over a finished lift), and with
    A64_MARK_EACH, A64_MARK_STACK or A64_MARK_FRAME at lift time. They change only where a store's page is marked, never what
    the guest's code does, so a shape can count on everything else"""
    return MARK_SP.sub(r"recomp_\1(", MARK_LINE.sub("", text))


def patch_host_zstd(s):
    """The host decoder's two calls: (s, how many of the two heads are in s with their call, made now or before). A function
    whose code is not the decoder's (another game version) is left as it is."""
    done = 0
    for head_text, name, shape in ZSTD_SITES:
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        hook = ZSTD_HOOK % name
        if body.startswith(head_text + hook):
            done += 1
        elif hook not in body:
            plain = _unmarked(body)
            if all(plain.count(_unmarked(line)) == 1 for line in shape):
                s = s[:head] + head_text + hook + body[len(head_text):] + s[end:]
                done += 1
    if done and ZSTD_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + ZSTD_DECL, 1)
    return s, done


def patch_text_speed(s):
    """The scale at the head of the letters' block of f_80b1e140; None when the file has no such function, s unchanged when the
    function is there but its code differs (another game version)."""
    head = s.find(TEXT_HEAD)
    if head < 0:
        return None
    end = s.find("\nvoid f_", head + len(TEXT_HEAD))
    body = s[head:end if end >= 0 else len(s)]
    for old in (TEXT_OLD_POLLED, TEXT_OLD):   # (with the interrupt poll before the block's backward goto, or without: --no-polls)
        if old + TEXT_ADD in body:   # (applied already: a second run)
            return s
        if body.count(old) == 1:
            break
    else:
        return s
    if body.count("goto L_80b1e1b4;") != 1:
        return s
    at = head + body.index(old)
    s = s[:at] + old + TEXT_ADD + s[at + len(old):]
    return s.replace('#include "a64.h"\n', '#include "a64.h"\n' + TEXT_DECL, 1)


# (local, RenoDX port) The scene's colour target, "agl::RenderDisplay(color)": the game picks engine format 26 (R11G11B10F) or 44
# (RGBA16F) at main+0x65234c (0x8067234c; RenoDX's addon.cpp names the place for build e0f3ccfa). RenoDX's tone mapping wants
# RGBA16F, whose values may be negative, with HDR Native: host/nn_vi.c hos_scene_rgba16f says when. The other choice of that
# csel is 44 already, so both become 44 then; the UNORM branch at main+0x6525b0 is left alone.
RGBA16F_DECL = "int hos_scene_rgba16f(void);\n"
RGBA16F_OLD = ("    c->x[9] = 0x1aULL;\n    c->x[9] &= 0xFFFFFFFFULL;\n"
               "    { uint64_t _r = (!c->z) ? c->x[10] : c->x[9]; _r &= 0xFFFFFFFFULL; c->x[9] = _r; }\nL_80672354:;")
RGBA16F_NEW = RGBA16F_OLD.replace("c->x[9] = 0x1aULL;", "c->x[9] = hos_scene_rgba16f() ? 0x2cULL : 0x1aULL;", 1)


def patch_scene_format(s):
    if RGBA16F_OLD not in s:
        return None
    return s.replace(RGBA16F_OLD, RGBA16F_NEW, 1).replace('#include "a64.h"\n', '#include "a64.h"\n' + RGBA16F_DECL, 1)


# (from TomShafford/Hookshot 55d68e8cd6 and 65c1998222) f_804566e0's two calls of f_80522050, the GPU memory a model's material
# block is made with, made through host/oot_heap_retry.c hos_oot_gpu_alloc, which calls the game's own and tries a full heap's
# failure again in the heap's parents. f_80522050's other callers stay as they are.
GPU_ALLOC_SITES = (0x80456f1c, 0x80457098)   # (the calls' return addresses)
GPU_ALLOC_OLD = "c->x[30] = %#xULL; f_80522050(c);"
GPU_ALLOC_NEW = "c->x[30] = %#xULL; hos_oot_gpu_alloc(c, f_80522050);   /* (nx2/oot_patches.py: host/oot_heap_retry.c) */"
GPU_ALLOC_DECL = "void hos_oot_gpu_alloc(Ctx *A64_NOESC c, A64Fn game);\n"
# f_804566e0's tryAllocs of the CPU buffers at its MatBlock's +200 (its bump allocator's memory) and +168, each sized for the
# model (x0 the heap, x1 the size, x2 the alignment): a null result tried in the heap's parents (hos_oot_heap_retry)
HEAP_ALLOC_SITES = (0x80456910, 0x80456da4)
HEAP_ALLOC_OLD = "{ uint64_t _t = c->x[8]; c->x[30] = %#xULL; A64_ICALL(c, _t); }\n"
HEAP_ALLOC_NEW = ("{ const uint64_t _hh = c->x[0], _hn = c->x[1], _ha = c->x[2];   /* (nx2/oot_patches.py: host/oot_heap_retry.c) */\n"
                  "  if (hos_oot_heap_refuse()) c->x[0] = 0;\n"
                  "  else { uint64_t _t = c->x[8]; c->x[30] = %#xULL; A64_ICALL(c, _t); }\n"
                  "  if (!c->x[0]) hos_oot_heap_retry(c, _hh, _hn, _ha, %#xULL); }\n")
HEAP_ALLOC_DECL = "int hos_oot_heap_refuse(void);\nvoid hos_oot_heap_retry(Ctx *c, uint64_t heap, uint64_t size, uint64_t align, uint64_t lr);\n"


def patch_heap_retry(s):
    """The four places above in one file's text: (text, [GPU sites, CPU sites] made now or found made). apply() wants
    [2, 2] over the whole lift and warns otherwise"""
    found = [0, 0]
    decls = []
    for kind, sites, old, new, decl in ((0, GPU_ALLOC_SITES, GPU_ALLOC_OLD, GPU_ALLOC_NEW, GPU_ALLOC_DECL),
                                        (1, HEAP_ALLOC_SITES, HEAP_ALLOC_OLD, HEAP_ALLOC_NEW, HEAP_ALLOC_DECL)):
        for lr in sites:
            o, n = old % lr, (new % lr if kind == 0 else new % (lr, lr))
            if n in s:
                found[kind] += 1
            elif s.count(o) == 1 and s.count('#include "a64.h"\n') == 1:
                s = s.replace(o, n, 1)
                found[kind] += 1
                if decl not in decls:
                    decls.append(decl)
    for decl in decls:
        if decl not in s:
            s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + decl, 1)
    return s, found


# ((Triforce) 11-19) f_807da3f0, the handler of the game's "aglTextureDataMgr::Compaction" thread, calls the compaction's step
# (f_807da480: with the compaction idle it plans, and starts a cycle that moves a texture's data in the game's heap) at one
# place, for each message that asks. That call is made through host/oot_tex_compact.c hos_oot_tex_compact, which calls the
# game's own, counts the cycles started and holds them to a pace when HOS_OOT_TEX_COMPACT_MS says so (unset: as shipped).
# f_807da480's other callers, the game's own waits for a compaction, stay as they are.
TEX_COMPACT_OLD = "c->x[30] = 0x807da430ULL; f_807da480(c);"   # (the call's return address: this one place)
TEX_COMPACT_NEW = "c->x[30] = 0x807da430ULL; hos_oot_tex_compact(c, f_807da480);   /* (nx2/oot_patches.py: host/oot_tex_compact.c) */"
TEX_COMPACT_DECL = "void hos_oot_tex_compact(Ctx *A64_NOESC c, A64Fn game);\n"


def patch_tex_compact(s):
    """The call above in one file's text: (text, 1 when made now or found made). apply() wants 1 over the whole lift"""
    if TEX_COMPACT_NEW in s:
        return s, 1
    if s.count(TEX_COMPACT_OLD) != 1 or s.count('#include "a64.h"\n') != 1:
        return s, 0
    s = s.replace(TEX_COMPACT_OLD, TEX_COMPACT_NEW, 1)
    if TEX_COMPACT_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + TEX_COMPACT_DECL, 1)
    return s, 1


# ((Triforce) f_80797240, the game's texture data manager's step, runs every frame: with no compaction round asked for (+776)
# and bit 1 of +960 set, it asks for one and sends the compaction thread the message, so a round could start every frame. The
# ask's test also asks the host (host/oot_tex_compact.c hos_oot_tex_compact_due: at most once a second, HOS_OOT_TEX_ASK_MS);
# a round held back is asked for again at the next step.
TEX_ASK_HEAD = "void f_80797240(Ctx *__restrict A64_NOESC c) {\n"
TEX_ASK_OLD = "    c->x[8]=recomp_load8(c,c->x[19] + 960);\nif (!((c->x[8] >> 1) & 1)) { goto L_80797288; }"
TEX_ASK_NEW = ("    c->x[8]=recomp_load8(c,c->x[19] + 960);\nif (!((c->x[8] >> 1) & 1) || !hos_oot_tex_compact_due()) { goto L_80797288; }"
               "   /* (nx2/oot_patches.py: host/oot_tex_compact.c) */")
TEX_ASK_DECL = "int hos_oot_tex_compact_due(void);\n"


def patch_tex_ask(s):
    """The ask's test above in one file's text: (text, 1 when made now or found made). apply() wants 1 over the whole lift"""
    at = _function(s, TEX_ASK_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(TEX_ASK_NEW) == 1:
        return s, 1
    if body.count(TEX_ASK_OLD) != 1 or s.count('#include "a64.h"\n') != 1:
        return s, 0
    s = s[:head] + body.replace(TEX_ASK_OLD, TEX_ASK_NEW, 1) + s[end:]
    if TEX_ASK_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + TEX_ASK_DECL, 1)
    return s, 1


# ((Triforce, 11-21, the performance audit's GAME-05, after Source B's) f_802640a0 (the game's 0x80264100 is in it) sizes a
# character's or an object's shadow map: it reads the side once (ldr w10, [x21, #0x4e8]) before it asks for the texture, and
# its later uses read the same register. That one read goes through the host, which rounds it up to a multiple of 64
# (host/oot_shadow_step.h; HOS_OOT_SHADOW_STEP). The lifter writes a register as c->x[n] or, in a function whose registers
# it keeps in locals, as xn_: both forms are looked for.
SHADOW_STEP_HEAD = "void f_802640a0(Ctx *__restrict A64_NOESC c) {\n"
SHADOW_STEP_FORMS = (("c->x[10]=recomp_load32(c,c->x[21] + 1256);",
                      "c->x[10]=hos_oot_shadow_side(recomp_load32(c,c->x[21] + 1256));"),
                     ("x10_=recomp_load32(c,x21_ + 1256);",
                      "x10_=hos_oot_shadow_side(recomp_load32(c,x21_ + 1256));"))
SHADOW_STEP_MARK = "   /* (nx2/oot_patches.py: a shadow map's side in steps, host/oot_shadow_step.h) */"
SHADOW_STEP_DECL = "extern uint32_t hos_oot_shadow_side(uint32_t side);\n"


# ((Triforce) 11-24) The neighbouring map the OptimizeChangeBank thread preloads, kept while the game's choice only flickers
# (host/oot_ocb_hold.h has why). f_832b9880 is the preload manager's update: at 0x832b9dc8 the unit it chose is in w21 (bit 31:
# none) and the manager in x19; from there it asks for that unit and lets the others go. The choice goes through the host
# first. The supported build's lift only (apply): the host reads the manager as that build lays it out, and checks the
# layout (and the build) again in the game before each read; a mismatch there gives the game's own choice.
OCBH_HEAD = "void f_832b9880(Ctx *__restrict A64_NOESC c) {\n"
OCBH_LABEL = "L_832b9dc8:;\n"
OCBH_RE = re.compile(r"L_832b9dc8:;\nif \(\(\((x21_|c->x\[21\]) >> 31\) & 1\)\) \{ goto L_832b9e0c; \}\n")
OCBH_MARK = "/* (nx2/oot_patches.py: HOS_OCB_HOLD_MS, the preloaded neighbour kept while the choice flickers) */"
OCBH_DECL = "extern uint64_t hos_oot_ocb_pick(Ctx *c, uint64_t mgr, uint64_t chosen);\n"


def patch_ocb_hold(s):
    """The preload manager's choice of a neighbouring map through the host: (s, 1) when its update is in s with it (made now
    or before), (s, 0) when it is not here or its code differs (another game version: left as it is)"""
    at = _function(s, OCBH_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(OCBH_MARK) == 1:
        return s, 1
    found = OCBH_RE.findall(body)
    if len(found) != 1 or OCBH_MARK in body:
        return s, 0
    w21 = found[0]
    x19 = "c->x[19]"
    if w21 == "x21_":
        # (the registers as locals: the manager is x19's local, which the function keeps up to date and c->x[19] need not be.
        # A function without that local on its first line is not the code this patch knows: left as it is, and apply's
        # warning says so)
        if not re.search(r"\bx19_ = c->x\[19\]", body[:body.find("\n", len(OCBH_HEAD)) + 1]):
            return s, 0
        x19 = "x19_"
    call = "    %s = hos_oot_ocb_pick(c, %s, %s);   %s\n" % (w21, x19, w21, OCBH_MARK)
    body = OCBH_RE.sub(lambda m: OCBH_LABEL + call + m.group(0)[len(OCBH_LABEL):], body, count=1)
    s = s[:head] + body + s[end:]
    if OCBH_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + OCBH_DECL, 1)
    return s, 1


def patch_shadow_step(s):
    """The shadow map's side through the host: (text, 1) when the function is in s with it (made now or before), (s, 0) when
    the function is not here or its code differs (another game version: left as it is)"""
    at = _function(s, SHADOW_STEP_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    for old, new in SHADOW_STEP_FORMS:
        if body.count(new + SHADOW_STEP_MARK) == 1:
            return s, 1
        if body.count(old) == 1 and s.count('#include "a64.h"\n') == 1:
            s = s[:head] + body.replace(old, new + SHADOW_STEP_MARK, 1) + s[end:]
            if SHADOW_STEP_DECL not in s:
                s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SHADOW_STEP_DECL, 1)
            return s, 1
    return s, 0


# ((Triforce) 11-24) The Graphics tab's Shadow resolution (host/oot_shadow.c). f_80492370 sizes the sun's shadow cascades each
# frame: at 0x804929ec it takes the size from the shadow object's table by quality level (1600 at the level the game runs),
# scales it, rounds it up to a multiple of 8 into w23 (add w8, w9, #7; and w23, w8, #~7) and stores it as the cascades' width
# and height at the object's +0xe0 (x19 the object). Right after the rounding the size goes through the host, which raises
# it to the row's 2200 or 3072 for the sun's object only; Game's, the default, leaves it the game's.
SHADOW_RES_HEAD = "void f_80492370(Ctx *__restrict A64_NOESC c) {\n"
SHADOW_RES_RE = re.compile(r"L_804929ec:;[^\n]*\n"
                           r"    \{ uint64_t _a=(?:c->x\[9\]|x9_), _b=7ULL; [^\n]*\n"
                           r"    \{ uint64_t _r = (?:c->x\[8\]|x8_) & 0xfffffff8ULL; _r &= 0xFFFFFFFFULL; (c->x\[23\]|x23_) = _r; \}\n")
SHADOW_RES_MARK = "   /* (nx2/oot_patches.py: the sun's shadow resolution, host/oot_shadow.c) */"
SHADOW_RES_DECL = "extern uint64_t hos_oot_shadow_size(Ctx *c, uint64_t shadow, uint64_t rounded);\n"


def patch_shadow_res(s):
    """The sun's cascades' size through the host: (s, 1) when the function is in s with it (made now or before), (s, 0) when
    the function is not here or its code differs (another game version: left as it is)"""
    at = _function(s, SHADOW_RES_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(SHADOW_RES_MARK) == 1:
        return s, 1
    found = SHADOW_RES_RE.findall(body)
    if len(found) != 1 or s.count('#include "a64.h"\n') != 1:
        return s, 0
    w23 = found[0]
    x19 = "c->x[19]" if w23 == "c->x[23]" else "x19_"
    if x19 == "x19_" and not re.search(r"\bx19_\b", body):
        return s, 0
    call = "    %s = hos_oot_shadow_size(c, %s, %s);%s\n" % (w23, x19, w23, SHADOW_RES_MARK)
    body = SHADOW_RES_RE.sub(lambda m: m.group(0) + call, body, count=1)
    s = s[:head] + body + s[end:]
    if SHADOW_RES_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SHADOW_RES_DECL, 1)
    return s, 1


# ((Triforce) 11-24) Steady sun shadows near Link on Shadow resolution Highest (host/oot_shadow_fit.c has why and what). The game
# refits its sun cascades every frame: f_80733120 builds a cascade's light basis (its call of f_80733620, which returns to
# 0x8073318c, x19 the cascade), then f_80733be0 fits the tightest box around the cascade's slice of the view in that basis;
# at 0x80733efc (ldp s7, s6, [x21]), where its two modes meet (the other, from 0x80734dfc, loads w9 and comes back there), the
# slice's bounds are in s5/s4 (min/max x) and s2/s3 (min/max y), x20 the cascade, before the projection is made from them.
# Two calls: after the basis, the sun's cascade 0 gets a basis that does not follow the camera; at the meeting point, its
# bounds become a square of steady size on whole texels. Below Highest (and with HOS_SHADOW_STABLE=0) the host changes
# nothing. Only the forms with the registers in c (the hooks read and write the vector registers there) are hooked.
SHADOW_BASIS_HEAD = "void f_80733120(Ctx *__restrict A64_NOESC c) {\n"
SHADOW_BASIS_RE = re.compile(r"c->x\[30\] = 0x8073318cULL; f_80733620\(c\);\nL_8073318c:;(?: A64_POLL\(c\);)?\n")
SHADOW_BASIS_MARK = "   /* (nx2/oot_patches.py: the sun's nearest cascade, a world-fixed basis) */"
SHADOW_BASIS_CALL = "    hos_shadow_fit_basis(c, c->x[19]);" + SHADOW_BASIS_MARK + "\n"
SHADOW_BOX_HEAD = "void f_80733be0(Ctx *__restrict A64_NOESC c) {\n"
SHADOW_BOX_RE = re.compile(r"L_80733efc:;(?: A64_POLL\(c\);)?\n"
                           r"    \{ uint64_t _b=c->x\[21\]; int64_t _o=0; \{ uint64_t _p0,_p1; recomp_ldp32\(c,\(_b\+_o\),&_p0,&_p1\); "
                           r"a64_vset64\(c->vreg\[7\],_p0\); a64_vset64\(c->vreg\[6\],_p1\); \}\}\n")
SHADOW_BOX_REJOIN = "L_80734dfc:;\n    c->x[9]=recomp_load8(c,c->x[20] + 1556);\n"
SHADOW_BOX_MARK = "   /* (nx2/oot_patches.py: the sun's nearest cascade, a steady square on whole texels) */"
_SHADOW_BOX_REGS = ((0, 5), (1, 4), (2, 2), (3, 3))   # (b[i], s register): min x, max x, min y, max y
SHADOW_BOX_CALL = ("    { float _b[4]; "
                   + "".join("memcpy(&_b[%d], c->vreg[%d], 4); " % r for r in _SHADOW_BOX_REGS)
                   + "if (hos_shadow_fit_box(c, c->x[20], _b)) { "
                   + "".join("{ uint32_t _u; memcpy(&_u, &_b[%d], 4); a64_vset64(c->vreg[%d], _u); } " % r for r in _SHADOW_BOX_REGS)
                   + "} }" + SHADOW_BOX_MARK + "\n")
SHADOW_FIT_DECL = ("extern void hos_shadow_fit_basis(Ctx *c, uint64_t cascade);\n"
                   "extern int hos_shadow_fit_box(Ctx *c, uint64_t cascade, float b[4]);\n")


def patch_shadow_fit(s):
    """The sun's nearest cascade's fit through the host: (s, n) with n the sites in s with their calls (made now or before:
    the basis's, the box's), 0 when neither function is here or their code differs (another game version: left as it is)"""
    found = 0
    for head_text, pattern, mark, call, check in ((SHADOW_BASIS_HEAD, SHADOW_BASIS_RE, SHADOW_BASIS_MARK, SHADOW_BASIS_CALL, None),
                                                  (SHADOW_BOX_HEAD, SHADOW_BOX_RE, SHADOW_BOX_MARK, SHADOW_BOX_CALL, SHADOW_BOX_REJOIN)):
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        if body.count(mark) == 1:
            found += 1
            continue
        if len(pattern.findall(body)) != 1 or (check and body.count(check) != 1) or s.count('#include "a64.h"\n') != 1:
            continue
        body = pattern.sub(lambda m: m.group(0) + call, body, count=1)
        s = s[:head] + body + s[end:]
        if SHADOW_FIT_DECL not in s:
            s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SHADOW_FIT_DECL, 1)
        found += 1
    return s, found


# (Triforce) The more rows of how the game plays (gpu/vk/vk_menu.cpp, vk_api.h's options 200 and on): each a call of the host
# in the supported build's function, which answers with the game's own value while its row is at its default.
#
# Field of view (host/oot_fov.c). The camera update f_804e48c0 (the function the free camera's call is in) loads the camera's
# vertical angle ([x19 + 0x13c], at 0x804e52f8) into s0 in the straight line under its label L_804e52d0, halves it into s8,
# and writes the angle and the half angle's sine, cosine and tangent into the projection (x20's +160 to +172). Right after
# that load the host gets the camera (x19) and scales s0 for the view of play; the camera's own angle is not written.
FOV_HEAD = VIEW_HEAD
FOV_LABEL = "L_804e52d0:;\n"
FOV_LOAD = "    { { uint64_t _v=recomp_load32(c,(c->x[19]+316ULL)); a64_vset64(c->vreg[0],_v); } }\n"
FOV_NEXT = "    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[0],4);memcpy(&_b,c->vreg[1],4);"   # (the half angle: s8 = s0 * s1)
FOV_HOOK = "    hos_oot_fov(c, c->x[19]);   /* (nx2/oot_patches.py: the Field of view row) */\n"
FOV_DECL = "extern void hos_oot_fov(Ctx *c, uint64_t camera);\n"


# Text size (host/oot_text_size.c). In the letters' block of f_80b1e140 (TEXT_OLD above: reached once a step of a text pane that
# shows text), after the Text speed row's scale, the host gets the LetterAnimControl (x19) and scales its pane's text. A call
# of its own, not part of the Text speed line, so that either is found made without the other.
TEXT_SIZE_HOOK = "    hos_oot_text_pane(c, c->x[19]);   /* (nx2/oot_patches.py: the Text size row; x19 the LetterAnimControl) */\n"
TEXT_SIZE_DECL = "extern void hos_oot_text_pane(Ctx *c, uint64_t anim);\n"


def patch_text_size(s):
    """The Text size row's call: (s, 1) when f_80b1e140 is in s with it (made now or before), (s, 0) when the function is not
    here or its code differs (another game version: left as it is)"""
    at = _function(s, TEXT_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if TEXT_SIZE_HOOK in body:
        return s, int(body.count(TEXT_SIZE_HOOK) == 1)
    if body.count("goto L_80b1e1b4;") != 1:
        return s, 0
    # (after the Text speed row's line where it is there, else at the block's head: with the poll or without, as TEXT_OLD)
    for anchor in (TEXT_OLD_POLLED + TEXT_ADD, TEXT_OLD + TEXT_ADD, TEXT_OLD_POLLED, TEXT_OLD):
        if body.count(anchor) == 1:
            break
    else:
        return s, 0
    at = head + body.index(anchor) + len(anchor)
    s = s[:at] + TEXT_SIZE_HOOK + s[at:]
    if TEXT_SIZE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + TEXT_SIZE_DECL, 1)
    return s, 1


# Camera centering (host/mouse_native.c hos_disable_camera_centering; the Controls tab's row). In the player camera's update
# f_80644c80, state 3's yaw follow: past the authored heading override (the branch to 0x806492c4), the block at 0x8064720c
# makes a heading from Link's movement and eases the yaw (+0x1a4) towards it. With the row Off that block is skipped: x25 gets
# the parameter base that path gives it (x26) and the code goes on where the other yaw paths join, at 0x80645ad8. The stick's
# turn (state 4), the game's own recentre (state 2), the authored overrides, the pitch and the collision stay as they are.
CAM_FOLLOW_ANCHOR = "L_8064720c:;\nif (!c->z) { goto L_806492c4; }\n"
CAM_FOLLOW_JOIN = "L_80645ad8:;\n"
CAM_FOLLOW_HOOK = ("    if (hos_disable_camera_centering()) { c->x[25] = c->x[26]; A64_POLL(c); goto L_80645ad8; }"
                   "   /* (nx2/oot_patches.py: the Camera centering row) */\n")
CAM_FOLLOW_DECL = "extern int hos_disable_camera_centering(void);\n"


def patch_camera_centering(s):
    """The Camera centering row's test: (s, 1) when f_80644c80 is in s with it (made now or before), (s, 0) when the function
    is not here or its code differs (another game version: left as it is)"""
    at = _function(s, CAM_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(CAM_FOLLOW_ANCHOR) != 1 or body.count(CAM_FOLLOW_JOIN) != 1:
        return s, 0
    if CAM_FOLLOW_HOOK in body:
        return s, int(body.count(CAM_FOLLOW_ANCHOR + CAM_FOLLOW_HOOK) == 1)
    at = head + body.index(CAM_FOLLOW_ANCHOR) + len(CAM_FOLLOW_ANCHOR)
    s = s[:at] + CAM_FOLLOW_HOOK + s[at:]
    if CAM_FOLLOW_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + CAM_FOLLOW_DECL, 1)
    return s, 1


# Damage taken (host/oot_damage.c; the System tab's row). f_804bd8c0 writes an actor's life with two compare-and-swaps
# (LIFE_CAS, where the heart protection's guard is): the first takes a hit off (x10 the life now, x9 the hit, never below 0:
# x12 = x10 - x9, kept within 0 and the most the actor can have, x11 = x10), the second adds a healing. Before the first, and
# after the heart protection's guard, the host gets Link's life, the game's new life and the whole hit, and answers with the
# life at the row's share of the hit. The call is made only while the row is not Normal (hos_oot_damage_scaled), for a write
# that lowers Link's own life; healing is the second write, which has no call.
DAMAGE_SUB = ("    { uint64_t _a=c->x[10],_b=((uint64_t)(uint32_t)(((uint32_t)(c->x[9])) << 0)),_r=_a-_b; _r&=0xFFFFFFFFULL; "
              "c->x[12]=_r; }\n")
DAMAGE_GUARD = ("    if ((uint32_t)c->x[12] < (uint32_t)c->x[11] && hos_oot_damage_scaled() &&\n"
                "        hos_oot_is_player(c, c->x[19]) &&\n"
                "        c->x[13] == recomp_load64(c,c->x[19] + 7184) + 8)   /* (nx2/oot_patches.py: the Damage taken row) */\n"
                "        c->x[12] = hos_oot_damage((uint32_t)c->x[11], (uint32_t)c->x[12], (uint32_t)c->x[9]);\n")
DAMAGE_DECL = ("extern int hos_oot_damage_scaled(void);\n"
               "extern uint32_t hos_oot_damage(uint32_t old, uint32_t next, uint32_t hit);\n"
               "extern int hos_oot_is_player(Ctx *c, uint64_t actor);\n")


def patch_damage(s):
    """The Damage taken row's call before the life write that takes a hit off: (s, 1) when f_804bd8c0 is in s with it (made
    now or before), (s, 0) when the function is not here or its code differs (another game version: left as it is)"""
    at = _function(s, LIFE_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(LIFE_CAS) != 2:
        return s, 0
    cas = body.index(LIFE_CAS)   # (the first of the two: the hit's)
    if body.count(DAMAGE_GUARD):   # (made before: once, before the hit's write, nothing but guards between the two)
        at = body.index(DAMAGE_GUARD)
        return s, int(body.count(DAMAGE_GUARD) == 1 and at < cas and _straight(body[at:cas]))
    label = body.rfind(":;\n", 0, cas)
    if label < 0 or body[label:cas].count(DAMAGE_SUB) != 1 or "goto " in body[label:cas]:   # (x12 = x10 - x9 in the CAS's own straight line)
        return s, 0
    s = s[:head + cas] + DAMAGE_GUARD + s[head + cas:]
    if DAMAGE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + DAMAGE_DECL, 1)
    return s, 1


# Skip opening (host/oot_opening.c; the System tab's row), the supported build's three functions: an event's request
# (SeqOneShotRequestEvent, f_80d9a820), a timeline's start (f_83b5bfb0) and the events' skip query (IsEventSkipedMostRecent,
# f_80de6cb0). Each asks the host at its head: the request is watched and always sent; the opening's two movies are not
# started and its skip query is answered yes, while one of the opening's requests is the current one. With the row Off the
# host answers 0 at once and each function runs as it is.
OPENING_SITES = (
    ("void f_80d9a820(Ctx *__restrict A64_NOESC c) {\n",
     "    hos_oot_opening(c, 0);   /* (nx2/oot_patches.py: the Skip opening row, an event's request) */\n"),
    ("void f_83b5bfb0(Ctx *__restrict A64_NOESC c) {\n",
     "    if (hos_oot_opening(c, 1)) return;   /* (nx2/oot_patches.py: the Skip opening row, the opening's movies) */\n"),
    ("void f_80de6cb0(Ctx *__restrict A64_NOESC c) {\n",
     "    if (hos_oot_opening(c, 2)) return;   /* (nx2/oot_patches.py: the Skip opening row, the opening's skip edge) */\n"),
)
OPENING_DECL = "extern int hos_oot_opening(Ctx *c, int mode);\n"


def patch_opening(s):
    """The Skip opening row's calls: (s, how many of the three functions are in s with their call, made now or before)"""
    done = 0
    for head, line in OPENING_SITES:
        if s.count(head) != 1:
            continue
        if head + line not in s:
            if line in s:   # (elsewhere than at its function's head: not ours to judge)
                continue
            s = s.replace(head, head + line, 1)
        done += 1
    if done and OPENING_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + OPENING_DECL, 1)
    return s, done


# Autosave (host/oot_autosave.c; the System tab's row), the supported build's function: f_80bc72d0 asks the save manager for a
# save (x1 the reason, x2 the mode; its answer in x0, bit 0 "queued"). At its head the host is asked first: with the row Off
# and the request one of a crossing's autosaves it answers 1, x0 is 0 ("not queued") and the function returns; otherwise
# (always, with the row On) it answers 0 and the function runs as it is.
AUTOSAVE_HEAD = "void f_80bc72d0(Ctx *__restrict A64_NOESC c) {\n"
AUTOSAVE_HOOK = "    if (hos_oot_save_request(c)) return;   /* (nx2/oot_patches.py: the Autosave row) */\n"
AUTOSAVE_DECL = "extern int hos_oot_save_request(Ctx *c);\n"


def patch_autosave(s):
    """The Autosave row's call: (s, 1) when f_80bc72d0 is in s with it at its head (made now or before), else (s, 0)"""
    if s.count(AUTOSAVE_HEAD) != 1:
        return s, 0
    if AUTOSAVE_HEAD + AUTOSAVE_HOOK in s:
        return s, 1
    if AUTOSAVE_HOOK in s:
        return s, 0
    s = s.replace(AUTOSAVE_HEAD, AUTOSAVE_HEAD + AUTOSAVE_HOOK, 1)
    if AUTOSAVE_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + AUTOSAVE_DECL, 1)
    return s, 1


# Movement speed (the Debug tab's tool, host/hos_main.c hos_oot_cct_speed): a character controller's forward speed (s0), on its
# way to *(controller+40)+472, which the physics step moves the body by with its collisions. The host scales it for Link's
# controller while the tool is above 1x. Four places set it: f_809552f0, the move Link's own walk, run and swim go through (a
# direction at x1, the speed in metres a frame), at its two uses of the setter, each right after it took the controller into
# x0; the setter itself, f_80559df0 (the controller's vtable +0x70); and f_80964bf0, which takes the CCT component and inlines
# that setter (OneShotPhysicsCctSetForwardSpeedMpf and others). The first inlines the setter too, so no speed is scaled twice.
# At 1x, the default (and always with the Debug tools off), the host holds no controller and each call returns at once.
SPEED_HOOK = ("    hos_oot_cct_speed(c, c->x[0], %d);   /* (nx2/oot_patches.py: the Movement speed tool; x0 the controller, s0 the speed, "
              "in metres a %s) */\n")
SPEED_PLACES = (   # (the function's head, the text in it the call follows, and 1 when s0 is a second's speed, 0 a frame's)
    ("void f_809552f0(Ctx *__restrict A64_NOESC c) {\n", "L_80955424:;\n    c->x[0]=recomp_load64(c,c->x[8] + 8);\n", 0),
    ("void f_809552f0(Ctx *__restrict A64_NOESC c) {\n", "L_809554dc:;\n    c->x[0]=recomp_load64(c,c->x[8] + 8);\n", 0),
    ("void f_80559df0(Ctx *__restrict A64_NOESC c) {\n", "void f_80559df0(Ctx *__restrict A64_NOESC c) {\n", 1),
    ("void f_80964bf0(Ctx *__restrict A64_NOESC c) {\n",
     "void f_80964bf0(Ctx *__restrict A64_NOESC c) {\n    c->x[0]=recomp_load64(c,c->x[0] + 8);\n", 1),
)
SPEED_DECL = "extern void hos_oot_cct_speed(Ctx *c, uint64_t controller, int per_second);\n"


def patch_cct_speed(s):
    """The Movement speed tool's calls: (s, how many of the four places are in s with their call, made now or before). A place
    whose function is not here, or whose code differs (another game version), is left as it is"""
    done = 0
    for head, anchor, per_second in SPEED_PLACES:
        hook = SPEED_HOOK % (per_second, "second" if per_second else "frame")
        at = _function(s, head)
        if at is None:
            continue
        start, end = at
        body = s[start:end]
        if body.count(anchor + hook) == 1:
            done += 1
        elif body.count(anchor) == 1:
            s = s[:start] + body.replace(anchor, anchor + hook, 1) + s[end:]
            done += 1
    if done and SPEED_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + SPEED_DECL, 1)
    return s, done


def _straight(text):
    """text is one straight line of code: no label, no branch and no call in it"""
    return ":;" not in text and "goto " not in text and "c->x[30] = " not in text and "return;" not in text


def patch_fov(s):
    """The Field of view row's call: (s, 1) when f_804e48c0 is in s with it (made now or before), (s, 0) when the function is
    not here or its code differs (another game version: left as it is)"""
    at = _function(s, FOV_HEAD)
    if at is None:
        return s, 0
    head, end = at
    body = s[head:end]
    if body.count(FOV_LOAD + FOV_HOOK) == 1:
        return s, 1
    if FOV_HOOK in body or body.count(FOV_LABEL) != 1:
        return s, 0
    label = body.index(FOV_LABEL) + len(FOV_LABEL)
    load = body.find(FOV_LOAD, label)
    if load < 0 or not _straight(body[label:load]):
        return s, 0
    after = load + len(FOV_LOAD)
    if not _unmarked(body[after:after + 400]).startswith(FOV_NEXT):   # (a store mark's line may stand between: _unmarked)
        return s, 0
    s = s[:head + after] + FOV_HOOK + s[head + after:]
    if FOV_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + FOV_DECL, 1)
    return s, 1


# ((Triforce) 11-24) The ocarina's note wait, told to the host (host/nn_hid.c oc_notes: the Controls page's five note rows).
# The wait action's start and tick (ExecuteWaitOcarinaInputCommon); the anchors carry call-return PC literals, so each is
# once in its function. The start decides from the action's input kind whether the game waits for the five note buttons
# (HOS_OC_BUTTONS: 1 and 3 the field ocarina, 2 a song lesson, 7 the Lost Woods skull kids' songs, 10 the scarecrow's
# recording, 11 the scarecrow's recall of it; 13, a dialogue's, stays the game's), every running tick arms it again and
# stamps the beat, and the tick's ends and its three gates clear it.
OC_DECL = ("extern volatile int hos_oc_wait;\nextern volatile int hos_oc_last_kind;\n"
           "extern volatile unsigned hos_oc_beat;\n"
           "#define HOS_OC_BUTTONS(k) ((k) == 1 || (k) == 2 || (k) == 3 || (k) == 7 || (k) == 10 || (k) == 11)\n")
OC_ENTRY_HEAD = "void f_828a9190(Ctx *__restrict A64_NOESC c) {"
OC_ENTRY_OLD = ("    c->x[1]=recomp_load32(c,c->x[19] + 32);\n"
                "    { uint64_t _r = ((uint64_t)0 | ((c->x[0]) << 0)); c->x[20] = _r; }\n"
                "c->x[30] = 0x828a91e4ULL; f_832b35d0(c);")
OC_ENTRY_NEW = ("    c->x[1]=recomp_load32(c,c->x[19] + 32);\n"
                "    hos_oc_last_kind = (int)c->x[1], hos_oc_wait = HOS_OC_BUTTONS(c->x[1]) ? 1 : 2, hos_oc_beat++;"
                "   /* (nx2/oot_patches.py: the note wait began; 1 and 3 are the field ocarina, 2 a song lesson, "
                "7 the Lost Woods skull kids' songs, 10 the scarecrow's recording, 11 the scarecrow's recall of it, "
                "13 a dialogue's, which stays the game's) */\n"
                "    { uint64_t _r = ((uint64_t)0 | ((c->x[0]) << 0)); c->x[20] = _r; }\n"
                "c->x[30] = 0x828a91e4ULL; f_832b35d0(c);")
OC_TICK_HEAD = "void f_828a9280(Ctx *__restrict A64_NOESC c) {"
OC_TICK_OLD = ("    c->x[8]=recomp_load8(c,c->x[0] + 24);\n"
               "if (!((c->x[8] >> 1) & 1)) { goto L_828a92e4; }")
OC_TICK_NEW = ("    c->x[8]=recomp_load8(c,c->x[0] + 24);\n"
               "if (!((c->x[8] >> 1) & 1)) { hos_oc_wait = 0; goto L_828a92e4; }"
               "   /* (nx2/oot_patches.py: this action stopped running: no wait) */\n"
               "    hos_oc_wait = HOS_OC_BUTTONS(hos_oc_last_kind) ? 1 : 2, hos_oc_beat++;"
               "   /* (nx2/oot_patches.py: re-armed every running tick: the input resets between note windows end "
               "one wait without ending the action; the beat tells the host the wait is alive) */")
# (the tick's own gates sit after the re-arm: while any of them refuses, the game is not asking for notes, say a
# dialogue took the buttons; the host must hear that, or its pad swap eats the buttons the dialogue wants)
OC_TICK_GATES = (
    ("if (!c->z) { goto L_828a92e4; }",
     "if (!c->z) { hos_oc_wait = 0; goto L_828a92e4; }"
     "   /* (nx2/oot_patches.py: the action's mode check refused: no wait) */"),
    ("c->x[30] = 0x828a92e0ULL; f_806aac40(c);\n"
     "if (c->x[0] != 0) { goto L_828a92f8; }",
     "c->x[30] = 0x828a92e0ULL; f_806aac40(c);\n"
     "if (c->x[0] != 0) { goto L_828a92f8; }\n"
     "hos_oc_wait = 0;   /* (nx2/oot_patches.py: the input context is gone: no wait) */"),
    ("c->x[30] = 0x828a9318ULL; f_82856760(c);\n"
     "if (c->x[0] == 0) { { A64_POLL(c); goto L_828a92e4; } }",
     "c->x[30] = 0x828a9318ULL; f_82856760(c);\n"
     "if (c->x[0] == 0) { { A64_POLL(c); hos_oc_wait = 0; goto L_828a92e4; } }"
     "   /* (nx2/oot_patches.py: the wait's owner refused: no wait, and the pads are the game's again) */"),
)
OC_DONE_OLD = "recomp_store32(c,c->x[19] + 24,c->x[9]);"
OC_DONE_NEW = (OC_DONE_OLD + "\n    hos_oc_wait = 0;"
               "   /* (nx2/oot_patches.py: the wait action finished) */")
OC_RESET_OLD = "c->x[30] = 0x828a93e4ULL; f_832b35d0(c);"
OC_RESET_NEW = (OC_RESET_OLD + "\n    hos_oc_wait = 0;"
                "   /* (nx2/oot_patches.py: the input reset: this window's wait is over) */")


def patch_ocarina_wait(s):
    """The wait action reports itself to the host; None when the lift has no such functions, s unchanged when an anchor
    drifted or it is applied already (never a half-patch)."""
    splices, hits = [], 0
    for head, pairs in ((OC_ENTRY_HEAD, [(OC_ENTRY_OLD, OC_ENTRY_NEW)]),
                        (OC_TICK_HEAD, [(OC_TICK_OLD, OC_TICK_NEW)] + [p for p in OC_TICK_GATES] +
                                       [(OC_DONE_OLD, OC_DONE_NEW), (OC_RESET_OLD, OC_RESET_NEW)])):
        at = s.find(head)
        if at < 0:
            return None
        end = s.find("\nvoid f_", at + len(head))
        body = s[at:end if end >= 0 else len(s)]
        out = body
        for old, new in pairs:
            if new in out:
                continue
            if out.count(old) != 1:
                return s
            out = out.replace(old, new, 1)
        if out != body:
            splices.append((at, end, out))
            hits = 1
    if not hits:
        return s
    if OC_DECL not in s and s.count('#include "a64.h"\n') != 1:   # (nowhere to declare the host's words: left as it is)
        return s
    for at, end, out in reversed(splices):   # (later functions first: earlier splices keep the earlier offsets valid)
        s = s[:at] + out + (s[end:] if end >= 0 else "")
    if OC_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + OC_DECL, 1)
    return s


# ((Triforce) 11-24) The game's job barriers waiting for their masks instead of sleeping 20 us (host/oot_barrier.h has the
# protocol and why; HOS_OOT_BARRIER_WAIT, on by default). Three parallel-for jobs are run by several threads over one job
# block P: every pass over the job's items takes an item by an atomic OR into a claim mask in P and, the item done, ORs it
# into a done mask; a thread with nothing to take sleeps (SleepThread of the tick frequency / 50000: 20 us) and goes back
# to its loop, until the masks it polls are full. With the switch on the sleep is hos_oot_barrier_wait(P, the polled
# words' offsets, the values the loop's pass saw, the full mask), and each OR into a polled word is followed by
# hos_oot_barrier_wake(P) (P: the OR's own address less the word's offset); off (=0), the sleep runs as lifted and the
# wakes do nothing. What was matched, read from the lift of the supported build with every path followed back from each
# sleep:
#   f_800998a0 (P in x24 at each sleep, reloaded from its frame slot x29-96 only; the full mask stored at x29-100 once):
#     - sleep LR 0x8009a478, back to the outer loop's head 0x80099a00: polls the claim masks P+0x1f4 (after the yield at
#       0x8009a420) and P+0x1fc (at 0x8009a6f0) against x22, both read after the passes: the hook reads them at the call;
#     - sleep LR 0x8009b234, back to 0x8009a768: polls P+0x200 through its value at that loop's head (x25, or its copy at
#       sp+104 put back after the pass), against x22;
#     - sleep LR 0x8009aff0, back to 0x8009aa1c: polls P+0x208 through its value at that loop's head (x19, or its copy at
#       sp+72), against the full mask read again from x29-100;
#     - the ORs into P+0x1f4, P+0x1fc, P+0x200 (the pass that ends at the yield at 0x8009a420) and P+0x208 (the pass that
#       ends at 0x8009aa00): the only writes of those words in the function.
#   f_800738e0 (P in x19, the entry's x0: no other write of x19 reaches the sleep): sleep LR 0x800747ac, back to
#     0x80073e38, polls P+0x210 and P+0x218 through their values at that loop's head (x25, x28) against the full mask at
#     sp+16 (stored once); the ORs into them are in the two passes before the loop.
#   f_8007e200 (P in x26, put back from x23 after each item): sleep LR 0x8007e90c, back to 0x8007e6c0, polls P+0x220
#     through its value at that loop's head (x21) against ~x28 (x28: the inverted full mask, stored at sp+68 at entry); the
#     OR into it is in the pass before the loop, which can reach the sleep without a yield: so the wakes are at the ORs.
# A function is hooked only where every one of its places and marks is there once (another game version, or a lift that
# keeps the function's registers as locals, A64_LOCAL_REGS: left as it is, and apply warns), and then at all its places:
# a sleep never waits for a wake that is not there. The supported build's lift only (apply).
def _barrier_or(base, off, addr, value, between=""):
    """(the lifted OR into P+off, its address made from register base into register addr; the same with the wake after it)"""
    head = "    { uint64_t _a=c->x[%d], _b=%dULL; uint64_t _r=_a+_b; c->x[%d]=_r; }\n%s" % (base, off, addr, between)
    rmw = ("{ uint64_t _a = c->x[%d]; uint32_t *_p = (uint32_t *)A64_PTR(_a); uint32_t _o = __atomic_fetch_or(_p, (uint32_t)c->x[%d], "
           "__ATOMIC_SEQ_CST); A64_MARK(_a, 4); c->x[8] = (uint64_t)_o;" % (addr, value))
    return (head + rmw + " }\n",
            head + rmw + " if (hos_oot_barrier_on()) hos_oot_barrier_wake(_a - %dULL); }   /* (nx2/oot_patches.py: "
                         "HOS_OOT_BARRIER_WAIT) */\n" % off)


def _barrier_sleep(lr, then, wait):
    """(the sleep at its return address and the lines after it; the same with the wait in front of it)"""
    return ("c->x[30] = 0x%xULL; f_85106220(c);\n%s" % (lr, then),
            "c->x[30] = 0x%xULL; if (!hos_oot_barrier_on() || !hos_oot_barrier_wait(%s)) f_85106220(c);"
            "   /* (nx2/oot_patches.py: HOS_OOT_BARRIER_WAIT) */\n%s" % (lr, wait, then))


BARRIER_SITES = (   # (the function's head, the marks its code must have, its places: (lifted text, the text in its place))
    ("void f_800998a0(Ctx *__restrict A64_NOESC c) {\n",
     ("    c->x[8]=recomp_load32(c,c->x[24] + 500);\n    recomp_barrier();\n"
      "    { uint64_t _b=c->x[29]; int64_t _o=-100; c->x[22]=recomp_load32(c,(_b+_o)); }\n",
      "L_8009a6f0:;\n    c->x[8]=recomp_load32(c,c->x[24] + 508);\n",
      "L_8009a768:;\n    c->x[25]=recomp_load32(c,c->x[24] + 512);\n", "recomp_store32_sp(c,c->x[31] + 104,c->x[25]);",
      "c->x[25]=recomp_load32(c,c->x[31] + 104);",
      "L_8009aa1c:;\n    c->x[19]=recomp_load32(c,c->x[24] + 520);\n", "recomp_store32_sp(c,c->x[31] + 72,c->x[19]);",
      "c->x[19]=recomp_load32(c,c->x[31] + 72);",
      "c->x[30] = 0x8009afa4ULL; f_85106210(c);\n    { uint64_t _b=c->x[29]; int64_t _o=-100; c->x[8]=recomp_load32(c,(_b+_o)); }\n"),
     (_barrier_sleep(0x8009a478, "{ A64_POLL(c); goto L_80099a00; }\n",
                     "c->x[24], 500, (uint32_t)recomp_load32(c,c->x[24] + 500), 508, (uint32_t)recomp_load32(c,c->x[24] + 508), "
                     "(uint32_t)c->x[22]"),
      _barrier_sleep(0x8009b234, "    c->x[11] = 0x1ULL;\n    c->x[11] &= 0xFFFFFFFFULL;\n{ A64_POLL(c); goto L_8009a768; }\n",
                     "c->x[24], 512, (uint32_t)c->x[25], 512, (uint32_t)c->x[25], (uint32_t)c->x[22]"),
      _barrier_sleep(0x8009aff0, "{ A64_POLL(c); goto L_8009aa1c; }\n",
                     "c->x[24], 520, (uint32_t)c->x[19], 520, (uint32_t)c->x[19], (uint32_t)recomp_load32(c,c->x[29] - 100)"),
      _barrier_or(24, 500, 8, 23), _barrier_or(24, 508, 8, 23), _barrier_or(24, 512, 8, 23),
      _barrier_or(24, 520, 8, 9, "    c->x[11] = 0x1ULL;\n    c->x[11] &= 0xFFFFFFFFULL;\n    c->x[9]=recomp_load32(c,c->x[31] + 112);\n"))),
    ("void f_800738e0(Ctx *__restrict A64_NOESC c) {\n",
     ("    { uint64_t _r = ((uint64_t)0 | ((c->x[0]) << 0)); c->x[19] = _r; }\n",
      "L_80073e38:;\n    c->x[25]=recomp_load32(c,c->x[19] + 528);\n    recomp_barrier();\n    c->x[28]=recomp_load32(c,c->x[19] + 536);\n",
      "recomp_store32_sp(c,c->x[31] + 16,c->x[8]);", "c->x[9]=recomp_load32(c,c->x[31] + 16);"),
     (_barrier_sleep(0x800747ac, "{ A64_POLL(c); goto L_80073e38; }\n",
                     "c->x[19], 528, (uint32_t)c->x[25], 536, (uint32_t)c->x[28], (uint32_t)recomp_load32(c,c->x[31] + 16)"),
      _barrier_or(19, 528, 27, 26, "c->x[30] = 0x80073958ULL; f_80279140(c);\n    recomp_barrier();\n"),
      _barrier_or(19, 536, 8, 9, "    { c->x[9]=(uint64_t)(uint32_t)((uint32_t)c->x[3]<<(c->x[21]&31)); }\n    recomp_barrier();\n"))),
    ("void f_8007e200(Ctx *__restrict A64_NOESC c) {\n",
     ("recomp_store32_sp(c,c->x[31] + 68,c->x[9]);",
      "L_8007e6c0:;\n    c->x[21]=recomp_load32(c,c->x[26] + 544);\n",
      "    c->x[28]=recomp_load32(c,c->x[31] + 68);\n",
      "{ uint64_t _r = (c->x[21] ^ ((uint64_t)(uint32_t)(((uint32_t)(c->x[28])) << 0))); _r &= 0xFFFFFFFFULL; c->x[8] = _r; }"),
     (_barrier_sleep(0x8007e90c, "{ A64_POLL(c); goto L_8007e6c0; }\n",
                     "c->x[26], 544, (uint32_t)c->x[21], 544, (uint32_t)c->x[21], ~(uint32_t)c->x[28]"),
      _barrier_or(26, 544, 8, 9, "    { c->x[9]=(uint64_t)(uint32_t)((uint32_t)c->x[23]<<(c->x[21]&31)); }\n    recomp_barrier();\n"))),
)
BARRIER_DECL = ("extern int hos_oot_barrier_on(void);\n"
                "extern int hos_oot_barrier_wait(uint64_t p, uint32_t off1, uint32_t seen1, uint32_t off2, uint32_t seen2, "
                "uint32_t full);\n"
                "extern void hos_oot_barrier_wake(uint64_t p);\n")
# (the texts above are the lift's own, as the patches meet them: before a64_lift.mark_groups, the lift's last step, and with
# the loops' polls in. Two other forms of a text are let through, each kept as it was found:
#   - a group's shared page mark (a64_lift.MG_MARK) on a line of its own after any line end inside it. mark_groups puts one
#     before a line that ends a run of stores, as the atomic OR, a call or recomp_barrier() do, so a run of the patches by
#     hand over a finished lift (python -I nx2/oot_patches.py) can find one there;
#   - a loop's back-edge `goto L_x;` without its `{ A64_POLL(c); ... }`: nx2/poll.py adds the polls around the function's
#     emit, and a lift without them (--no-polls) has none)
_BARRIER_MARKS = r"((?:    A64_MARK\(\(c->x\[\d+\] \+ \(uint64_t\)\(int64_t\)\(-?\d+\)\), \d+\);\n)*)"
_BARRIER_POLLED = re.compile(r"\{ A64_POLL\(c\); (goto L_[0-9a-f]{8};) \}")


class _BarrierText:
    """A text of BARRIER_SITES as a pattern: its fixed pieces with a slot between two of them after each line end inside it
    (group marks) and at each polled back-edge (the goto with or without its poll)"""

    def __init__(self, text):
        self.pieces, self.slots = [""], []
        parts = _BARRIER_POLLED.split(text)   # (each polled goto at an odd index)
        for k, part in enumerate(parts):
            if k % 2:
                goto = re.escape(part)
                self.slots.append(r"(\{ A64_POLL\(c\); %s \}|%s)" % (goto, goto))
                self.pieces.append("")
                continue
            lines = part.split("\n")
            for i, line in enumerate(lines):
                if i:
                    self.pieces[-1] += "\n"
                    if line or i < len(lines) - 1 or k < len(parts) - 1:   # (none after the text's own last line end)
                        self.slots.append(_BARRIER_MARKS)
                        self.pieces.append("")
                self.pieces[-1] += line
        self.re = re.compile("".join(re.escape(p) + s for p, s in zip(self.pieces, self.slots + [""])))

    def count(self, body):
        return sum(1 for _ in self.re.finditer(body))

    def put(self, body, old):
        """body with the first place old finds made this text, what old's slots found kept in this text's slots (body as it
        is where old finds none, as str.replace)"""
        m = old.re.search(body)
        if m is None:
            return body
        return body[:m.start()] + "".join(p + f for p, f in zip(self.pieces, m.groups() + ("",))) + body[m.end():]


def _barrier_forms():
    forms = []
    for head_text, marks, places in BARRIER_SITES:
        made = [(_BarrierText(old), _BarrierText(new)) for old, new in places]
        if any(old.slots != new.slots for old, new in made):   # (a place and its text in its place, slot for slot)
            raise ValueError("oot_patches: a barrier place and its hooked text differ in their lines or loops")
        forms.append((head_text, [_BarrierText(m) for m in marks], made))
    return tuple(forms)


BARRIER_FORMS = _barrier_forms()


def patch_barrier_wait(s):
    """The job barriers' sleeps and ORs through the host: (s, how many of BARRIER_SITES' functions are in s with all their
    places hooked, made now or before). A function whose code differs (another game version) is left as it is"""
    done = 0
    for head_text, marks, places in BARRIER_FORMS:
        at = _function(s, head_text)
        if at is None:
            continue
        head, end = at
        body = s[head:end]
        if all(new.count(body) == 1 and not old.count(body) for old, new in places):
            done += 1
            continue
        if not all(m.count(body) == 1 for m in marks) or not all(old.count(body) == 1 for old, _ in places):
            continue
        if BARRIER_DECL not in s and s.count('#include "a64.h"\n') != 1:   # (nowhere to declare the hooks: left as it is)
            continue
        for old, new in places:
            body = new.put(body, old)
        s = s[:head] + body + s[end:]
        done += 1
    if done and BARRIER_DECL not in s:
        s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + BARRIER_DECL, 1)
    return s, done


def apply(gen, *, protect_hearts=False, required=False):
    """required: the lift of the supported build (LIFE_BUILD_ID), whole: a missing output-size edit stops it (apply_output_size).
    The other patches only warn when their place is not found once."""
    import oot_native_resolution   # (HOS_SCENE_NATIVE=1: the scene's base scale 1.0; off by default since #849's output resolution)
    oot_native_resolution.apply(gen)
    done = {"dynamic resolution branch": 0, "text speed block": 0, "fixed path's scale": 0, "movie's frame count": 0,
            "ocarina note wait": 0}
    if protect_hearts:   # (the supported build's: these places are its functions)
        done["menu focus hook"] = 0
        done["menu tick hook"] = 0
        done["gameplay HUD map hook"] = 0   # ((Triforce) host/hos_wide_ui.c hos_gameplay_hud_screen)
        done["player heart protection"] = 0
        done["player flight"] = 0
        done["player flight rotation"] = 0
        done["free camera"] = 0
        done["mouse camera"] = 0
        done["scene colour target format"] = 0   # (local, RenoDX port)
        done.update({"text draw hook": 0, "glyph hook": 0, "text layout hook": 0})   # ((Triforce) the prompts' live part)
    step_sites, step_files = 0, []   # (the divides with the hook, and the files that have it)
    whole_sites = 0   # (the counters of WHOLE_SITES with the whole frames: patch_whole_frames)
    loop_sites = pose_sites = 0   # (patch_loop_steps, patch_loop_pose: a one-frame loop's two clock advances and its drawn time)
    sound_jobs = solver_sites = 0   # (patch_sound_job, patch_solver_steps: the places found with their hooks)
    bgm_time_sites = bgm_flags_sites = 0   # (patch_bgm_time, patch_bgm_flags: the music manager's update, once each)
    floor_sites = sim_sites = record_sites = 0   # (patch_floor_carry, patch_sim_steps, patch_record_clock: the same)
    battle_sites = 0   # (patch_battle_steps: Link's two state steps)
    turn_sites = 0   # (patch_turn_rate: the saved steering rate's two bounds, one place)
    horse_sites = 0   # (patch_horse_jump: a horse's jump state machine's step test)
    cue_sites = 0   # (patch_song_cue: the two song playbacks' reads of the note flag)
    drive_sites = 0   # (patch_drive_target: the two copies of a driven body's path)
    jump_sites = velocity_sites = 0   # (patch_jump_speed, patch_takeoff_velocity: a jump's takeoff speed and its set-velocity call)
    cloth_sites = cloth_solve_sites = 0   # (patch_cloth_time, patch_cloth_solve: the cloth's setup and its solve job)
    sprint_sites = 0  # (patch_sprint: its two calls)
    zstd_sites = 0   # (patch_host_zstd: its two calls, the supported build's alone)
    mod_size_sites = 0   # ((Triforce) patch_mod_sizes: its one call, the supported build's alone)
    heap_sites = [0, 0]   # (the GPU memory's sites, the CPU buffers': patch_heap_retry, the supported build only)
    tex_compact_sites = 0   # ((Triforce) patch_tex_compact: its one call, the supported build's alone)
    ocb_sites = 0   # ((Triforce) 11-24: patch_ocb_hold: the preload manager's choice, the supported build's alone)
    tex_ask_sites = 0   # ((Triforce) patch_tex_ask: its one test, the supported build's alone)
    shadow_step_sites = 0   # ((Triforce, 11-21, GAME-05) patch_shadow_step: the one read of a shadow map's side)
    shadow_res_sites = shadow_fit_sites = 0   # ((Triforce) 11-24: patch_shadow_res, patch_shadow_fit: the sun's cascades)
    fov_sites = 0   # ((Triforce) patch_fov: the Field of view row's one call)
    text_size_sites = 0   # ((Triforce) patch_text_size: the Text size row's one call)
    centering_sites = 0   # ((Triforce) patch_camera_centering: the Camera centering row's one test)
    damage_sites = 0   # ((Triforce) patch_damage: the Damage taken row's one call)
    opening_sites = 0   # ((Triforce) patch_opening: the Skip opening row's three calls)
    autosave_sites = 0   # ((Triforce) patch_autosave: the Autosave row's one call)
    speed_sites = 0   # ((Triforce) patch_cct_speed: the Movement speed tool's four calls)
    barrier_sites = 0   # ((Triforce) 11-24: patch_barrier_wait: the three job functions, the supported build's alone)
    for path in sorted(glob.glob(os.path.join(glob.escape(gen), "code_*.c"))):
        with open(path, encoding="utf-8", newline="") as f:
            s = f.read()
        out = s
        d = patch_dynres(out)
        if d is not None:
            out = d
            done["dynamic resolution branch"] += 1
            print("oot_patches: dynamic resolution switch in", os.path.basename(path))
        t = patch_text_speed(out)
        if t is not None and t != out:
            out = t
            done["text speed block"] += 1
            print("oot_patches: text speed scale in", os.path.basename(path))
        focus = patch_menu_focus(out) if protect_hearts else None
        if focus is not None:
            out = focus
            done["menu focus hook"] += 1
            print("oot_patches: the menus' focus hook in", os.path.basename(path))
        tick = patch_menu_tick(out) if protect_hearts else None
        if tick is not None:
            out = tick
            done["menu tick hook"] += 1
            print("oot_patches: the menus' update hook in", os.path.basename(path))
        hud = patch_gameplay_hud_screen(out) if protect_hearts else None   # ((Triforce) after the menu tick's hook, around it)
        if hud is not None:
            out = hud
            done["gameplay HUD map hook"] += 1
            print("oot_patches: the shared map's scoped gameplay HUD placement in", os.path.basename(path))
        for name, patch in ((("text draw hook", patch_text_draw), ("glyph hook", patch_glyph),
                             ("text layout hook", patch_text_layout)) if protect_hearts else ()):   # ((Triforce) prompts' live part)
            hooked = patch(out)
            if hooked is not None:
                out = hooked
                done[name] += 1
                print("oot_patches: the button prompts'", name, "in", os.path.basename(path))
        movie = patch_movie_frames(out)
        if movie is not None:
            if MOVIE_NEW in movie:   # (made now, or by an earlier run over this file)
                done["movie's frame count"] += 1
            if movie != out:
                print("oot_patches: the movie's frame count by the frames' time in", os.path.basename(path))
            out = movie
        ocw = patch_ocarina_wait(out)
        if ocw is not None:
            if OC_ENTRY_NEW in ocw:   # (made now, or by an earlier run over this file)
                done["ocarina note wait"] += 1
            if ocw != out:
                print("oot_patches: the ocarina note wait in", os.path.basename(path))
            out = ocw
        out, n = fixed_scale(out)
        if n:
            done["fixed path's scale"] += 1
            print("oot_patches: the fixed path's scale in", os.path.basename(path))
        fmt = patch_scene_format(out) if protect_hearts else None
        if fmt is not None:
            out = fmt
            done["scene colour target format"] += 1
            print("oot_patches: the scene's colour target format in", os.path.basename(path))
        life = patch_life(out) if protect_hearts else None
        if life is not None:
            out = life
            done["player heart protection"] += 1
            print("oot_patches: player heart protection in", os.path.basename(path))
        move = patch_movement(out) if protect_hearts else None
        if move is not None:
            out = move
            done["player flight"] += 1
            print("oot_patches: player flight in", os.path.basename(path))
        rotation = patch_flight_rotation(out) if protect_hearts else None
        if rotation is not None:
            out = rotation
            done["player flight rotation"] += 1
            print("oot_patches: player flight rotation in", os.path.basename(path))
        mouse = patch_mouse_camera(out) if protect_hearts else None
        if mouse is not None:
            out = mouse
            done["mouse camera"] += 1
            print("oot_patches: native mouse camera in", os.path.basename(path))
        view = patch_view(out) if protect_hearts else None
        if view is not None:
            out = view
            done["free camera"] += 1
            print("oot_patches: free camera in", os.path.basename(path))
        out, sites = patch_frame_seconds(out)
        if STEP_MARK in out:   # (made now, or by an earlier run over this file)
            step_sites += out.count(STEP_MARK)
            step_files.append(path)
        if sites:
            print("oot_patches: the frame's time at %d step divide(s) in %s" % (sites, os.path.basename(path)))
        heap, found = patch_heap_retry(out) if protect_hearts else (out, [0, 0])
        heap_sites[0] += found[0]
        heap_sites[1] += found[1]
        if heap != out:
            print("oot_patches: heap-full retries of the OptimizeChangeBank allocations in", os.path.basename(path))
        out = heap
        out, whole = patch_whole_frames(out)
        whole_sites += out.count(WHOLE_MARK)   # (made now, or by an earlier run over this file)
        if whole:
            print("oot_patches: %d frame counter(s) with the step's whole frames in %s" % (whole, os.path.basename(path)))
        looped, found = patch_loop_steps(out)
        loop_sites += found
        if looped != out:
            print("oot_patches: the animation clocks with whole frames for a loop of one frame in", os.path.basename(path))
        out = looped
        posed, found = patch_loop_pose(out)
        pose_sites += found
        if posed != out:
            print("oot_patches: the drawn time of a loop of one frame by its start in", os.path.basename(path))
        out = posed
        sound, found = patch_sound_job(out)
        sound_jobs += found
        if sound != out:
            print("oot_patches: the sound job at 60 Hz above 60 fps in", os.path.basename(path))
        out = sound
        bgm, found = patch_bgm_time(out)
        bgm_time_sites += found
        if bgm != out:
            print("oot_patches: the music manager's whole step above 60 fps in", os.path.basename(path))
        out = bgm
        flags, found = patch_bgm_flags(out)
        bgm_flags_sites += found
        if flags != out:
            print("oot_patches: the music manager's change flags kept above 60 fps in", os.path.basename(path))
        out = flags
        solver, found = patch_solver_steps(out)
        solver_sites += found
        if solver != out:
            print("oot_patches: the solver steps rounded up above 60 fps in", os.path.basename(path))
        out = solver
        floor, found = patch_floor_carry(out)
        floor_sites += found
        if floor != out:
            print("oot_patches: a floor's carry above 100 fps in", os.path.basename(path))
        out = floor
        sim, found = patch_sim_steps(out)
        sim_sites += found
        if sim != out:
            print("oot_patches: the water and floor surfaces' fixed steps above 60 fps in", os.path.basename(path))
        out = sim
        record, found = patch_record_clock(out)
        record_sites += found
        if record != out:
            print("oot_patches: the ocarina recorder's clock above 60 fps in", os.path.basename(path))
        out = record
        battle, found = patch_battle_steps(out)
        battle_sites += found
        if battle != out:
            print("oot_patches: Link's state steps above 60 fps (the battle music's end) in", os.path.basename(path))
        out = battle
        turn, found = patch_turn_rate(out)
        turn_sites += found
        if turn != out:
            print("oot_patches: the saved steering rate above 60 fps in", os.path.basename(path))
        out = turn
        horse, found = patch_horse_jump(out)
        horse_sites += found
        if horse != out:
            print("oot_patches: a horse's jump blend above 60 fps in", os.path.basename(path))
        out = horse
        drive, found = patch_drive_target(out)
        drive_sites += found
        if drive != out:
            print("oot_patches: Link's driven body's target above 60 fps in", os.path.basename(path))
        out = drive
        jump, found = patch_jump_speed(out)
        jump_sites += found
        if jump != out:
            print("oot_patches: a jump's takeoff speed above 60 fps in", os.path.basename(path))
        out = jump
        velocity, found = patch_takeoff_velocity(out)
        velocity_sites += found
        if velocity != out:
            print("oot_patches: a jump's takeoff velocity above 60 fps in", os.path.basename(path))
        out = velocity
        cloth, found = patch_cloth_time(out)
        cloth_sites += found
        if cloth != out:
            print("oot_patches: the cloth's time below 60 fps in", os.path.basename(path))
        out = cloth
        solve, found = patch_cloth_solve(out)
        cloth_solve_sites += found
        if solve != out:
            print("oot_patches: the cloth's solves above 60 fps in", os.path.basename(path))
        out = solve
        cue, found = patch_song_cue(out)
        cue_sites += found
        if cue != out:
            print("oot_patches: the song playbacks' note flag once a note above 60 fps in", os.path.basename(path))
        out = cue
        sprinted, found = patch_sprint(out)
        sprint_sites += found
        if sprinted != out:
            print("oot_patches: the sprint button in", os.path.basename(path))
        out = sprinted
        if protect_hearts:   # (found by address: the supported build's functions)
            zstd, found = patch_host_zstd(out)
            zstd_sites += found
            if zstd != out:
                print("oot_patches: the host's zstd decoder's call(s) in", os.path.basename(path))
            out = zstd
            sized, found = patch_mod_sizes(out)
            mod_size_sites += found
            if sized != out:
                print("oot_patches: room for the mods' files in", os.path.basename(path))
            out = sized
            compacted, found = patch_tex_compact(out)
            tex_compact_sites += found
            if compacted != out:
                print("oot_patches: the texture compaction's step through the host in", os.path.basename(path))
            out = compacted
            asked, found = patch_tex_ask(out)
            tex_ask_sites += found
            if asked != out:
                print("oot_patches: the texture compaction's ask at most once a second in", os.path.basename(path))
            out = asked
            # (the supported build's only: the host reads the manager as that build lays it out, host/oot_ocb_hold.h)
            ocbh, found = patch_ocb_hold(out)
            ocb_sites += found
            if ocbh != out:
                print("oot_patches: the preload manager's choice of a neighbouring map through the host in", os.path.basename(path))
            out = ocbh
            stepped, found = patch_shadow_step(out)
            shadow_step_sites += found
            if stepped != out:
                print("oot_patches: the shadow maps' side through the host in", os.path.basename(path))
            out = stepped
            sized, found = patch_shadow_res(out)
            shadow_res_sites += found
            if sized != out:
                print("oot_patches: the sun's shadow cascades' size through the host in", os.path.basename(path))
            out = sized
            fitted, found = patch_shadow_fit(out)
            shadow_fit_sites += found
            if fitted != out:
                print("oot_patches: the sun's nearest cascade's fit through the host in", os.path.basename(path))
            out = fitted
            fov, found = patch_fov(out)
            fov_sites += found
            if fov != out:
                print("oot_patches: the Field of view row's call in", os.path.basename(path))
            out = fov
            sized_text, found = patch_text_size(out)
            text_size_sites += found
            if sized_text != out:
                print("oot_patches: the Text size row's call in", os.path.basename(path))
            out = sized_text
            centered, found = patch_camera_centering(out)
            centering_sites += found
            if centered != out:
                print("oot_patches: the Camera centering row's test in", os.path.basename(path))
            out = centered
            damaged, found = patch_damage(out)
            damage_sites += found
            if damaged != out:
                print("oot_patches: the Damage taken row's call in", os.path.basename(path))
            out = damaged
            opened, found = patch_opening(out)
            opening_sites += found
            if opened != out:
                print("oot_patches: the Skip opening row's call(s) in", os.path.basename(path))
            out = opened
            autosaved, found = patch_autosave(out)
            autosave_sites += found
            if autosaved != out:
                print("oot_patches: the Autosave row's call in", os.path.basename(path))
            out = autosaved
            sped, found = patch_cct_speed(out)
            speed_sites += found
            if sped != out:
                print("oot_patches: the Movement speed tool's call(s) in", os.path.basename(path))
            out = sped
            waited, found = patch_barrier_wait(out)
            barrier_sites += found
            if waited != out:
                print("oot_patches: the job barriers' sleeps and mask ORs through the host in", os.path.basename(path))
            out = waited
        if out != s:
            whole_write.write_whole(path, out, newline="")
    if sound_jobs != 1:   # (without it, above 60 fps sounds and then the music can stop after a few loading zones)
        print("oot_patches: WARNING: the sound job was found %d times, not once" % sound_jobs)
    if (loop_sites, pose_sites) != (len(LOOP_SITES), 1):   # (without them, above 60 fps a pose held by a one-frame loop twitches)
        print("oot_patches: WARNING: a one-frame loop's clock advances were found at %d of %d places, its drawn time at %d of 1"
              % (loop_sites, len(LOOP_SITES), pose_sites))
    if bgm_time_sites != 1:   # (without it, above 60 fps the music manager's timers run at 60 / fps of real time)
        print("oot_patches: WARNING: the music manager's time was found %d times, not once" % bgm_time_sites)
    if bgm_flags_sites != 1:   # (without it, above 60 fps the battle music can play on after a fight)
        print("oot_patches: WARNING: the music manager's change flags were found %d times, not once" % bgm_flags_sites)
    if solver_sites != len(SOLVER_HEADS):   # (without them, above 60 fps moving platforms can drop Link)
        print("oot_patches: WARNING: the solver step count was found at %d of %d places" % (solver_sites, len(SOLVER_HEADS)))
    if floor_sites != len(FLOOR_HEADS):   # (without them, above 100 fps a moving platform carries Link at a tenth of its speed)
        print("oot_patches: WARNING: a floor's carry was found at %d of %d places" % (floor_sites, len(FLOOR_HEADS)))
    if sim_sites != len(SIM_SITES):   # (without them, above 60 fps the water and web surfaces stand still)
        print("oot_patches: WARNING: the surfaces' fixed steps were found at %d of %d places" % (sim_sites, len(SIM_SITES)))
    if record_sites != sum(n for _, n in RECORD_SITES):   # (without them, above 60 fps a recorded song loses its rests)
        print("oot_patches: WARNING: the ocarina recorder's clock was found at %d of %d places"
              % (record_sites, sum(n for _, n in RECORD_SITES)))
    if battle_sites != len(BATTLE_SITES):   # (without them, above 60 fps the battle music keeps playing after the last enemy)
        print("oot_patches: WARNING: Link's state steps were found at %d of %d places" % (battle_sites, len(BATTLE_SITES)))
    if turn_sites != 1:   # (without it, above 60 fps Gohma can keep circling the ceiling)
        print("oot_patches: WARNING: the saved steering rate was found %d times, not once" % turn_sites)
    if horse_sites != 1:   # (without it, above 60 fps Epona gallops through the fences she jumps)
        print("oot_patches: WARNING: the horse's jump step test was found %d times, not once" % horse_sites)
    if drive_sites != len(DRIVE_REGS):   # (without them, above 60 fps Link's pull-up onto a ledge falls short)
        print("oot_patches: WARNING: the driven body's target was found at %d of %d places" % (drive_sites, len(DRIVE_REGS)))
    if jump_sites != 1:   # (without it, above 60 fps Link's jumps hop lower and a backflip down a slope takes off twice)
        print("oot_patches: WARNING: a jump's takeoff speed was found %d times, not once" % jump_sites)
    if velocity_sites != 1:   # (without it the takeoff speed is kept and not used: the hop is the game's)
        print("oot_patches: WARNING: the set-velocity call for a jump's takeoff was found %d times, not once" % velocity_sites)
    if cloth_sites != 1:   # (without it, below 60 fps Link's cap and the other cloth run slow: they swing out and settle slowly)
        print("oot_patches: WARNING: the cloth's time was found %d times, not once" % cloth_sites)
    if cloth_solve_sites != 1:   # (without it, above 60 fps with HOS_FPS_CLOTH_60=1 the cloth is still solved every frame)
        print("oot_patches: WARNING: the cloth's solve job was found %d times, not once" % cloth_solve_sites)
    if cue_sites != len(SONG_CUE_SITES):   # (without them, above 60 fps a song's notes come in twos and threes)
        print("oot_patches: WARNING: the song playbacks' note flag was found at %d of %d places" % (cue_sites, len(SONG_CUE_SITES)))
    if sprint_sites != 2:   # (without them the Sprint button row does nothing)
        print("oot_patches: WARNING: the sprint button's calls were found at %d of 2 places" % sprint_sites)
    if protect_hearts and mod_size_sites != 1:   # (without it a mod's bigger model can crash the game: host/mods.c)
        print("oot_patches: WARNING: the resource size table's lookup was found at %d of 1 place" % mod_size_sites)
    if protect_hearts and tex_compact_sites != 1:   # (without it the compaction is neither counted nor paced: host/oot_tex_compact.c)
        print("oot_patches: WARNING: the texture compaction's step was found at %d of 1 place" % tex_compact_sites)
    if protect_hearts and shadow_step_sites != 1:   # (without it every shadow map has a side of its own, as shipped: host/oot_shadow_step.h)
        print("oot_patches: WARNING: the shadow maps' side was found at %d of 1 place" % shadow_step_sites)
    if protect_hearts and shadow_res_sites != 1:   # (without it Shadow resolution does nothing: host/oot_shadow.c)
        print("oot_patches: WARNING: the sun's shadow cascades' size was found at %d of 1 place" % shadow_res_sites)
    if protect_hearts and shadow_fit_sites != 2:   # (without them Highest keeps the game's fit: host/oot_shadow_fit.c)
        print("oot_patches: WARNING: the sun's nearest cascade's fit was found at %d of 2 places" % shadow_fit_sites)
    if protect_hearts and barrier_sites != len(BARRIER_SITES):   # (without them the job barriers sleep 20 us there, as before)
        print("oot_patches: WARNING: the job barriers were found in %d of %d functions" % (barrier_sites, len(BARRIER_SITES)))
    if protect_hearts and ocb_sites != 1:   # (without it HOS_OCB_HOLD_MS does nothing: the neighbours reload as before)
        print("oot_patches: WARNING: the preload manager's choice was found %d times, not once" % ocb_sites)
    if protect_hearts and fov_sites != 1:   # (without it the Field of view row does nothing: host/oot_fov.c)
        print("oot_patches: WARNING: the camera's angle for the Field of view row was found at %d of 1 place" % fov_sites)
    if protect_hearts and text_size_sites != 1:   # (without it the Text size row does nothing: host/oot_text_size.c)
        print("oot_patches: WARNING: the text panes' step for the Text size row was found at %d of 1 place" % text_size_sites)
    if protect_hearts and centering_sites != 1:   # (without it the Camera centering row does nothing: host/mouse_native.c)
        print("oot_patches: WARNING: the camera's yaw follow for the Camera centering row was found at %d of 1 place" % centering_sites)
    if protect_hearts and damage_sites != 1:   # (without it the Damage taken row does nothing: host/oot_damage.c)
        print("oot_patches: WARNING: the life write for the Damage taken row was found at %d of 1 place" % damage_sites)
    if protect_hearts and opening_sites != len(OPENING_SITES):   # (without them the Skip opening row does nothing, or half: host/oot_opening.c)
        print("oot_patches: WARNING: the Skip opening row's functions were found at %d of %d places" % (opening_sites, len(OPENING_SITES)))
    if protect_hearts and autosave_sites != 1:   # (without it the Autosave row does nothing: host/oot_autosave.c)
        print("oot_patches: WARNING: the save request for the Autosave row was found at %d of 1 place" % autosave_sites)
    if protect_hearts and speed_sites != len(SPEED_PLACES):   # (without them the Debug tab's Movement speed does nothing, or part)
        print("oot_patches: WARNING: the Movement speed tool's places were found %d times, not %d" % (speed_sites, len(SPEED_PLACES)))
    if protect_hearts and tex_ask_sites != 1:   # (without it the compaction may be asked for every frame: host/oot_tex_compact.c)
        print("oot_patches: WARNING: the texture compaction's ask was found at %d of 1 place" % tex_ask_sites)
    if protect_hearts and zstd_sites != len(ZSTD_SITES):   # (without them HOS_HOST_ZSTD does nothing, or half: host/hos_zstd.c)
        print("oot_patches: WARNING: the host's zstd decoder's calls were found at %d of %d places" % (zstd_sites, len(ZSTD_SITES)))
    if protect_hearts and heap_sites != [len(GPU_ALLOC_SITES), len(HEAP_ALLOC_SITES)]:   # (the supported build's functions)
        print("oot_patches: WARNING: the OptimizeChangeBank allocations were found %s times, not once each: a full heap is "
              "not tried again" % heap_sites)
    for what, n in done.items():
        if n != 1:
            print("oot_patches: WARNING: the %s was found %d times" % (what, n))
    if step_sites != len(STEP_SITES):
        # (both or neither: with one divide timed and the other stepping 1/60 s the two clocks of the game would run apart. Without
        # the hook the host keeps the rate up to the cap, as before: host/nn_vi.c, hos_step_probe)
        for path in step_files:
            with open(path, encoding="utf-8", newline="") as f:
                s = f.read()
            whole_write.write_whole(path, unpatch_frame_seconds(s), newline="")
        print("oot_patches: WARNING: the frame's time was found at %d of %d step divides, none patched (a Frame rate cap above 60 "
              "keeps the game's own step)" % (step_sites, len(STEP_SITES)))
    elif whole_sites != len(WHOLE_SITES):   # (the frames' own time without them: the pick-up indicator stays above 60 fps)
        print("oot_patches: WARNING: %d of %d frame counters found for the step's whole frames (above 60 fps a counter can stop: "
              "the pick-up indicator, the water ripples, the time of day)" % (whole_sites, len(WHOLE_SITES)))
    apply_output_size(gen, required=required)


# Output size (host/nn_applet.c hos_output_size: the Insert menu's Output resolution, 2560 x 1440 as shipped):
# - nnMain (f_81222ce0) puts the display size in the framework's create arg (+20/+24, the framework's +156/+160); the window
#   textures are made at it.
# - f_810a7b70 sets up the display-size object (B = [[0x84ca29c0]+216]) from a config (x1): its docked size list (+8, first
#   2560 x 1440) is the frame's base (B+244; the frame is the base times the graphics scale's factor, f_806702e0, capped by the
#   scale's display class: docked 3840 x 2160 at scale 0). Its first entry asks the host when it differs.
OUT_DECL = "uint32_t hos_output_size(int height);\nuint64_t hos_rt_pool_size(uint64_t game);\n"
OUT_EDITS = [
    # (the picture's 2560 x 1440 at 0x81202ee4, not f_831f3200's copy at +0xb68; nx2/oot_wide.py's widescreen size, after it,
    # stays over it: host/hos_main.c makes that one at this height)
    ("    c->x[8] = 0xa00ULL;\n    c->x[8] = (c->x[8] & ~(0xFFFFULL<<32)) | (0x5a0ULL<<32);\n"
     "{ extern volatile uint64_t hos_wide_out; const uint64_t _s = hos_wide_out; if (_s) c->x[8] = _s; }   /* (nx2/oot_wide.py: hos_wide_out) */\n"
     "    { uint64_t _b=c->x[21]; int64_t _o=20; recomp_store64(c,(_b+_o),c->x[8]); }",
     "    c->x[8] = hos_output_size(0) | ((uint64_t)hos_output_size(1) << 32);\n"
     "{ extern volatile uint64_t hos_wide_out; const uint64_t _s = hos_wide_out; if (_s) c->x[8] = _s; }   /* (nx2/oot_wide.py: hos_wide_out) */\n"
     "    { uint64_t _b=c->x[21]; int64_t _o=20; recomp_store64(c,(_b+_o),c->x[8]); }"),
    ("    { uint64_t _a=c->x[0], _b=724ULL; uint64_t _r=_a+_b; c->x[21]=_r; }\n"
     "    { uint64_t _r = ((uint64_t)0 | ((c->x[1]) << 0)); c->x[20] = _r; }\n",
     "    { uint64_t _a=c->x[0], _b=724ULL; uint64_t _r=_a+_b; c->x[21]=_r; }\n"
     "    { uint64_t _r = ((uint64_t)0 | ((c->x[1]) << 0)); c->x[20] = _r; }\n"
     "    if (hos_output_size(0) != 2560 && recomp_load32(c, c->x[20] + 8) == 2560) { recomp_store32(c, c->x[20] + 8, hos_output_size(0)); recomp_store32(c, c->x[20] + 12, hos_output_size(1)); }\n"),
    # - f_80ea2f30: the 3D's largest size, ResolutionParam's BaseResolution (or 1920 x 1080 as constants), 3/4 of 2560 x 1440;
    #   above it the game takes a smaller upscale network (1/3: 1280 x 720 at 4K). Scaled with the output.
    ("c->x[30] = 0x80ea2ffcULL; f_831cca50(c);\n"
     "    { uint64_t _b=c->x[0]; int64_t _o=0; { uint64_t _p0,_p1; recomp_ldp32(c,(_b+_o),&_p0,&_p1); c->x[24]=_p0; c->x[25]=_p1; } }\n",
     "c->x[30] = 0x80ea2ffcULL; f_831cca50(c);\n"
     "    { uint64_t _b=c->x[0]; int64_t _o=0; { uint64_t _p0,_p1; recomp_ldp32(c,(_b+_o),&_p0,&_p1); c->x[24]=_p0; c->x[25]=_p1; } }\n"
     "    if (hos_output_size(0) != 2560) { c->x[24] = (uint32_t)c->x[24] * hos_output_size(0) / 2560; c->x[25] = (uint32_t)c->x[25] * hos_output_size(1) / 1440; }\n"),
    ("    c->x[8] = 0x44f00000ULL;\n    c->x[8] &= 0xFFFFFFFFULL;\n    recomp_store32(c,c->x[19] + 3668,c->x[8]);\n"
     "    c->x[8] = 0x44870000ULL;\n    c->x[8] &= 0xFFFFFFFFULL;\n",
     "    c->x[8] = hos_output_size(0) * 3 / 4;\n    { float _f = (float)c->x[8]; uint32_t _u; memcpy(&_u, &_f, 4); c->x[8] = _u; }\n"
     "    recomp_store32(c,c->x[19] + 3668,c->x[8]);\n"
     "    c->x[8] = hos_output_size(1) * 3 / 4;\n    { float _f = (float)c->x[8]; uint32_t _u; memcpy(&_u, &_f, 4); c->x[8] = _u; }\n"),
    # - The render targets' GPU pool: 0x13100000 bytes (the graphics config's +1464, read in f_836ce9d0, which takes its storage from
    #   the "Graphics" heap and makes a physical pool and a virtual one over it: f_80c4a1c0 -> f_80c49070 -> f_80c49380 -> f_811c9ba0).
    #   Sized for 2560 x 1440: a 3840x2160 3D at the 4K output ran out of it and the next target came back null (crash in f_8005ed00,
    #   the pool's allocator, its +0x28 0x13100000). Scaled with the output's pixels (host/nn_applet.c
    #   hos_rt_pool_size: 687 MB at 3840 x 2160), at the config, so the storage and the pool agree.
    ("L_836cea54:;\n",
     "L_836cea54:;\n"
     "    if (recomp_load64(c, c->x[19] + 1464) == 0x13100000ULL) recomp_store64(c, c->x[19] + 1464, hos_rt_pool_size(0x13100000ULL));\n"),
    # - The "Graphics" heap holds it, made by f_83b7b340 with the other module heaps (twice: 0x34900000 bytes in f_83b7a2c0's first
    #   pass, then the heap kept, 0x348ffe20; it had under 16 MB to spare): grown by as much as the pool.
    ("c->x[30] = 0x83b7b440ULL; f_809df710(c);\n",
     "if (c->x[0] == 0x34900000ULL || c->x[0] == 0x348ffe20ULL) c->x[0] += hos_rt_pool_size(0x13100000ULL) - 0x13100000ULL;\n"
     "c->x[30] = 0x83b7b440ULL; f_809df710(c);\n"),
    # - f_83b7b340 then takes each module heap's use (its vtable +120) off the module's budget (the configured size, a table of slots)
    #   and aborts below zero (f_8351c280): the Graphics heap's use counts as the shipped one.
    ("{ uint64_t _t = c->x[8]; c->x[30] = 0x83b7b4e0ULL; A64_ICALL(c, _t); }\n",
     "{ uint64_t _t = c->x[8]; c->x[30] = 0x83b7b4e0ULL; A64_ICALL(c, _t); }\n"
     "{ const uint64_t _b = recomp_load64(c, c->x[21] + (c->x[22] << 3)), _g = hos_rt_pool_size(0x13100000ULL) - 0x13100000ULL; "
     "if ((_b == 0x34900000ULL || _b == 0x348ffe20ULL) && c->x[0] > _g) c->x[0] -= _g; }\n"),
    # - f_80b72340 (from the graphics init f_836cf4b0) makes a heap of what the Graphics heap can still give, which took the growth as
    #   well (0x1b6cb48 bytes as shipped, 0x1996cb48 grown) and left too little for the pool: it keeps its shipped size.
    ("c->x[30] = 0x80b723acULL; f_809df700(c);\n",
     "if (c->x[0] > hos_rt_pool_size(0x13100000ULL) - 0x13100000ULL) c->x[0] -= hos_rt_pool_size(0x13100000ULL) - 0x13100000ULL;\n"
     "c->x[30] = 0x80b723acULL; f_809df700(c);\n"),
]


def apply_output_size(gen, required=False):
    """required (the supported build's whole lift): each edit must be made, or found made, exactly once, else SystemExit: without
    one the Insert menu's Output resolution is ignored, or a 4K output runs out of the render targets' pool. Elsewhere (another
    build, part of a lift, by hand) a warning"""
    found = [0] * len(OUT_EDITS)
    for path in sorted(glob.glob(os.path.join(glob.escape(gen), "code_*.c"))):
        with open(path, encoding="utf-8", newline="") as f:
            s = f.read()
        hit = False
        for i, (old, new) in enumerate(OUT_EDITS):
            # (every place: each made one, and each old text outside a made one; a new text can hold its old one. A file with
            # both is counted for both, and its old ones are left: a second made place or a stray raw one is not once)
            made = s.count(new)
            raw = (s.replace(new, "\0") if made else s).count(old)
            found[i] += made + raw
            if raw and not made:
                s = s.replace(old, new)
                hit = True
        if hit:
            if OUT_DECL not in s:
                s = s.replace('#include "a64.h"\n', '#include "a64.h"\n' + OUT_DECL, 1)
            whole_write.write_whole(path, s, newline="")
            print("oot_patches: output size in", os.path.basename(path))
    if found != [1] * len(OUT_EDITS):
        if required:
            raise SystemExit("oot_patches: the output size places were found %s times, not once each (OUT_EDITS %s): the "
                             "lifted C no longer has the text they match" % (found, [i for i, n in enumerate(found) if n != 1]))
        print("oot_patches: WARNING: the output size places were found %s times" % found)


if __name__ == "__main__":
    apply(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work", "sa", "gen"))
