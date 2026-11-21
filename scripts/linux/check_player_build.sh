#!/bin/bash
# Game-free: a player's build started from what the AppImage carries, not from the repository. CI's AppImage job packages
# the builder but never builds a game with it, so a file the AppImage leaves out was found by every player instead: #1459
# made nx2/build.py write the menu's fonts from third_party/fonts at every build start, the AppImage does not carry that
# folder, and every Linux build stopped at LibertinusSans-Regular.ttf while CI stayed green (2026-11-10, #1567).
#
#   scripts/linux/check_player_build.sh [<Triforce-...-x86_64.AppImage>]   (default: the newest in build-linux/)
#
# The image is extracted, as its runtime does, and run with AppRun's own environment (the AppImage's Python, compiler,
# sysroot, FFmpeg and the prebuilt Vulkan back end, HOOKSHOT_VK_PREBUILT) in an otherwise empty one, so nothing of the
# checkout or of CI's caches stands in for what the image lacks:
#   - AppRun --cli --help: nx2/make_game.py, as the builder window starts it;
#   - nx2/build.py --standalone --dry-run, as make_game.py runs it: its whole start-up up to the compile, which is where
#     the game's lifted code is first needed. Every other file the compile would read must be in the image.
# Neither may write into the image's tree: on a player's PC it is read-only.
set -euo pipefail
cd "$(dirname "$0")/../.."
IMAGE=${1:-$(ls -t build-linux/Triforce-*-x86_64.AppImage 2>/dev/null | head -1 || true)}
[ -n "$IMAGE" ] && [ -f "$IMAGE" ] || { echo "no AppImage to check (scripts/linux/appimage.sh makes one)"; exit 1; }
IMAGE=$(readlink -f "$IMAGE")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
(cd "$TMP" && "$IMAGE" --appimage-extract >/dev/null)
R=$TMP/squashfs-root
T=$R/usr/share/hookshot
mkdir -p "$TMP/home" "$TMP/work"
# (AppRun's environment, from AppRun itself: its lines before it starts Python, sourced with $0 naming it, so HERE is the image)
sed '/^PY=/,$d' "$R/AppRun" > "$TMP/apprun-env.sh"
in_image() {
    env -i PATH=/usr/bin:/bin HOME="$TMP/home" LANG=C.UTF-8 bash -c '. "$1"; shift; exec "$@"' "$R/AppRun" "$TMP/apprun-env.sh" "$@"
}
touch "$TMP/before"
sleep 1   # (so a file written below is newer than the stamp)

echo "== AppRun --cli --help"
in_image "$R/AppRun" --cli --help > "$TMP/help.txt"
grep -q -- "--nup" "$TMP/help.txt" || { cat "$TMP/help.txt"; echo "nx2/make_game.py did not start"; exit 1; }

# ((Triforce) v0.5.0: the dry run stops before the compile, so a header the compile includes went unseen: v0.5.0's first
# AppImage had no third_party/smaa and every Linux build stopped at gpu/vk/vk_aa.cpp. Each "../" include of the sources the
# image compiles must be in the image)
echo "== the sources' relative includes"
missing=0
while IFS= read -r src; do
    d=$(dirname "$src")
    for inc in $(grep -hoE '^[[:space:]]*#[[:space:]]*include[[:space:]]*"\.\./[^"]+"' "$src" | sed -E 's/.*"(.*)"/\1/'); do
        [ -f "$d/$inc" ] || { echo "missing: $inc (included by ${src#"$T"/})"; missing=1; }
    done
done < <(find "$T/host" "$T/gpu" -type f \( -name "*.c" -o -name "*.cpp" -o -name "*.h" \))
[ "$missing" = 0 ] || exit 1
echo "every relative include of the image's sources is in it"
# ((Triforce) 11-20) and the folders nx2/build.py adds with -I for the optional parts a player's build may turn on: AMD FSR 4's
# headers were not in the image, and the --update of a folder built with FSR 4 stopped at gpu/vk/vk_fsr4.cpp
for need in third_party/fidelityfx/api/include/ffx_api.h third_party/fidelityfx/api/include/vk/ffx_api_vk.h; do
    [ -f "$T/$need" ] || { echo "missing: $need (gpu/vk/vk_fsr4.cpp, a build with AMD FSR 4)"; exit 1; }
done
echo "AMD FSR 4's headers are in it"
# ((Triforce) 11-20) and the back end a player's build reuses (HOOKSHOT_VK_PREBUILT) has FSR 4 compiled in: it names the Linux
# library it looks for only then (vk_fsr4.cpp kLoader; the stubs do not). Built without it, no Linux player could have FSR 4
grep -aq "amd_fidelityfx_upscaler_vk.so" "$R/usr/lib/hookshot/hookshot_vk.so" ||
    { echo "usr/lib/hookshot/hookshot_vk.so was built without AMD FSR 4 (scripts/linux/appimage.sh: HOOKSHOT_FSR=1)"; exit 1; }
echo "the Vulkan back end has AMD FSR 4"

echo "== nx2/build.py --standalone --dry-run (as nx2/make_game.py runs it, with no game)"
# (-B: no __pycache__ written into the image's tree. make_game.py's other settings: nx2/make_game.py, the compile's run())
(cd "$T" && in_image env OOT_WORK="$TMP/work" RX_RELEASE=1 A64_HOT_CHUNK=1 PYTHONIOENCODING=utf-8 \
    "$R/usr/python/bin/python3" -I -B -u -X utf8 nx2/build.py --standalone --jobs 1 --dry-run)

# (Python's own __pycache__ aside: AppRun runs Python with -I, which writes it where it can, and does without where it cannot)
written=$(find "$R" -type f -newer "$TMP/before" ! -path "*/__pycache__/*" -print)
if [ -n "$written" ]; then
    echo "a player's build wrote into the AppImage's tree, which is read-only on a player's PC:"
    echo "$written" | head -20
    exit 1
fi
echo "a player's build starts from the AppImage's tree"
