// (Triforce, 11-22, the performance audit's THREAD-68, after Source B's) The lock census: who holds the lock a thread waits for.
//
// The log has totals of the waits for the renderer's locks (the memory sync's lock wait, the virtual cores' line, the order lock's
// slow takes), none of which names the holder. With RX_VK_LOCK_CENSUS=1 a lock that is busy when a thread comes for it notes the
// waiter, the thread that held it, and how long the wait was; every 10 s a thread of the census's own logs the 12 pairs that
// waited longest:
//   vk: lock census: Presentation Thread <- MainThread (replay_mu) 17.2 ms/s (2900/s, 6 us each)
// Counted: replay_mu (DrainingMutex), sync_order_mu (OrderMutex), held_mu, and in vk_memory.cpp pools_mu, sync_mu and cap_mu.
// Only the counting is ported: Source B's also samples the holders' stacks, which disturbs a millisecond or two a second.
//
// Off (unset, or 0): every lock is taken exactly as before, behind one branch on a value read once. On: a free lock is one
// try_lock and a store of its holder; only a busy lock reads the clock, twice. The holder is read without the lock, so a holder
// that lets go at that moment can be misnamed, never more. The census's own mutex is taken last, with the counted lock held, and
// nothing that holds it ever takes a counted lock. With RX_VK_LAB_AB naming a knob lockcensus it counts only in that knob's phases.
//
// No windows.h here (vk_recorder.h, which includes this, has none): a thread's name is read through g_thread_name, which
// vk_replay.cpp sets. tests/test_lock_census.py cuts DrainingMutex and OrderMutex out and compiles them with this.
#pragma once

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <tuple>
#include <vector>

