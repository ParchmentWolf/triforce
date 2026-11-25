// (Triforce) A step of a start that a crash in the driver would repeat at every start has a file beside the notes that says it
// began and has not ended: the precompile's (<pipeline notes>.running, vk_draw.cpp precompile_run). The next start reads it
// and, after two starts that ended inside, goes on without that step. Only a crash, or a kill that no quit asked for, may
// count. A quit does not: the window's close ends the process at once (ExitProcess: no destructor runs, no thread is joined),
// so when the step's workers did not stop within the close's 10 s the file was left as if the start had crashed there, and two
// such quits in the precompile dropped its notes. Nor does a process ended while it closes, after the quit (the close takes up
// to 10 s and more, with the window not answering: a player who quits again then ends it). The close (mkwvk_close_asked) puts
// every step still open back as its start found it, before anything else. (The stage libraries' journal, <prepared>.warming,
// has rules of its own: gpl_rules.h.)
#pragma once

#include <cstddef>
#include <cstdio>
#include <mutex>
#include <string>
#include <vector>

namespace crash_markers {

/// A count for no file at all
constexpr int none = -1;

namespace detail {
struct Open {
    std::string path;
    int closed;   // (what a close leaves in the file)
};
struct State {
    std::mutex mu;
    std::vector<Open> open;
    bool closing = false;
};
/// (never freed: the close's ExitProcess can come while a step's thread is still in begin() or end())
inline State& state() {
    static State* s = new State;
    return *s;
}
/// The file holds `count` (none: there is no file)
inline void put(const std::string& path, int count) {
    if (count == none) std::remove(path.c_str());
    else if (FILE* f = std::fopen(path.c_str(), "wb")) std::fprintf(f, "%d\n", count), std::fclose(f);
}
inline void forget(State& s, const std::string& path) {
    for (std::size_t i = 0; i < s.open.size(); i++)
        if (s.open[i].path == path) {
            s.open.erase(s.open.begin() + (std::ptrdiff_t)i);
            return;
        }
}
} // namespace detail

/// A step begins: its file holds `count` from now on. A close before end() leaves `closed` there instead (none: no file), as the
/// start found it, so that a start the player closed counts neither as one that crashed in the step nor as one that got through
inline void begin(const std::string& path, int count, int closed) {
    detail::State& s = detail::state();
    std::lock_guard lk(s.mu);
    if (s.closing) return;
    detail::forget(s, path);
    detail::put(path, count);
    s.open.push_back({path, closed});
}

/// The step got through (or its file is no longer wanted): the file goes
inline void end(const std::string& path) {
    detail::State& s = detail::state();
    std::lock_guard lk(s.mu);
    if (s.closing) return;
    detail::forget(s, path);
    std::remove(path.c_str());
}

/// The step was stopped in order before its end, and its thread came back (the window's close whose workers stopped in time, the
/// builder's Cancel): its file put back as its start found it, as close() does for the steps still open
inline void stopped(const std::string& path) {
    detail::State& s = detail::state();
    std::lock_guard lk(s.mu);
    if (s.closing) return;
    for (std::size_t i = 0; i < s.open.size(); i++)
        if (s.open[i].path == path) {
            detail::put(path, s.open[i].closed);
            s.open.erase(s.open.begin() + (std::ptrdiff_t)i);
            return;
        }
}

/// The player asked to quit (mkwvk_close_asked, first): every step still open has its file put back as its start found it,
/// before the close stops the workers, so that the process ended meanwhile (End task, the system at a log-out) is not taken
/// for a crash either. A worker that crashes the driver after this is not counted: one that does so at every start crashes the
/// next start too, which counts. From then on begin(), end() and stopped() do nothing: the files stay as the start found them
/// until the process ends, whatever a worker still running does (a restart's new process may already read them)
inline void close() {
    detail::State& s = detail::state();
    std::lock_guard lk(s.mu);
    s.closing = true;
    for (const detail::Open& o : s.open) detail::put(o.path, o.closed);
    s.open.clear();
}

} // namespace crash_markers
