// tests/test_ub_update_batch.py puts vk_replay.cpp's own UbUpdate, gpu_write, ub_batch_mode, ub_batch_line,
// flush_ub_batched and flush_ub_updates in the place of ACTUAL and runs the flush on a stand-in that records the commands
// and then applies them to memory in order. No game, no GPU. (Triforce, 11-22, the performance audit's SYNC-21.)
//
//   <exe> <scenario>   with RX_VK_UB_BATCH as the test sets it (unset: as before; 1: the batch; 2: as before, counted)
//
// Scenarios: aligned (every piece 4-byte aligned and in a pool: the old way's memory is the model's too), any (unaligned
// pieces, pieces outside the pools, a second buffer onto the first one's memory), full (the stream runs out), moved (the
// stream goes on in another buffer).
// It prints the hash of the bindings it asked for, of the memory it ended with, and its counts; with the batch it fails
// if memory is not the updates applied in stream order, if a copy's regions overlap, or if bytes written since the last
// barrier are written again.
#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <utility>
#include <vector>
#include "ub_batch.h"

static int fails = 0;
#define CHECK(x) do { if (!(x)) { if (fails++ < 12) std::printf("FAIL:%d %s\n", __LINE__, #x); } } while (0)

// ---- the stand-ins ----
using VkBuffer = int;
using VkCommandBuffer = int;
#define VK_NULL_HANDLE 0
struct VkBufferCopy { uint64_t srcOffset, dstOffset, size; };
struct BufferRef {
    VkBuffer buffer = VK_NULL_HANDLE;
    uint64_t offset = 0, size = 0;
    uint64_t address = 0;
    explicit operator bool() const { return buffer != VK_NULL_HANDLE; }
};
// (guest memory: three pools' ranges, bound as buffers 1, 2 and 3. Buffer 3 is a second buffer onto buffer 1's memory, as a
// pool's guest buffer and its mirror's are in the renderer when `alias`; else a pool of its own. Above them: outside the pools)
constexpr uint64_t kPool = 256 << 10, kBase = 0x10000000ull, kOutside = kBase + 3 * kPool, kOutsideBytes = 64 << 10;
static bool alias = false;
static std::vector<uint8_t> mem[3], cpu_only(kOutsideBytes);   // (mem[0], mem[1], mem[2]: the pools' memory)
static int mem_of(VkBuffer b) { return b == 3 && alias ? 0 : b - 1; }
static uint64_t bind_hash = 1469598103934665603ull;
static long binds = 0, cpu_writes = 0;
BufferRef gpu_buffer_bind(uint64_t gpu, uint64_t size, bool written) {
    for (uint64_t v : {gpu, size, (uint64_t)written}) bind_hash = (bind_hash ^ v) * 1099511628211ull;
    binds++;
    if (gpu < kBase || gpu + size > kOutside) return {};
    const VkBuffer b = (VkBuffer)((gpu - kBase) / kPool) + 1;
    return {b, (gpu - kBase) % kPool, size, 0};
}
int guest_cpu_write(uint64_t gpu, const void* src, uint64_t n) {   // (at record time: before any command runs)
    cpu_writes++;
    if (gpu >= kOutside) std::memcpy(cpu_only.data() + (gpu - kOutside), src, n);
    else std::memcpy(mem[mem_of((VkBuffer)((gpu - kBase) / kPool) + 1)].data() + (gpu - kBase) % kPool, src, n);
    return 1;
}
// (the recording's stream: buffers 100, 101, ...; `stream_room` bytes each; `stream_moves`: it goes on in the next one when full)
static uint64_t stream_room = 8 << 20, stream_used = 0;
static bool stream_moves = false;
static long moves = 0;
static std::vector<std::vector<uint8_t>> streams(1);
BufferRef stream_copy(const void* src, uint64_t n) {
    uint64_t at = (stream_used + 255) & ~255ull;
    if (at + n > stream_room) {
        if (!stream_moves || n > stream_room) return {};
        streams.emplace_back(), stream_used = 0, at = 0, moves++;
    }
    std::vector<uint8_t>& s = streams.back();
    if (s.size() < at + n) s.resize(at + n);
    std::memcpy(s.data() + at, src, n);
    stream_used = at + n;
    return {(VkBuffer)(100 + streams.size() - 1), at, n, 0};
}
struct Cmd {
    int kind = 0;   // 0 a barrier, 1 an update, 2 a copy
    VkBuffer src = 0, dst = 0;
    uint64_t offset = 0;
    std::vector<uint8_t> data;
    std::vector<VkBufferCopy> regions;
};
static std::vector<Cmd> cmds;
void full_barrier(VkCommandBuffer, const char* = "") { cmds.push_back(Cmd{}); }
void vkCmdUpdateBuffer(VkCommandBuffer, VkBuffer b, uint64_t offset, uint64_t n, const void* data) {
    CHECK(n <= 65536 && !(n & 3) && !(offset & 3));
    Cmd c;
    c.kind = 1, c.dst = b, c.offset = offset, c.data.assign((const uint8_t*)data, (const uint8_t*)data + n);
    cmds.push_back(std::move(c));
}
void vkCmdCopyBuffer(VkCommandBuffer, VkBuffer src, VkBuffer dst, uint32_t n, const VkBufferCopy* regions) {
    CHECK(n > 0 && src >= 100 && dst >= 1 && dst <= 3);
    Cmd c;
    c.kind = 2, c.src = src, c.dst = dst, c.regions.assign(regions, regions + n);
    cmds.push_back(std::move(c));
}
struct GprofSpan {
    int items = 1;
    uint64_t bytes = 0;
    GprofSpan(VkCommandBuffer, const char*) {}
};
struct UbReadGuard { UbReadGuard() {} };
namespace lab_ab { bool on(const char*) { return false; } }
static std::string last_line;
void logf(const char* fmt, ...) {
    char line[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    last_line = line;
}

/* ACTUAL-1 */
std::deque<UbUpdate> ub_updates;
size_t ub_first_of_recording = 0;
/* ACTUAL-2 */

// ---- the queue: the commands applied in order, and what they may not do ----
static long unordered = 0, copies = 0, regions_n = 0, updates_n = 0, barriers = 0;
static void run_commands() {
    std::vector<std::pair<uint64_t, uint64_t>> since[3];   // (per memory: [at, end) written since the last barrier)
    const auto wrote = [&](int m, uint64_t at, uint64_t end) {
        for (const auto& w : since[m])
            if (at < w.second && w.first < end) { unordered++; break; }
        since[m].push_back({at, end});
    };
    for (const Cmd& c : cmds) {
        if (c.kind == 0) {
            barriers++;
            for (auto& s : since) s.clear();
        } else if (c.kind == 1) {
            updates_n++;
            wrote(mem_of(c.dst), c.offset, c.offset + c.data.size());
            std::memcpy(mem[mem_of(c.dst)].data() + c.offset, c.data.data(), c.data.size());
        } else {
            copies++, regions_n += (long)c.regions.size();
            const std::vector<uint8_t>& s = streams[(size_t)(c.src - 100)];
            for (const VkBufferCopy& r : c.regions) {
                CHECK(r.srcOffset + r.size <= s.size() && r.dstOffset + r.size <= kPool);
                wrote(mem_of(c.dst), r.dstOffset, r.dstOffset + r.size);   // (a region over another of its copy is counted here too)
                std::memcpy(mem[mem_of(c.dst)].data() + r.dstOffset, s.data() + r.srcOffset, r.size);
            }
        }
    }
    cmds.clear();
}
static uint64_t rnd_state = 0xA0761D6478BD642Full;
static uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}

