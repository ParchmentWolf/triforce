// Which of the game's network dispatches the plain stretch stands in for, and how it draws (no game, no GPU: a rule).
//
// (Triforce, 11-22, the performance audit's GPUWORK-20, after Source A's.) The game upscales its 3D with a small neural
// network every frame: fd029a317a9a4b94 from 3/4 size, 9dc98871eb7fc101 at full size, and one network of its own for each
// other share of the Render resolution row. vk_draw.cpp taau_stand_in already draws the first one's output with a
// stretch of its input (shaders/taau_upscale.comp, which undoes the network's square-root encoding) where the network
// runs on software matrix multiplies and costs most of a frame; 9dc98871 still ran every frame there (2.6 ms of GPU
// time at 2560x1440 on a mid-range AMD card, as Source A measured its like).
//
// "Off" leaves every gameplay upscale network out: its input stretched linearly into its output, no FXAA of the
// stand-in's and no history bound (the game's own SMAA has already run on the input and stays). It is opt-in
// (RX_VK_UPSCALE_OFF=1, or the lab's "upoff" phases): the picture is softer below 100% and has none of the network's
// sharpening. The networks are still compiled as before, so leaving Off again needs nothing made.
#pragma once

namespace upscale_off {

struct Choice {
    bool stand_in;   // the stretch draws the dispatch's output; the network is not dispatched
    bool temporal;   // as the stand-in was before: its history bound and FXAA. false: the plain linear stretch
    bool by_shape;   // taken for its shape alone: the caller must still see the scene's formats at both ends
};

/// listed:  the program is one RX_VK_TAAU_KEYS names (by default fd029a317a9a4b94 on software multiplies);
/// off:     the upscaler is Off;
/// by_key:  the program is one of the two gameplay networks known by key;
/// shaped:  it has a gameplay upscale's shape (a network sampling one texture into one image).
constexpr Choice choose(bool listed, bool off, bool by_key, bool shaped) {
    if (off && by_key) return {true, false, false};
    if (off && shaped && !listed) return {true, false, true};
    return {listed, true, false};
}

} // namespace upscale_off
