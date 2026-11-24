"""Keep stock 0.6 and native 0.5.2 options distinct despite their shared version 8."""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    source = r'''
#include "gpu/vk/output_sizes.h"
#include "gpu/vk/merged_rows.h"
#include <cassert>
int main() {
    static_assert(OUTPUT_SCREEN == 8 && OUTPUT_CUSTOM == 9);
    static_assert(OUTPUT_OPTIONS_VERSION == 9);
    // Stock 0.6's handheld, and fixed sizes with a different aspect row.
    assert(output_file_read(7, 8, 2, 0) == 7);
    assert(output_file_read(4, 8, 2, 0) == 1);
    assert(output_file_read(6, 8, 3, 0) == 2);
    // Native files always wrote size fields, including under fixed choices.
    assert(output_file_read(7, 8, 2, 1) == OUTPUT_SCREEN);
    assert(output_file_read(8, 8, 2, 1) == OUTPUT_CUSTOM);
    assert(output_file_read(4, 8, 2, 1) == 4);
    assert(output_file_read(6, 8, 3, 1) == 6);
    assert(output_file_read(7, 7, 2, 0) == OUTPUT_SCREEN);
    assert(output_file_read(8, 7, 2, 0) == OUTPUT_CUSTOM);
    for (int v = 0; v <= OUTPUT_LAST; ++v)
        for (int row = 0; row != 4; ++row)
            assert(output_file_read(v, 9, row, 1) == v);
    // The player's active pair remains the native 12:5 picture.
    unsigned w, h;
    assert(output_size_used(3840, 1600, &w, &h));
    assert(w == 3840 && h == 1600 && output_frame_width(h) == 2848);
    // Native v8 predates stock's merged rows: retain handheld and stick meaning.
    mkwvk::merged_rows::Before7 old;
    old.handheld = 1; old.stick_shared = 3;
    int out = OUTPUT_CUSTOM, left = -1, right = 30;
    mkwvk::merged_rows::migrate(7, old, out, left, right);
    assert(out == 7 && left == 15 && right == 30);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        cpp = Path(tmp) / "migration.cpp"
        exe = Path(tmp) / "migration.exe"
        cpp.write_text(source, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-I", str(ROOT), str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: stock/native migration and version-9 round trip")


if __name__ == "__main__":
    main()
