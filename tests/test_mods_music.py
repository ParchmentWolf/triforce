"""The Mods screen's music: the game's shop theme under the Mods screen opened from the title, the title's own music
faded out meanwhile (host/mods_music.h and mods_music.c, host/nn_audio.c render_frame, gpu/vk/vk_menu.cpp
menu_mods_music; no game, no sound device).

(Triforce, 11-20) The owner: "have the in game mods menu in the title screen play the shop theme quietly in the
background ... it mutes the title screen music's audio while in the mod menu and fades in/out". This compiles
mods_music.h alone and checks the rule, with a made-up tune and a made-up game mix:

- with no tune (not read, or not in the game's files) a block is the game's as it is, whatever is asked;
- the screen opening: the level rises a sample at a time to 1 over MODS_MUSIC_FADE samples, never stepping; every one
  of the game's channels has 1 - level, down to nothing; the tune is in the front pair times level times its gain;
- the tune goes round between the loop points its file names, and a tune with none plays once and is silent after;
- the screen shutting: the level falls back to 0 the same way, the game's own sound is whole again, and the tune is at
  its top for the next opening; a shut and silent block is not touched at all;
- a loop outside the tune, or too short to be one, is no loop.

And reads the source: the sound thread calls it after the game's limiter and before the options' own sounds (which
keep their level) and the Master volume; mods_music.c asks the options (HOS_OPT_MODS_MUSIC) and the Menu sounds row,
reads the shop theme through nn_fs.c (a mod's file where a mod replaces it) on a thread of its own, and takes the
loop from the file; the options answer 2 only for the Mods screen opened from the title's list.

    python -I -B tests/test_mods_music.py [--cxx clang++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cxx", "{cxx}"]


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PROGRAM = r"""
#include <cmath>
#include <cstdio>
#include <vector>
#include "mods_music.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
static bool near(float a, float b, float tol = 1e-4f) { return std::fabs(a - b) <= tol; }
constexpr uint32_t kBlock = 240;   // (nn_audio.c's block: 5 ms)

struct Mix {
    std::vector<float> ch[6];
    float* p[6];
    explicit Mix(int nch) {
        for (int c = 0; c < 6; c++) ch[c].assign(kBlock, c < nch ? 0.5f + 0.1f * (float)c : 0.0f), p[c] = ch[c].data();
    }
};

