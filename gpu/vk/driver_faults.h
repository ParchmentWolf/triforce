// Programs the driver faulted on, kept out of it, and one build of a program at a time (no game, no GPU: the rules and the
// gate; vk_draw.cpp fault_quarantine, build_graphics, guarded_graphics). Apart from Vulkan so that
// tests/test_driver_faults.py runs it alone, on many made-up PCs.
//
// (Triforce, 11-22, the performance audit's PIPE-57, after Source A's.) The guards catch a fault inside the driver's
// compiler (vk_draw.cpp guarded_graphics), and a fault during the start's own shader work starts the game again
// (driver_fault_restart). Nothing remembered the program: the next start asked the driver for it again, faulted again and
// restarted again, and in play a second thread could ask for the same program while the driver was still inside the
// first. Source A saw that on AMD's Windows driver (an RX 6800 XT): in a freeze, three threads sat in the driver on two
// programs' builds while the presenting thread waited for one of them; a preparation stuck at "6625 of 6627, nothing
// finished for 30 s" took 32.5 s, and 4.2 s with three faulted programs kept out on the first run, 2.3 s after. Triforce
// has the same class of report: "two of 4926 on an RX 5700 XT, stuck at 99%".
//
// What. On AMD's own Windows driver (or everywhere with RX_VK_DRIVER_FAULTS=2):
// - a program whose pipeline build faulted in the driver is not asked of the driver again this run, and its key goes to
//   triforce_driver_faults.txt beside the executable, one line under the vendor and the driver's version, written by the
//   fault's handler before the restart can end the process (so a start that faults does not fault again); later starts
//   with that driver skip those programs, and say so once (delete the file to try again; another driver version ignores
//   the lines);
// - one build of a program at a time: a second waits at the gate, outside the driver, and a probe that asks the caches
//   only is told a compile is required.
// Elsewhere (NVIDIA's, Intel's, Mesa's drivers, AMD's on Linux) nothing of it runs, as before: the NVIDIA fault of 11-13
// was a race in the driver, not a bad program. RX_VK_DRIVER_FAULTS=0: nowhere.
#pragma once

#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <string>
#include <unordered_set>
#include <vector>

namespace driver_faults {

/// RX_VK_DRIVER_FAULTS: 0 off, 1 (unset) AMD's Windows driver, 2 every driver
inline int mode(const char* env) {
    if (!env || !*env) return 1;
    const int v = std::atoi(env);
    return v <= 0 ? 0 : v >= 2 ? 2 : 1;
}
/// Whether the quarantine, its file and the gate are on: mode 2 anywhere, mode 1 on Windows with AMD's own driver
/// (VK_DRIVER_ID_AMD_PROPRIETARY)
inline bool on(int mode, bool windows, bool amd_proprietary) {
    return mode >= 2 || (mode == 1 && windows && amd_proprietary);
}

inline constexpr int kLine = 35;   // ("vvvvvvvv dddddddd kkkkkkkkkkkkkkkk\n")

/// One line of the file into out (kLine bytes and a 0): made without the C library, as the fault's handler makes it
inline int line(char* out, uint32_t vendor, uint32_t driver, uint64_t key) {
    static const char hex[] = "0123456789abcdef";
    int n = 0;
    for (int i = 7; i >= 0; i--) out[n++] = hex[(vendor >> (4 * i)) & 0xF];
    out[n++] = ' ';
    for (int i = 7; i >= 0; i--) out[n++] = hex[(driver >> (4 * i)) & 0xF];
    out[n++] = ' ';
    for (int i = 15; i >= 0; i--) out[n++] = hex[(key >> (4 * i)) & 0xF];
    out[n++] = '\n';
    out[n] = 0;
    return n;
}
/// The keys of the file's lines for this vendor and driver version; another's, and a broken line, are passed over
inline std::vector<uint64_t> parse(const std::string& text, uint32_t vendor, uint32_t driver) {
    std::vector<uint64_t> keys;
    const auto hexval = [](const std::string& s, size_t at, int digits, uint64_t* v) {
        if (at + (size_t)digits > s.size()) return false;
        uint64_t x = 0;
        for (int i = 0; i < digits; i++) {
            const char c = s[at + i];
            const int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
            if (d < 0) return false;
            x = x << 4 | (uint64_t)d;
        }
        *v = x;
        return true;
    };
    size_t at = 0;
    while (at < text.size()) {
        size_t end = text.find('\n', at);
        if (end == std::string::npos) end = text.size();
        std::string l = text.substr(at, end - at);
        if (!l.empty() && l.back() == '\r') l.pop_back();
        uint64_t v = 0, d = 0, k = 0;
        if (l.size() == (size_t)kLine - 1 && l[8] == ' ' && l[17] == ' ' && hexval(l, 0, 8, &v) && hexval(l, 9, 8, &d) &&
            hexval(l, 18, 16, &k) && v == vendor && d == driver)
            keys.push_back(k);
        at = end + 1;
    }
    return keys;
}

/// The run's quarantine and the gate: begin before a program's build, end after it (with whether it faulted)
class Quarantine {
public:
    enum class Begin { Go, Busy, Faulted };
    void load(const std::vector<uint64_t>& keys) {
        std::lock_guard lk(mu_);
        bad_.insert(keys.begin(), keys.end());
    }
    /// Faulted: not asked of the driver. Busy: another build of it is inside the driver and the caller may not wait (a
    /// probe of the caches). Go: this build may go in; the caller ends it with end(). may_wait: wait at the gate instead
    Begin begin(uint64_t key, bool may_wait) {
        std::unique_lock lk(mu_);
        for (;;) {
            if (bad_.count(key)) return Begin::Faulted;
            if (!busy_.count(key)) break;
            if (!may_wait) return Begin::Busy;
            cv_.wait(lk);
        }
        busy_.insert(key);
        return Begin::Go;
    }
    /// True when it faulted now for the first time
    bool end(uint64_t key, bool faulted) {
        bool fresh = false;
        {
            std::lock_guard lk(mu_);
            busy_.erase(key);
            if (faulted) fresh = bad_.insert(key).second;
        }
        cv_.notify_all();
        return fresh;
    }
    bool faulted(uint64_t key) const {
        std::lock_guard lk(mu_);
        return bad_.count(key) != 0;
    }
    size_t count() const {
        std::lock_guard lk(mu_);
        return bad_.size();
    }

private:
    mutable std::mutex mu_;
    std::condition_variable cv_;
    std::unordered_set<uint64_t> bad_, busy_;
};

}   // namespace driver_faults
