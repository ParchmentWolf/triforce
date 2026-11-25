"""VK_EXT_memory_priority behind RX_VK_MEMORY_PRIORITY: the switch's reading, the tiers, and that nothing of it is on
without the switch and the extension (gpu/vk/memory_priority.h, vk_main.cpp, vk_vma.cpp, vk_texture.cpp; no game, no GPU).

(Triforce, 11-22, the performance audit's TEX-47, after Source A's.) When a card is short of video memory the system
moves some of the game's device memory to system memory. With the extension the game ranks it: the render targets 1.0,
the sampled textures 0.25, the rest 0.5. Off unless the switch is set.

Compiles a driver against the header: the switch unset, empty, 0, off, no (off); 1 (1.0, 0.25, 0.5); `0.5,0.25` and
`1,0.5` (those two); `0,5`, nan, one other number, three numbers, text (off: what cannot be read changes nothing); the
tiers by kind, the lab's ballast at 1.0, everything at the driver's 0.5 while off or where the device lacks the
extension.

And reads the source:
  - every VmaPoolCreateInfo and VmaAllocationCreateInfo in vk_vma.cpp names a priority before it is used (with the
    extension on, one that names none gets 0, below the textures), the pools their own tier, and no other file of the
    renderer makes one;
  - the allocator's bit is set only with dev.memory_priority, which is the switch, the extension and its feature;
  - vk_main.cpp asks for the extension and chains its feature only with the switch;
  - vk_texture.cpp takes the textures' pool for the rank only with dev.memory_priority and leaves the compaction's own
    line as it was, and a sparse texture's chunks chain a priority only then;
  - the switch is in the switches table.

    python -I -B tests/test_memory_priority.py [--cxx clang++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
RUN_ALL_ARGS = ["--cxx", "{cxx}"]

PROGRAM = r'''
#include <cstdio>
#include "memory_priority.h"
static int fails = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL:%d %s\n", __LINE__, #x); fails++; } } while (0)
using namespace memory_priority;
static bool off(const char* env) {
    const Tiers t = parse(env);
    return !t.on && t.targets == 0.5f && t.textures == 0.5f && t.other == 0.5f;
}
static bool is(const char* env, float targets, float textures) {
    const Tiers t = parse(env);
    return t.on && t.targets == targets && t.textures == textures && t.other == 0.5f;
}
int main() {
    CHECK(kDefault == 0.5f);
    // off: unset, empty, 0, off, no
    CHECK(off(nullptr) && off("") && off("  ") && off("0") && off("off") && off("OFF") && off("no") && off(" 0 "));
    // 1: Source A's tiers
    CHECK(is("1", 1.0f, 0.25f) && is(" 1 ", 1.0f, 0.25f));
    // two numbers: the render targets' and the textures'
    CHECK(is("0.5,0.25", 0.5f, 0.25f) && is("1,0.5", 1.0f, 0.5f) && is("0,0", 0.0f, 0.0f) && is("1,1", 1.0f, 1.0f));
    CHECK(is("0.75,0.125", 0.75f, 0.125f));
    // what cannot be read is off, not a guess
    CHECK(off("0,5"));                 // (5 is no priority; not read as 0.5)
    CHECK(off("nan") && off("nan,0.5") && off("0.5,nan") && off("inf,0.5") && off("0.5,-inf"));
    CHECK(off("1,0.25,0.5"));          // (three numbers)
    CHECK(off("0.5") && off("2") && off("1.0") && off("yes") && off("on") && off("high"));
    CHECK(off("-0.1,0.5") && off("0.5,1.5") && off("0.5,") && off(",0.5") && off("0.5;0.25") && off("0.5 0.25") && off("0.5,0.25x"));
    CHECK(off("0.50000000000000000000000000000,0.25"));   // (longer than a switch is)
    // the tiers by what the memory is for
    const Tiers t = parse("1");
    CHECK(of(t, Kind::Target) == 1.0f && of(t, Kind::Texture) == 0.25f && of(t, Kind::Other) == 0.5f && of(t, Kind::Held) == 1.0f);
    const Tiers low = parse("0.5,0.25");
    CHECK(of(low, Kind::Target) == 0.5f && of(low, Kind::Texture) == 0.25f && of(low, Kind::Held) == 1.0f);   // (the ballast stays)
    // off: the driver's own 0.5 for everything, the ballast too
    const Tiers none;
    CHECK(of(none, Kind::Target) == 0.5f && of(none, Kind::Texture) == 0.5f && of(none, Kind::Other) == 0.5f && of(none, Kind::Held) == 0.5f);
    // the device decides with the switch: without the extension the switch gives nothing
    CHECK(!active("1", false).on && of(active("1", false), Kind::Texture) == 0.5f && of(active("0.9,0.1", false), Kind::Target) == 0.5f);
    CHECK(active("1", true).on && of(active("1", true), Kind::Texture) == 0.25f && !active(nullptr, true).on && !active("0", true).on);
    return fails ? 1 : 0;
}
'''


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


def check_create_infos(vma):
    """Every create info of the allocator's names a priority before its address or a copy of it is taken"""
    made = list(re.finditer(r"\b(VmaPoolCreateInfo|VmaAllocationCreateInfo) (\w+)(\{\};| = (\w+);)", vma))
    check(len(made) >= 16, "vk_vma.cpp: the create infos are no longer found (%d)" % len(made))
    for m in made:
        kind, name, source = m.group(1), m.group(2), m.group(4)
        where = "vk_vma.cpp line %d: %s %s" % (vma.count("\n", 0, m.start()) + 1, kind, name)
        if source:   # (a copy of one that has its priority)
            before = vma[:m.start()]
            check(before.rfind(source + ".priority = ") > max(before.rfind("VmaAllocationCreateInfo " + source + "{};"),
                                                              before.rfind("VmaAllocationCreateInfo " + source + " = ")) or
                  re.search(r"VmaAllocationCreateInfo %s = \w+;" % source, before) is not None,
                  where + " is a copy of an info that names no priority")
            continue
        rest = vma[m.end():]
        used = re.search(r"&%s\b|= %s;" % (name, name), rest)
        check(used is not None, where + " is never used")
        check(("%s.priority = " % name) in rest[:used.start()], where + " names no priority before it is used: with the extension on it gets 0")
    return len(made)


