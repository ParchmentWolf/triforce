"""pass() and dw() are taken once in each of the draw's hot functions (gpu/vk/vk_draw.cpp; no game, no GPU).

(Triforce, 11-22, the performance audit's DESC-20, after Source A's.) The thread's Pass and DescWriter are reached through
plain thread-local pointers (TLS_OBJECT, tests/test_tls_objects.py): each pass() or dw() is a thread-local read and a
null test, and in a Linux library built with -fPIC a call for the address. The hot functions asked at every use: end_pass
57 times, build_descriptors 31. They now take the object once at their top and use the reference.

Reads the source:
  - build_descriptors and bind_descriptors: their first statement is `auto& dwr = dw();` and there is no other dw() in them;
  - begin_pass, dynamic_state, draw_hazards, end_pass and draw: their first statement is `Pass& ps = pass();` and there is
    no other pass() in them; draw keeps its four dw() (tests/test_mesh_fallback.py reads them);
  - the bound names are not declared a second time in those functions (bind_descriptors' own `ps`, the pushed state, is
    not a Pass and stays);
  - what makes the reference sound: a recording's start assigns into the thread's Pass (pass() = Pass{}), TLS_OBJECT is
    the only place a per-thread pointer is set, and nothing names pass_tls or dw_tls outside it.

    python -I -B tests/test_tls_once.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DESCRIPTORS = ["void build_descriptors(const NvnState& s, const Program& p, bool keep = false, bool scene = false) {",
               "bool bind_descriptors(VkCommandBuffer cmd, VkPipelineBindPoint bp, const Program& p) {"]
PASSES = ["void begin_pass(VkCommandBuffer cmd, const Targets& at) {",
          "void dynamic_state(VkCommandBuffer cmd, const NvnState& s, const Targets& at, VkPrimitiveTopology topo, bool mesh) {",
          "uint16_t draw_hazards(VkCommandBuffer cmd, const Program& p, const NvnState& s, const Targets& at, uint16_t& samples) {",
          "void end_pass(VkCommandBuffer cmd) {", "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d) {"]


def block(text, marker):
    if text.count(marker) != 1:
        raise SystemExit("FAIL: vk_draw.cpp does not have exactly one: " + marker)
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def code(text):
    """Without its line comments (a comment may name the accessor)"""
    return "\n".join(line.split("//")[0] for line in text.split("\n"))


def calls(text, name):
    return len(re.findall(r"(?<![A-Za-z0-9_])%s\(\)" % name, code(text)))


def need(ok, why):
    if not ok:
        raise SystemExit("FAIL: " + why)


def main():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    for marker, first, name, accessor in [(m, "auto& dwr = dw();", "dwr", "dw") for m in DESCRIPTORS] + \
                                         [(m, "Pass& ps = pass();", "ps", "pass") for m in PASSES]:
        body = block(draw, marker)
        what = marker.split("(")[0].split()[-1]
        lines = [line for line in body.split("\n")[1:] if line.strip()]
        need(lines[0].strip().startswith(first), "%s does not begin by taking %s() once (%s)" % (what, accessor, first))
        need(calls(body, accessor) == 1, "%s asks %s() %d times: once, at its top" % (what, accessor, calls(body, accessor)))
        uses = len(re.findall(r"(?<![A-Za-z0-9_.>])%s\." % name, code(body)))
        need(uses >= 4, "%s takes %s() and uses it %d times" % (what, accessor, uses))
        # (the name on the left of an = once: its binding; a second would be another variable of that name, or the object copied over)
        declared = len(re.findall(r"(?<![A-Za-z0-9_.>])%s\s*=(?!=)" % name, code(body)))
        if what == "bind_descriptors":
            # (its own ps is the pushed state of the bind point, not a Pass)
            need("Pass& ps" not in body and re.search(r"Pushed& ps = pushed\(\)\[", body), "bind_descriptors' ps is no longer its pushed state")
        need(declared == 1, "%s sets %s %d times: once, where it is taken" % (what, name, declared))
    need(calls(block(draw, PASSES[-1]), "dw") == 4, "draw no longer has its four dw() (tests/test_mesh_fallback.py reads dw().prog there)")
    # what the references stand on
    need("TLS_OBJECT(pass, Pass)" in draw and "TLS_OBJECT(dw, DescWriter)" in draw, "pass and dw are no longer TLS_OBJECTs")
    at = draw.index("#define TLS_OBJECT(name, ...)")
    macro = draw[at:draw.index("\n\n", at)]   # (the macro: up to the first empty line after it)
    need("return p ? *p : tls_make(name##_tls);" in macro and "slot = new T();" in block(draw, "T& tls_make(T*& slot) {"),
         "TLS_OBJECT no longer makes a thread's object once and hands the same one back")
    need(not re.search(r"(?<![A-Za-z0-9_#])(pass|dw)_tls(?![A-Za-z0-9_])", draw), "something names pass_tls or dw_tls: the pointer may be swapped")
    need("pass() = Pass{};" in block(draw, "void draw_begin_recording(int slot, VkCommandBuffer cmd, uint64_t value) {"),
         "a recording's start no longer assigns into the thread's Pass in place")
    need(len(re.findall(r"(?<![A-Za-z0-9_])slot = ", block(draw, "T& tls_make(T*& slot) {"))) == 1, "tls_make sets its slot more than once")
    print("PASS: pass() and dw() are taken once in each of the draw's hot functions")


if __name__ == "__main__":
    main()
