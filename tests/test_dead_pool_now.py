"""A dead render target's image goes to the pool in the pass that lets it go (gpu/vk/vk_texture.cpp texture_sweep; no game,
no GPU).

(Triforce, 11-21, the performance audit's TEX-30, after Source A's.) A render target let go waited in the dead list until
the next present's texture_frame put its image in the pool: a target made in this present's recording made a new image
meanwhile. texture_sweep now pools the ones the GPU is done with right after it lets them go.

Reads the source: after the pass has erased the textures it let go, the dead list's entries with a pool key whose value
the GPU has completed go to pool_put, never while a compaction pass is open, and only with the switch on; texture_frame's
own loop still pools and destroys the rest, and the pool is still trimmed each present; the switches are in the table.

    python -I -B tests/test_dead_pool_now.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def check(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def in_order(text, parts, why):
    at = 0
    for p in parts:
        at = text.find(p, at)
        check(at >= 0, why + " (missing, or out of order: " + p + ")")
        at += len(p)


def main():
    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    sweep = tex[tex.rindex("void texture_sweep("):]
    sweep = sweep[:sweep.index("\n}\n")]
    in_order(sweep, ["destroy_later(*tex);", "it = textures.erase(it);",
                     'static const bool dead_pool_now = !(getenv("RX_VK_DEAD_POOL_NOW") && !atoi(getenv("RX_VK_DEAD_POOL_NOW")));',
                     "if (dead_pool_now && !compact.in_pass)", "for (auto it = dead.begin(); it != dead.end();) {",
                     "if (it->pool_key && it->value <= completed) {", "pool_put(*it);", "it = dead.erase(it);", "++it;"],
             "texture_sweep does not pool the dead targets' images the GPU is done with after it lets them go, or does so in a "
             "compaction pass, for an image with no pool key, or for one the GPU still uses")
    frame = tex[tex.index("void texture_frame(uint64_t completed) {"):]
    frame = frame[:frame.index("\n}\n")]
    in_order(frame, ["for (auto it = dead.begin(); it != dead.end();) {", "if (compact.in_pass) break;", "if (it->value > completed) {",
                     "if (it->pool_key) {", "pool_put(*it);", "destroy_image(it->image, it->allocation);", "pool_trim();"],
             "texture_frame no longer pools and destroys what is left of the dead list, or no longer trims the pool each present")
    dev = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("`RX_VK_DEAD_SUM=0`, `RX_VK_DEAD_POOL_NOW=0`, `RX_VK_DEAD_MIN_UNUSED=3`" in dev,
          "docs/development.md: TEX-30's switches are not in the switches table")
    print("PASS: a dead render target's image goes to the pool in the pass that lets it go")


if __name__ == "__main__":
    main()
