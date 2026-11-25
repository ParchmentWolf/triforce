// Game-free regression for the Ampere -> Maxwell lowerings' size limits (lower_to_maxwell.h and lower_to_maxwell_regmap.h)
// and the capture's (program_capture.h): a program over 1 MiB (65,536 native instructions) lowers, a branch or a call
// whose target is more than 8 MiB of lowered code away takes its absolute form (JMP, JCAL), and the capture reads a branch
// to past 1 MiB as one inside the program. OoT's compute program 79116b290d46542f has 0x104680 bytes of code and was
// refused whole. And where a program ends: a loop that leaves only by predicated EXITs ends at the closing self-branch after
// its jump back (one of OoT's compute programs did not lower), unless a branch before it goes past it.
//   clang++ -std=c++20 -I gpu/vk/eden -I gpu/vk/compat gpu/vk/tests/far_branch_test.cpp -o far_branch_test
#include <cstdio>
#include <vector>

#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include "shader_recompiler/frontend/ampere/lower_to_maxwell_regmap.h"
#include "shader_recompiler/frontend/ampere/program_address_map.h"
#include "shader_recompiler/frontend/ampere/program_capture.h"

namespace {
using Shader::Ampere::Instruction;

int failures = 0;
void check(bool ok, const char* lowering, const char* what) {
    if (!ok) std::printf("FAIL: %s: %s\n", lowering, what), failures++;
}

Instruction insn(u32 a, u32 b, u32 c, u32 d) { return {{{a, b, c, d}}}; }
const Instruction exit_pt = insn(0x0000794d, 0, 0x03800000, 0x000fea00);   // EXIT
const Instruction nop = insn(0x00007918, 0, 0, 0x000fc000);
// BRA at native instruction `at` to native instruction `to` (a 50-bit offset from the next instruction, at bit 32)
Instruction bra(s64 at, s64 to, u32 predicate) {
    const u64 r = static_cast<u64>(to * 16 - (at * 16 + 16));
    return insn(0x947 | (predicate << 12), static_cast<u32>(r), 0x03800000 | static_cast<u32>((r >> 32) & 0x3ffff), 0x000fea00);
}
u32 address_of(u32 index) { return 0x50U + index * 8 + ((index + 1) / 3) * 8; }   // (a lowered word's address, as the lowerings count it)

// What native instruction `at` lowered to: opcode `op` with predicate `pred`, landing on what native `to` lowered to; near
// by a 24-bit offset (BRA 0xe24), far by the target's address in bits 20-51 (JMP 0xe21, JCAL 0xe22)
template <class Lowered> bool lands(const Lowered& l, u32 at, u32 to, u64 op, u32 pred, bool far) {
    if (at >= l.source_instruction_offsets.size() || to >= l.source_instruction_offsets.size()) return false;
    const u32 from = l.source_instruction_offsets[at], target = l.source_instruction_offsets[to];
    if (from >= l.instructions.size()) return false;
    const u64 word = l.instructions[from];
    const s64 distance = s64{address_of(target)} - address_of(from) - 8;
    if ((word >> 52) != op || ((word >> 16) & 15) != pred) return false;
    if (far) return ((word >> 20) & 0xffffffffu) == address_of(target) && (distance > 0x7fffff || distance < -0x800000);
    return (static_cast<s64>(word << 20) >> 40) == distance;
}

template <class Ins, class Lower> void run(const char* name, Lower lower) {
    {   // 79116b29's size: a @P0 BRA at instruction 16404 to the EXIT at its end, a @P1 BRA back
        const u32 n = 0x104680 / 16;
        std::vector<Instruction> code(n, nop);
        code[16404] = bra(16404, n - 2, 0);
        code[n - 3] = bra(n - 3, 1, 1);
        code[n - 2] = exit_pt;
        const auto l = lower(std::span{reinterpret_cast<const Ins*>(code.data()), code.size()});
        check(static_cast<bool>(l), name, "0x104680 bytes of code do not lower");
        if (l) check(lands(l, 16404, n - 2, 0xe24, 0, false) && lands(l, n - 3, 1, 0xe24, 1, false), name,
                     "0x104680 bytes: a BRA does not land on its target");
    }
    {   // more than 8 MiB of lowered code between a branch and its target: JMP, there and back
        const u32 n = 800000;
        std::vector<Instruction> code(n, nop);
        code[0] = bra(0, n - 2, 0);
        code[n - 3] = bra(n - 3, 1, 1);
        code[n - 2] = exit_pt;
        const auto l = lower(std::span{reinterpret_cast<const Ins*>(code.data()), code.size()});
        check(static_cast<bool>(l), name, "12.8 MB with branches more than 8 MiB of lowered code apart do not lower");
        if (l) check(lands(l, 0, n - 2, 0xe21, 0, true) && lands(l, n - 3, 1, 0xe21, 1, true), name,
                     "12.8 MB: a branch is not a JMP to its target");
    }
    {   // a loop left only by @P0 EXIT, its jump back, and the closing branch to itself: the program ends there
        const Instruction exit_p0 = insn(0x0000094d, 0, 0x03800000, 0x000fea00);
        const std::vector<Instruction> loop{exit_p0, bra(1, 0, 7), bra(2, 2, 7)};
        const auto l = lower(std::span{reinterpret_cast<const Ins*>(loop.data()), loop.size()});
        check(static_cast<bool>(l) && l.source_size == 3 * sizeof(Instruction), name,
              "a loop that leaves by predicated EXITs does not end at its closing self-branch");
        // (but a branch that goes past such a self-branch says the program goes on behind it)
        const std::vector<Instruction> on{bra(0, 3, 0), bra(1, 0, 7), bra(2, 2, 7), exit_pt};
        const auto m = lower(std::span{reinterpret_cast<const Ins*>(on.data()), on.size()});
        check(static_cast<bool>(m) && m.source_size == 4 * sizeof(Instruction), name,
              "a program a branch reaches behind a self-branch was ended at the self-branch");
    }
    {   // past the largest program: refused, as before
        std::vector<Instruction> code(Shader::Ampere::MaximumNativeInstructions + 1, nop);
        code.back() = exit_pt;
        const auto l = lower(std::span{reinterpret_cast<const Ins*>(code.data()), code.size()});
        check(!l, name, "a program past 16 MiB lowered");
    }
}
}  // namespace

