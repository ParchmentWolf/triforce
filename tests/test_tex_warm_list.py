"""Textures made ahead by a list of what was drawn (gpu/vk/tex_warm.h, RX_VK_TEX_WARM_LIST; the performance audit's TEX-23,
after Source A's; no game, no GPU).

The list's rules, compiled and run: the switch is off unless 1 or 2; a texture is learnt within 90 s of the game making it,
not at 91 s; its signature changes with a byte of any sample and with each field of its shape, and its place with its
address; the samples lie inside the storage; the list starts again at 32,768; a listed texture is made only while the
textures and 256 MB more fit their budget and the target pool is not being given back; the file round trips, and one cut
short, of another version or magic, with a byte changed or a count past the list's bound loads nothing. Each rule taken out
in turn (a mutation) must make the test fail. Then the sources: the look by the list runs only with the switch, before the
40% rule of the look without it; the list is asked before a slot is looked up as a draw's first look (texture_get); the look
learns nothing (warm_looking), a draw's first upload and a made-ahead texture's first draw do; only BC and ASTC storages
under 2^39 are noted, at the texture's creation, and forgotten at its release; the list is read once and saved whole every
300 presents when it changed; the switch's row is in the development guide.

    python -I -B tests/test_tex_warm_list.py [--cxx clang++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def in_order(text, parts, where):
    at = 0
    for part in parts:
        found = text.find(part, at)
        if found < 0:
            raise SystemExit("%s: %r is missing, or not after the part before it (update the test with the code)" % (where, part))
        at = found + len(part)


HEADER_TEST = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "tex_warm.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
using namespace tex_warm;
int main() {
    // (the switch: off unless 1 or 2)
    CHECK(list_mode_of(nullptr) == 0 && list_mode_of("") == 0 && list_mode_of("0") == 0 && list_mode_of("3") == 0);
    CHECK(list_mode_of("x") == 0 && list_mode_of("-1") == 0 && list_mode_of("1") == 1 && list_mode_of("2") == 2);
    // (learnt within 90 s of the game making it, not at 91 s; a time not known, or ahead of now, learns nothing)
    const int64_t s = 1000000000ll, born = 5000 * s;
    CHECK(learnable(born, born) && learnable(born, born + 90 * s) && !learnable(born, born + 91 * s));
    CHECK(!learnable(0, 10 * s) && !learnable(born, born - 1));
    // (the samples: the first at the start, the last at the end, each inside the storage, 64-byte aligned)
    CHECK(sample_at(1 << 20, 0) == 0 && sample_at(1 << 20, kSamples - 1) == (1 << 20) - kSampleBytes);
    for (uint64_t size : {64ull, 65ull, 100ull, 512ull, 4096ull, 4100ull, 1ull << 20, 3ull << 30})
        for (int i = 0; i < kSamples; i++)
            CHECK(sample_at(size, i) + sample_len(size) <= size && sample_at(size, i) % kSampleBytes == 0);
    CHECK(sample_at(32, 5) == 0 && sample_len(32) == 32 && sample_len(64) == 64 && sample_len(1 << 20) == 64);
    CHECK(sample_at(1 << 20, 1) > 0 && sample_at(1 << 20, 1) < sample_at(1 << 20, 2));
    // (the signature: a byte of any sample, each field of the shape; the place: the address)
    uint8_t b[kSamples * kSampleBytes];
    for (size_t i = 0; i < sizeof b; i++) b[i] = (uint8_t)(i * 7);
    const Shape sh{1024, 512, 1, 11, 0x9e, 1, 1, 699056};
    const uint64_t sig = signature(sh, b);
    CHECK(sig == signature(sh, b));
    for (size_t i : {size_t(0), size_t(63), size_t(64), size_t(300), sizeof b - 1}) {
        b[i] ^= 1;
        CHECK(signature(sh, b) != sig);
        b[i] ^= 1;
    }
    for (int f = 0; f < 8; f++) {
        Shape o = sh;
        switch (f) {
            case 0: o.width++; break;
            case 1: o.height++; break;
            case 2: o.depth++; break;
            case 3: o.levels++; break;
            case 4: o.format++; break;
            case 5: o.target++; break;
            case 6: o.layers++; break;
            default: o.size += 512; break;
        }
        CHECK(signature(o, b) != sig);
    }
    CHECK(place(sig, 0x12340000) != place(sig, 0x12350000) && place(sig, 0x12340000) == place(sig, 0x12340000));
    CHECK(place(sig, 0x12340000) != place(sig + 1, 0x12340000) && place(0, 0) != 0);
    // (the list: once a place, and it starts again past kListMost)
    std::unordered_set<uint64_t> list;
    CHECK(remember(list, 5) && !remember(list, 5) && !remember(list, 0) && list.size() == 1);
    list.clear();
    for (uint64_t i = 1; i <= kListMost; i++) remember(list, i * 2 + 1);
    CHECK(list.size() == kListMost && kListMost == 32768);
    CHECK(remember(list, 7777777) && list.size() == 1 && list.count(7777777));
    // (a listed texture's room: the pool not given back, the textures and 256 MB more inside a budget that is set)
    const uint64_t MB = 1ull << 20, GB = 1ull << 30;
    CHECK(listed_room(false, 3 * GB, 3 * GB + 256 * MB) && !listed_room(false, 3 * GB, 3 * GB + 255 * MB));
    CHECK(!listed_room(true, 0, 8 * GB) && !listed_room(false, 0, 0) && !listed_room(false, 0, ~0ull));
    CHECK(!listed_room(false, 5 * GB, 4 * GB) && listed_room(false, 0, 256 * MB) && kListRoom == 256 * MB);
    // (the file: a round trip; cut short, another version or magic, a byte changed, a count past the bound: nothing)
    std::unordered_set<uint64_t> in{11, 13, 0xFFFFFFFFFFFFFFFFull, 0x123456789ull}, out{99};
    std::vector<uint8_t> f = encode(in);
    CHECK(f.size() == 16 + in.size() * 8 + 8 && decode(f.data(), f.size(), out) && out == in);
    CHECK(!decode(f.data(), f.size() - 1, out) && out.empty());
    out = {1};
    CHECK(!decode(f.data(), 20, out) && out.empty() && !decode(nullptr, 0, out));
    std::vector<uint8_t> g = f;
    g[8] ^= 2;   // (the version)
    CHECK(!decode(g.data(), g.size(), out) && out.empty());
    g = f, g[0] ^= 1;   // (the magic)
    CHECK(!decode(g.data(), g.size(), out));
    g = f, g[20] ^= 0x40;   // (a place's byte)
    CHECK(!decode(g.data(), g.size(), out) && out.empty());
    g = f, g.push_back(0);   // (one byte too many)
    CHECK(!decode(g.data(), g.size(), out));
    g = f;
    const uint32_t big = (uint32_t)kListMost + 1;
    std::memcpy(g.data() + 12, &big, 4);   // (a count past the bound)
    CHECK(!decode(g.data(), g.size(), out));
    std::unordered_set<uint64_t> none;
    f = encode(none);
    out = {3};
    CHECK(f.size() == 24 && decode(f.data(), f.size(), out) && out.empty());
    std::puts("PASS header: the switch, 90 s, the samples, the signature and place, the list's bound, the room, the file");
    return 0;
}
'''

MUTATIONS = [
    ("off unless 1 or 2", "return v == 1 || v == 2 ? v : 0;", "return v;"),
    ("90 s, not more", "now_ns - born_ns <= kLearnNs;", "now_ns - born_ns <= kLearnNs + 1000000000;"),
    ("a time not known learns nothing", "return born_ns > 0 && now_ns >= born_ns", "return now_ns >= born_ns"),
    ("the samples spread over the storage", "((size - kSampleBytes) * (uint64_t)i / (kSamples - 1))", "((size - kSampleBytes) / (kSamples - 1))"),
    ("the shape in the signature", "add(s.width), add(s.height), add(s.depth), add(s.levels), add(s.format), add(s.target), add(s.layers), add(s.size);",
     "add(s.width), add(s.height), add(s.depth), add(s.format), add(s.target), add(s.layers), add(s.size);"),
    ("the address in the place", "uint64_t h = sig ^ (gpu * 0x9E3779B97F4A7C15ull);", "uint64_t h = sig ^ (0 * gpu);"),
    ("the list starts again at its bound", "    if (list.size() >= kListMost) list.clear();\n", ""),
    ("no room while the pool is given back", "if (pressed || !budget || budget == ~0ull) return false;", "if (!budget || budget == ~0ull) return false;"),
    ("256 MB of room", "budget - texture_bytes >= kListRoom;", "budget - texture_bytes >= 0;"),
    ("a file of another version", "if (head[0] != kListVersion || head[1] > kListMost", "if (head[1] > kListMost"),
    ("the check of the places", "    if (check != list_check(b + 16, (size_t)head[1] * 8)) return false;\n", ""),
]


def check_source(tex, replay, dev):
    step = block(tex, "void texture_warm_step(int64_t last_frame_work) {")
    in_order(step, ["if (!tex_warm::may_warm(texture_warm_on(), last_frame_work, frame_upload_ns.load(std::memory_order_relaxed), warm_frame_ns)) return;",
                    "if (const int mode = texture_warm_list_mode()) return warm_step_listed(mode);",
                    "if (!tex_warm::has_room(warm_known, warm_used, warm_allowed, total_bytes, warm_budget)) return;"],
             "vk_texture.cpp texture_warm_step: the list's look with its switch, before the 40% rule")
    mode = block(tex, "int texture_warm_list_mode() {")
    if 'texture_warm_on() ? tex_warm::list_mode_of(getenv("RX_VK_TEX_WARM_LIST")) : 0' not in mode:
        raise SystemExit("vk_texture.cpp texture_warm_list_mode: the switch is not read through tex_warm::list_mode_of with RX_VK_TEX_WARM")
    listed = block(tex, "void warm_step_listed(int mode) {")
    in_order(listed, ["warm_list_load_once();", "Looking() { warm_looking = true; }", "~Looking() { warm_looking = false; }",
                      "ParLock lk;", "Texture* tex = texture_get(&t, true);", "if (made && tex) tex->warmed = true;",
                      "if (warm_pending.empty() || !tex_warm::ripe(warm_pending.front().second, frame_no)) break;",
                      "const uint64_t p = warm_place_of(t.d, t.L, t.gpu);", "listed = p && warm_list.count(p);",
                      "if (mode == 1 && warm_unlisted.size() < tex_warm::kMaxPending) warm_unlisted.push_back(e.first)",
                      "} else if (!tex_warm::listed_room(pool_pressed, total_bytes, warm_budget)) {",
                      "st_warm_made += make(t);", "if (!(more = goes_on())) break;",
                      "while (more && mode == 1 && !warm_unlisted.empty() &&",
                      "tex_warm::has_room(warm_known, warm_used, warm_allowed, total_bytes, warm_budget)) {",
                      "st_warm_made += make(t);", "warm_frame_ns += spent;"], "vk_texture.cpp warm_step_listed")
    if listed.count("texture_get(") != 1:
        raise SystemExit("vk_texture.cpp warm_step_listed: a texture is looked up in a place this test does not know")
    learn = block(tex, "void warm_learn(const Texture& tex) {")
    in_order(learn, ["if (warm_looking || !texture_warm_list_mode() || !tex.gpu || tex.gpu >= (1ull << 39)) return;",
                     "const auto it = warm_born.find(tex.gpu);", "if (!tex_warm::learnable(born, warm_now_ns())) return;",
                     "const uint64_t p = warm_place_of(tex.d, tex.L, tex.gpu);", "warm_list_load_once();",
                     "if (tex_warm::remember(warm_list, p)) warm_list_changed = true"], "vk_texture.cpp warm_learn")
    up = block(tex, "bool upload(Texture& tex, const Ranges* dirty) {")
    in_order(up, ["if (!tex.uploaded) warm_learn(tex);", "const bool ok = upload_inner(tex, dirty);"], "vk_texture.cpp upload: a first upload learns")
    get = block(tex, "Texture* texture_get(const nvn_tex* t, bool for_sampling) {")
    in_order(get, ["tex = it->second.get();", "if (tex->warmed && for_sampling && !warm_looking) tex->warmed = false, warm_learn(*tex);",
                   "return texture_touch(tex, for_sampling);"], "vk_texture.cpp texture_get: a made-ahead texture's first draw learns")
    born = block(tex, "void texture_warm_born(const nvn_tex* t) {")
    in_order(born, ["if (!texture_warm_list_mode() || !t || !t->gpu || t->gpu >= (1ull << 39)) return;",
                    "if (nvn_block_size(t->d.format, &bw, &bh) <= 0 || bw <= 1) return;", "warm_born[t->gpu] = now;"],
             "vk_texture.cpp texture_warm_born: BC and ASTC under 2^39, with the switch")
    gone = block(tex, "void texture_warm_gone(const nvn_tex* t) {")
    in_order(gone, ["if (!texture_warm_list_mode() || !t || !t->gpu) return;", "warm_born.erase(t->gpu);"], "vk_texture.cpp texture_warm_gone")
    load = block(tex, "void warm_list_load_once() {")
    in_order(load, ["std::call_once(once,", "fopen(warm_list_path().c_str(), \"rb\")", "ok = tex_warm::decode(b.data(), b.size(), had);",
                    "for (const uint64_t p : had) tex_warm::remember(warm_list, p);"], "vk_texture.cpp warm_list_load_once")
    save = block(tex, "void warm_list_save_due() {")
    in_order(save, ["if (!texture_warm_list_mode() || frame_no % tex_warm::kSaveEvery) return;", "if (!warm_list_changed) return;",
                    "b = tex_warm::encode(warm_list);", "if (!file_writers::write_whole(warm_list_path(), b.data(), b.size())) {"],
             "vk_texture.cpp warm_list_save_due")
    in_order(tex, ["warm_known = known, warm_used = used, warm_allowed = allowed, warm_budget = budget;", "warm_list_save_due();",
                   "texture_sweep(completed, total_bytes <= budget, budget, evict_to, known, used, allowed, false, hold_to, rule_to);"],
             "vk_texture.cpp texture_frame: the list saved at the looks")
    if '"triforce_textures_drawn.bin"' not in tex:
        raise SystemExit("vk_texture.cpp: the list's file is not triforce_textures_drawn.bin")
    created = block(replay, "void texture_created_of(const nvn_tex* t) {")
    in_order(created, ["tex_pages_add(t, +1);", "texture_warm_born(t);"], "vk_replay.cpp texture_created_of")
    released = block(replay, "void texture_released_of(const nvn_tex* t) {")
    in_order(released, ["if (!t) return;", "tex_pages_add(t, -1);", "texture_warm_gone(t);", "if (!async_on()) {"],
             "vk_replay.cpp texture_released_of: forgotten on every path")
    if "RX_VK_TEX_WARM_LIST" not in dev:
        raise SystemExit("docs/development.md: RX_VK_TEX_WARM_LIST is not in the switches table")


def build(cxx, d, name, src, include):
    cpp, exe = d / (name + ".cpp"), d / (name + ".exe")
    cpp.write_text(src, encoding="utf-8")
    r = subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I" + str(include), str(cpp),
                        "-o", str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode:
        return None, r.stdout
    return exe, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    a = ap.parse_args()
    check_source((VK / "vk_texture.cpp").read_text(encoding="utf-8"), (VK / "vk_replay.cpp").read_text(encoding="utf-8"),
                 (ROOT / "docs" / "development.md").read_text(encoding="utf-8"))
    print("PASS sources: the list's look with its switch before the 40% rule, the list asked before the look, nothing learnt by "
          "the look, a draw's first upload and a made-ahead texture's first draw learnt, BC and ASTC noted and forgotten, the "
          "file read once and saved whole, the switch's row")
    header = (VK / "tex_warm.h").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="tex-warm-list-") as tmp:
        d = Path(tmp)
        exe, out = build(a.cxx, d, "header", HEADER_TEST, VK)
        if not exe:
            raise SystemExit("header: the build failed:\n" + out)
        r = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        if r.returncode:
            raise SystemExit("the header test failed:\n" + r.stdout)
        print(r.stdout.strip())
        for i, (what, old, new) in enumerate(MUTATIONS):
            if header.count(old) != 1:
                raise SystemExit("mutation %r: its text is not once in tex_warm.h (update the test with the header)" % what)
            inc = d / ("mutant%d" % i)
            inc.mkdir()
            (inc / "tex_warm.h").write_text(header.replace(old, new), encoding="utf-8")
            exe, out = build(a.cxx, d, "mutant%d" % i, HEADER_TEST, inc)
            if exe:
                r = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
                if r.returncode == 0:
                    raise SystemExit("mutation %r: the header test still passed without it" % what)
        print("PASS mutations: %d rules of the list, each taken out, fail the header's test" % len(MUTATIONS))


if __name__ == "__main__":
    main()
