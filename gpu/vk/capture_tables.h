// (Triforce, 11-21, the upscaler audit's UPS-02) The stored draws' two tables, kept from one frame to the next.
//
// While NVIDIA DLSS, AMD FSR 4 or AMD FSR 3.1 upscales, every plain draw into the scene stores its positions and is drawn
// again into the motion vectors (vk_temporal.cpp capture_motion). Two tables go with that, both filled again every frame:
// the draws of a model so far this frame (which of them a draw is: the n-th this frame is the n-th the frame before), and
// the frame before's draws by their key (where each one's positions of that frame are). Both were std::unordered_map,
// emptied and filled each frame: a node from the heap for every entry and back to it a frame later, about 1,400 of each
// a frame in the owner's log of 11-21 ("captured motion ... of 1444 stored a frame ... 0.650 ms CPU a frame"), on the
// thread that records the frame. Here they keep their memory: the count in one open-addressed array (flat_map.h) that is
// emptied in place, the frame before's draws in two lists that take turns, found through such an array. A frame of about
// the size of the one before takes nothing from the heap.
//
// RX_VK_CAPTURE_TABLES=0: std::unordered_map again, a node an entry, as before (kept()).
//
// No Vulkan: tests/test_capture_tables.py compiles this and counts the heap's calls.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <unordered_map>
#include <utility>
#include <vector>

#include "flat_map.h"

namespace capture_tables {

/// RX_VK_CAPTURE_TABLES (value, null when unset): kept unless it is 0
inline bool kept(const char* value) { return !value || !*value || std::atoi(value) != 0; }

/// An array emptied for the next frame: in place, so the frame fills it without the heap; given back when it is far
/// larger than what the frame put in it (a frame of many draws once, then few), so emptying it does not walk all of that
template <class K, class V>
inline void empty_for_next(FlatMap<K, V>& m) {
    if (m.capacity() > 8 * (m.size() + 512)) m.clear();
    else m.reset();
}

/// The room a frame's list is given at its start: the frame before's count (kept), so it grows once and not a dozen times
/// from nothing; 0, as before, with the switch off
inline size_t room(size_t taken, bool keep) { return keep ? taken : 0; }

/// How many of a model's draws came so far this frame
class Nth {
public:
    explicit Nth(bool keep = true) : keep_(keep) {}
    /// The draws of `model` before this one, which is counted
    int next(uint64_t model) { return keep_ ? flat_[model]++ : node_[model]++; }
    void clear() {
        if (keep_) empty_for_next(flat_);
        else node_.clear();
    }
    size_t size() const { return keep_ ? flat_.size() : node_.size(); }

private:
    bool keep_;
    FlatMap<uint64_t, int> flat_;
    std::unordered_map<uint64_t, int> node_;
};

/// A frame's entries by key, and the frame before's: turn() makes what was put since the last turn the frame before's,
/// put() notes one of this frame's (the last with a key stands), before() finds the frame before's
template <class V>
class Before {
public:
    explicit Before(bool keep = true) : keep_(keep) {}
    void turn() {
        if (!keep_) {
            node_old_ = std::move(node_now_);
            node_now_.clear();
            return;
        }
        std::swap(now_, old_), std::swap(now_at_, old_at_);
        now_.clear();   // (its memory kept)
        empty_for_next(now_at_);
    }
    void put(uint64_t key, const V& v) {
        if (!keep_) {
            node_now_[key] = v;
            return;
        }
        uint32_t& at = now_at_[key];   // (the entry's place in now_, plus one: 0 is none yet)
        if (at) now_[at - 1] = v;
        else now_.push_back(v), at = (uint32_t)now_.size();
    }
    /// The frame before's entry of `key`, null when it had none: good until the next turn() or clear()
    const V* before(uint64_t key) {
        if (!keep_) {
            const auto it = node_old_.find(key);
            return it == node_old_.end() ? nullptr : &it->second;
        }
        const auto* s = old_at_.find(key);
        return s ? &old_[s->second - 1] : nullptr;
    }
    /// Nothing of either frame (the chain let go: its memory too)
    void clear() {
        std::vector<V>().swap(now_), std::vector<V>().swap(old_);
        now_at_.clear(), old_at_.clear();
        node_now_.clear(), node_old_.clear();
    }
    size_t size() const { return keep_ ? now_.size() : node_now_.size(); }

private:
    bool keep_;
    std::vector<V> now_, old_;
    FlatMap<uint64_t, uint32_t> now_at_, old_at_;
    std::unordered_map<uint64_t, V> node_now_, node_old_;
};

}   // namespace capture_tables
