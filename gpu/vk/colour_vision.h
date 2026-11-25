// ((Triforce) 11-24) The Display tab's Colour vision correction (opts.colour_vision): 0 Off, the default (the picture as the
// game makes it), 1 Protan, 2 Deutan (red-green), 3 Tritan (blue-yellow). The finished SDR picture is corrected at the window's
// size by shaders/colour_vision.comp (vk_framegen.cpp framegen_scale), before the HDR10 expansion and before the overlays.
#pragma once

namespace mkwvk::colour_vision {

constexpr bool enabled(int mode) { return mode >= 1 && mode <= 3; }

} // namespace mkwvk::colour_vision
