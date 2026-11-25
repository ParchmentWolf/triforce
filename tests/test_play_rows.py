"""The rows of how the game plays (gpu/vk/vk_menu.cpp; vk_api.h's options 200 to 239; host/oot_play.h has their rules).

Each row's default must leave the game as it plays without the row. Checked here, without the game:

- the rules (host/oot_play.h), compiled and run: at a row's default the game's own value comes back, bit for bit;
- the patches of the lifted game code (nx2/oot_patches.py): each call goes in once, a second run changes nothing, and code
  that differs (another game version) is left as it is;
- the menu's table, the options' defaults, the host's option numbers and the launcher's copy of the rows agree.

python -I -B tests/test_play_rows.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

FIXTURE = r'''
#include <stdio.h>
#include <string.h>
#include "oot_play.h"
#include "oot_autoload.h"
#include "mic_gain.h"

static int fails;
#define CHECK(cond, what) do { if (!(cond)) { fails++; printf("FAIL line %d: %s\n", __LINE__, what); } } while (0)
static uint32_t bits(float f) { uint32_t u; memcpy(&u, &f, 4); return u; }

int main(void) {
    /* Field of view */
    {
        const float game[] = {0.5f, 0.8726646f, 1.0471976f, 0.1f, 2.4f, 0.0f, -1.0f, 3.2f};
        for (unsigned i = 0; i < sizeof game / sizeof game[0]; i++)
            CHECK(bits(oot_fov_angle(game[i], 100)) == bits(game[i]), "100%: the game's own angle, bit for bit");
        CHECK(oot_fov_angle(1.0f, 150) > 1.49f && oot_fov_angle(1.0f, 150) < 1.51f, "150%: half as wide again");
        CHECK(oot_fov_angle(1.0f, 50) > 0.49f && oot_fov_angle(1.0f, 50) < 0.51f, "50%: half");
        CHECK(oot_fov_angle(1.0f, 49) == 1.0f && oot_fov_angle(1.0f, 151) == 1.0f && oot_fov_angle(1.0f, 0) == 1.0f, "a percent outside the row: the game's");
        CHECK(oot_fov_angle(2.4f, 150) < 2.45f, "never past 140 degrees");
        CHECK(oot_fov_angle(0.1f, 50) > 0.087f, "never under 5 degrees");
        CHECK(oot_fov_angle(0.0f, 150) == 0.0f && oot_fov_angle(-1.0f, 150) == -1.0f && oot_fov_angle(3.2f, 50) == 3.2f, "not an angle: left");
        const float nan = oot_fov_angle(NAN, 150);
        CHECK(nan != nan, "not a number: left");
    }
    /* Text size */
    {
        CHECK(oot_text_size_scale(0) == 1.0f && oot_text_size_scale(-1) == 1.0f && oot_text_size_scale(5) == 1.0f, "Normal, and anything outside the row: 1");
        CHECK(oot_text_size_scale(1) == 1.10f && oot_text_size_scale(4) == 1.75f, "the row's scales");
        OotTextField f = {0x1000, bits(0.8f), bits(0.8f), 0};
        CHECK(oot_text_size_value(&f, bits(0.8f), 1.0f) == bits(0.8f), "Normal: the game's own value, bit for bit");
        const uint32_t big = oot_text_size_value(&f, bits(0.8f), 1.5f);
        CHECK(big == bits(0.8f * 1.5f), "150%: the game's value times 1.5");
        CHECK(oot_text_size_value(&f, big, 1.5f) == big, "our own value seen again: not scaled twice");
        CHECK(oot_text_size_value(&f, bits(1.0f), 1.5f) == bits(1.5f) && f.game == bits(1.0f), "the game wrote it since: that is its own value now");
        CHECK(oot_text_size_value(&f, bits(1.5f), 1.0f) == bits(1.0f), "back at Normal: the game's value back");
    }
    /* Damage taken (life in quarter hearts) */
    {
        for (uint32_t old = 0; old <= 80; old++)
            for (uint32_t hit = 0; hit <= 90; hit++) {
                const uint32_t next = hit >= old ? 0 : old - hit;   /* (the game's: the whole hit off, never below 0) */
                CHECK(oot_damage_life(old, next, hit, OOT_DAMAGE_NORMAL) == next, "Normal: the game's own life");
                CHECK(oot_damage_life(old, next, hit, 4) == next && oot_damage_life(old, next, hit, -1) == next, "outside the row: the game's");
                CHECK(oot_damage_life(old, next, hit, OOT_DAMAGE_HALF) >= next, "Half never takes more");
                CHECK(oot_damage_life(old, next, hit, OOT_DAMAGE_DOUBLE) <= next && oot_damage_life(old, next, hit, OOT_DAMAGE_QUADRUPLE) <= next, "Double and Quadruple never take less");
                CHECK(oot_damage_life(old, next, hit, OOT_DAMAGE_QUADRUPLE) <= old, "never above the life before");
            }
        CHECK(oot_damage_life(12, 8, 4, OOT_DAMAGE_HALF) == 10, "Half: half the hit");
        CHECK(oot_damage_life(12, 11, 1, OOT_DAMAGE_HALF) == 11, "Half: a quarter heart still takes a quarter");
        CHECK(oot_damage_life(12, 9, 3, OOT_DAMAGE_HALF) == 10, "Half: rounded up");
        CHECK(oot_damage_life(3, 0, 16, OOT_DAMAGE_HALF) == 0, "Half of a hit clamped at 0 is half of the whole hit: still deadly here");
        CHECK(oot_damage_life(12, 0, 16, OOT_DAMAGE_HALF) == 4, "Half of a deadly hit: by the whole hit, not by what was left");
        CHECK(oot_damage_life(12, 8, 4, OOT_DAMAGE_DOUBLE) == 4 && oot_damage_life(12, 8, 4, OOT_DAMAGE_QUADRUPLE) == 0, "Double, Quadruple");
        CHECK(oot_damage_life(12, 8, 0xc0000000u, OOT_DAMAGE_QUADRUPLE) == 0, "a huge hit does not wrap");
        CHECK(oot_damage_life(8, 12, 4, OOT_DAMAGE_QUADRUPLE) == 12 && oot_damage_life(8, 8, 4, OOT_DAMAGE_HALF) == 8, "healing, or nothing lost: never scaled");
    }
    /* Autosave: which requests are a crossing's */
    {
        CHECK(oot_autosave_transition(0x80bc7764ULL, 0x80bc7710ULL, 6, 0), "the transition's own");
        CHECK(oot_autosave_transition(0x80bc7764ULL, 0x80bc7864ULL, 2, 0) && oot_autosave_transition(0x80bc7764ULL, 0x832a9764ULL, 1, 0), "the arrival's two");
        CHECK(!oot_autosave_transition(0x80bc7764ULL, 0x80bc7710ULL, 2, 0) && !oot_autosave_transition(0x80bc7764ULL, 0x80bc7864ULL, 6, 0), "another reason at the same place: not one");
        CHECK(!oot_autosave_transition(0x80bc7764ULL, 0x80bc7710ULL, 6, 1), "another mode: not one");
        CHECK(!oot_autosave_transition(0x83296490ULL, 0, 6, 0) && !oot_autosave_transition(0x832a588cULL, 0, 2, 0) && !oot_autosave_transition(0x82d12c7cULL, 0, 1, 0), "the function's other callers (the pause menu's Save): never");
        CHECK(!oot_autosave_transition(0x80bc7764ULL, 0x832a276cULL, 6, 0) && !oot_autosave_transition(0x80bc7764ULL, 0x805938b0ULL, 2, 0), "the wrapper's other callers: never");
    }
    /* Microphone gain */
    {
        int16_t pcm[4] = {1000, -2000, 30000, -32768}, was[4];
        memcpy(was, pcm, sizeof pcm);
        CHECK(mic_gain_apply(MIC_GAIN_PCM16, (uint8_t *)pcm, sizeof pcm, 100) == 0 && !memcmp(pcm, was, sizeof pcm), "100%: the microphone's own samples");
        CHECK(mic_gain_apply(MIC_GAIN_PCM16, (uint8_t *)pcm, sizeof pcm, 401) == 0 && mic_gain_apply(MIC_GAIN_PCM16, (uint8_t *)pcm, sizeof pcm, -1) == 0 &&
              !memcmp(pcm, was, sizeof pcm), "a percent outside the row: untouched");
        CHECK(mic_gain_apply(3, (uint8_t *)pcm, sizeof pcm, 200) == 0 && !memcmp(pcm, was, sizeof pcm), "a format that is none of them: untouched");
        CHECK(mic_gain_apply(MIC_GAIN_PCM16, (uint8_t *)pcm, sizeof pcm, 200) == 1, "200%: a sample past full scale clipped");
        CHECK(pcm[0] == 2000 && pcm[1] == -4000 && pcm[2] == 32767 && pcm[3] == -32768, "twice, held at full scale");
        memcpy(pcm, was, sizeof pcm);
        CHECK(mic_gain_apply(MIC_GAIN_PCM16, (uint8_t *)pcm, sizeof pcm, 50) == 0 && pcm[0] == 500 && pcm[1] == -1000 && pcm[3] == -16384, "50%: half");
        float f[3] = {0.25f, -0.75f, 0.5f};
        CHECK(mic_gain_apply(MIC_GAIN_FLOAT, (uint8_t *)f, sizeof f, 400) == 1 && f[0] == 1.0f && f[1] == -1.0f && f[2] == 1.0f, "float: within -1 to 1");
        int8_t b[2] = {10, -100};
        CHECK(mic_gain_apply(MIC_GAIN_PCM8, (uint8_t *)b, sizeof b, 200) == 1 && b[0] == 20 && b[1] == -128, "8 bits");
        int32_t w[2] = {1 << 20, -(1 << 30)};
        CHECK(mic_gain_apply(MIC_GAIN_PCM32, (uint8_t *)w, sizeof w, 400) == 1 && w[0] == 1 << 22 && w[1] == INT32_MIN, "32 bits");
        uint8_t odd[5] = {0x10, 0x00, 0x20, 0x00, 0x7f};   /* (a block that ends inside a sample: the rest is left) */
        CHECK(mic_gain_apply(MIC_GAIN_PCM16, odd, sizeof odd, 200) == 0 && odd[0] == 0x20 && odd[2] == 0x40 && odd[4] == 0x7f, "whole samples only");
    }
    /* Skip title screen */
    {
        const int64_t S = 1000000000LL;
        const int64_t three[3] = {100, 300, 200};
        CHECK(oot_autoload_newest_here(three, 3, 1) == 1, "the file saved in last is the newest");
        CHECK(oot_autoload_newest_here(three, 3, 0) == 0 && oot_autoload_newest_here(three, 3, 2) == 0, "another file was saved in later: not here");
        const int64_t none[3] = {0, 0, 0}, one[3] = {0, 50, 0};
        CHECK(oot_autoload_newest_here(none, 3, 0) == 0, "no save at all: the title stays");
        CHECK(oot_autoload_newest_here(one, 3, 0) == 0 && oot_autoload_newest_here(one, 3, 1) == 1, "a new file with no save: the title stays");
        CHECK(oot_autoload_newest_here(three, 3, 3) == 0 && oot_autoload_newest_here(three, 3, -1) == 0, "a file that is none");
        CHECK(oot_autoload_stage(0x84c106e8ULL) == OOT_AUTOLOAD_TITLE && oot_autoload_stage(0x84c0eba0ULL) == OOT_AUTOLOAD_FILES &&
              oot_autoload_stage(0x84c0f840ULL) == OOT_AUTOLOAD_BOX && oot_autoload_stage(0x84c0f108ULL) == OOT_AUTOLOAD_OTHER, "the start's three screens");

        OotAutoload a = {0};
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, S, 0, 0, 0) == 0, "not begun: nothing is pressed");
        /* the whole way: Continue, the file it opens on, Load */
        oot_autoload_begin(&a, 10 * S);
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, 10 * S, 0, 0, 5 * S) == 1, "A on Continue at once");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, 10 * S + S / 2, 0, 0, 5 * S) == 0, "not again within 0.7 s");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, 11 * S, 0, 0, 5 * S) == 1, "again when the title did not take it");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_FILES, 3, 12 * S, 0, 0, 5 * S) == 1, "A on the file the select opens on, wherever its place");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, 12 * S + S, 0, 0, 5 * S) == 0, "the title fading out under it: not pressed");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_BOX, 0, 14 * S, 0, 0, 5 * S) == 1, "A on Load");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_BOX, 0, 17 * S, 0, 0, 5 * S) == 0, "the box is given 5 s");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_BOX, 0, 18 * S, 0, 1, 5 * S) == 0 && a.state == OOT_AUTOLOAD_OVER && a.why == OOT_AUTOLOAD_LOADED, "Link runs: over");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_BOX, 0, 30 * S, 0, 0, 5 * S) == 0, "over is over");
        /* what ends a run without a press */
        oot_autoload_begin(&a, 10 * S);
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 1, 10 * S, 0, 0, 0) == 0 && a.why == OOT_AUTOLOAD_CURSOR, "the title's cursor not on Continue: nothing pressed");
        oot_autoload_begin(&a, 10 * S);
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_BOX, 1, 10 * S, 0, 0, 0) == 0 && a.why == OOT_AUTOLOAD_CURSOR, "the box's cursor not on Load: nothing pressed");
        oot_autoload_begin(&a, 10 * S);
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_OTHER, 0, 10 * S, 0, 0, 0) == 0 && a.why == OOT_AUTOLOAD_SCREEN, "another screen: nothing pressed");
        oot_autoload_begin(&a, 10 * S);
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, 11 * S, 0, 0, 10 * S + 1) == 0 && a.why == OOT_AUTOLOAD_PLAYER, "the player pressed something: theirs");
        oot_autoload_begin(&a, 10 * S);
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, 11 * S, 1, 0, 0) == 0 && a.state == OOT_AUTOLOAD_RUNS, "our options open: it waits");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, 12 * S, 0, 0, 0) == 1, "and goes on when they close");
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_BOX, 0, 17 * S, 0, 0, 0) == 0 && a.why == OOT_AUTOLOAD_LATE, "a list that comes up after a gap is the player's (the pause menu's Load)");
        oot_autoload_begin(&a, 10 * S);
        int presses = 0;
        for (int64_t t = 10 * S; t < 20 * S && a.state == OOT_AUTOLOAD_RUNS; t += S / 60) presses += oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, t, 0, 0, 0);
        CHECK(presses == OOT_AUTOLOAD_PRESSES && a.why == OOT_AUTOLOAD_NOT_TAKEN, "a screen that takes no press: four, then over");
        oot_autoload_begin(&a, 10 * S);
        CHECK(oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, 10 * S, 1, 0, 0) == 0, "held");
        for (int64_t t = 10 * S; t <= 101 * S; t += S) (void)oot_autoload_step(&a, OOT_AUTOLOAD_TITLE, 0, t, 1, 0, 0);
        CHECK(a.state == OOT_AUTOLOAD_OVER && a.why == OOT_AUTOLOAD_LATE, "90 s after it began: over");
    }
    if (!fails) printf("all checks passed\n");
    return fails != 0;
}
'''

HEAD = '#include "a64.h"\n'
# (f_804e48c0's shape around the camera's angle, build e0f3ccfa: the label, the straight line to the angle's load, the half
# angle after it with a store mark's line between, as the lift on disk has it, and the function's second load of the angle)
FOV_LIFTED = (
    HEAD +
    "void f_804e48c0(Ctx *__restrict A64_NOESC c) {\n"
    "if (c->x[8] != 0) { goto L_804e5420; }\n"
    + oot_patches.FOV_LABEL +
    "    c->x[8]=recomp_load64(c,c->x[19] + 24);\n"
    "    c->x[20]=recomp_load64(c,c->x[8] + 16);\n"
    + oot_patches.FOV_LOAD +
    "    A64_MARK((c->x[20] + (uint64_t)(int64_t)(8)), 152);\n"
    + oot_patches.FOV_NEXT + "_z=(_a^_b)&0x80000000ULL;\n"
    "L_804e53e8:;\n"
    + oot_patches.FOV_LOAD +
    "{ A64_POLL(c); goto L_804e52d0; }\n"
    "}\n"
    "\nvoid f_80000000(Ctx *__restrict A64_NOESC c) {\n"   # (another function with the same lines: left)
    + oot_patches.FOV_LABEL.replace("804e52d0", "80000010") + oot_patches.FOV_LOAD + oot_patches.FOV_NEXT + "\n"
    "}\n"
)

# (f_80b1e140's shape, as tests/test_text_speed.py has it: the call that reaches the letters' block, and the block's head)
TEXT_LIFTED = (
    HEAD +
    "void f_80b1e140(Ctx *__restrict A64_NOESC c) {\n"
    "if (((c->x[9] >> 0) & 1)) { goto L_80b1e1b4; }\n"
    "L_80b1e18c:;\n"
    "return;\n"
    "%s"
    "if (((c->x[8] >> 4) & 1)) { goto L_80b1e460; }\n"
    "}\n"
    "void f_80b1e9f0(Ctx *__restrict A64_NOESC c) {\n"
    "}\n"
)

# (f_80644c80's shape around state 3's yaw follow: the join of the yaw paths, the game's own way there past the authored
# override, and the movement's block)
CAM_LIFTED = (
    HEAD +
    "void f_80644c80(Ctx *__restrict A64_NOESC c) {\n"
    "c->x[30] = 0x80645ad8ULL; f_80649c10(c);\n"
    "L_80645ad8:;\n"
    "    c->x[8]=recomp_load32(c,c->x[19] + 516);\n"
    "if (((c->x[28] >> 0) & 1)) { goto L_8064720c; }\n"
    "    { uint64_t _r = ((uint64_t)0 | ((c->x[26]) << 0)); c->x[25] = _r; }\n"
    "if (c->z) { { A64_POLL(c); goto L_80645ad8; } }\n"
    "goto L_806492c4;\n"
    + oot_patches.CAM_FOLLOW_ANCHOR +
    "c->x[30] = 0x80647218ULL; f_80649970(c);\n"
    "c->x[30] = 0x806475e8ULL; f_80642410(c);\n"
    "{ A64_POLL(c); goto L_80645ad8; }\n"
    "L_806492c4:;\n"
    "}\n"
    "\nvoid f_80000000(Ctx *__restrict A64_NOESC c) {\n"
    + oot_patches.CAM_FOLLOW_ANCHOR + oot_patches.CAM_FOLLOW_JOIN +
    "}\n"
)

# (f_804bd8c0's shape at its two writes of an actor's life: the hit's, x12 = x10 - x9 under its own label, and the healing's;
# %s: what stands before each write, the heart protection's guard)
LIFE_LIFTED = (
    HEAD +
    "void f_804bd8c0(Ctx *__restrict A64_NOESC c) {\n"
    "L_804bdcdc:;\n"
    + oot_patches.DAMAGE_SUB +
    "    { uint64_t _a=c->x[8], _b=8ULL; uint64_t _r=_a+_b; c->x[13]=_r; }\n"
    "%s"
    + oot_patches.LIFE_CAS + "\n"
    "L_804bdeb8:;\n"
    "    { uint64_t _a=c->x[11],_b=((uint64_t)(uint32_t)(((uint32_t)(c->x[10])) << 0)),_r=_a+_b; _r&=0xFFFFFFFFULL; c->x[12]=_r; }\n"
    "%s"
    + oot_patches.LIFE_CAS + "\n"
    "L_804bdeac:;\n"
    "}\n"
)


def table_rows():
    """vk_menu.cpp's rows: name -> (tab, value, lo, hi, step), for the rows with a value"""
    text = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    body = text[text.index("Row rows[] = {"):text.index("constexpr int kRowsEnd")]
    rows = {}
    for m in re.finditer(r'\{(TAB_[A-Z0-9]+), "([^"]+)", &opts\.(\w+), (-?\w+), ([^,]+), (\d+),', body):
        rows[m.group(2)] = (m.group(1), m.group(3), m.group(4), m.group(5).strip(), int(m.group(6)))
    return rows


