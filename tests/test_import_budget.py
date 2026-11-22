"""What the idle imports' valve measures the system heap against (gpu/vk/import_budget.h; no game, no GPU).

(Triforce, 11-22, the performance audit's MEM-22, after Source A's.) The valve that gives idle imports back ran only
under a 12 GB system heap budget, or with RX_VK_IMPORT_HIGH set. With Mesa's RADV and a budget of 12 GB or more it now
runs against 4,500 MB; every other case is the rule as it was.

Compiles a small driver against the header and checks, budgets in MB:
  RADV      12,287 -> on, the whole budget (as before); 12,288 and 15,434 -> on, measured against 4,500;
            with RX_VK_IMPORT_HIGH or _LOW set -> the whole budget, on only as before (HIGH set, or a small budget);
            RX_VK_IMPORT_CAP_MB=0 -> no cap, off at 15,434 as before;
  others    NVIDIA, Intel, AMD's own drivers at 15,434 -> off, no cap; at 7,503 -> on, the whole budget;
            exactly the rule as it was (on = HIGH set or under 12 GB), for every budget and every setting but the cap;
  the cap   RX_VK_IMPORT_CAP_MB=3000 -> on, 3,000 on any driver and budget; a cap over the budget measures the budget;
  a pass    against the cap, 1 GB at most; without a cap, all the way down to the target as before; nothing under it.

And reads the source: imports_give_back asks the rule once with the driver, measures by_heap and the target against
import_budget::measured, bounds a capped pass with pass_want, keeps LOW at 75 and the idle filter of 600 submissions;
and the switches table documents RX_VK_IMPORT_HIGH, _LOW and _CAP_MB.

    python -I -B tests/test_import_budget.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

DRIVER = r'''
#include "import_budget.h"
#include <cstdio>
#include <initializer_list>

using namespace import_budget;
static int checks, fails;
static void want(const char* what, bool got, bool wanted) {
    checks++;
    if (got != wanted) fails++, printf("FAIL %s: %d, want %d\n", what, (int)got, (int)wanted);
}
static bool is(const Rule& r, uint64_t budget, bool on, uint64_t measure_mb) {
    return r.on == on && measured(r, budget) == measure_mb * kMB;
}

int main() {
    const uint64_t under = 12287 * kMB, at = 12288 * kMB, big = 15434 * kMB, small = 7503 * kMB;
    // RADV
    want("RADV, 12,287 MB: the whole budget, on", is(rule(under, false, false, -1, true), under, true, 12287), true);
    want("RADV, 12,288 MB: against 4,500", is(rule(at, false, false, -1, true), at, true, 4500), true);
    want("RADV, 15,434 MB: against 4,500", is(rule(big, false, false, -1, true), big, true, 4500), true);
    want("RADV, HIGH set: the whole budget, on", is(rule(big, true, false, -1, true), big, true, 15434), true);
    want("RADV, LOW set alone: the whole budget, off as before", is(rule(big, false, true, -1, true), big, false, 15434), true);
    want("RADV, the cap 0: no cap, off as before", is(rule(big, false, false, 0, true), big, false, 15434), true);
    want("RADV, the cap 0 and HIGH set: on, the whole budget", is(rule(big, true, false, 0, true), big, true, 15434), true);
    // every other driver: the rule as it was, whatever the budget and the percent switches
    for (const uint64_t mb : {2048ull, 7503ull, 12287ull, 12288ull, 15434ull, 32768ull, 65536ull})
        for (int high = 0; high < 2; high++)
            for (int low = 0; low < 2; low++)
                for (const int64_t cap : {(int64_t)-1, (int64_t)0}) {
                    const uint64_t b = mb * kMB;
                    const Rule r = rule(b, high, low, cap, false);
                    want("another driver: on as before", r.on, high || b < kBigBudget);
                    want("another driver: no cap", r.cap == 0 && measured(r, b) == b, true);
                    want("another driver: a pass goes down to the target as before", pass_want(r, b, b, b / 100 * 75) == b - b / 100 * 75, true);
                    // and RADV is the same wherever its cap does not apply
                    if (cap == 0 || high || low || b < kBigBudget) {
                        const Rule a = rule(b, high, low, cap, true);
                        want("RADV outside its cap: as another driver", a.on == r.on && a.cap == r.cap, true);
                    }
                }
    want("another driver, 15,434 MB: off", is(rule(big, false, false, -1, false), big, false, 15434), true);
    want("another driver, 7,503 MB: on, the whole budget", is(rule(small, false, false, -1, false), small, true, 7503), true);
    // the switch's cap, any driver
    for (int radv = 0; radv < 2; radv++) {
        want("the cap 3000 at a big budget", is(rule(big, false, false, 3000, radv), big, true, 3000), true);
        want("the cap 3000 at a small budget", is(rule(small, false, false, 3000, radv), small, true, 3000), true);
        want("a cap over the budget measures the budget", is(rule(small, false, false, 9000, radv), small, true, 7503), true);
        want("the cap over HIGH and LOW", is(rule(big, true, true, 3000, radv), big, true, 3000), true);
    }
    // a pass
    const Rule capped = rule(big, false, false, -1, true), plain = rule(small, false, false, -1, false);
    const uint64_t target = 4500 * kMB / 100 * 75;
    want("capped: 1 GB at most", pass_want(capped, big, 9000 * kMB, target) == kPassMost, true);
    want("capped: less than 1 GB as it is", pass_want(capped, big, target + 300 * kMB, target) == 300 * kMB, true);
    want("capped: nothing under the target", pass_want(capped, big, target - kMB, target) == 0, true);
    want("no cap: down to the target", pass_want(plain, small, 7400 * kMB, 5000 * kMB) == 2400 * kMB, true);
    const Rule over = rule(small, false, false, 9000, false);   // (a cap over the budget is no cap)
    want("a cap over the budget: down to the target", pass_want(over, small, 7400 * kMB, 5000 * kMB) == 2400 * kMB, true);
    want("the cap is 4,500 MB, the line 12 GB, a pass 1 GB", kCapMb == 4500 && kBigBudget == (12ull << 30) && kPassMost == (1ull << 30), true);
    if (fails) printf("import budget: FAILED (%d of %d checks)\n", fails, checks);
    else printf("import budget: all %d checks passed\n", checks);
    return fails != 0;
}
'''


def check_source():
    src = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
    if '#include "import_budget.h"' not in src:
        raise SystemExit("vk_memory.cpp does not include import_budget.h")
    at = src.index("void imports_give_back() {")
    body = src[at:src.index("\n}\n", at)]
    order = [body.find(n) for n in (
        "if (!system_heap_usage(&used, &budget)) return;",
        "static import_budget::Rule live;",
        "live = import_budget::rule(budget, env_high != nullptr, getenv(\"RX_VK_IMPORT_LOW\") != nullptr, env_cap ? atoll(env_cap) : -1,",
        "dev.driver_id == VK_DRIVER_ID_MESA_RADV);",
        "const uint64_t measure = import_budget::measured(live, budget);",
        "const bool by_heap = small && used > measure / 100 * (uint64_t)high;",
        "const uint64_t target = measure / 100 * (uint64_t)low;",
        "const uint64_t want = by_heap ? import_budget::pass_want(live, budget, used, target) :",   # (MEM-141: then the hold's episode)
        "if (freed >= want) break;")]
    if min(order) < 0 or order != sorted(order):
        raise SystemExit("imports_give_back does not ask import_budget.h once with the driver and measure the heap, the target and "
                         "a pass by it")
    for gone in ("used > budget / 100 * (uint64_t)high", "budget / 100 * (uint64_t)low", "env_high || budget < (12ull << 30)"):
        if gone in body:
            raise SystemExit("imports_give_back still measures against the whole budget itself: " + gone)
    if 'getenv("RX_VK_IMPORT_CAP_MB")' not in body:
        raise SystemExit("imports_give_back does not read RX_VK_IMPORT_CAP_MB")
    if 'std::clamp(atoi(getenv("RX_VK_IMPORT_LOW")), 10, 95) : 75;' not in body or "constexpr uint64_t kImportIdle = 600;" not in src \
            or "const uint64_t idle_for = by_heap ? kImportIdle : kImportIdleRam;" not in body:
        raise SystemExit("imports_give_back: LOW is no longer 75 by default, or the idle filter changed")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    for row in ("| `RX_VK_IMPORT_HIGH=<percent>` or `0`, `RX_VK_IMPORT_LOW=<percent>` |", "| `RX_VK_IMPORT_CAP_MB=<n>` or `0` |",
                "`gpu/vk/import_budget.h`"):
        if row not in docs:
            raise SystemExit("docs/development.md: the switches table lacks " + row)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="import-budget-") as tmp:
        cpp, exe = Path(tmp) / "import_budget_test.cpp", Path(tmp) / "import-budget.exe"
        cpp.write_text(DRIVER, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "gpu/vk"), str(cpp), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            raise SystemExit("FAIL: the import budget's checks failed")


if __name__ == "__main__":
    main()
