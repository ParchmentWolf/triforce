"""A colour pass that tests depth EQUAL gets a margin towards the camera on Intel.

The game draws a depth prepass, then colour passes that test EQUAL against it with another program. Intel's compiler
does not give the two programs the same position to the last bit, so most ground pixels failed the test and the sky
showed through (issue 17, Arc B390). The test becomes LESS_OR_EQUAL with a depth bias towards the camera, only where depth
is tested, not written, and the game asked for EQUAL. RX_VK_EQ_BIAS=<units> chooses it on any GPU, 0 turns it off.
Not for a draw that blends (Death Mountain Trail's haze sheet, drawn whole over the mountain as a khaki veil): it keeps EQUAL.
python -I -B tests/test_equal_depth_margin.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gpu" / "vk" / "vk_draw.cpp"


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    source = SOURCE.read_text(encoding="utf-8")
    state = block(source, "void dynamic_state(VkCommandBuffer cmd")
    if 'getenv("RX_VK_EQ_BIAS")' not in state:
        raise SystemExit("no RX_VK_EQ_BIAS switch")
    if "equal_depth_bias_default(dev.props.vendorID, dev.props.deviceID)" not in state:
        raise SystemExit("the margin's default is not the rule's")
    # (the rule: Intel only, and not discrete Battlemage, 0xE2xx, where the margin drew alpha-tested cutouts as rectangles)
    rule = block(source, "float equal_depth_bias_default(uint32_t vendor, uint32_t device) {")
    if "if (vendor != 0x8086) return 0.0f;" not in rule or "return 64.0f;" not in rule:
        raise SystemExit("the margin is not on by default on Intel only")
    if "(device & 0xFF00u) == 0xE200u" not in rule:
        raise SystemExit("the margin is not off on discrete Battlemage (0xE2xx)")
    if "(device & 0xFF00u) == 0x6400u" not in rule:
        raise SystemExit("the margin is not off on Lunar Lake (0x64xx)")
    cond = "if (eq_bias > 0 && d.dt && !d.dw && d.dop == VK_COMPARE_OP_EQUAL && !blends)"
    if cond not in state:
        raise SystemExit("the margin is not limited to EQUAL tests that do not write depth and do not blend")
    # (a draw that blends keeps the game's EQUAL: a written target with blending on and a factor pair other than ONE, ZERO,
    # which is the same as off and keeps the margin)
    for need in ("(s.color.blend_en >> i & 1) && at.color_format[i]", "target_write_mask(*cur_program, s, i)",
                 "blend_factor(b.src_rgb) != VK_BLEND_FACTOR_ONE || blend_factor(b.dst_rgb) != VK_BLEND_FACTOR_ZERO"):
        if need not in state or state.index(need) > state.index(cond):
            raise SystemExit("the blend check lacks %r before the margin" % need)
    margin = block(state, cond)
    for line in ("d.dop = VK_COMPARE_OP_LESS_OR_EQUAL;", "d.bias_en = VK_TRUE;", "d.bias[0] = -eq_bias"):
        if line not in margin:
            raise SystemExit("the margin lacks %r" % line)
    if not state.index("d.dop = compare_op(s.ds.df);") < state.index(cond):
        raise SystemExit("the margin must come after the game's compare op is read")
    print("EQUAL depth margin ok")


if __name__ == "__main__":
    main()