def table_help(name):
    """A row's help as the menu shows it: the string literals after its value's text function, joined"""
    text = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    body = text[text.index("Row rows[] = {"):text.index("constexpr int kRowsEnd")]
    at = body.index('"%s", &opts.' % name)
    m = re.compile(r'[^"{}]*?,((?:\s*"(?:[^"\\]|\\.)*")+)').match(body, at + len(name) + 2)
    if not m:
        return None
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace('\\"', '"')


def schema_rows():
    """The launcher's copy of the rows, in its order: (tab, section, name, lo, hi, step, default, restart, exempt, help)"""
    text = (ROOT / "launcher/Logic/GameOptions/GameOptionsSchema.cs").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'Row\(GameOptionTab\.(\w+), "([^"]+)", "([^"]+)", (-?\d+), (-?\d+), (\d+), (-?\d+), GameOptionKind\.\w+, \w+, '
                         r'(true|false), (true|false),\s*"((?:[^"\\]|\\.)*)"\)', text):
        out.append((m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), int(m.group(6)), int(m.group(7)),
                    m.group(8) == "true", m.group(9) == "true", m.group(10).replace('\\"', '"')))
    return out


def option_defaults():
    text = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
    body = text[text.index("struct Options {"):text.index("extern Options opts;")]
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"^\s*int (\w+) = (-?\d+);", body, re.M)}


