"""Compile the actual mix effects (biquad filter, delay, plain reverb), the splitter destinations' biquad filters and
their nn::audio setters from host/nn_audio.c around authored mixes and samples.

The "Volcano eruption audio bugged" ticket: the game's AddBiquadFilter, AddDelay and AddReverb on its sub mixes and
SetSplitterBiquadFilterParameter were import stubs, so what it routes through them played unfiltered and too loud.
Checked: a low pass passes a low tone and takes a high one down, a delay's echo lands at the delay time and decays by
the feedback gain, the channel spread moves the echo to the other channel, the plain reverb adds a tail on top of the
dry signal, a splitter destination's filter reaches the voice's mix through render_voice with a history of each
voice's own (a second voice through the same splitter does not hear the first one's), and with
HOS_AUDIO_EFFECTS=0 every sample is left as it was. No game, SDK or output device is used.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
SPLIT_BIQUAD = ("_ZN2nn5audio32SetSplitterBiquadFilterParameterEPNS0_12SplitterTypeEiPNS0_10SubMixTypeEiRKNS0_22"
                "TBiquadFilterParameterIfEE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--source", type=Path, default=ROOT / "host/nn_audio.c")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("audio_block_helper", ROOT / "tests/test_audio_deadline.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    source = args.source.read_text(encoding="utf-8")
    constants = []
    for name in ("FRAME", "RATE", "AU_MAGIC", "MAX_VOICES", "MAX_MIXES", "MAX_SPLITTERS", "MAX_SPLIT_DESTS",
                 "MAX_CH", "MAX_BUF", "MAX_WB", "MAX_REL"):
        matches = re.findall(r"^#define " + name + r"\s+[^\n]+", source, re.M)
        assert len(matches) == 1, name
        constants.extend(matches)
    types = source[source.index("enum { K_VOICE"):source.index("static CRITICAL_SECTION lock;")]
    queue = source[source.index("enum { OP_VOICE_RELEASE"):source.index("static int64_t last_update_ns;")]
    effects = source[source.index("/* ---- I3DL2 reverb (on a sub mix"):source.index("/* ---- the mixer")]
    setters = source[source.index("/* ---- I3DL2 reverb: AddI3dl2Reverb"):]
    actual = ["\n".join(constants), types, """
static Voice voices[MAX_VOICES];
static Mix mixes[MAX_MIXES];
static Splitter splitters[MAX_SPLITTERS];
static int sink_mix = -1;
static void release_wb(Voice *voice, uint64_t buffer) { (void)voice; (void)buffer; }
"""]
    actual.extend(helper.block(source, marker) for marker in (
        "static void put_handle(", "static int get_handle(", "static float farg(", "static int mix_index(",
        "static Mix *mix_of(", "static int splitter_index(", "static Splitter *splitter_of("))
    # (the effects before the update queue, as in the file: apply names the Aux effects)
    actual.extend([effects, queue, helper.block(source, "static void apply("), helper.block(source, "static void submit("),
                   helper.block(source, "static void commit("),
                   "static int next_source_frame(Voice *v);   /* (the fixture's tone) */",
                   """/* ((Triforce) the controller speaker (host/pad_speaker.c, host/audio_source.h), off: nothing classed, nothing sent */
enum { AUDIO_SOURCE_NONE, AUDIO_SOURCE_NAVI_VOICE, AUDIO_SOURCE_NAVI_SOUND, AUDIO_SOURCE_TARGET, AUDIO_SOURCE_OCARINA };
enum { HOS_PAD_SPEAKER_OFF = 0, HOS_PAD_SPEAKER_ONLY = 1, HOS_PAD_SPEAKER_BOTH = 2 };
static int hos_pad_speaker_active(void) { return 0; }
static int speaker_on, tv_delay;
static int hos_pad_speaker_mode(int cls) { (void)cls; return HOS_PAD_SPEAKER_OFF; }
static void hos_pad_speaker_ocarina_seen(void) {}
static void speaker_voice(const Voice *v, float out[][FRAME], const int *pad) { (void)v, (void)out, (void)pad; }
static float (*tv_stage(int mi))[FRAME] { (void)mi; return NULL; }""",
                   helper.block(source, "static void render_voice("),
                   helper.block(source, "static void set_split_biquad("),
                   helper.block(source, "HLE(" + SPLIT_BIQUAD + ")"), setters])
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="audio-mix-effects-") as temporary:
        folder = Path(temporary)
        (folder / "actual_audio_effects.inc").write_text("\n\n".join(actual), encoding="utf-8")
        executable = folder / "fixture.exe"
        build = [args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                 "-Wno-unused-function", "-I" + str(folder), str(ROOT / "tests/audio_mix_effects_test.c"), "-lm", "-o",
                 str(executable)]
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_AUDIO")}
        runs = [(build, env), ([str(executable)], env), ([str(executable)], dict(env, HOS_AUDIO_EFFECTS="0"))]
        for command, environment in runs:
            result = subprocess.run(command, creationflags=flags, capture_output=True, text=True, env=environment,
                                    encoding="utf-8", errors="replace", timeout=60)
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            if result.returncode:
                raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
