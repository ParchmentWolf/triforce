"""The per-thread cache of the nn::os object lookups: 16,384 entries, four ways a set (host/nn_os_sync.c obj_lookup_cached,
HOS_OBJ_CACHE).

The game's record pass under the graphics front end locks and unlocks some 4,000 per-slot mutexes 0x80 apart; the
direct-mapped cache's multiply-shift index folded those keys onto few entries and missed at nearly every step. The code from
the ObjWay type to the end of obj_nockpt (the switch's parse, the four-way cache, the counts' flush, obj and obj_nockpt with
the direct-mapped cache) is cut out unchanged and compiled with stand-ins: an object table that answers every lookup as
obj_lookup does (an object a key, re-kinded in place, buried ones reused for other keys), a clock and a log.

Checked: HOS_OBJ_CACHE's values (unset, empty or not a number 16,384; 0 the direct-mapped cache; else 256 to 65,536, down to
a power of two); a 4,000-mutex walk at a 0x80 stride misses under 100 times on its third pass by default, most of the 4,000
with =0, all of them with =256, and both lookups of each step with HOS_NO_OBJ_CACHE=1; 200,000 lookups among buried, re-kinded and reused objects each
answer the table's object of that key and kind; the counts' log line every 10 s, from obj only; obj_nockpt neither logs nor
flushes (it runs under host locks: tests/test_multiwait_wake.py); the docs rows.

    python -I -B tests/test_obj_cache_size.py [--cxx clang++]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def fail(message):
    raise SystemExit("FAIL: " + message)


HARNESS = r"""
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct Obj { uint64_t key; int kind; struct Obj *spare; } Obj;
static int64_t fake_now = 1;
static int64_t hos_now_ns(void) { return fake_now; }
static char logged[512];
static int nlogged;
static void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(logged, sizeof logged, fmt, ap);
    va_end(ap);
    nlogged++;
}
static void hos_vcore_checkpoint(void) {}

/* (the stand-in table: keys from a fixed pool, an object a key, as obj_lookup answers) */
#define POOL 8192
static uint64_t pool[POOL];
static int npool;
static Obj *live[POOL];
static Obj *spares;
static long slow;
static int pool_index(uint64_t key) {
    for (int i = 0; i < npool; i++) if (pool[i] == key) return i;
    if (npool == POOL) { fprintf(stderr, "pool full\n"); exit(2); }
    pool[npool] = key;
    return npool++;
}
static int last_index = -1;
static Obj *obj_lookup(uint64_t key, int kind) {
    slow++;
    const int i = last_index >= 0 && pool[last_index] == key ? last_index : pool_index(key);
    Obj *o = live[i];
    if (o && o->kind == kind) return o;
    if (o) {   /* (the address initialized again as another kind) */
        __atomic_store_n(&o->kind, kind, __ATOMIC_RELEASE);
        return o;
    }
    if ((o = spares)) spares = o->spare;
    else o = (Obj *)calloc(1, sizeof *o);
    __atomic_store_n(&o->key, key, __ATOMIC_RELAXED);
    __atomic_store_n(&o->kind, kind, __ATOMIC_RELEASE);
    live[i] = o;
    return o;
}
static void bury(int i) {   /* (the object goes to the spares, to be reused for another address) */
    Obj *o = live[i];
    if (!o) return;
    __atomic_store_n(&o->kind, 0, __ATOMIC_RELEASE);
    live[i] = NULL;
    o->spare = spares;
    spares = o;
}

CUT

