"""A BC texture can be rendered and cleared through a raw (one texel a block) view, sized in blocks, and OoT's noise pass runs
where those views can be made.

OoT renders the slices of two 64^3 BC4 noise volumes as RGBA16UI targets while an area loads (program 53509044401d78d2).
BC images had no colour attachment usage, so those views were not made; the pass ran over no target at the texels' 64 x 64,
and it was left out by default after it lost the device on first starts. The volumes stayed zero and the foliage's dithered
LOD crossfade, which reads them, left trees bare at mid distance (issue 1151).

python -I -B tests/test_bc_raw_targets.py
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class BcRawTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tex = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")
        cls.draw = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
        cls.xfer = (ROOT / "gpu" / "vk" / "vk_xfer.cpp").read_text(encoding="utf-8")

    def test_bc_images_take_colour_attachment_usage_asked_with_the_3d_flags(self):
        raw = self.tex.index("Raw storage views address one compressed block per texel")
        branch = self.tex[raw:self.tex.index("CUBE_COMPATIBLE_BIT", raw)]
        self.assertIn("VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT", branch)
        self.assertRegex(branch, r"x\.usage \|= VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;")
        self.assertIn("VK_IMAGE_CREATE_2D_ARRAY_COMPATIBLE_BIT | (dev.view_2d_of_3d", branch)

    def test_a_refused_bc_image_is_made_again_without_the_attachment_usage_first(self):
        fallback = self.tex.index("// (a compressed image refused:")
        begin = self.tex.rfind("} else if (", 0, fallback)
        self.assertGreaterEqual(begin, 0)
        chain = self.tex[begin:]
        chain = chain[:chain.index("logf(\"vk: image %ux%ux%u")]
        self.assertIn("!create_image(ci, x.image, x.allocation", chain)
        attach = chain.index("ci.usage &= ~VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT")
        storage = chain.index("ci.usage &= ~VK_IMAGE_USAGE_STORAGE_BIT")
        self.assertLess(attach, storage)

    def test_raw_views_of_bc_targets_are_sized_in_blocks(self):
        targets = block(self.draw, "Targets targets(NvnState& s)")
        self.assertRegex(targets, r"if \(bc\(tex->format\) && !bc\(f\)\) w = \(w \+ 3\) / 4, h = \(h \+ 3\) / 4;")
        self.assertLess(targets.index("w = (w + 3) / 4"), targets.index("at.width = at.width ?"))

    def test_clears_through_raw_views_are_sized_in_blocks(self):
        clear = block(self.xfer, "void clear_tex(")
        self.assertIn("raw ? (lw + 3) / 4 : lw", clear)
        self.assertIn("ri.renderArea = {{0, 0}, {aw, ah}};", clear)
        self.assertIn("const VkClearRect rect{{{rx, ry}, {rw, rh}}, 0, 1};", clear)

    def test_the_noise_pass_is_left_out_only_while_its_targets_have_no_view(self):
        line = re.search(r'const char\* list = .*RX_VK_SKIP_PROG.*;', self.draw).group(0)
        self.assertNotIn("53509044401d78d2", line)
        self.assertRegex(self.draw, r"default_list && cp->key == 0x53509044401d78d2ull && !at\.n")

    def test_3d_bc_images_take_no_attachment_usage_on_nvidia_before_turing(self):
        # (Pascal loses the device on a raw view of a 3D BC image: no usage there, so no raw view; its slices are drawn into
        # through block attachments of their own instead, and the noise pass runs: bc3d_way)
        raw = self.tex.index("Raw storage views address one compressed block per texel")
        branch = self.tex[raw:self.tex.index("CUBE_COMPATIBLE_BIT", raw)]
        guard = branch.index("if (x.type == VK_IMAGE_TYPE_3D && bc3d_way() != 1) {")
        usage = branch.index("x.usage |= VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;")
        self.assertLess(guard, usage)
        self.assertIn("} else if (format_props(raw).optimalTilingFeatures & VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT)", branch)
        way = block(self.tex, "int bc3d_way() {")
        self.assertIn("dev.props.vendorID == 0x10de && dev.props.deviceID < 0x1e00", way)
        self.assertIn('getenv("RX_VK_BC3D_TARGET")', way)
        self.assertIn("old_nvidia ? 2 : 1", way)

    def test_3d_bc_slices_are_drawn_through_block_attachments_where_raw_views_cannot_be(self):
        attach = block(self.tex, "TextureAttachment texture_attachment(")
        # (every other image, and every card whose raw views work: texture_view's, as before)
        first = attach[:attach.index("// (the view's format")]
        self.assertIn("tex->type != VK_IMAGE_TYPE_3D || !is_bc(tex->format) || tex->bc || bc3d_way() != 2", first)
        self.assertIn("texture_view(tex, t, v, VK_IMAGE_VIEW_TYPE_2D, ViewUse::Attachment, &out.format)", first)
        # (one texel a block: the level's extent in blocks, every slice, uncompressed, copied to and from)
        self.assertIn("(std::max(1u, tex->width >> level) + 3) / 4, (std::max(1u, tex->height >> level) + 3) / 4, depth", attach)
        self.assertIn("bytes != tex->bpb", attach)
        self.assertIn("VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT", attach)
        self.assertIn("InitRedirect redirect;", attach)
        copy = block(self.tex, "void copy_block_attachment(")
        self.assertIn("to_attachment ? VkExtent3D{width, height, 1} : VkExtent3D{(width + 3) / 4, (height + 3) / 4, 1}", copy)
        # (the pass: loaded behind a full barrier before it begins, stored back behind one after it ends)
        targets = block(self.draw, "Targets targets(NvnState& s)")
        self.assertIn("const TextureAttachment ta = texture_attachment(tex, t, v);", targets)
        begin = block(self.draw, "void begin_pass(VkCommandBuffer cmd, const Targets& at) {")
        load = begin.index("copy_block_attachment(cmd, *at.color[i], at.block_image[i], at.color_level[i], at.color_layer[i], true);")
        self.assertLess(begin.index('full_barrier(cmd, "barrier (before BC slice loads)");'), load)
        self.assertLess(load, begin.index('full_barrier(cmd, "barrier (after BC slice loads)");'))
        self.assertLess(load, begin.index("vkCmdBeginRendering(cmd, &ri);"))
        end = block(self.draw, "void end_pass(VkCommandBuffer cmd) {")
        store = end.index("copy_block_attachment(cmd, *ps.tex[i], ps.block_image[i], ps.level[i], ps.layer[i], false);")
        self.assertLess(end.index("vkCmdEndRendering(cmd);"), store)
        self.assertLess(end.index('full_barrier(cmd, "barrier (before BC slice stores)");'), store)
        self.assertLess(store, end.index('full_barrier(cmd, "barrier (after BC slice stores)");'))
        # (and they go with their texture)
        gone = block(self.tex, "void destroy_later(Texture& tex) {")
        self.assertIn("for (const auto& a : tex.block_attachments) dead.push_back(Dead{tex.last_value, a.image, a.allocation, {}, {}});", gone)

    def test_a_bc_image_is_never_cleared_with_vkCmdClearColorImage(self):
        clear = block(self.xfer, "void clear_tex(")
        self.assertIn("if (whole && !volume && !raw) {", clear)
        self.assertLess(clear.index("const bool raw ="), clear.index("vkCmdClearColorImage("))
        self.assertIn("const uint32_t slices = volume ? s.d : s.layers;", clear)
        self.assertIn("const TextureAttachment attachment = texture_attachment(s.tex, p.tex, &lv);", clear)
        self.assertIn("copy_block_attachment(cmd, *s.tex, attachment.blocks, s.level, slice, true);", clear)
        self.assertIn("copy_block_attachment(cmd, *s.tex, attachment.blocks, s.level, slice, false);", clear)


if __name__ == "__main__":
    unittest.main()
