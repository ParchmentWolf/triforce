"""Game-free checks of recomplauncher.json: it parses, every settings key is a row of the in-game menu, and no value it
writes means something else under another options_version.

Run with: python -I tests/test_recomplauncher_json.py
"""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecompLauncherJsonTests(unittest.TestCase):
    def test_settings_are_menu_rows(self):
        manifest = json.loads((ROOT / "recomplauncher.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], 1)
        menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
        rows = {re.sub(" ", "_", name.lower()) for name in re.findall(r'\{TAB_[A-Z]+, "([^"]+)"', menu)}
        # (vk_menu.cpp ini_key: the rows whose key is not their name, renamed rows keeping the key an options file has:
        # output_res, resolution, frame_rate_cap, dlss, and (Triforce, options_version 7) its table of the rows renamed as
        # their groups came, {"<name>", "<key>"})
        ini_key = menu.split("const char* ini_key(const Row& r) {", 1)[1].split("\n}", 1)[0]
        rows |= set(re.findall(r'return "([a-z_0-9]+)";', ini_key))
        rows |= set(re.findall(r'\{"[^"]+", "([a-z_0-9-]+)"\}', ini_key))
        keys = {key for setting in manifest["settings"] for choice in setting["choices"] for key in choice["set"]}
        self.assertTrue(keys)
        self.assertEqual(keys - rows, set())

    def test_values_mean_the_same_in_every_options_version(self):
        """The manifest writes key=value lines and never options_version (it has no way to: a line it wrote into an older
        file would also switch off that file's other rules). So a value it writes is read by the rules of whatever
        version the file has, or of none in a file it makes. It may only offer values no rule changes:
        - ultrawide=1 was "Monitor's shape" before options_version 6 and is 16:10 from 6 on (gpu/vk/ultrawide_rows.h);
        - output_res=4 and 6 (5120x1440, 5120x2160) are read as 2560x1440 and 3840x2160 before 8 when ultrawide is on
          another shape than theirs (gpu/vk/output_sizes.h output_res_read)."""
        manifest = json.loads((ROOT / "recomplauncher.json").read_text(encoding="utf-8"))
        written = {(key, value) for setting in manifest["settings"] for choice in setting["choices"]
                   for key, value in choice["set"].items()}
        self.assertNotIn("options_version", {key for key, _ in written})
        moved = {("ultrawide", "1"), ("output_res", "4"), ("output_res", "6"), ("output_res", "7"), ("output_res", "8")}
        self.assertEqual(written & moved, set())
        rows_h = (ROOT / "gpu" / "vk" / "ultrawide_rows.h").read_text(encoding="utf-8")
        sizes_h = (ROOT / "gpu" / "vk" / "output_sizes.h").read_text(encoding="utf-8")
        # (the rules those three come from, as the headers have them: a new rule there is a new value to leave out here)
        self.assertIn("return version < 6 && row == 1 ? ultrawide_row_nearest(screen_w, screen_h) : row;", rows_h)
        self.assertIn("    if (v == 4 && ultrawide_row != 0 && ultrawide_row != 3) return 1;\n"
                      "    if (v == 6 && ultrawide_row != 0 && ultrawide_row != 2) return 2;\n    return v;", sizes_h)
        # (what it still offers of the two rows: the 16:9 sizes and Screen, and the shapes 16:9, 21:9 and 32:9)
        self.assertEqual({value for key, value in written if key == "output_res"}, {"0", "1", "2", "3", "5"})
        self.assertEqual({value for key, value in written if key == "ultrawide"}, {"0", "2", "3"})

    def test_appimage_carries_it(self):
        self.assertIn('cp recomplauncher.json "$APPDIR/recomplauncher.json"',
                      (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8"))

    def test_windows_zip_carries_it(self):
        workflow = (ROOT / ".github" / "workflows" / "windows-builder.yml").read_text(encoding="utf-8")
        self.assertIn('z.write("recomplauncher.json", "recomplauncher.json")', workflow)
        self.assertIn("dist/Hookshot-*-Windows-x64.zip", workflow)


if __name__ == "__main__":
    unittest.main()