def check_source():
    vma = (VK / "vk_vma.cpp").read_text(encoding="utf-8")
    n = check_create_infos(vma)
    for path in sorted(VK.glob("*.cpp")) + sorted(VK.glob("*.h")):
        if path.name != "vk_vma.cpp":
            text = path.read_text(encoding="utf-8", errors="replace")
            check("VmaPoolCreateInfo" not in text and "VmaAllocationCreateInfo" not in text,
                  path.name + " makes an allocator create info of its own: this check reads vk_vma.cpp alone")
    for head, tier, what in (("VmaPool small_targets_pool() {", "pi.priority = prio(PrioKind::Target);", "the small render targets' pool"),
                             ("VmaPool target_images_pool() {", "pi.priority = prio(PrioKind::Target);", "the render targets' pool"),
                             ("VmaPool images_pool() {", "pi.priority = prio(PrioKind::Other);", "the other images' pool"),
                             ("VmaPool textures_pool() {", "pi.priority = prio(PrioKind::Texture);", "the textures' pool"),
                             ("bool vma_piece_alloc(", "pi.priority = prio(PrioKind::Other);", "the mirrors' pieces' pool"),
                             ("bool vma_init(PFN_vkGetInstanceProcAddr gipa) {", "ai.priority = prio(PrioKind::Held);", "the lab's ballast"),
                             ("bool create_image_inner_(const VkImageCreateInfo& ci, VkImage& image, VmaAllocation& allocation, bool dedicated, bool target, bool textures,\n"
                              "                         ImageNeed* need) {",
                              "ai.priority = prio(target ? PrioKind::Target : textures ? PrioKind::Texture : PrioKind::Other);", "an image")):
        check(tier in block(vma, head), "vk_vma.cpp: %s does not name its tier" % what)
    init = block(vma, "bool vma_init(PFN_vkGetInstanceProcAddr gipa) {")
    check("(dev.memory_priority ? VMA_ALLOCATOR_CREATE_EXT_MEMORY_PRIORITY_BIT : 0)" in init and
          vma.count("VMA_ALLOCATOR_CREATE_EXT_MEMORY_PRIORITY_BIT") == 2,   # (the comment's and the flag's)
          "vk_vma.cpp: the allocator's priority bit is not set with dev.memory_priority alone")
    check('static const memory_priority::Tiers t = memory_priority::active(getenv("RX_VK_MEMORY_PRIORITY"), dev.memory_priority);' in vma and
          "float prio(PrioKind k) { return memory_priority::of(memory_tiers(), k); }" in vma,
          "vk_vma.cpp: the tiers are not the switch's where the device has the extension")
    check("vk: memory priorities on" in init, "vk_vma.cpp: the tiers are not logged at the start")

    main = (VK / "vk_main.cpp").read_text(encoding="utf-8")
    at = [main.index(s) for s in (
        'const bool prio_asked = memory_priority::parse(getenv("RX_VK_MEMORY_PRIORITY")).on;',
        "if (prio_asked) optional(VK_EXT_MEMORY_PRIORITY_EXTENSION_NAME, dev.memory_priority);",
        "VkPhysicalDeviceMemoryPriorityFeaturesEXT mem_prio{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_PRIORITY_FEATURES_EXT};",
        "if (dev.memory_priority) *tail = &mem_prio, tail = &mem_prio.pNext;",
        "vkGetPhysicalDeviceFeatures2(dev.physical, &f);",
        "dev.memory_priority = dev.memory_priority && mem_prio.memoryPriority;",
        "VkDeviceCreateInfo ci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};")]
    check(at == sorted(at), "vk_main.cpp does not ask for the extension and its feature with the switch alone, before the device is made")
    check(main.count("VK_EXT_MEMORY_PRIORITY_EXTENSION_NAME") == 1 and main.count("&mem_prio") == 2,
          "vk_main.cpp names the extension or chains its feature somewhere else")
    internal = (VK / "vk_internal.h").read_text(encoding="utf-8")
    check("memory_priority = false," in internal and "const memory_priority::Tiers& memory_tiers();" in internal,
          "vk_internal.h: the device's flag starts on, or the tiers are not declared")
    every = "".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(VK.glob("*.cpp")))
    check(len(re.findall(r"dev\.memory_priority = ", every)) == 1, "dev.memory_priority is set somewhere but vk_main.cpp's feature check")

    tex = (VK / "vk_texture.cpp").read_text(encoding="utf-8")
    create = tex[tex.index("Texture* create(const Key& key"):]
    create = create[:create.index("\n}\n")]
    at = [create.index(s) for s in (
        "const bool in_textures = compact_on() && !x.sparse && !(as_target && !is_bc(x.format) && !is_astc(x.format));",
        "const bool ranked = !in_textures && dev.memory_priority && !x.sparse && !(as_target && !is_bc(x.format) && !is_astc(x.format));",
        "} else if (in_textures && create_image(ci, x.image, x.allocation, false, false, true)) {",
        "} else if (ranked && create_image(ci, x.image, x.allocation, false, false, true)) {",
        "pool_take(pool_key, x.image, x.allocation, x.views)")]
    check(at == sorted(at), "create() does not take the textures' pool for its rank only with dev.memory_priority, after the compaction's own line")
    check("if (!((compact_on() || dev.memory_priority) && create_image(ci, image, allocation, false, false, true)) &&" in tex,
          "a BC1 texture made BC3 again does not come from the textures' pool with the priorities on")
    take = block(tex, "bool sparse_take(Texture* tex, VkDeviceSize n, VkDeviceMemory& mem, VkDeviceSize& off) {")
    at = [take.index(s) for s in (
        "VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};",
        "VkMemoryPriorityAllocateInfoEXT chunk_prio{VK_STRUCTURE_TYPE_MEMORY_PRIORITY_ALLOCATE_INFO_EXT};",
        "if (dev.memory_priority) {\n            chunk_prio.priority = memory_priority::of(memory_tiers(), memory_priority::Kind::Texture);\n"
        "            ai.pNext = &chunk_prio;\n        }",
        "if (vkAllocateMemory(dev.device, &ai, nullptr, &m) != VK_SUCCESS) {")]
    check(at == sorted(at) and take.count("ai.pNext") == 1, "a sparse texture's chunks chain a priority without dev.memory_priority, or not the textures'")
    check(len(re.findall(r"getenv\(\"RX_VK_MEMORY_PRIORITY\"\)", every)) == 2,
          "RX_VK_MEMORY_PRIORITY is read somewhere but vk_main.cpp's ask and vk_vma.cpp's tiers")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    check("| `RX_VK_MEMORY_PRIORITY=1` or `<targets>,<textures>` |" in docs and "`gpu/vk/memory_priority.h`" in docs,
          "docs/development.md: RX_VK_MEMORY_PRIORITY is not in the switches table")
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check((VK / "memory_priority.h").is_file(), "gpu/vk/memory_priority.h is not there")
    n = check_source()
    with tempfile.TemporaryDirectory(prefix="memory-priority-") as tmp:
        c, exe = Path(tmp) / "prio.cpp", Path(tmp) / "prio.exe"
        c.write_text(PROGRAM, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I" + str(VK), str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0, "the switch's reading or the tiers:\n" + r.stdout)
    print("PASS: memory priorities are off without the switch and the extension; %d create infos in vk_vma.cpp name their tier" % n)


if __name__ == "__main__":
    main()
