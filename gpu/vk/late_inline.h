// (Triforce, 11-22, the performance audit's MEM-80, after Source B's) Which of take_capture's no-wait rules for late pages run.
//
// A late page is one the CPU wrote while a submission still on the GPU writes it back (vk_memory.cpp capture_make). By default
// every late page is waited for (RX_VK_LATE_QUEUE: at the queue's next submit) and taken again. RX_VK_LATE_NEW=1 (the lab
// knob latenew) turns four rules on that take the wait away from some of them: pages of pools with no mirror skipped, pages
// with the bytes they were last synced with left as they are, pages written back in part synced in their other parts (the
// partial rule, late_partial), pages written back whole put off. Each brought brightness steps back at the Castle Town save.
//
// RX_VK_LATE_INLINE=1 (the lab knob lateinline), OFF unless set: the partial rule ALONE, Source B's analogue (the CPU's
// bytes go in, the GPU's ranges stay the GPU's, nothing waits); the other three stay off, and the pages they would take
// (no mirror, texture storage, whole write-backs, unknown ranges) are waited for as before.
//
// And the partial rule asks which ranges are still on the GPU against the GPU's progress capture_make read before its
// copies, not a second read at the take: a write-back that landed between the copy and the take is then still counted in
// flight, so its range is not synced from the older copy (the bug Source B fixed with the same change). This is so under
// RX_VK_LATE_NEW too.
//
// The rule alone: no Vulkan, no game. tests/test_late_inline.py.
#pragma once
#include <cstdlib>

namespace late_inline {

/// RX_VK_LATE_INLINE: a number other than 0 on, 0 off; unset: the lab knob lateinline (on only in its phases)
inline bool on(const char* env, bool knob) {
    if (env) return std::atoi(env) != 0;
    return knob;
}

struct Rules {
    bool any = false;     // (any rule: the late pages looked at one by one; else every one waited for, as by default)
    bool skip = false;    // (a page of a pool with no mirror: not waited for)
    bool same = false;    // (a page with the bytes it was last synced with: left as it is)
    bool part = false;    // (a page written back in part: its other parts synced, no wait)
    bool defer = false;   // (a page written back whole: put off)
};
/// late_new: RX_VK_LATE_NEW or its knob; inline_on: on() above; same_on, part_on, defer_on: RX_VK_LATE_SAME, RX_VK_LATE_PART,
/// RX_VK_LATE_DEFER as read today (on, on, off unless set)
inline Rules rules(bool late_new, bool inline_on, bool same_on, bool part_on, bool defer_on) {
    Rules r;
    r.any = late_new || inline_on;
    r.skip = late_new;
    r.same = late_new && same_on;
    r.part = r.any && part_on;
    r.defer = late_new && defer_on;
    return r;
}

} // namespace late_inline