def api_options():
    """vk_api.h's HOS_OPT_* numbers, by name"""
    text = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"enum\s*\{([^}]*)\}", text):
        value = -1
        for part in m.group(1).split(","):
            part = re.sub(r"/\*.*?\*/", "", part, flags=re.S).strip()
            if not part:
                continue
            name, _, number = part.partition("=")
            try:
                value = int(number.strip(), 0) if number.strip() else value + 1
            except ValueError:
                value = out.get(number.strip(), value)
            if name.strip().startswith("HOS_OPT_"):
                out[name.strip()] = value
    return out


# (row, its tab, the Options field, lo, hi, step, the default, the option's name; the launcher's section)
ROWS = (
    ("Field of view", "TAB_SYSTEM", "fov", "50", "150", 5, 100, "HOS_OPT_FOV", "Game"),
    ("Text size", "TAB_SYSTEM", "text_size", "0", "4", 1, 0, "HOS_OPT_TEXT_SIZE", "Game"),
    ("Camera centering", "TAB_CONTROLS", "camera_centering", "0", "1", 1, 1, "HOS_OPT_CAMERA_CENTERING", "Gameplay"),
    ("Damage taken", "TAB_SYSTEM", "damage_taken", "0", "3", 1, 1, "HOS_OPT_DAMAGE_TAKEN", "Game"),
    ("Skip opening", "TAB_SYSTEM", "skip_opening", "0", "1", 1, 0, "HOS_OPT_SKIP_OPENING", "Game"),
    ("Skip title screen", "TAB_SYSTEM", "skip_title", "0", "1", 1, 0, "HOS_OPT_SKIP_TITLE", "Game"),
    ("Autosave", "TAB_SYSTEM", "autosave", "0", "1", 1, 1, "HOS_OPT_AUTOSAVE", "Saves & reports"),
    ("Mute in background", "TAB_AUDIO", "mute_background", "0", "1", 1, 0, "HOS_OPT_MUTE_BACKGROUND", "Sound"),
    ("Microphone gain", "TAB_AUDIO", "mic_gain", "25", "400", 25, 100, "HOS_OPT_MIC_GAIN", "Microphone"),
)


