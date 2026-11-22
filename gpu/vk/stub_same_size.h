// A gameplay upscale network that cannot run: its input drawn into its output, also where the two are one size (no
// game, no GPU: the rule; vk_draw.cpp upscale_stub).
//
// (Triforce, 11-22, the performance audit's GPUWORK-21, after Source B's and Source A's.) The game draws its 3D through
// a small network every frame: fd029a317a9a4b94 from 3/4 size, 9dc98871eb7fc101 at full size. upscale_stub stands in
// for a network that was left out or did not translate (RX_VK_NO_F16, a card or driver that cannot build it), by
// drawing the network's input into its output. It declined a dispatch whose output is no larger than its input, as not
// an upscale's last pass, so at Render resolution 100% a 9dc98871 that could not run was skipped whole: nothing wrote
// the picture, a black 3D under the HUD. Source B turns its bypass on by itself where its network cannot be built, and
// Source A lets that pass through for the gameplay networks.
//
// So, for the two gameplay networks only:
//   - an output as large as its input is accepted too (any other program is still declined: a pass of that shape that
//     is no gameplay network is not an upscale's last one);
//   - both take the typed upscale first, which reads the scene's shared-exponent picture as what it is and undoes the
//     network's square-root encoding (shaders/taau_upscale.comp). It was fd029a317a9a4b94's alone, so a 9dc98871 that
//     upscaled went to the blit, which copies the encoded bits as they lie;
//   - the blit, where the typed upscale cannot be made, warns of wrong colours for both.
// The stand-in looks like the upscaler Off (GPUWORK-20): softer, none of the network's anti-aliasing. Only the path of
// a network that cannot run changes; where it runs, nothing does.
//
// RX_VK_STUB_SAME_SIZE=0: the decline and the first network alone in the typed upscale, as before.
// RX_VK_NO_UPSCALE_STUB still turns the whole stub off.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace stub_same_size {

/// RX_VK_STUB_SAME_SIZE: on unless set to 0
inline bool on(const char* env) {
    return !env || std::atoi(env) != 0;
}

/// Whether the stub takes a dispatch by its sizes: an output larger than its input, or (the rule on) a gameplay
/// network's as large as it. An output smaller than its input never
constexpr bool sized(uint64_t out_area, uint64_t in_area, bool gameplay, bool on) {
    return out_area > in_area || (on && gameplay && out_area == in_area && out_area != 0);
}

/// Whether the typed upscale is tried first: any program that is not a gameplay network, the 3/4 network, and (the
/// rule on) the other gameplay network too
constexpr bool typed(bool gameplay, bool taau, bool on) {
    return !gameplay || taau || on;
}

/// Whether the blit that follows a typed upscale that could not be made warns of wrong colours: the 3/4 network's, and
/// (the rule on) every gameplay network's
constexpr bool warns(bool gameplay, bool taau, bool on) {
    return taau || (on && gameplay);
}

} // namespace stub_same_size