static uint64_t rng = 0x9E3779B97F4A7C15ULL;
static uint64_t next_rand(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; }

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "";
    if (!strcmp(mode, "entries")) {
        printf("%d\n", obj_cache_entries());
        return 0;
    }
    if (!strcmp(mode, "walk")) {
        long misses = 0;
        for (int pass = 0; pass < 3; pass++) {
            const long before = slow;
            for (int i = 0; i < 4000; i++) {
                const uint64_t key = 0x8a3f1200ULL + (uint64_t)i * 0x80;
                Obj *o = obj(key, 1);
                if (!o || o->key != key || o->kind != 1) { printf("wrong object\n"); return 1; }
                Obj *again = obj(key, 1);   /* (lock, then unlock: the second is a hit) */
                if (again != o) { printf("wrong object\n"); return 1; }
            }
            misses = slow - before;
        }
        printf("%ld\n", misses);
        return 0;
    }
    if (!strcmp(mode, "random")) {
        for (int i = 0; i < 6000; i++)
            pool_index(0x80000000ULL + (next_rand() % 0x1000000) * 16 + (i % 3) * 0x80000000ULL);
        long wrong = 0;
        for (long n = 0; n < 200000; n++) {
            const uint64_t r = next_rand();
            const int i = (int)(r % 1500 + (r >> 20) % 7 * ((r >> 40) % 2 ? 600 : 0)) % npool;
            if ((r >> 32) % 97 == 0) { bury(i); continue; }
            const int kind = (r >> 48) % 13 == 0 ? 2 + (int)((r >> 52) % 3) : 1;
            last_index = i;
            Obj *o = obj(pool[i], kind);
            last_index = -1;
            if (o != live[i] || o->key != pool[i] || o->kind != kind) wrong++;
        }
        printf("%ld wrong of 200000, %ld to the table\n", wrong, slow);
        return wrong != 0;
    }
    if (!strcmp(mode, "log")) {
        for (int round = 0; round < 3; round++) {
            for (int n = 0; n < 70000; n++) obj(0x81000000ULL, 1);
            obj(0x82000000ULL + (uint64_t)round * 0x1000, 1);   /* (a miss past 65,536 lookups: due) */
            obj(0x81000000ULL, 1);                              /* (the flush, in obj) */
            if (round == 0 && nlogged) { printf("logged at the first flush\n"); return 1; }
            if (round == 0) fake_now += 11000000000LL;   /* (the third round within 10 s of the second: no line) */
        }
        printf("%d|%s\n", nlogged, logged);
        return 0;
    }
    return 1;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    source = (ROOT / "host" / "nn_os_sync.c").read_text(encoding="utf-8")
    start = "typedef struct { uint64_t key; Obj *o; } ObjWay;"
    if start not in source:
        fail("host/nn_os_sync.c has no four-way object cache (ObjWay)")
    nockpt = block(source, "static Obj *obj_nockpt(uint64_t key, int kind) {")
    cut = source[source.index(start):source.index(nockpt) + len(nockpt)]
    # (the source's own rules)
    if "hos_log" in nockpt or "obj_cache_flush" in nockpt or "hos_log" in block(source, "static Obj *obj_lookup_cached("):
        fail("obj_nockpt or the cache logs or flushes: it runs under host locks")
    obj = block(source, "static Obj *obj(uint64_t key, int kind) {")
    if "if (obj_cache_due) obj_cache_flush();" not in obj or obj.index("hos_vcore_checkpoint();") > obj.index("obj_cache_flush"):
        fail("obj: the counts are not flushed there, after the checkpoint")
    if 'getenv("HOS_NO_OBJ_CACHE")' not in nockpt or "if (entries) return obj_lookup_cached(key, kind, entries);" not in nockpt:
        fail("obj_nockpt: HOS_NO_OBJ_CACHE before both caches, the four-way one unless HOS_OBJ_CACHE=0")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if "`HOS_OBJ_CACHE=<n>`" not in docs or "`HOS_NO_OBJ_CACHE=1`" not in docs:
        fail("docs/development.md: rows for HOS_OBJ_CACHE and HOS_NO_OBJ_CACHE")
    with tempfile.TemporaryDirectory(prefix="obj-cache-") as tmp:
        c, exe = Path(tmp) / "obj_cache.c", Path(tmp) / "obj_cache.exe"
        c.write_text(HARNESS.replace("CUT", cut), encoding="utf-8")
        subprocess.run([args.cxx, "-x", "c", "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        str(c), "-o", str(exe)], check=True)

        def run(mode, **env):
            e = {k: v for k, v in os.environ.items() if k not in ("HOS_OBJ_CACHE", "HOS_NO_OBJ_CACHE")}
            e.update(env)
            r = subprocess.run([str(exe), mode], capture_output=True, text=True, env=e, timeout=120)
            if r.returncode:
                fail("%s %s: %s%s" % (mode, env, r.stdout, r.stderr))
            return r.stdout.strip()
        for value, want in ((None, 16384), ("", 16384), ("abc", 16384), ("-5", 16384), ("12k", 16384), ("0", 0), ("256", 256),
                            ("300", 256), ("100", 256), ("16384", 16384), ("20000", 16384), ("65536", 65536),
                            ("99999999", 65536)):
            got = int(run("entries", **({} if value is None else {"HOS_OBJ_CACHE": value})))
            if got != want:
                fail("HOS_OBJ_CACHE=%r: %d entries, not %d" % (value, got, want))
        print("ok   HOS_OBJ_CACHE: unset 16,384; 0 the direct-mapped cache; 256 to 65,536, a power of two")
        walk = int(run("walk"))
        fixed, small, off = int(run("walk", HOS_OBJ_CACHE="0")), int(run("walk", HOS_OBJ_CACHE="256")), int(run("walk", HOS_NO_OBJ_CACHE="1"))
        print("     a 4,000-mutex walk at 0x80, misses on its third pass: %d by default, %d with =0, %d with =256, %d with "
              "HOS_NO_OBJ_CACHE=1" % (walk, fixed, small, off))
        if walk >= 100:
            fail("the walk missed %d times on its third pass (under 100 wanted)" % walk)
        if fixed < 3000 or small != 4000 or off != 8000:
            fail("the walk's controls: =0 %d (over 3,000 wanted), =256 %d (4,000 wanted), HOS_NO_OBJ_CACHE=1 %d (8,000: both lookups a step)" % (fixed, small, off))
        print("ok   the walk: under 100 misses a pass; its controls miss as before")
        for env in ({}, {"HOS_OBJ_CACHE": "256"}, {"HOS_OBJ_CACHE": "0"}):
            print("ok   random lookups %s: %s" % (env or "(default)", run("random", **env)))
        n, line = run("log").split("|", 1)
        m = re.fullmatch(r"sync: object cache \(16384 entries, 4 ways a set; HOS_OBJ_CACHE\): (\d+) lookups, (\d+) missed "
                         r"\((\d+\.\d\d) %\) in (\d+) s", line)
        if int(n) != 1 or not m or int(m.group(1)) < 140000 or int(m.group(2)) > 10 or m.group(4) != "11":
            fail("the log line: %s times, the last %r" % (n, line))
        print("ok   the log line every 10 s, from obj: " + line)
    print("PASS: the four-way object cache")


if __name__ == "__main__":
    main()
