// (Triforce) The all-zero upload check's reads (vk_texture.cpp upload_all_zero): which bytes of a storage it reads, split between its
// threads. tests/test_guest_holes.py.
//
// On Linux, where /dev/udmabuf is usable, the guest window is a memfd's (host/hos_main.c). A page the game never wrote is a hole
// there: it reads as zero, but a read through the shared mapping makes the kernel allocate and zero it. The check read every byte
// of a 32 MB+ storage, so the never-written 288 MB shadow map (12288 x 12288 D16) became RAM at each Hyrule Field arrival, and
// took 200-300 ms of the replay thread on a Steam Deck. fd_data_extents asks the memfd where its data is (lseek SEEK_DATA and
// SEEK_HOLE): a hole is zero by definition, and SEEK_DATA may call a hole data, never the other way round (a page in swap is
// data), so reading only the data says the same. Anywhere else, or on any failure, one extent of the whole storage.
#pragma once

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <thread>
#include <vector>
#if defined(__linux__) || defined(GUEST_HOLES_TEST)   // (the test: its own lseek)
#include <cerrno>
#include <unistd.h>
#endif

namespace mkwvk::guest_holes {

struct Extent {
    uint64_t lo, hi;   // (bytes from the storage's start)
};

inline uint64_t bytes(const std::vector<Extent>& ex) {
    uint64_t n = 0;
    for (const Extent& e : ex) n += e.hi - e.lo;
    return n;
}

/// Thread t's part of n: the extents' bytes, not their range, split into n runs of whole 4 KB (the last takes the rest); every
/// byte of the extents in exactly one part
inline std::vector<Extent> share(const std::vector<Extent>& ex, uint32_t t, uint32_t n) {
    std::vector<Extent> out;
    const uint64_t total = bytes(ex);
    if (!n || t >= n || !total) return out;
    const uint64_t per = ((total / n) + 4095) & ~4095ull;
    const uint64_t a = std::min<uint64_t>(total, (uint64_t)t * per), b = t + 1 == n ? total : std::min<uint64_t>(total, a + per);
    uint64_t at = 0;   // (bytes of the extents before e)
    for (const Extent& e : ex) {
        const uint64_t len = e.hi - e.lo, lo = std::max(a, at), hi = std::min(b, at + len);
        if (lo < hi) out.push_back({e.lo + (lo - at), e.lo + (hi - at)});
        at += len;
        if (at >= b) break;
    }
    return out;
}

/// Whether any byte of p's extents is not 0, read on nthreads threads (this one among them), each stopping once one found it
inline bool any_set(const uint8_t* p, const std::vector<Extent>& ex, uint32_t nthreads) {
    std::atomic<bool> found{false};
    if (ex.empty()) return false;
    nthreads = std::max(nthreads, 1u);
    auto part = [&](uint32_t t) {
        for (const Extent& e : share(ex, t, nthreads))
            for (uint64_t at = e.lo; at < e.hi && !found.load(std::memory_order_relaxed); at += 65536) {
                const uint64_t end = std::min<uint64_t>(e.hi, at + 65536);
                uint64_t acc = 0;
                uint64_t k = at;
                for (; k + 8 <= end; k += 8) {
                    uint64_t w;
                    std::memcpy(&w, p + k, 8);
                    acc |= w;
                }
                for (; k < end; k++) acc |= p[k];
                if (acc) found.store(true, std::memory_order_relaxed);
            }
    };
    if (nthreads > 1) {
        std::vector<std::thread> th;
        for (uint32_t t = 1; t < nthreads; t++) th.emplace_back(part, t);
        part(0);
        for (auto& x : th) x.join();
    } else {
        part(0);
    }
    return found.load();
}

#if defined(__linux__) || defined(GUEST_HOLES_TEST)   // (the test: its own lseek)
/// The data of [off, off + len) in fd, as extents from off (none: all holes). At most max extents: past them, the rest as one.
/// False when the file cannot say (a seek failed): the caller reads it all
inline bool fd_data_extents(int fd, uint64_t off, uint64_t len, std::vector<Extent>* out, size_t max = 1024) {
    out->clear();
    const uint64_t end = off + len;
    uint64_t pos = off;
    while (pos < end) {
        if (out->size() + 1 >= max) {   // (the last one: the rest, whole)
            out->push_back({pos - off, len});
            return true;
        }
        const off_t d = lseek(fd, (off_t)pos, SEEK_DATA);
        if (d < 0) {
            if (errno == ENXIO) return true;   // (no data from pos to the file's end)
            return out->clear(), false;
        }
        if ((uint64_t)d >= end) return true;
        const off_t h = lseek(fd, d, SEEK_HOLE);
        if (h < 0 || (uint64_t)h <= (uint64_t)d) return out->clear(), false;
        const uint64_t hi = std::min<uint64_t>(end, (uint64_t)h);
        out->push_back({(uint64_t)d - off, hi - off});
        pos = hi;
    }
    return true;
}
#endif

}   // namespace mkwvk::guest_holes