namespace mkwvk {
void logf(const char* fmt, ...);   // (vk_main.cpp)

namespace lock_census {

/// RX_VK_LOCK_CENSUS, read once: 1 (any number but 0) counts
inline bool enabled() {
    static const bool v = [] {
        const char* e = getenv("RX_VK_LOCK_CENSUS");
        return e && atoi(e) != 0;
    }();
    return v;
}
inline std::atomic<bool> phase_on{true};   // (lab: false outside the knob's phases)
inline bool counting() { return enabled() && phase_on.load(std::memory_order_relaxed); }

/// The clock a busy lock reads (a test counts the reads through it)
inline int64_t steady_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
inline int64_t (*now_ns)() = steady_ns;
inline std::atomic<int> period_ms{10000};   // (between two reports)
constexpr int kTop = 12;

struct Pair {
    int64_t ns = 0, n = 0;
};
/// The census's own state. Names are kept as pointers to strings that are never freed, one per distinct name
struct Book {
    std::mutex mu;
    std::map<std::string, const char*> names;
    std::map<std::tuple<const char*, const char*, const char*>, Pair> pairs;   // (waiter, holder, lock)
    bool reporter = false;
    int64_t since_ns = 0;
};
inline Book& book() {
    static Book* b = new Book;   // (never destroyed: a thread may count while the process ends)
    return *b;
}
/// the one pointer for a name (book().mu held)
inline const char* intern(Book& b, const char* name) {
    auto it = b.names.find(name);
    if (it == b.names.end()) {
        char* kept = new char[strlen(name) + 1];
        strcpy(kept, name);
        it = b.names.emplace(name, kept).first;
    }
    return it->second;
}

/// A thread as the census names it: its description (the game's threads and the renderer's own are named), else its number. The
/// slot is never freed, so a lock's note of its holder can be read after that thread has ended
struct Slot {
    std::atomic<const char*> name{"?"};
    int64_t named_ns = 0;   // (its own thread's: when the name was last read)
};
/// (set by vk_replay.cpp, which has windows.h: the calling thread's description into out, left empty when it has none; and what
/// the reporting thread does first, which names it)
inline void (*g_thread_name)(char* out, size_t cap) = nullptr;
inline void (*g_report_start)() = nullptr;
inline void name_slot(Slot* s) {
    char text[96] = "";
    if (g_thread_name) g_thread_name(text, sizeof text);
    if (!text[0]) snprintf(text, sizeof text, "thread %zu", std::hash<std::thread::id>()(std::this_thread::get_id()) % 100000);
    Book& b = book();
    std::lock_guard lk(b.mu);
    s->name.store(intern(b, text), std::memory_order_relaxed);
}
/// the calling thread's slot; named at its first use, and again by `again_at` (a waiter's clock read: a thread named after its
/// first lock is not "thread 1234" for the whole session) when a second has passed
inline const Slot* me(int64_t again_at = 0) {
    thread_local Slot* mine = nullptr;
    if (!mine) {
        mine = new Slot;
        mine->named_ns = again_at;   // (0 on a free lock, which reads no clock: named again at this thread's first wait)
        name_slot(mine);
    } else if (again_at && again_at - mine->named_ns > 1000000000) {
        mine->named_ns = again_at;
        name_slot(mine);
    }
    return mine;
}

/// The pairs counted since the last call, the longest waited first, kTop at most, as the log's lines; all counts start again
inline std::vector<std::string> report(int64_t now) {
    Book& b = book();
    std::vector<std::pair<std::tuple<const char*, const char*, const char*>, Pair>> rows;
    double seconds = 0;
    {
        std::lock_guard lk(b.mu);
        rows.assign(b.pairs.begin(), b.pairs.end());
        b.pairs.clear();
        seconds = (double)(now - b.since_ns) / 1e9;
        b.since_ns = now;
    }
    if (seconds <= 0) seconds = 1e-9;
    std::sort(rows.begin(), rows.end(), [](const auto& x, const auto& y) { return x.second.ns > y.second.ns; });
    std::vector<std::string> out;
    for (size_t i = 0; i < rows.size() && i < (size_t)kTop; i++) {
        const auto& [key, p] = rows[i];
        char line[320];
        snprintf(line, sizeof line, "vk: lock census: %s <- %s (%s) %.1f ms/s (%.0f/s, %.0f us each)", std::get<0>(key), std::get<1>(key),
                 std::get<2>(key), (double)p.ns / 1e6 / seconds, (double)p.n / seconds, p.n ? (double)p.ns / 1e3 / (double)p.n : 0.0);
        out.emplace_back(line);
    }
    return out;
}
inline void report_main() {
    if (g_report_start) g_report_start();
    for (;;) {
        // (slept in steps, the period read at each: a test shortens it while this thread sleeps)
        for (int slept = 0; slept < period_ms.load(std::memory_order_relaxed); slept += 50)
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        for (const std::string& line : report(now_ns())) logf("%s", line.c_str());
    }
}
/// A wait is over: self waited ns for the lock `lock`, which `holder` held when it came (null: not known). The first one starts
/// the reporting thread
inline void waited(const Slot* self, const Slot* holder, const char* lock, int64_t ns, int64_t now) {
    Book& b = book();
    bool start = false;
    {
        std::lock_guard lk(b.mu);
        if (!b.since_ns) b.since_ns = now - ns;
        Pair& p = b.pairs[{self->name.load(std::memory_order_relaxed), holder ? holder->name.load(std::memory_order_relaxed) : intern(b, "?"),
                           intern(b, lock)}];
        p.ns += ns, p.n++;
        if (!b.reporter) b.reporter = start = true;
    }
    if (start) std::thread(report_main).detach();
}

/// m.lock() for a counted lock. owner: where that lock keeps its holder (set here, cleared by unlocking())
template <class M>
inline void lock(M& m, std::atomic<const Slot*>& owner, const char* name) {
    if (!counting()) {   // (off: the lock as it was)
        m.lock();
        return;
    }
    if (m.try_lock()) {   // (free: no clock read)
        owner.store(me(), std::memory_order_relaxed);
        return;
    }
    const Slot* holder = owner.load(std::memory_order_relaxed);
    const int64_t t0 = now_ns();
    m.lock();
    const int64_t t1 = now_ns();
    const Slot* self = me(t1);
    owner.store(self, std::memory_order_relaxed);
    waited(self, holder, name, t1 - t0, t1);
}
/// m.try_lock() for a counted lock
template <class M>
inline bool try_lock(M& m, std::atomic<const Slot*>& owner) {
    if (!m.try_lock()) return false;
    if (counting()) owner.store(me(), std::memory_order_relaxed);
    return true;
}
/// just before a counted lock's unlock: it has no holder
inline void unlocking(std::atomic<const Slot*>& owner) {
    if (owner.load(std::memory_order_relaxed)) owner.store(nullptr, std::memory_order_relaxed);
}

/// A std::mutex the census counts, for std::lock_guard and std::unique_lock
struct CensusMutex {
    const char* name;
    std::mutex m;
    std::atomic<const Slot*> owner{nullptr};
    explicit CensusMutex(const char* n) : name(n) {}
    void lock() { lock_census::lock(m, owner, name); }
    bool try_lock() { return lock_census::try_lock(m, owner); }
    void unlock() {
        unlocking(owner);
        m.unlock();
    }
};

} // namespace lock_census
} // namespace mkwvk
