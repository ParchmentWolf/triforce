// (Triforce, 11-22, the performance audit's MEM-85, after Source B's idea) Texture and program releases queued for the
// replaying thread, not waited for.
//
// The game's nvnTextureFinalize and nvnProgramFinalize reach vk_replay.cpp texture_released_of and program_released_locked.
// Without the replay thread (RX_VK_ASYNC=0, the default) a release is held for the replaying thread only while a queue is
// stopped at a wait (PR 430: after the stopped work, which may still use it); otherwise the game's thread takes replay_mu,
// which a replay holds through whole submissions: the finalizing thread waited 45% of its time in Kokiri before PR 430.
//
// RX_VK_RELEASE_QUEUE=1 (OFF unless set; the lab knob relq in its phases while it is unset): every such release is pushed to
// a list under held_mu, stopped queue or not, and applied by the thread that replays next, at the start of a submission's
// replay or a present (replay_mu held there already), when no queue is stopped; with one stopped, update_blocked applies
// them after the stopped work, as PR 430's. A texture's release carries the write generation of its call, so the CPU's
// writes after the call still count as written after the release (vk_texture.cpp release_gen). The RX_VK_ASYNC job path is
// not touched. Unset, a release goes the way it went: way() is the old decision then (tests/test_release_queue.py).
//
// And a count, on by default: the releases that went the old way, their time in sync_drain and the replay's lock, the
// longest; a line every 600 releases when one of them waited 0.5 ms or more.
//
// The rule alone: no Vulkan, no game, no clock.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>

namespace release_queue {

/// RX_VK_RELEASE_QUEUE: a number other than 0 on, 0 off; unset: the lab knob relq (on only in its phases)
inline bool on(const char* env, bool knob) {
    if (env) return std::atoi(env) != 0;
    return knob;
}

/// Where a release without the replay thread goes. Now: sync_drain(1) and the replay's lock on the caller's thread, as
/// before; Held: PR 430's list, while a queue is stopped (hold: RX_VK_RELEASE_DRAIN unset; sync_waits: the event ordering
/// on); Queued: the switch's list, whatever is stopped
enum class Way { Now, Held, Queued };
inline Way way(bool queue_on, bool hold, bool sync_waits, bool blocked) {
    if (queue_on) return Way::Queued;
    return hold && sync_waits && blocked ? Way::Held : Way::Now;
}
/// The old decision, for the test: held or not
inline bool held_before(bool hold, bool sync_waits, bool blocked) { return hold && sync_waits && blocked; }

/// Whether the queued releases are applied at a submission's replay start or a present: something queued, no queue stopped
inline bool apply_now(size_t queued, int blocked) { return queued != 0 && blocked == 0; }

/// The releases that went the old way: how many, how many waited kWaitNs or more, their time, the longest
struct Waits {
    static constexpr int64_t kWaitNs = 500000;   // (0.5 ms: a replay met, not the release's own work)
    static constexpr int64_t kEvery = 600;
    int64_t n = 0, waited = 0, ns = 0, max_ns = 0, queued = 0;
    void note(int64_t took_ns) {
        n++, ns += took_ns;
        if (took_ns >= kWaitNs) waited++;
        if (took_ns > max_ns) max_ns = took_ns;
    }
    void note_queued() { queued++; }
    /// Every kEvery releases (either way) the counts start again; a line when one of them waited, or went to the switch's list
    bool due() const { return n + queued >= kEvery; }
    bool worth_a_line() const { return waited > 0 || queued > 0; }
    void reset() { *this = Waits{}; }
};

} // namespace release_queue
