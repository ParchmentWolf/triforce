// (Triforce, 11-21, the upscaler audit's UPS-03) What a redraw of the stored draws has to set before it draws.
//
// The stored draws are drawn again into the motion vectors in one pass (vk_temporal.cpp capture_motion), about 900 of
// them a frame in the owner's log of 11-21. Each one set the primitive topology, the primitive restart and the index
// buffer before it drew, whatever the draw before had set: three commands a draw beside its push constants and the draw
// itself, and nearly every draw of the scene is a list of triangles without restart. Dynamic state and the index buffer
// stay as they were set until they are set again in the same command buffer, so a command that would set what is set
// already says nothing new. Here is what the pass has set so far, and whether a draw's own differs from it.
//
// A pass starts knowing nothing (a new Pass): its first draw sets everything, as before.
// RX_VK_REDRAW_STATE=0: every draw sets all three, as before (every()).
//
// No Vulkan: tests/test_redraw_state.py compiles this.
#pragma once
#include <cstdint>
#include <cstdlib>

namespace redraw_state {

/// RX_VK_REDRAW_STATE (value, null when unset): 0, every draw sets its state whatever is set, as before
inline bool every(const char* value) { return value && *value && std::atoi(value) == 0; }

/// What one pass has set so far, from its first draw on
struct Pass {
    bool all = false;   // (every(): each asks true)
    bool have_topology = false, have_restart = false, have_index = false;
    uint32_t topology = 0;
    bool restart = false;
    uint64_t index_buffer = 0, index_offset = 0;
    uint32_t index_type = 0;
    uint64_t set = 0, left = 0;   // (commands recorded, and left out: for a count in the log)
};

/// Whether the topology is to be set for a draw of `topology` (and it is then what the pass has set)
inline bool topology(Pass& p, uint32_t topology) {
    if (!p.all && p.have_topology && p.topology == topology) return p.left++, false;
    p.have_topology = true, p.topology = topology;
    return p.set++, true;
}

/// The same for primitive restart
inline bool restart(Pass& p, bool restart) {
    if (!p.all && p.have_restart && p.restart == restart) return p.left++, false;
    p.have_restart = true, p.restart = restart;
    return p.set++, true;
}

/// The same for an indexed draw's index buffer: the buffer's handle as a number, the offset into it and the index type,
/// all three the same as the one bound
inline bool index(Pass& p, uint64_t buffer, uint64_t offset, uint32_t type) {
    if (!p.all && p.have_index && p.index_buffer == buffer && p.index_offset == offset && p.index_type == type)
        return p.left++, false;
    p.have_index = true, p.index_buffer = buffer, p.index_offset = offset, p.index_type = type;
    return p.set++, true;
}

}   // namespace redraw_state