int main() {
    // a tune: 2 s, its left the frame's number over its length, its right the negative
    const uint32_t frames = 2 * MODS_MUSIC_RATE;
    std::vector<float> tune((size_t)frames * 2);
    for (uint32_t i = 0; i < frames; i++) tune[2 * (size_t)i] = (float)i / (float)frames, tune[2 * (size_t)i + 1] = -(float)i / (float)frames;

    {   // no tune: the game's block as it is
        ModsMusic m{};
        Mix x(2);
        CHECK(mods_music_block(&m, 1, x.p, 2, x.p[0], x.p[1], kBlock, 1.0f) == 0.0f);
        CHECK(x.ch[0][0] == 0.5f && x.ch[1][kBlock - 1] == 0.6f && m.level == 0.0f);
    }

    ModsMusic m{};
    m.pcm = tune.data(), m.frames = frames;
    mods_music_loop(&m, MODS_MUSIC_RATE / 2, frames);   // (round from 0.5 s to its end)
    CHECK(m.loop_start == MODS_MUSIC_RATE / 2 && m.loop_end == frames);

    {   // shut and silent: not touched
        Mix x(6);
        CHECK(mods_music_block(&m, 0, x.p, 6, x.p[0], x.p[1], kBlock, 0.35f) == 0.0f);
        for (int c = 0; c < 6; c++) CHECK(x.ch[c][0] == 0.5f + 0.1f * (float)c && x.ch[c][kBlock - 1] == 0.5f + 0.1f * (float)c);
        CHECK(m.pos == 0);
    }

    // the screen opens: the level up a sample at a time, the game's six channels down, the tune in the front pair
    const float gain = 0.35f;
    float last = 0.0f;
    uint32_t played = 0;
    for (uint32_t done = 0; done < MODS_MUSIC_FADE + 2 * kBlock; done += kBlock) {
        Mix x(6);
        const float before = m.level;
        const uint32_t pos = m.pos;
        const float level = mods_music_block(&m, 1, x.p, 6, x.p[0], x.p[1], kBlock, gain);
        CHECK(level >= last && level <= 1.0f && level - before <= (float)kBlock / (float)MODS_MUSIC_FADE + 1e-4f);
        for (uint32_t i = 0; i < kBlock; i += 79) {
            float l = before + (float)(i + 1) / (float)MODS_MUSIC_FADE;
            if (l > 1.0f) l = 1.0f;
            for (int c = 2; c < 6; c++) CHECK(near(x.ch[c][i], (0.5f + 0.1f * (float)c) * (1.0f - l)));   // (every channel)
            const float t = tune[2 * (size_t)(pos + i)];
            CHECK(near(x.ch[0][i], 0.5f * (1.0f - l) + t * l * gain) && near(x.ch[1][i], 0.6f * (1.0f - l) - t * l * gain));
        }
        last = level, played += kBlock;
        CHECK(m.pos == played);   // (no loop yet: 0.6 s in)
    }
    CHECK(near(m.level, 1.0f, 1e-6f));
    {   // all there: the game's own sound is nothing, the tune alone times its gain
        Mix x(2);
        const uint32_t pos = m.pos;
        mods_music_block(&m, 1, x.p, 2, x.p[0], x.p[1], kBlock, gain);
        CHECK(near(x.ch[0][10], tune[2 * (size_t)(pos + 10)] * gain) && near(x.ch[1][10], tune[2 * (size_t)(pos + 10) + 1] * gain));
    }

    // round the loop: past the tune's end it is at the loop's start, never past the end
    bool wrapped = false;
    for (int k = 0; k < 600; k++) {
        Mix x(2);
        const uint32_t before = m.pos;
        mods_music_block(&m, 1, x.p, 2, x.p[0], x.p[1], kBlock, gain);
        CHECK(m.pos < frames && m.pos >= (wrapped ? MODS_MUSIC_RATE / 2 : 0u));
        if (m.pos < before) {
            wrapped = true;
            CHECK(m.pos == MODS_MUSIC_RATE / 2 + (before + kBlock - frames));
        }
    }
    CHECK(wrapped);

    // the screen shuts: down the same way, then the game's own whole and the tune at its top
    last = m.level;
    for (uint32_t done = 0; done < MODS_MUSIC_FADE + 2 * kBlock; done += kBlock) {
        Mix x(2);
        const float before = m.level;
        const float level = mods_music_block(&m, 0, x.p, 2, x.p[0], x.p[1], kBlock, gain);
        CHECK(level <= last && level >= 0.0f && before - level <= (float)kBlock / (float)MODS_MUSIC_FADE + 1e-4f);
        last = level;
    }
    CHECK(m.level == 0.0f && m.pos == 0);
    {
        Mix x(2);
        mods_music_block(&m, 0, x.p, 2, x.p[0], x.p[1], kBlock, gain);
        CHECK(x.ch[0][0] == 0.5f && x.ch[1][kBlock - 1] == 0.6f);
    }
    {   // shut half way through its coming: back down from where it is, no step
        for (int k = 0; k < 40; k++) { Mix x(2); mods_music_block(&m, 1, x.p, 2, x.p[0], x.p[1], kBlock, gain); }
        const float half = m.level;
        CHECK(half > 0.2f && half < 0.5f);
        Mix x(2);
        CHECK(near(mods_music_block(&m, 0, x.p, 2, x.p[0], x.p[1], kBlock, gain), half - (float)kBlock / (float)MODS_MUSIC_FADE));
    }

    // a tune with no loop: once, then silence, the game's own still down while the screen is open
    ModsMusic once{};
    once.pcm = tune.data(), once.frames = MODS_MUSIC_RATE;   // (its first second)
    mods_music_loop(&once, 0, 0);
    CHECK(once.loop_end == 0);
    for (int k = 0; k < 400; k++) { Mix x(2); mods_music_block(&once, 1, x.p, 2, x.p[0], x.p[1], kBlock, gain); }
    CHECK(once.pos == once.frames && once.level == 1.0f);
    {
        Mix x(2);
        mods_music_block(&once, 1, x.p, 2, x.p[0], x.p[1], kBlock, gain);
        CHECK(x.ch[0][5] == 0.0f && x.ch[1][5] == 0.0f);
    }
    // loops that are none: past the tune (cut to it), the wrong way round, too short
    mods_music_loop(&once, 100, 0xfffffff0u);
    CHECK(once.loop_start == 100 && once.loop_end == once.frames);
    mods_music_loop(&once, 5000, 4000);
    CHECK(once.loop_end == 0 && once.loop_start == 0);
    mods_music_loop(&once, 1000, 1000 + MODS_MUSIC_RATE / 20);
    CHECK(once.loop_end == 0);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    host, vk = ROOT / "host", ROOT / "gpu" / "vk"

    audio = (host / "nn_audio.c").read_text(encoding="utf-8")
    frame = audio[audio.index("static void render_frame("):]
    frame = frame[:frame.index("\n}\n") + 3]
    call = "hos_mods_music_frame(channels, nch < 6 ? nch : 6, FRAME);"
    check(call in frame, "render_frame does not call the Mods screen's music")
    check(frame.index("if (lim_enabled)") < frame.index(call) < frame.index("hos_menu_sound_frame(out[0], out[1], FRAME);") <
          frame.index("the Insert menu's Master volume"),
          "the music is not after the game's limiter, before the options' sounds and the Master volume")

    music = (host / "mods_music.c").read_text(encoding="utf-8")
    tick = block(music, "void hos_mods_music_frame(float *const *channels, int nch, uint32_t frames) {")
    check("rx_option(HOS_OPT_MODS_MUSIC, 0)" in tick and "rx_option(HOS_OPT_MENU_SOUND_VOLUME, -1)" in tick,
          "the sound thread does not ask the options for the screen and the Menu sounds row")
    check("const int want = mode == 2 && volume > 0;" in tick, "the tune is wanted without the Mods screen open, or with the sounds off")
    check("mods_music_block(&music, want, channels, nch," in tick, "the block is not the rule's")
    check("CreateThread(NULL, 0, load_main" in tick and "atomic_compare_exchange_strong(&loaded, &none, 1)" in tick,
          "the tune is not read once, on a thread of its own")
    load = block(music, "static DWORD WINAPI load_main(void *arg) {")
    check('"Sound/Resource/Stream/BGM_Shop_Market_Mask.bwav"' in music and "hos_fs_rom_file(files[i], FILE_MOST, &size)" in load,
          "the shop theme is not read from the game's files through nn_fs.c")
    check("hos_menu_sound_decode_long(b, size, &frames, SECONDS_MOST)" in load and "loop_end = u32(b + 0x10 + 0x3c), loop_start = u32(b + 0x10 + 0x40)" in load,
          "the tune is not menu_sound.c's decoder's, or its loop is not its file's")
    sound = (host / "menu_sound.c").read_text(encoding="utf-8")
    check("float *hos_menu_sound_decode(const uint8_t *b, uint64_t size, uint32_t *frames_out) { return decode_most(b, size, frames_out, 10); }" in sound,
          "the interface sounds are no longer held to ten seconds")

    api = (vk / "vk_api.h").read_text(encoding="utf-8")
    check("enum { HOS_OPT_MODS_MUSIC = 161 };" in api and "HOS_OPT_TEXT_CHAR = 159, HOS_OPT_TEXT_WANTED };" in api,
          "HOS_OPT_MODS_MUSIC is not an option of its own number")
    replay = (vk / "vk_replay.cpp").read_text(encoding="utf-8")
    check("if (id == HOS_OPT_MODS_MUSIC) return menu_mods_music();" in replay, "the renderer does not answer HOS_OPT_MODS_MUSIC")
    menu = (vk / "vk_menu.cpp").read_text(encoding="utf-8")
    answer = block(menu, "int menu_mods_music() {")
    check("if (!mods_title_list()) return 0;" in answer and
          "if (open_now.load(std::memory_order_relaxed) && page == kModsPage) return 2;" in answer and
          answer.index("mods_title_list()") < answer.index("return 2;"),
          "the music is not for the Mods screen opened from the title's list alone")

    with tempfile.TemporaryDirectory(prefix="mods-music-") as tmp:
        src, exe = Path(tmp) / "music.cpp", Path(tmp) / "music.exe"
        src.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(host), str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the Mods screen's music as made:\n" + r.stdout)
    print("PASS: the shop theme comes under the Mods screen opened from the title and the title's music goes, 0.6 s each way")


if __name__ == "__main__":
    main()