int main(int argc, char** argv) {
    const std::string scenario = argc == 2 ? argv[1] : "";
    const bool aligned = scenario == "aligned", full = scenario == "full", moved = scenario == "moved";
    if (!(aligned || full || moved || scenario == "any")) return std::printf("a known scenario\n"), 1;
    alias = scenario == "any";
    const char* e = std::getenv("RX_VK_UB_BATCH");
    const bool batched = e && std::atoi(e) == 1;
    for (auto& m : mem) m.assign(kPool, 0xEE);
    std::vector<uint8_t> model[3] = {mem[0], mem[1], mem[2]}, model_cpu = cpu_only;
    long flushes = 0, model_differs = 0, shape_wrong = 0;
    for (int f = 0; f < 600; f++) {
        // a recording's updates: a few behind the window (flushed by an earlier part) and a few past its limit
        const size_t before = rnd() % 3, n = 1 + rnd() % 90, after = rnd() % 3;
        ub_updates.clear();
        for (size_t i = 0; i < before + n + after; i++) {
            UbUpdate u{};
            const uint64_t r = rnd();
            uint64_t size = r % 13 == 0 ? 60000 + rnd() % 80000 : 16 + rnd() % 600, at;
            const int where = scenario == "any" ? (int)(rnd() % 8) : (int)(rnd() % 2);   // (0, 1: pools 1, 2; 2: the second buffer onto 1; 7: outside)
            if (where == 7) {
                size = std::min<uint64_t>(size, 4096);
                at = kOutside + rnd() % (kOutsideBytes - size);
            } else {
                // (near the start of its pool, so that updates of one flush often share bytes)
                const uint64_t pool = where == 2 ? 2 : (uint64_t)(where & 1);
                at = kBase + pool * kPool + rnd() % (rnd() % 4 == 0 ? kPool - size : 6000);
            }
            if (scenario != "any") size = (size + 3) & ~3ull, at &= ~3ull;
            if (at + size > kOutside && at < kOutside) at = kOutside - size;
            u.dst = at, u.bytes.resize(size);
            for (auto& b : u.bytes) b = (uint8_t)rnd();
            ub_updates.push_back(std::move(u));
        }
        ub_first_of_recording = before;
        const size_t lim = after ? before + n : (rnd() % 2 ? SIZE_MAX : before + n);
        for (size_t i = before; i < before + n; i++) {   // (the model: the window's updates, in stream order)
            const UbUpdate& u = ub_updates[i];
            if (u.dst >= kOutside) std::memcpy(model_cpu.data() + (u.dst - kOutside), u.bytes.data(), u.bytes.size());
            else {
                const int m = mem_of((VkBuffer)((u.dst - kBase) / kPool) + 1);
                std::memcpy(model[m].data() + (u.dst - kBase) % kPool, u.bytes.data(), u.bytes.size());
            }
        }
        streams.assign(1, {}), stream_used = 0;
        stream_room = full ? 4096 + rnd() % 30000 : moved ? 2048 + rnd() % 9000 : 8 << 20;
        stream_moves = moved;
        flush_ub_updates(1, lim);
        flushes++;
        // the flush begins and ends with a barrier, whatever is between
        if (cmds.size() < 2 || cmds.front().kind != 0 || cmds.back().kind != 0) shape_wrong++;
        if (!batched)
            for (size_t i = 1; i + 1 < cmds.size(); i++) shape_wrong += cmds[i].kind != 1;   // (as before: updates alone between the two)
        run_commands();
        if (mem[0] != model[0] || mem[1] != model[1] || mem[2] != model[2] || cpu_only != model_cpu) {
            model_differs++;
            if (batched || aligned || full || moved) {   // (the next flush starts from the model: one failure is one flush's)
                for (int m = 0; m < 3; m++) mem[m] = model[m];
                cpu_only = model_cpu;
            } else {   // (as before with unaligned pieces: the CPU's writes at record time are out of order; go on from what it left)
                for (int m = 0; m < 3; m++) model[m] = mem[m];
                model_cpu = cpu_only;
            }
        }
    }
    CHECK(shape_wrong == 0);
    if (batched) {
        CHECK(model_differs == 0);   // (memory is the updates in stream order)
        CHECK(unordered == 0);       // (no copy's regions overlap; no byte written twice with no barrier between)
        CHECK(copies > 0 && regions_n > copies);
        if (scenario == "any" || aligned) CHECK(updates_n == 0);
        if (full) CHECK(updates_n > 0);     // (pieces written singly when the stream is full)
        if (moved) CHECK(moves > 0);   // (the stream went on in another buffer: a copy a source)
    } else {
        CHECK(copies == 0 && updates_n > 0 && barriers == 2 * flushes);
        if (scenario != "any") CHECK(model_differs == 0);   // (aligned pieces in pools: the old way's memory is the model's)
    }
    uint64_t h = 1469598103934665603ull;
    for (int m = 0; m < 3; m++)
        for (uint8_t b : mem[m]) h = (h ^ b) * 1099511628211ull;
    for (uint8_t b : cpu_only) h = (h ^ b) * 1099511628211ull;
    std::printf("binds %ld %016llx\nmemory %016llx\n", binds, (unsigned long long)bind_hash, (unsigned long long)h);
    std::printf("counts: %ld flushes, %ld barriers, %ld updates, %ld copies of %ld regions, %ld writes on the CPU, %ld unordered, %ld flushes off the model\n",
                flushes, barriers, updates_n, copies, regions_n, cpu_writes, unordered, model_differs);
    std::printf("line: %s\n", last_line.c_str());
    return fails != 0;
}
