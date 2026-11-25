// (Triforce, 11-23) Evil HD: one Graphics row (opts.evil_hd, saved as evil_hd) for a powerful PC, the owner's "for the people
// that have beefy systems ... a single on off switch". It raises what the renderer already has, not the resolution: while on,
// these take the place of the rows below it (each row keeps its own value, back when Evil HD is off), as plain functions with
// no Vulkan and no menu, so that tests/test_evil_hd.py can run them.
//
// - Anti-aliasing: SMAA at its Ultra preset (aa_rows.h SMAA) in place of the game's own; vk_aa.cpp choice_now. As the row,
//   not while DLSS, DLAA or FSR smooth the edges themselves, nor under N64 Classic. Changes at once.
// - Texture filtering: 16x (opts.aniso 4) on the samplers the row reaches; vk_draw.cpp sampler_for. Changes at once.
// - Texture detail: Full (tex_detail.h's row value 1), every texture whole; vk_menu.cpp, the value at the start. From the next
//   start, as the row.
// - The foliage in the sun's far shadow cascades as the game draws it: neither foliage_shadow.h cut (the cull from layer 1, the
//   2 x 2 shading rate from layer 2); vk_draw.cpp draw_cull and draw_rate. Changes at once (both are dynamic state).
// - Ambient occlusion: vk_aa.cpp ao_after (shaders/evil_ao.comp, evil_ao_apply.comp), from the scene's depth
//   (vk_temporal.cpp temporal_ao_camera), over the picture where the game's SMAA composition (or the row's stand-in) stores
//   it: after the tone mapping, before the gameplay upscale and the HUD. Not with DLSS or FSR (no composition to stand in
//   for). RX_VK_EVIL_AO=0 leaves it out, "radius,strength,far" tunes it; RX_VK_EVIL_AO_SHOW=1 shows it alone.
// - Left out on purpose (11-23): a texture LOD bias at native size (the lab's FSR runs showed 5-8 % more shimmer with one,
//   and 16x filtering gives the sharpness); larger characters' shadow maps (they live in the game's own target heap, which
//   has no room to give: sharpen_rules.h, host/shadow_slot.h); draw distance, grass density and the sun's cascade size (the
//   game's own, in code not mapped yet).
//
// RX_VK_EVIL_FLIP=<presents>: the lab's before and after, Evil HD the other way every that many presents (vk_menu.cpp
// evil_hd_now, which every one of these reads).
//
// RX_VK_AA and RX_VK_TEX_DETAIL still go over this for a run's A/B, as they go over the rows; the foliage switches do not
// (Evil HD on: the game's foliage shadows whatever they say).
#pragma once

namespace mkwvk::evil_hd {

constexpr int kAa = 3;          // (aa_rows.h SMAA, "SMAA Ultra")
constexpr int kAniso = 4;       // (16x)
constexpr int kTexDetail = 1;   // (tex_detail.h's row: Full)

/// The Anti-aliasing row's value as it applies: SMAA Ultra while Evil HD is on, else the row's
constexpr int aa(int evil, int row) { return evil ? kAa : row; }
/// The Texture filtering row's value as it applies: 16x while Evil HD is on, else the row's
constexpr int aniso(int evil, int row) { return evil ? kAniso : row; }
/// The Texture detail row's value at the start as it applies: Full while Evil HD is on, else the row's
constexpr int tex_detail(int evil, int row) { return evil ? kTexDetail : row; }
/// The far foliage shadow cuts' first layer as it applies (foliage_shadow.h: -1 none): none while Evil HD is on, else the switch's
constexpr int foliage_from(int evil, int from) { return evil ? -1 : from; }

}  // namespace mkwvk::evil_hd