int main() {
    static_assert(sizeof(Shader::AmpereRegmap::Instruction) == sizeof(Instruction));
    run<Instruction>(
        "lower_to_maxwell.h", [](std::span<const Instruction> c) { return Shader::Ampere::LowerToMaxwell(c); });
    run<Shader::AmpereRegmap::Instruction>("lower_to_maxwell_regmap.h", [](std::span<const Shader::AmpereRegmap::Instruction> c) {
        return Shader::AmpereRegmap::LowerToMaxwell(c);
    });
    {   // the capture: a branch to past 1 MiB is inside the program; one to past 16 MiB, or between two instructions, is not
        using Capture = Shader::Ampere::ProgramCaptureState;
        Capture inside, past, between;
        check(inside.Observe(bra(0, 70000, 0), 0) == Capture::Result::Continue, "program_capture.h",
              "a branch to instruction 70,000 is not inside the program");
        check(past.Observe(bra(0, s64{Shader::Ampere::MaximumNativeInstructions} + 4, 0), 0) == Capture::Result::InvalidTarget,
              "program_capture.h", "a branch to past 16 MiB is inside the program");
        Instruction odd = bra(0, 4, 0);
        odd.words[1] += 8;
        check(between.Observe(odd, 0) == Capture::Result::InvalidTarget, "program_capture.h",
              "a branch to between two instructions is inside the program");
    }
    std::printf("%s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
