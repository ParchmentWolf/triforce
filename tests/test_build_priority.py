"""The builders start the build tools at normal priority, and below normal only on request (no game, no build).

(Triforce, 11-22, the performance audit's OS-57, after Source A's.) Every Windows build started nx2/make_game.py below
normal priority, from four places, with no switch. Source A starts its tools at normal priority and reports, without a
measurement, that below normal Windows kept the one-process steps of a build on a hybrid Intel CPU's efficiency cores.
HOOKSHOT_LOW_PRIORITY=1 brings the below-normal start back.

Reads the source: in each of the four files the below-normal set is there once and sits directly under a check of
HOOKSHOT_LOW_PRIORITY == "1"; the switches table lists the switch; prepare_priority's comment and the design notes
say what the default is now.

And runs the Python builder's own start (builder/py/hookshot_builder/core.py Runner._run) with a stand-in for the tools:
a child that prints its own priority class. By default the child has the class a plain start gives it; with
HOOKSHOT_LOW_PRIORITY=1 it is below normal; =0 and an empty value are the default. The rule build_priority is asked the
same on every OS; the start itself only on Windows.

    python -I -B tests/test_build_priority.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SWITCH = "HOOKSHOT_LOW_PRIORITY"
BELOW_NORMAL, IDLE, NORMAL = 0x4000, 0x40, 0x20
# (a child that says the priority class Windows gave it)
CHILD = "import ctypes; k = ctypes.WinDLL('kernel32'); k.GetCurrentProcess.restype = ctypes.c_void_p; " \
        "k.GetPriorityClass.argtypes = [ctypes.c_void_p]; print('class', k.GetPriorityClass(k.GetCurrentProcess()))"


def fail(text):
    raise SystemExit("FAIL: " + text)


def check_csharp(rel, set_line):
    text = (ROOT / rel).read_text(encoding="utf-8")
    code = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("//")]
    sets = [i for i, line in enumerate(code) if "ProcessPriorityClass.BelowNormal" in line]
    if len(sets) != 1:
        fail("%s sets the below normal class %d times, not once" % (rel, len(sets)))
    i = sets[0]
    if code[i] != set_line:
        fail("%s: the below normal set is no longer the line the check knows: %s" % (rel, code[i]))
    if code[i - 1] != 'if (Environment.GetEnvironmentVariable("%s") == "1")' % SWITCH:
        fail("%s starts the build tools below normal without asking %s: the line above the set is: %s" % (rel, SWITCH, code[i - 1]))
    if "the performance audit's OS-57" not in text:
        fail("%s no longer says where the switch comes from" % rel)


def own_class():
    import ctypes
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    return k.GetPriorityClass(k.GetCurrentProcess())


def main():
    # ---- the three C# starts
    check_csharp("builder/HookshotBuilder/Runner.cs", "try { p.PriorityClass = ProcessPriorityClass.BelowNormal; } catch (Exception) { }")
    check_csharp("setup/Setup.cs", "try { p.PriorityClass = ProcessPriorityClass.BelowNormal; } catch (Exception) { }")
    check_csharp("launcher/Logic/Build/BuildRunner.cs",
                 "try { if (ctx.IsWindows) p.PriorityClass = ProcessPriorityClass.BelowNormal; } catch (Exception) { }")
    head = (ROOT / "launcher/Logic/Build/BuildRunner.cs").read_text(encoding="utf-8").split("using System", 1)[0]
    if "below-normal priority (Windows)" in head or SWITCH not in head:
        fail("BuildRunner.cs's header still says the tools always run below normal")

    # ---- the Python builder: the source, the rule, then its own start
    core_text = (ROOT / "builder/py/hookshot_builder/core.py").read_text(encoding="utf-8")
    uses = re.findall(r"\bBELOW_NORMAL_PRIORITY_CLASS\b", core_text)
    if len(uses) != 2 or 'return BELOW_NORMAL_PRIORITY_CLASS if env.get("%s") == "1" else 0' % SWITCH not in core_text:
        fail("core.py uses BELOW_NORMAL_PRIORITY_CLASS outside build_priority's %s check" % SWITCH)
    if "creationflags=CREATE_NO_WINDOW | build_priority())" not in core_text:
        fail("core.py's Runner no longer starts the tools with build_priority()")
    sys.path.insert(0, str(ROOT / "builder" / "py"))
    from hookshot_builder import core
    for env, want in (({}, 0), ({SWITCH: "1"}, BELOW_NORMAL), ({SWITCH: "0"}, 0), ({SWITCH: ""}, 0), ({SWITCH: "yes"}, 0)):
        if core.build_priority(env) != want:
            fail("build_priority(%r) is 0x%x, want 0x%x" % (env, core.build_priority(env), want))
    started = "the rule only (the start is Windows')"
    if os.name == "nt":
        mine = own_class()
        plain = mine if mine in (BELOW_NORMAL, IDLE) else NORMAL   # (what a child gets with no priority flag)
        with tempfile.TemporaryDirectory() as folder:
            tools = SimpleNamespace(python=sys.executable, python_args=[], root=folder)
            for value, want in ((None, plain), ("0", plain), ("1", BELOW_NORMAL if mine != IDLE else None)):
                if want is None:   # (an idle-class parent: Windows does not raise the child; nothing to tell apart)
                    continue
                env = {k: v for k, v in os.environ.items() if k != SWITCH}
                if value is not None:
                    env[SWITCH] = value
                lines, ended = [], []
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(core, "build_command", return_value=[sys.executable, "-I", "-c", CHILD]), \
                        patch.object(core, "build_env", return_value=dict(env)):
                    core.Runner(tools, [], on_line=lines.append, on_finished=ended.append)._run()
                if ended != [None] or ["class %d" % want] != [l for l in lines if l.startswith("class ")]:
                    fail("the tools started with %s=%s have %s (ended %s), want class %d" % (SWITCH, value, lines, ended, want))
        started = "the Python builder's start gives its child class 0x%x by default and 0x%x with the switch" % (plain, BELOW_NORMAL)

    # ---- the docs and the comments that described the old start
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    rows = [line for line in docs.splitlines() if line.startswith("| `%s=1` |" % SWITCH)]
    if len(rows) != 1 or "OS-57" not in rows[0] or "normal priority" not in rows[0]:
        fail("docs/development.md's switches table has no %s=1 row" % SWITCH)
    building = docs[docs.index("### Building"):docs.index("## Mods: code patches and cheats")]
    if rows[0] not in building:
        fail("the %s row is not in the Building table" % SWITCH)
    design = (ROOT / "docs/design.md").read_text(encoding="utf-8")
    if SWITCH not in design:
        fail("docs/design.md's first-build line does not say the builders' start changed")
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    comment = draw[draw.index("/// (Triforce) The priority of the workers of the shader preparation"):draw.index("int prepare_priority() {")]
    if SWITCH not in comment or "builders start their build tools so: Runner.cs" in comment:
        fail("prepare_priority's comment still says the builders always start their tools below normal")
    print("ok: the four builders ask %s before a below-normal start; %s" % (SWITCH, started))


if __name__ == "__main__":
    main()
