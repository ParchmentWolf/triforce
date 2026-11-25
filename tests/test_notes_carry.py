"""The pipeline notes are kept across a translator change (gpu/vk/vk_draw.cpp notes_stamp; no game, no GPU: source checks).

A note holds what the game asked for (PipeNote, NvnState), which no translator makes; the notes were stamped with the
program cache's stamp and started again at every update that changed the translator. Now they have a stamp of their own,
made of kNotesFormat and the places and sizes of PipeNote's and NvnState's members. What must hold:
- every member of NvnState (gpu/vk/vk_state.h) and of PipeNote (gpu/vk/vk_draw.h) is in notes_stamp, so that a change of
  their layout starts the notes again by itself (a new member must be added there: this check names it);
- every reader of the notes file takes the notes' own stamp (or this translator's program cache stamp, a file of before,
  stamped anew where the notes are read whole or walked), and the writer stamps a new file with the notes' own;
- a key noted again is the later note's in both readers, and play can note a key only a passed-over note holds;
- where a pipeline is kept under a note's key (the precompile that keeps its pipelines, the load at a create call), a note
  whose key this build makes otherwise is passed over (note_key_holds); the precompile that keeps none builds it all the same.

python -I -B tests/test_notes_carry.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"


def fail(msg):
    raise SystemExit("FAIL: " + msg)


def body(text, head):
    start = text.index(head)
    return text[start:text.index("\n}\n", start)]


def struct_members(text, name):
    """The member names of a plain struct's body: each declaration's names (no functions, no nested types in these)"""
    block = text[text.index("struct %s {" % name):]
    block = block[block.index("{") + 1:block.index("\n};")]
    block = re.sub(r"//[^\n]*", "", block)
    names = []
    for decl in block.split(";"):
        decl = re.sub(r"\{[^{}]*\}", "", decl)           # (default values in braces)
        decl = re.sub(r"=[^,]*", "", decl).strip()       # (default values after =)
        if not decl:
            continue
        parts = [p.strip() for p in decl.split(",")]
        first = re.sub(r"\[[^\]]*\]", "", parts[0]).split()
        names.append(first[-1])
        names += [re.sub(r"\[[^\]]*\]", "", p).split()[-1] for p in parts[1:]]
    return names


def main():
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    state = (VK / "vk_state.h").read_text(encoding="utf-8")
    draw_h = (VK / "vk_draw.h").read_text(encoding="utf-8")
    programs = (VK / "vk_programs.cpp").read_text(encoding="utf-8")

    stamp = body(draw, "uint64_t notes_stamp() {")
    listed = set(re.findall(r"(?<!define )NOTE_MEMBER\((\w+)\)", stamp))
    nvn = struct_members(state, "NvnState")
    if len(nvn) < 40:
        fail("NvnState read as %d members: the reader of vk_state.h is wrong" % len(nvn))
    missing = [m for m in nvn if m not in listed]
    if missing:
        fail("notes_stamp lacks NvnState's %s: add each as NOTE_MEMBER(...) (a new member changes what a note holds)" % missing)
    gone = sorted(listed - set(nvn))
    if gone:
        fail("notes_stamp names %s, which NvnState no longer has" % gone)
    for m in struct_members(draw_h, "PipeNote"):
        if "offsetof(PipeNote, %s)" % m not in stamp:
            fail("notes_stamp lacks offsetof(PipeNote, %s)" % m)
    for needle in ("add(kNotesFormat);", "add(sizeof(NvnState));", "sizeof(PipeNote)"):
        if needle not in stamp:
            fail("notes_stamp lacks " + needle)
    if "bool notes_stamp_ok(uint64_t stamp) { return stamp == notes_stamp() || stamp == program_cache_stamp(); }" not in draw:
        fail("notes_stamp_ok is not the notes' own stamp or this translator's program cache stamp")

    # (the readers and the writer)
    read = body(draw, "std::vector<std::unique_ptr<PipeNote>> pipe_notes_read(")
    refs = body(draw, "std::vector<NoteRef> pipe_notes_refs() {")
    opened = body(draw, "void notes_open_locked(const std::vector<std::unique_ptr<PipeNote>>* known) {")
    for name, text in (("pipe_notes_read", read), ("pipe_notes_refs", refs)):
        for needle in ("notes_stamp_ok(head[0])", "notes_restamp(pipe_notes_path(), ", "seen.try_emplace(",
                       "head[1] == sizeof(PipeNote)"):
            if needle not in text:
                fail("%s lacks %s" % (name, needle))
        if "program_cache_stamp()" in text:
            fail("%s still reads the notes by the program cache's stamp alone" % name)
    if "notes[slot->second] = std::move(rec);" not in read or "refs[slot->second] = r;" not in refs:
        fail("a reader keeps a key's first note, not its last")
    for needle in ("static const uint64_t stamp = notes_stamp();", "notes_stamp_ok(head[0]) && head[1] == sizeof(PipeNote)",
                   "notes_restamp(path, head[0])"):
        if needle not in opened:
            fail("notes_open_locked lacks " + needle)
    if "predict_check::find(f, notes_stamp(), sizeof(PipeNote), want)" not in draw or \
            "predict_stream::index(f, notes_stamp(), sizeof(PipeNote)" not in draw:
        fail("the prediction's readers of the notes file do not take the notes' own stamp")
    if re.search(r"head\[0\] == program_cache_stamp\(\) && head\[1\] == sizeof\(PipeNote\)", draw):
        fail("a reader of the notes file by the program cache's stamp is left")

    # (play notes a freed key again; the places that keep a pipeline under a note's key ask first)
    note = body(draw, "void pipeline_note(uint64_t key, const Program& p, const NvnState& s, const Targets& at,")
    if "notes_key_left.erase(key)" not in note:
        fail("pipeline_note does not note a key only a passed-over note holds")
    holds = body(draw, "bool note_key_holds(const Program& p, const PipeNote& n) {")
    for needle in ("pipeline_key(p, n.s, note_targets(n), (VkPrimitiveTopology)n.topo) == n.key", "notes_key_left.insert(n.key);",
                   "notes_key_moved.fetch_add("):
        if needle not in holds:
            fail("note_key_holds lacks " + needle)
    pre = body(draw, "void precompile_run(void (*progress)(size_t done, size_t total)) {")
    if "if (p && !note_key_holds(*p, n) && !pre->light) p = nullptr;" not in pre:
        fail("the precompile keeps a pipeline under a note's key without asking note_key_holds")
    at = pre.index("if (p && !note_key_holds(*p, n) && !pre->light) p = nullptr;")
    if pre.index("pipelines.emplace(n.key, std::move(e));") < at:
        fail("the precompile asks note_key_holds after it keeps the pipeline")
    if "if (!note_key_ok(*p, *note)) continue;" not in programs or \
            programs.index("if (!note_key_ok(*p, *note)) continue;") > programs.index("pipeline_keep_ready(n.key, pl)"):
        fail("vk_programs.cpp keeps a pipeline ready under a note's key without asking note_key_ok first")
    print("PASS: the pipeline notes carry their own stamp (every member of NvnState and PipeNote in it), are read by it or by "
          "this translator's program cache stamp and stamped anew, take a key's last note, and a note whose key moved is "
          "passed over where a pipeline is kept under it")


if __name__ == "__main__":
    main()
