// tests/test_mirror_bookkeeping.py puts vk_memory.cpp's own wb_notes_off, memory_cpu_owned (with its two merges),
// shadow_written_to and its two callers, guest_cpu_write and guest_cpu_wrote in the place of ACTUAL and runs them with
// and without mirrors. No game, no GPU. (Triforce, 11-22, the performance audit's MEM-51, after Source A's.)
//
//   <exe> off      mirrors off, the device made: nothing is noted, no guest page is looked up, the write still lands
//   <exe> early    mirrors off, the device not made yet: noted as before, and mirror_on() is not asked
//   <exe> dump     mirrors on: a fixed random run of calls, then every list printed. The test builds this file twice,
//                  from the code as it is and from the code with the new condition taken out (the code as it was):
//                  the two prints must be the same
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>
#include <vector>

#define VK_NULL_HANDLE nullptr
#define CHECK(ok) do { if (!(ok)) { std::printf("FAIL:%d %s\n", __LINE__, #ok); fails++; } } while (0)
static int fails = 0;
constexpr uint64_t kPageShift = 12;

struct Dev { void* device = nullptr; } dev;
static bool mirrors = true;
static int mirror_asked = 0;
bool mirror_on() { return mirror_asked++, mirrors; }
bool wb_diff_on() { return true; }

static int looked_up = 0, writes = 0;
struct Host {
    static uint64_t gpu_guest(uint64_t gpu) { return looked_up++, gpu >= 0x100000 ? gpu - 0x100000 + 0x4000000 : 0; }
    static int gpu_write(uint64_t, const void*, uint64_t) { return writes++, 1; }
};
static Host the_host;
static Host* host = &the_host;

std::mutex cpu_words_mu;
std::vector<uint64_t> cpu_words, cpu_words_recent, cpu_words_new;
std::mutex shadow_written_mu;
std::vector<uint32_t> shadow_written_pages, shadow_written_collected_list, shadow_written_by_replay;
bool shadow_written_all = false;
void shadow_written_to(std::vector<uint32_t>& list, const uint32_t* pages, int64_t n);
void guest_cpu_wrote(uint64_t gpu, uint64_t n);

/* ACTUAL */

static uint64_t rnd_state = 0x1234567887654321ull;
static uint64_t rnd() {
    rnd_state ^= rnd_state << 13, rnd_state ^= rnd_state >> 7, rnd_state ^= rnd_state << 17;
    return rnd_state;
}
static bool nothing_noted() {
    return cpu_words.empty() && cpu_words_recent.empty() && cpu_words_new.empty() && shadow_written_pages.empty() &&
           shadow_written_collected_list.empty() && shadow_written_by_replay.empty() && !shadow_written_all;
}
/// The calls the replay and the capture make, n of them, from the generator's state
static void calls(int n) {
    uint32_t pages[80];
    const uint32_t word = 0;
    for (int i = 0; i < n; i++) {
        const uint64_t at = 0x100000 + (rnd() % 4096) * 8, len = 1 + rnd() % 20000;
        switch (rnd() % 5) {
            case 0: memory_cpu_owned(rnd() % 9 == 0 ? 0 : 0x4000000 + (rnd() % 70000) * 8 + rnd() % 8, 1 + rnd() % 40); break;
            case 1: {
                const int k = (int)(rnd() % 80);
                for (int j = 0; j < k; j++) pages[j] = (uint32_t)(rnd() % 100000);
                shadow_written(pages, k);
                break;
            }
            case 2: {
                const int k = (int)(rnd() % 80);
                for (int j = 0; j < k; j++) pages[j] = (uint32_t)(rnd() % 100000);
                shadow_written_collected(pages, k);
                break;
            }
            case 3: guest_cpu_wrote(rnd() % 7 == 0 ? 0x1000 : at, rnd() % 11 == 0 ? 0 : len); break;
            default: guest_cpu_write(at, &word, 4); break;
        }
    }
}
template <class T> static void dump(const char* name, const std::vector<T>& v) {
    uint64_t h = 1469598103934665603ull;
    for (const T& e : v) h = (h ^ (uint64_t)e) * 1099511628211ull;
    std::printf("%s %zu %016llx\n", name, v.size(), (unsigned long long)h);
}

int main(int argc, char** argv) {
    const std::string test = argc == 2 ? argv[1] : "";
    if (test == "off") {
        dev.device = &dev, mirrors = false;
        calls(20000);
        CHECK(nothing_noted());
        CHECK(looked_up == 0);    // (guest_cpu_wrote asks the host for no page)
        CHECK(writes > 1000);     // (guest_cpu_write still writes)
        CHECK(mirror_asked > 0);
    } else if (test == "early") {
        dev.device = nullptr, mirrors = false;
        calls(2000);
        CHECK(!nothing_noted() && looked_up > 0);
        CHECK(mirror_asked == 0);   // (mirror_on() decides once, by the card: not asked before there is one)
    } else if (test == "dump") {
        dev.device = &dev, mirrors = true;
        for (int round = 0; round < 40; round++) {
            calls(3000);
            if (round % 8 == 7) {   // (a write-back reads them: the lists start again, as shadows_forget_written leaves them)
                std::lock_guard lk(shadow_written_mu);
                shadow_written_pages.clear(), shadow_written_collected_list.clear(), shadow_written_by_replay.clear(), shadow_written_all = false;
            }
            dump("words", cpu_words), dump("recent", cpu_words_recent), dump("new", cpu_words_new);
            dump("game", shadow_written_pages), dump("collected", shadow_written_collected_list), dump("replay", shadow_written_by_replay);
            std::printf("all %d looked_up %d writes %d\n", (int)shadow_written_all, looked_up, writes);
        }
        CHECK(!nothing_noted() && looked_up > 0);
    } else {
        std::printf("a known case\n");
        return 1;
    }
    return fails != 0;
}
