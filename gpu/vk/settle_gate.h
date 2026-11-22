// (Triforce, 11-22, the performance audit's SYNC-29, after Source A's) A CPU read looks at the stopped queues only after a
// new CPU signal. A read that settles (vk_replay.cpp sync_settle: the stopped queues whose waits are met go on, none forced)
// takes sync_order_mu whenever a queue is stopped, and that lock is held through whole replays and presents: the readback's
// look (RX_VK_RB_SETTLE, off) and the two looks invalidate makes for a range a texture may be in.
//
// What can make a stopped queue's wait met:
//   a signal in the stream  replayed by a thread that holds sync_order_mu, and every such holder runs schedule() and ends its
//                           burst (burst_end: finish_recording) before it lets the lock go: it looked itself;
//   a signal of the CPU's   event_signal_queued: queued, then counted (signals);
//   a plain store           into the memory of an event nothing has set yet (the wait reads its value from guest memory,
//                           event_value_in): not seen by anything, so such a wait keeps every look (wait_in_memory).
// So a look is needed only while a queue is stopped and the CPU has signalled since the last look, or a stopped queue waits
// on an event read from memory. A look notes the signals' count at its start (burst_begin) and publishes it once its recording
// is finished (burst_end, after finish_recording): a reader that sees signals == settled finds the work those signals let on
// recorded. Publishing the count as it is at the look's END would cover a signal that came after the look's schedule() and
// was never acted on; counting a signal BEFORE it is queued would let a look publish it without having seen it. The test runs
// both mistakes and finds them.
//
// RX_VK_SETTLE_GATE: unset or 0, no gate (every look as before); 1 the readback's look (the one RX_VK_RB_SETTLE turns on);
// 2 the texture sites' looks too. Those two order the exposure meter's readback: the trial that skipped them outright made
// the Market flicker at once, and Source A left them ungated, so 2 is new ground and needs the lab's flicker count. The lab
// knobs settlegate (1) and texgate (2) in their phases. tests/test_settle_gate.py
#pragma once
#include <cstdint>

namespace mkwvk::settle_gate {

/// The sites that settle
enum Site { kReadback = 0, kTexture = 1, kSites = 2 };

/// RX_VK_SETTLE_GATE's text: "1" and "2"; unset, empty, "0" and anything else: 0, no gate
inline int level(const char* text) {
    if (!text || !text[0] || text[1]) return 0;
    return text[0] == '1' ? 1 : text[0] == '2' ? 2 : 0;
}
/// The level in force: the variable's, raised by the lab knobs in their phases
inline int level_now(int env, bool knob_settlegate, bool knob_texgate) {
    int l = env;
    if (knob_settlegate && l < 1) l = 1;
    if (knob_texgate && l < 2) l = 2;
    return l;
}
/// Whether a site's look goes through the gate at this level
inline bool gated(int level, int site) { return site == kReadback ? level >= 1 : level >= 2; }
/// Whether a gated site looks: a queue stopped, and a CPU signal since the last look or a stopped queue waiting on an event
/// whose value is read from guest memory
inline bool look(bool blocked, uint64_t signals, uint64_t settled, bool wait_in_memory) {
    return blocked && (signals != settled || wait_in_memory);
}
/// The whole decision of a site: 0 nothing to do (no queue stopped: as before), 1 look, 2 skipped by the gate
enum What { kNothing = 0, kLook = 1, kSkip = 2 };
inline int decide(int level, int site, bool blocked, uint64_t signals, uint64_t settled, bool wait_in_memory) {
    if (!blocked) return kNothing;
    if (gated(level, site) && !look(true, signals, settled, wait_in_memory)) return kSkip;
    return kLook;
}

} // namespace mkwvk::settle_gate