class PlayRowsTest(unittest.TestCase):
    def test_rules(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory(prefix="play-rows-") as d:
            tmp = Path(d)
            (tmp / "t.c").write_text(FIXTURE, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-O1", "-I", str(ROOT / "host"),
                                    str(tmp / "t.c"), "-o", str(binary), "-lm"], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("all checks passed", run.stdout)

    def test_fov_patch(self):
        out, n = oot_patches.patch_fov(FOV_LIFTED)
        self.assertEqual(n, 1)
        self.assertEqual(out.count(oot_patches.FOV_HOOK), 1)
        self.assertEqual(out.count(oot_patches.FOV_DECL), 1)
        hook = out.index(oot_patches.FOV_HOOK)
        self.assertEqual(out[:hook].count(oot_patches.FOV_LOAD), 1)                       # (after the first load of the angle)
        self.assertLess(out.index(oot_patches.FOV_LABEL), hook)
        self.assertLess(hook, out.index("A64_MARK((c->x[20]"))                            # (before the half angle is made)
        self.assertEqual(oot_patches.patch_fov(out), (out, 1))                            # (a second run)
        self.assertEqual(out.replace(oot_patches.FOV_HOOK, "").replace(oot_patches.FOV_DECL, ""), FOV_LIFTED)   # (nothing else)

    def test_fov_other_code_left(self):
        for other in (FOV_LIFTED.replace("f_804e48c0", "f_804e48d0"),                      # (no such function)
                      FOV_LIFTED.replace("+316ULL", "+320ULL"),                            # (another offset)
                      FOV_LIFTED.replace("    c->x[20]=recomp_load64(c,c->x[8] + 16);\n", "L_804e52e0:;\n"),   # (a label between)
                      FOV_LIFTED.replace("memcpy(&_b,c->vreg[1],4);", "memcpy(&_b,c->vreg[2],4);")):   # (not the half angle)
            self.assertEqual(oot_patches.patch_fov(other), (other, 0))

    def test_text_size_patch(self):
        for block in (oot_patches.TEXT_OLD_POLLED, oot_patches.TEXT_OLD):          # (with the block's poll, and without)
            lifted = TEXT_LIFTED % block
            speed = oot_patches.patch_text_speed(lifted)
            for before in (speed, lifted):                                          # (after the Text speed row's line, or alone)
                out, n = oot_patches.patch_text_size(before)
                self.assertEqual(n, 1)
                self.assertEqual(out.count(oot_patches.TEXT_SIZE_HOOK), 1)
                self.assertEqual(out.count(oot_patches.TEXT_SIZE_DECL), 1)
                self.assertLess(out.index("L_80b1e1b4:;"), out.index(oot_patches.TEXT_SIZE_HOOK))
                self.assertLess(out.index(oot_patches.TEXT_SIZE_HOOK), out.index("goto L_80b1e460;"))
                if before is speed:
                    self.assertIn(oot_patches.TEXT_ADD + oot_patches.TEXT_SIZE_HOOK, out)
                self.assertEqual(oot_patches.patch_text_size(out), (out, 1))        # (a second run)
                self.assertEqual(out.replace(oot_patches.TEXT_SIZE_HOOK, "").replace(oot_patches.TEXT_SIZE_DECL, ""), before)
            # (the Text speed row's line made after it still goes in once, before the call)
            late = oot_patches.patch_text_speed(oot_patches.patch_text_size(lifted)[0])
            self.assertEqual(late.count(oot_patches.TEXT_ADD + oot_patches.TEXT_SIZE_HOOK), 1)
        for other in ((TEXT_LIFTED % oot_patches.TEXT_OLD).replace("f_80b1e140", "f_80b1e150"),
                      (TEXT_LIFTED % oot_patches.TEXT_OLD).replace("+ 110);", "+ 112);")):
            self.assertEqual(oot_patches.patch_text_size(other), (other, 0))

    def test_camera_centering_patch(self):
        out, n = oot_patches.patch_camera_centering(CAM_LIFTED)
        self.assertEqual(n, 1)
        self.assertEqual(out.count(oot_patches.CAM_FOLLOW_ANCHOR + oot_patches.CAM_FOLLOW_HOOK), 1)   # (after the authored override's branch)
        self.assertEqual(out.count(oot_patches.CAM_FOLLOW_DECL), 1)
        self.assertIn("c->x[25] = c->x[26]; A64_POLL(c); goto L_80645ad8;", oot_patches.CAM_FOLLOW_HOOK)   # (as the game's own path to the join)
        self.assertEqual(oot_patches.patch_camera_centering(out), (out, 1))                # (a second run)
        self.assertEqual(out.replace(oot_patches.CAM_FOLLOW_HOOK, "").replace(oot_patches.CAM_FOLLOW_DECL, ""), CAM_LIFTED)
        for other in (CAM_LIFTED.replace("f_80644c80", "f_80644c90"),                       # (no such function)
                      CAM_LIFTED.replace("if (!c->z) { goto L_806492c4; }", "if (c->z) { goto L_806492c4; }"),
                      CAM_LIFTED.replace("L_80645ad8:;\n", "L_80645adc:;\n")):               # (no join)
            self.assertEqual(oot_patches.patch_camera_centering(other), (other, 0))
        host = (ROOT / "host/mouse_native.c").read_text(encoding="utf-8")
        self.assertIn("int hos_disable_camera_centering(void) { return !rx_option(HOS_OPT_CAMERA_CENTERING, 1); }", host)

    def test_damage_patch(self):
        guard = ("    if ((uint32_t)c->x[12] < (uint32_t)c->x[11] && hos_oot_hearts_enabled() &&\n"
                 "        c->x[13] == recomp_load64(c,c->x[19] + 7184) + 8)\n        c->x[12] = c->x[11];\n")
        for hearts in ("", guard, guard + guard):       # (alone, after the heart protection's guard, and after it made twice)
            lifted = LIFE_LIFTED % (hearts, hearts)
            out, n = oot_patches.patch_damage(lifted)
            self.assertEqual(n, 1)
            self.assertEqual(out.count(oot_patches.DAMAGE_GUARD), 1)
            self.assertEqual(out.count(oot_patches.DAMAGE_DECL), 1)
            first = out.index(oot_patches.LIFE_CAS)
            self.assertEqual(out.index(oot_patches.DAMAGE_GUARD) + len(oot_patches.DAMAGE_GUARD), first)   # (right before the hit's write)
            self.assertLess(out.index(oot_patches.DAMAGE_SUB), out.index(oot_patches.DAMAGE_GUARD))
            self.assertEqual(oot_patches.patch_damage(out), (out, 1))                     # (a second run)
            self.assertEqual(out.replace(oot_patches.DAMAGE_GUARD, "").replace(oot_patches.DAMAGE_DECL, ""), lifted)
        lifted = LIFE_LIFTED % ("", "")
        for other in (lifted.replace("f_804bd8c0", "f_804bd8d0"),                          # (no such function)
                      lifted.replace(oot_patches.DAMAGE_SUB, ""),                          # (the first write is not a hit's)
                      lifted.replace(oot_patches.LIFE_CAS + "\nL_804bdeac:;", "L_804bdeac:;")):   # (one write only)
            self.assertEqual(oot_patches.patch_damage(other), (other, 0))
        # (the call is made only while the row is not Normal, and before anything of the game is read)
        self.assertLess(oot_patches.DAMAGE_GUARD.index("hos_oot_damage_scaled()"), oot_patches.DAMAGE_GUARD.index("hos_oot_is_player("))
        host = (ROOT / "host/oot_damage.c").read_text(encoding="utf-8")
        self.assertIn("int hos_oot_damage_scaled(void) { return rx_option(HOS_OPT_DAMAGE_TAKEN, OOT_DAMAGE_NORMAL) != OOT_DAMAGE_NORMAL; }", host)

    def test_opening_patch(self):
        lifted = HEAD + "".join(head + "    /* nop/hint */\nreturn;\n}\n" for head, _ in oot_patches.OPENING_SITES)
        out, n = oot_patches.patch_opening(lifted)
        self.assertEqual(n, 3)
        for head, line in oot_patches.OPENING_SITES:
            self.assertEqual(out.count(head + line), 1)                                   # (the function's first line)
        self.assertEqual(out.count(oot_patches.OPENING_DECL), 1)
        self.assertEqual(oot_patches.patch_opening(out), (out, 3))                        # (a second run)
        # (one function to a file, as the lift's pieces have them)
        for head, line in oot_patches.OPENING_SITES:
            one, n = oot_patches.patch_opening(HEAD + head + "return;\n}\n")
            self.assertEqual((n, one.count(head + line), one.count("hos_oot_opening(c, ")), (1, 1, 1))   # (its own call alone)
        other = lifted.replace("f_80d9a820", "f_80d9a830").replace("f_83b5bfb0", "f_83b5bfc0").replace("f_80de6cb0", "f_80de6cc0")
        self.assertEqual(oot_patches.patch_opening(other), (other, 0))
        # (the host: Off answers before anything of the game is read; the request is always sent; only the opening's own
        # two timelines are held back)
        host = (ROOT / "host/oot_opening.c").read_text(encoding="utf-8")
        body = host[host.index("int hos_oot_opening(Ctx *c, int mode) {"):]
        off = body.index("rx_option(HOS_OPT_SKIP_OPENING, 0) <= 0")
        self.assertLess(off, body.index("recomp_load"))
        self.assertIn('return 0;   /* (the request is still sent) */', body)
        self.assertEqual(sorted(set(re.findall(r'"(Dm_\w+|Opening_\w+)"', body))),
                         ["Dm_Kokiri_0000", "Dm_Kokiri_0030", "Opening_Introduction", "Opening_LoadingKokiriForest"])
        self.assertNotIn("Meet_DekuTree\"", body)

    def test_autosave_patch(self):
        lifted = HEAD + oot_patches.AUTOSAVE_HEAD + "    c->x[8]=recomp_load32(c,c->x[0] + 344);\nreturn;\n}\n"
        out, n = oot_patches.patch_autosave(lifted)
        self.assertEqual((n, out.count(oot_patches.AUTOSAVE_HEAD + oot_patches.AUTOSAVE_HOOK), out.count(oot_patches.AUTOSAVE_DECL)), (1, 1, 1))
        self.assertEqual(oot_patches.patch_autosave(out), (out, 1))                      # (a second run)
        self.assertEqual(out.replace(oot_patches.AUTOSAVE_HOOK, "").replace(oot_patches.AUTOSAVE_DECL, ""), lifted)
        other = lifted.replace("f_80bc72d0", "f_80bc72e0")
        self.assertEqual(oot_patches.patch_autosave(other), (other, 0))
        # (the host: with the row On nothing of the game is read; a request is skipped only with the row Off)
        host = (ROOT / "host/oot_autosave.c").read_text(encoding="utf-8")
        body = host[host.index("int hos_oot_save_request(Ctx *c) {"):]
        self.assertLess(body.index("if (on && !trace) return 0;"), body.index("c->x["))
        self.assertLess(body.index("if (on || !oot_autosave_transition(caller, parent, reason, mode)) return 0;"), body.index("c->x[0] = 0;"))
        self.assertIn("const int on = rx_option(HOS_OPT_AUTOSAVE, 1) != 0;", body)

    def test_movement_speed(self):
        """The Debug tab's Movement speed tool: its four calls, the host's limits, the menu's choices"""
        lifted = (HEAD +
                  "void f_809552f0(Ctx *__restrict A64_NOESC c) {\n"
                  "L_80955424:;\n    c->x[0]=recomp_load64(c,c->x[8] + 8);\n    c->x[9] = 0x42700000ULL;\n"
                  "L_809554dc:;\n    c->x[0]=recomp_load64(c,c->x[8] + 8);\n    c->x[9] = 0x42700000ULL;\n"
                  "}\n"
                  "void f_80559df0(Ctx *__restrict A64_NOESC c) {\n    c->x[8]=recomp_load64(c,c->x[0] + 40);\nreturn;\n}\n"
                  "void f_80964bf0(Ctx *__restrict A64_NOESC c) {\n    c->x[0]=recomp_load64(c,c->x[0] + 8);\nreturn;\n}\n")
        out, n = oot_patches.patch_cct_speed(lifted)
        self.assertEqual(n, 4)
        frame, second = oot_patches.SPEED_HOOK % (0, "frame"), oot_patches.SPEED_HOOK % (1, "second")
        self.assertEqual((out.count(frame), out.count(second), out.count(oot_patches.SPEED_DECL)), (2, 2, 1))
        for head, anchor, per_second in oot_patches.SPEED_PLACES:
            self.assertEqual(out.count(anchor + (second if per_second else frame)), 1)   # (right after the controller is in x0)
        self.assertEqual(oot_patches.patch_cct_speed(out), (out, 4))                     # (a second run)
        self.assertEqual(out.replace(frame, "").replace(second, "").replace(oot_patches.SPEED_DECL, ""), lifted)
        other = lifted.replace("c->x[8] + 8);", "c->x[8] + 16);").replace("f_80559df0", "f_80559e00").replace("c->x[0] + 8);", "c->x[0] + 16);")
        self.assertEqual(oot_patches.patch_cct_speed(other), (other, 0))
        # (the host: nothing but Link's controller, and none is kept at 1x; only while the player steers, up to 15 m/s)
        host = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
        speed = host[host.index("void hos_oot_cct_speed(Ctx *c, uint64_t controller, int per_second) {"):]
        speed = speed[:speed.index("\n}\n")]
        first = speed.index("if (!controller || controller != __atomic_load_n(&oot_speed_controller, __ATOMIC_RELAXED)) return;")
        self.assertLess(first, speed.index("memcpy("))
        self.assertIn("if (percent <= 100 || percent > 400 || !hos_move_stick_held()) return;", speed)
        self.assertIn("<= 15.0f)) return;", speed)
        player = host[host.index("static void oot_player_speed(Ctx *c, uint64_t components) {"):]
        player = player[:player.index("\n}\n")]
        self.assertIn("int percent = rx_option(HOS_OPT_CHEAT_SPEED, 100);", player)
        self.assertLess(player.index("if (percent > 100) {"), player.index("recomp_load64("))   # (1x: nothing of the game is read)
        menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
        self.assertIn("constexpr int link_speeds[] = {100, 125, 150, 200, 300};", menu)
        self.assertIn("std::atomic<int> link_speed{0};", menu)                            # (1x at every start: never saved)
        self.assertIn("int menu_link_speed() { return cheats_on() ? link_speeds[", menu)  # (and 1x with the tools off)
        self.assertRegex(menu, r'\{TAB_DEBUG, "Movement speed", nullptr, 0, 0, 0, nullptr,\s*"[^"]*", nullptr, false, true, 14\},')
        self.assertIn("if (id == HOS_OPT_CHEAT_SPEED) return menu_link_speed();", (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8"))
        self.assertTrue(200 <= api_options()["HOS_OPT_CHEAT_SPEED"] <= 239)

    def test_mouse_camera_off(self):
        """Mouse camera's third choice, Off: the mouse is never captured, and feeds neither the camera nor the stick"""
        menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
        self.assertIn('{TAB_CONTROLS, "Mouse camera", &opts.mouse_native, 0, 2, 1, tx_mousecam,', menu)
        self.assertIn('const char* tx_mousecam(int v) { return v == 2 ? "Off" : v ? "Native" : "As the stick"; }', menu)
        hints = menu[menu.index("MENU_HINTS(hn_mousecam, 0,"):]
        self.assertEqual(len(re.findall(r'"[^"]+"', hints[:hints.index(")\n")])), 3)       # (a line for each of the three)
        self.assertEqual(option_defaults()["mouse_native"], 0)                            # (As the stick, as before)
        for path in ("host/display.c", "host/posix/display_sdl.c"):
            text = (ROOT / path).read_text(encoding="utf-8")
            capture = text[text.index("static void mouse_capture("):]
            self.assertLess(capture.index("if (on && rx_option(6, 0) == 2) return;"), capture.index("if (on == (int)mouse_captured) return;"), path)
        hid = (ROOT / "host/nn_hid.c").read_text(encoding="utf-8")
        self.assertIn("const int native = mode == 1 && !deck_builtin_input;", hid)
        self.assertIn("int captured = 0, as_stick = mode == 0;", hid)
        self.assertIn("rx_option(6, 0) == 1;", (ROOT / "host/mouse_native.c").read_text(encoding="utf-8"))
        row = {r[2]: r for r in schema_rows()}["Mouse camera"]
        self.assertEqual(row[3:7], ("0", "2", 1, 0))
        self.assertIn('v == 2 ? "Off" : v != 0 ? "Native" : "As the stick"', (ROOT / "launcher/Logic/GameOptions/GameOptionsSchema.cs").read_text(encoding="utf-8"))

    def test_audio_mono(self):
        """Audio output's Mono: stereo's layout for the game, the two channels' average in both as a block is mixed; nothing
        with the row on another choice, and 5.1 is never touched"""
        audio = (ROOT / "host/nn_audio.c").read_text(encoding="utf-8")
        start = audio.index("static void audio_mono(")
        function = audio[start:audio.index("\n}\n", start) + 3]
        self.assertIn("audio_mono(pcm, FRAME, out_channels, rx_option(HOS_OPT_AUDIO_OUTPUT, 0) == 3);", audio)
        self.assertIn("return v < 1 ? 0 : v > 3 ? 3 : v;", audio)                         # (the file's 3 is read as Mono)
        self.assertIn("n = menu == 2 ? 6 : 2;", audio)                                    # (and is stereo for the game)
        menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
        self.assertIn('{TAB_AUDIO, "Audio output", &opts.audio_output, 0, 3, 1, tx_audio_output,', menu)
        self.assertIn("if (r.value == &opts.audio_output && *r.value == 3) return 1;", menu)   # (Stereo to Mono asks no restart)
        self.assertEqual(option_defaults()["audio_output"], 0)
        self.assertEqual({r[2]: r for r in schema_rows()}["Audio output"][3:7], ("0", "3", 1, 0))
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        fixture = ("#include <stdint.h>\n#include <stdio.h>\n#include <string.h>\n" + function + r'''
int main(void) {
    int16_t a[8] = {100, 300, -32768, -32768, 32767, 32767, 32767, -32768}, was[8];
    memcpy(was, a, sizeof a);
    audio_mono(a, 4, 2, 0);
    if (memcmp(a, was, sizeof a)) return printf("FAIL: changed with the row not on Mono\n"), 1;
    audio_mono(a, 1, 6, 1);
    if (memcmp(a, was, sizeof a)) return printf("FAIL: 5.1 changed\n"), 1;
    audio_mono(a, 4, 2, 1);
    const int16_t want[8] = {200, 200, -32768, -32768, 32767, 32767, 0, 0};
    if (memcmp(a, want, sizeof a)) return printf("FAIL: not the average in both channels (full scale too)\n"), 1;
    printf("all checks passed\n");
    return 0;
}
''')
        with tempfile.TemporaryDirectory(prefix="play-rows-mono-") as d:
            tmp = Path(d)
            (tmp / "t.c").write_text(fixture, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-O1", str(tmp / "t.c"), "-o", str(binary)],
                                   text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_mute_in_background(self):
        """Mute in background: the Master volume's gain is 0 while another window has the focus; Off asks no window"""
        audio = (ROOT / "host/nn_audio.c").read_text(encoding="utf-8")
        volume = audio[audio.index("static float master_volume(void) {"):]
        volume = volume[:volume.index("\n}\n")]
        self.assertIn("if (v && rx_option(HOS_OPT_MUTE_BACKGROUND, 0) && !audio_window_in_front()) v = 0;", volume)
        start = audio.index("static int audio_front_decide(")
        decide = audio[start:audio.index("\n}\n", start) + 3]
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        fixture = ("#include <stdio.h>\n" + decide + r'''
int main(void) {
    int last = 1, fails = 0;
#define CHECK(cond, what) do { if (!(cond)) { fails++; printf("FAIL line %d: %s\n", __LINE__, what); } } while (0)
    CHECK(audio_front_decide(1, 0, &last) == 1, "the game's own window: in front");
    CHECK(audio_front_decide(0, 1, &last) == 1, "an overlay over the game: still the game's");
    CHECK(audio_front_decide(0, 0, &last) == 0, "another window: not in front");
    CHECK(audio_front_decide(0, 1, &last) == 0, "an overlay over another window: not the game's");
    CHECK(audio_front_decide(1, 0, &last) == 1 && audio_front_decide(0, 1, &last) == 1, "back in front, and its overlay");
    if (!fails) printf("all checks passed\n");
    return fails != 0;
}
''')
        with tempfile.TemporaryDirectory(prefix="play-rows-mute-") as d:
            tmp = Path(d)
            (tmp / "t.c").write_text(fixture, encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-O1", str(tmp / "t.c"), "-o", str(binary)],
                                   text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_skip_title_source(self):
        """The Skip title screen row's host side: Off asks nothing of the game, nothing of a save is opened or written, and the
        presses are A alone"""
        host = (ROOT / "host/oot_autoload.c").read_text(encoding="utf-8")
        wants = host[host.index("int hos_oot_autoload_wants(void) {"):host.index("static const char *why_text")]
        self.assertIn("if (row == 0) over = 1;", wants)
        self.assertIn("if (row <= 0) return 0;", wants)
        for word in ("fopen", "CreateFile", "fwrite", "WriteFile", "remove(", "MoveFile", "recomp_store", "hos_hid_tap"):
            self.assertNotIn(word, host, word)
        self.assertIn("hos_bench_on()", host)                                            # (benchmark mode has its own start)
        menu = (ROOT / "host/oot_menu.c").read_text(encoding="utf-8")
        auto = menu[menu.index("static void autoload_menu("):]
        auto = auto[:auto.index("\n}\n")]
        self.assertIn('if (hos_oot_autoload_menu(vt, l.index)) hos_hid_tap("0:A/120");', auto)
        self.assertEqual(menu.count("hos_oot_autoload_wants()) autoload_menu(screen, vt_now);"), 1)   # (the Windows half)
        self.assertEqual(menu.count("} else if (hos_oot_autoload_wants()) {"), 1)                     # (the other half)
        files = (ROOT / "host/save_files.c").read_text(encoding="utf-8")
        newest = files[files.index("static int64_t folder_saved("):files.index("/* ---- a file's card")]
        for word in ("fopen", "CreateFile", "fwrite", "WriteFile", "remove(", "MoveFile", "files_save", "card_keep"):
            self.assertNotIn(word, newest, word)
        self.assertIn("return oot_autoload_newest_here(times, SAVE_FILES, files.current);", newest)

    def test_rows(self):
        rows, defaults, api = table_rows(), option_defaults(), api_options()
        schema = {row[2]: row for row in schema_rows()}
        replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
        mine = {name: number for name, number in api.items() if 200 <= number <= 239}
        self.assertEqual(len(set(api.values())), len(api), "two options with one number")
        tabs = {"TAB_SYSTEM": "System", "TAB_CONTROLS": "Controls", "TAB_AUDIO": "Audio", "TAB_DISPLAY": "Display",
                "TAB_GRAPHICS": "Graphics", "TAB_PAGE": "Controls", "TAB_MOTION": "Controls"}
        for name, tab, field, lo, hi, step, default, option, section in ROWS:
            self.assertEqual(rows.get(name), (tab, field, lo, hi, step), name)
            self.assertEqual(defaults.get(field), default, name + ": default")
            self.assertTrue(int(lo) <= default <= int(hi), name + ": the default is a value of the row")
            if option:
                self.assertIn(option, mine, name + ": its option's number is one of 200 to 239")
                self.assertIn("id == %s)" % option, replay, name + ": the renderer answers its option")
            if section is None:   # (a Debug tab's row: not in the launcher, a kept key there)
                self.assertNotIn(name, schema)
                continue
            self.assertIn(name, schema, name + ": in the launcher's schema")
            row = schema[name]
            self.assertEqual(row[:2], (tabs[tab], section), name + ": the launcher's tab and section")
            self.assertEqual(row[3:7], (lo, hi, step, default), name + ": the launcher's range and default")
            self.assertEqual(row[9], table_help(name), name + ": the launcher's help is the menu's")

    def test_launcher_order(self):
        """The launcher's rows come in the menu's order (the launcher's own test holds the whole table to it)"""
        text = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
        body = text[text.index("Row rows[] = {"):text.index("constexpr int kRowsEnd")]
        menu = [m.group(1) for m in re.finditer(r'\{TAB_[A-Z0-9]+, "([^"]+)", &(?:opts|merged)\.', body)]
        launcher = [row[2] for row in schema_rows()]
        both = [name for name in launcher if name in menu]
        self.assertEqual(both, [name for name in menu if name in both])


if __name__ == "__main__":
    unittest.main()
