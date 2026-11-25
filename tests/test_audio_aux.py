"""The actual Aux API and its effect code from host/nn_audio.c, around authored signals; no game or audio device.

The game's own effects (its CPU effect workers) read what a mix sends them with ReadAuxSendBuffer and hand the result
back with WriteAuxReturnBuffer. The host accepted an Aux and passed its mix through: the effect's send was heard as one
more dry source and the effect never. Checked: the buffer size the game is told, whole planar frames out to the worker
and back in place of the send, the channel maps (crossed too), changes waiting for the update, an underrun as silence
and never an old return again, an overflow never queuing a part of a frame, a removed Aux's buffers left alone at once,
its slot taken again before the update, the order across a reverb and an Aux, and a released mix. With HOS_AUDIO_AUX=0
or HOS_AUDIO_EFFECTS=0 an Aux is accepted and passed through, as before.

python -I -B tests/test_audio_aux.py [--cc clang] [--source host/nn_audio.c]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def function(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--source', type=Path, default=ROOT / 'host/nn_audio.c')
    args = parser.parse_args()
    source = args.source.read_text(encoding='utf-8')
    # (the file's own types, update queue, effect code and entry points, in the file's order)
    api = source.index('/* ---- Aux effects: the API')
    reverb = source.index('static Reverb *reverb_of(')
    chunks = [
        source[source.index('#define FRAME'):source.index('/* ---- wave buffers')],
        function(source, 'static void release_wb('),
        source[source.index('/* ---- I3DL2 reverb ('):source.index('/* ---- the mixer')],
        source[source.index('/* ---- parameter updates'):source.index("/* The mixer's next deadline.")],
        function(source, 'HLE(_ZN2nn5audio43GetRequiredBufferSizeForAuxSendReturnBuffer'),
        source[api:source.index('HLE(_ZN2nn5audio17IsReverbRemovable', api)],
        source[reverb:source.index('static void ret_float(', reverb)],
    ]
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 0
    with tempfile.TemporaryDirectory(prefix='audio-aux-') as tmp:
        directory = Path(tmp)
        (directory / 'audio_aux.inc').write_text('\n'.join(chunks), encoding='utf-8')
        exe = directory / 'audio_aux.exe'
        build = [args.cc, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                 '-Wno-unused-variable', '-Wno-unused-parameter', '-I' + str(directory),
                 str(ROOT / 'tests/audio_aux_test.c'), '-lm', '-o', str(exe)]
        env = {k: v for k, v in os.environ.items() if not k.startswith('HOS_AUDIO')}
        for command, environment in ((build, env), ([str(exe)], env), ([str(exe)], dict(env, HOS_AUDIO_AUX='0')),
                                     ([str(exe)], dict(env, HOS_AUDIO_EFFECTS='0'))):
            result = subprocess.run(command, creationflags=flags, capture_output=True, text=True, env=environment,
                                    encoding='utf-8', errors='replace', timeout=120)
            print(result.stdout, end='')
            print(result.stderr, end='', file=sys.stderr)
            if result.returncode:
                raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
