"""AMD FSR 4's unrolled layers survive an update that changes the translator (no game or GPU required).

The unrolled layers (gpu/vk/vk_fsr4.cpp build_unrolled, RX_VK_FSR4_TUNE=1) take the driver about 50 s and 3 GB of memory each
to build cold on an RX 6700 XT. Built into the translator's pipeline cache, they went with it whenever the translator changed
(the file is kept for one stamp: gpu/vk/vk_draw.cpp pcache_init), and the first FSR 4 frames of each update built them again.
They go into a cache file of their own now, and a layer found in the caches is taken without asking for the memory a compile
wants. This check, on the source as text:
- finds the file vk_fsr4.cpp builds and saves them through (kOwnCacheFile, own_cache_compute_pipeline, own_pipeline_cache_save),
  and that build_unrolled asks the caches (no compile) before it asks for kBuildHeadroom;
- that file is none of the stamp's files (gpu/vk/cache_set.h kPieces), so a change of stamp neither drops nor swaps it;
- vk_draw.cpp reads it only when its header is this device's and driver's (pcache_head_ok) and writes it through a .tmp.

python -I -B tests/test_fsr4_own_cache.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def body(text, head):
    start = text.index(head)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    problems = []
    fsr4 = (ROOT / "gpu/vk/vk_fsr4.cpp").read_text(encoding="utf-8")
    build = body(fsr4, "void build_unrolled(")
    if "shared_cache_compute(" in build or "pipeline_cache_save_play()" in build:
        problems.append("the unrolled layers are built into the translator's pipeline cache, kept for one stamp: every update "
                        "that changes the translator builds them cold again")
    m = re.search(r'constexpr const char\* kOwnCacheFile = "([^"]+)";', fsr4)
    if not m:
        raise SystemExit("FAIL: vk_fsr4.cpp: no kOwnCacheFile, the unrolled layers' own pipeline cache file")
    name = m.group(1)
    save = body(fsr4, "bool save_own_cache(")
    if ("own_cache_compute_pipeline(own_cache()" not in build or "save_own_cache()" not in build
            or "own_pipeline_cache_save(own_cache(), kOwnCacheFile" not in save):
        problems.append("build_unrolled does not build and save through its own cache (kOwnCacheFile)")
    # (the preparation's warm: a frame first, the layers' jobs waited for, then the file written; before the game's caches)
    prepare = body(fsr4, "void fsr4_prepare_shaders() {")
    if not prepare.find("work.run(") < prepare.find("jobs.cv.wait(") < prepare.find("tune::save_own_cache()") or \
            prepare.find("work.run(") < 0:
        problems.append("fsr4_prepare_shaders does not record its frame and wait for the layers' jobs before it saves")
    if "fsr4_model())" not in prepare:
        problems.append("fsr4_prepare_shaders does not warm the model the player picked (fsr4_model), as prepare asks for")
    startup = body((ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8"), "bool started_up()")
    if "fsr4_prepare_shaders();" not in startup or startup.index("fsr4_prepare_shaders();") > startup.index("prepare_run(progress"):
        problems.append("the preparation does not make FSR 4's pipelines before the game's shader caches")
    # (a layer in the caches is taken before the memory a compile wants is asked for: a PC with less than kBuildHeadroom to
    # spare ran without the unrolled layers even when they were cached)
    ask = build.find("VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT")
    if ask < 0 or ask > build.index("build_headroom("):
        problems.append("build_unrolled asks for kBuildHeadroom before it asks the caches for the layer")
    pieces = (ROOT / "gpu/vk/cache_set.h").read_text(encoding="utf-8")
    pieces = pieces[pieces.index("kPieces[]"):pieces.index("};", pieces.index("kPieces[]"))]
    if '"%s"' % name in pieces or '"%s"' % name.split(".")[0] in pieces:
        problems.append("%s is one of the stamp's files (cache_set.h kPieces): a change of stamp would swap or drop it" % name)
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    read = body(draw, "VkPipelineCache own_pipeline_cache(")
    if "pcache_head_ok(" not in read:
        problems.append("own_pipeline_cache takes a file without checking it is this device's and driver's")
    save = body(draw, "bool own_pipeline_cache_save(")
    if '".tmp"' not in save or "MoveFileExA(" not in save:
        problems.append("own_pipeline_cache_save writes the file in place (a cut save would leave half a file)")
    if problems:
        raise SystemExit("FAIL:\n  " + "\n  ".join(problems))
    print("PASS: FSR 4's unrolled layers are kept in %s, apart from the stamp's files, asked of the caches before a compile, "
          "read only from this device and driver, written whole" % name)


if __name__ == "__main__":
    main()
