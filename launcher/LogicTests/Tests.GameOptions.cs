using System.Text;
using System.Text.RegularExpressions;
using Triforce.Logic;
using static Triforce.LogicTests.T;

namespace Triforce.LogicTests;

static partial class Tests
{
    // (READ ONLY: the owner's own game folder. Nothing here writes there; the tests that write work on a copy in a test root)
    const string RealGame = @"D:\src\triforce-game";

    public static IEnumerable<(string Name, Func<Task> Run)> GameOptionsTests()
    {
        (string, Func<Task>) Sync(string n, Action a) => (n, () => { a(); return Task.CompletedTask; });
        yield return Sync("game options: output migration", OutputMigration);
        yield return Sync("game options: schema matches vk_menu.cpp's table", GameOptionsMatchMenu);
        yield return Sync("game options: keys, labels, choices, no Hookshot", GameOptionsLabels);
        yield return Sync("game options: the real triforce_options.ini (read only)", GameOptionsRealFile);
        yield return Sync("game options: round trip, merge, atomic write (a copy)", GameOptionsWrite);
        yield return Sync("game options: Set's rules, merged rows, Upscaler, Apply", GameOptionsSetRules);
        yield return Sync("game options: an older options_version, a new file", GameOptionsOldVersion);
    }

    // ---- the schema against the game's source ----

    /// <summary>gpu/vk of this source tree (the launcher's own repository), found from this file's folder up, else from the test
    /// program's.</summary>
    static string? MenuSource([System.Runtime.CompilerServices.CallerFilePath] string here = "")
    {
        foreach (var start in new[] { Path.GetDirectoryName(here), AppContext.BaseDirectory })
            for (var d = start is { Length: > 0 } ? new DirectoryInfo(start) : null; d != null; d = d.Parent)
                if (File.Exists(Path.Combine(d.FullName, "gpu", "vk", "vk_menu.cpp"))) return Path.Combine(d.FullName, "gpu", "vk");
        return null;
    }

    sealed record MenuRow(string Tab, string Name, string Value, string Lo, string Hi, string Step, string Text, string? Help, bool Restart, bool Exempt, bool Heading);

    /// <summary>vk_menu.cpp's rows[] table, each entry's fields (comments out, adjacent string literals joined).</summary>
    static List<MenuRow> ReadMenuTable(string cpp)
    {
        var body = cpp[cpp.IndexOf("Row rows[] = {", StringComparison.Ordinal)..cpp.IndexOf("constexpr int kRowsEnd", StringComparison.Ordinal)];
        var sb = new StringBuilder();
        for (int i = 0, inStr = 0; i < body.Length; i++)
        {
            var c = body[i];
            if (inStr == 1)
            {
                sb.Append(c);
                if (c == '\\') { sb.Append(body[++i]); continue; }
                if (c == '"') inStr = 0;
                continue;
            }
            if (c == '"') { inStr = 1; sb.Append(c); continue; }
            if (c == '/' && i + 1 < body.Length && body[i + 1] == '/') { while (i < body.Length && body[i] != '\n') i++; sb.Append('\n'); continue; }
            sb.Append(c);
        }
        body = sb.ToString();
        // (the in-game UI merge, 11-20: section titles written as MENU_HEADING(tab, "title"), vk_menu.cpp's macro for a heading
        // row: expanded here as the compiler does, so the sections are read again)
        body = Regex.Replace(body, @"MENU_HEADING\((TAB_[A-Z]+),\s*(""(?:[^""\\]|\\.)*"")\)",
            "{$1, $2, nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true}");
        var rows = new List<MenuRow>();
        foreach (Match m in Regex.Matches(body, @"\{(TAB_[A-Z]+),"))
        {
            int k = m.Index + m.Length, depth = 1;
            var inS = false;
            var fields = new List<string>();
            var cur = new StringBuilder();
            for (; depth > 0; k++)
            {
                var c = body[k];
                if (inS)
                {
                    cur.Append(c);
                    if (c == '\\') { cur.Append(body[++k]); continue; }
                    if (c == '"') inS = false;
                    continue;
                }
                if (c == '"') { inS = true; cur.Append(c); }
                else if (c == '{') { depth++; cur.Append(c); }
                else if (c == '}') { if (--depth > 0) cur.Append(c); }
                else if (c == ',') { fields.Add(cur.ToString().Trim()); cur.Clear(); }
                else cur.Append(c);
            }
            if (cur.ToString().Trim().Length > 0) fields.Add(cur.ToString().Trim());
            string? Lit(int i) => i < fields.Count && fields[i].StartsWith('"')
                ? string.Concat(Regex.Matches(fields[i], "\"((?:[^\"\\\\]|\\\\.)*)\"").Select(x => x.Groups[1].Value)).Replace("\\\"", "\"").Replace("\\\\", "\\")
                : null;
            string F(int i, string dflt) => i < fields.Count ? fields[i] : dflt;
            rows.Add(new MenuRow(m.Groups[1].Value, Lit(0) ?? fields[0], fields[1], fields[2], fields[3], fields[4], fields[5], Lit(6),
                F(8, "false") == "true", F(9, "false") == "true", F(11, "false") == "true"));
        }
        return rows;
    }

    /// <summary>vk_menu.h's Options defaults, by field.</summary>
    static Dictionary<string, int> ReadOptionDefaults(string h)
    {
        var s = h[h.IndexOf("struct Options {", StringComparison.Ordinal)..h.IndexOf("extern Options opts;", StringComparison.Ordinal)];
        var d = new Dictionary<string, int>();
        foreach (var line in s.Split('\n'))
        {
            var code = line.Split("//")[0];
            // ((Triforce) 11-24) arrays, pad_speaker[12] = {0, ...}: each element by its index, and the name alone where every
            // element is the same (toggle[HOS_SW_ZL]: a symbol for an index)
            var arr = Regex.Match(code, @"^\s*int\s+(\w+)\[\d+\]\s*=\s*\{([^}]*)\}\s*;");
            if (arr.Success)
            {
                var vals = arr.Groups[2].Value.Split(',').Select(x => int.Parse(x.Trim())).ToList();
                for (var i = 0; i < vals.Count; i++) d[arr.Groups[1].Value + "[" + i + "]"] = vals[i];
                if (vals.Distinct().Count() == 1) d[arr.Groups[1].Value + "[]"] = vals[0];
                continue;
            }
            var m = Regex.Match(code, @"^\s*int\s+(.*);");
            if (!m.Success) continue;
            foreach (var part in m.Groups[1].Value.Split(','))
            {
                var kv = part.Split('=');
                d[kv[0].Trim()] = int.Parse(kv[1].Trim());
            }
        }
        return d;
    }

    static void GameOptionsMatchMenu()
    {
        var dir = MenuSource();
        Check(dir != null, "gpu/vk/vk_menu.cpp is found above the test program");
        var table = ReadMenuTable(File.ReadAllText(Path.Combine(dir!, "vk_menu.cpp")));
        var defaults = ReadOptionDefaults(File.ReadAllText(Path.Combine(dir!, "vk_menu.h")));
        Check(table.Count > 100, "the table read: " + table.Count + " entries");
        var symbols = new Dictionary<string, int>
        {
            ["kLastOutput"] = 9, ["OUTPUT_MIN_W"] = 640, ["OUTPUT_MAX_W"] = 7680, ["OUTPUT_MIN_H"] = 360, ["OUTPUT_MAX_H"] = 2880, ["ur::kValues - 1"] = 6, ["ur::kUpscalers - 1"] = 9, ["ur::kModels - 1"] = 3, ["aa_rows::kValues - 1"] = 3,
            ["2 + kMaxMics"] = 18, ["HOS_PROMPT_N"] = 6, ["mr7::FG_DLSS_LAST"] = 12, ["framegen_rows::kRowMax"] = 9,
            // ((Triforce) 11-22..25: N64 Classic, the FPS counter's levels, Frame generation by, FSR 4 model, ReShade, Menu language)
            ["n64_rules::FAITHFUL"] = 1, ["n64_rules::REMEMBERED"] = 2, ["n64_rules::kPresets - 1"] = 2, ["fps_levels::kMax"] = 6,
            ["framegen_rows::kByMax"] = 1, ["ur::kFsr4Models - 1"] = 1, ["reshade::last_builtin_preset"] = 26, ["i18n::lang_count()"] = 14,
        };
        // (an array element by a symbol's index, toggle[HOS_SW_ZL]: the array's one value)
        int Dflt(string field) => defaults.TryGetValue(field, out var v) ? v : defaults[Regex.Replace(field, @"\[.*\]$", "[]")];
        int Num(string s, string what) => int.TryParse(s, out var v) ? v : symbols.TryGetValue(s, out v) ? v : throw new TestFailed(what + ": a symbol the test does not know, " + s);
        var tabs = new Dictionary<string, GameOptionTab>
        {
            ["TAB_DISPLAY"] = GameOptionTab.Display, ["TAB_GRAPHICS"] = GameOptionTab.Graphics, ["TAB_AUDIO"] = GameOptionTab.Audio,
            ["TAB_CONTROLS"] = GameOptionTab.Controls, ["TAB_SYSTEM"] = GameOptionTab.System, ["TAB_MOTION"] = GameOptionTab.Controls,
            ["TAB_PAGE"] = GameOptionTab.Controls,
        };
        // ((Triforce, options_version 8) the saved values the merged rows stand for: the TAB_HIDDEN rows, each a part here, with
        // the hidden row's range and vk_menu.h's default; and the merged rows' own (&merged.*): their default the view of their
        // parts' defaults, by the schema's own rules)
        var hidden = table.Where(r => r.Tab == "TAB_HIDDEN" && r.Value != "nullptr").ToList();
        var partDefaults = new Dictionary<string, int>(StringComparer.Ordinal);
        // ((Triforce) 11-24/25) the game's own state among them (auto_tune, auto_for, n64_classic_last): kept keys, no part
        hidden = hidden.Where(r => !GameOptionsSchema.KeptKeys.ContainsKey(GameOptionsSchema.IniKey(r.Name))).ToList();
        foreach (var r in hidden)
        {
            var key = GameOptionsSchema.IniKey(r.Name);
            var part = GameOptionsSchema.Part(key);
            Check(part != null, "the hidden row \"" + r.Name + "\" is a merged row's part, key " + key);
            Equal(Num(r.Lo, r.Name), part!.Lo, r.Name + " (hidden): lo");
            Equal(Num(r.Hi, r.Name), part.Hi, r.Name + " (hidden): hi");
            Equal(defaults[r.Value["&opts.".Length..]], part.Default, r.Name + " (hidden): default");
            Equal(1, GameOptionsSchema.All.Count(m => m.Parts?.Any(p => p.Key == key) == true), r.Name + " (hidden): the part of one merged row");
            partDefaults[key] = part.Default;
        }
        Equal(string.Join(",", hidden.Select(r => GameOptionsSchema.IniKey(r.Name)).OrderBy(k => k, StringComparer.Ordinal)),
            string.Join(",", GameOptionsSchema.Parts.Keys.OrderBy(k => k, StringComparer.Ordinal)), "the parts are the hidden rows");
        var left = new[] { "&opts.language", "&opts.pad_layout", "&output_pick", "&reshade_menu::user_pick" };   // (+ 11-24: the Output device and the User preset file, the game's own lists of this PC's devices and files)   // (Game language: language.txt's; Layout preset: KeptKeys)
        var sections = new Dictionary<string, string>();
        var names = new List<string>();
        foreach (var r in table)
        {
            if (r.Heading) { sections[r.Tab] = r.Name; continue; }
            if (r.Value == "nullptr" || r.Tab == "TAB_DEBUG" || r.Tab == "TAB_HIDDEN" || left.Contains(r.Value)) continue;
            var row = GameOptionsSchema.ByName(r.Name);
            Check(row != null, "the menu's row \"" + r.Name + "\" is in the schema");
            names.Add(r.Name);
            Equal(tabs[r.Tab], row!.Tab, r.Name + ": tab");
            var section = r.Tab == "TAB_MOTION" ? "Motion" : r.Tab == "TAB_PAGE" ? "Controls" : sections.GetValueOrDefault(r.Tab);
            Equal(section, row.Section, r.Name + ": section");
            Equal(Num(r.Lo, r.Name), row.Lo, r.Name + ": lo");
            Equal(Num(r.Hi, r.Name), row.Hi, r.Name + ": hi");
            Equal(Num(r.Step, r.Name), row.Step, r.Name + ": step");
            Equal(r.Help, row.Help, r.Name + ": help");
            Equal(r.Restart, row.Restart, r.Name + ": restart");
            Equal(r.Exempt, row.PresetExempt, r.Name + ": preset exempt");
            if (r.Value.StartsWith("&merged.", StringComparison.Ordinal))
            {
                Check(row.IsMerged, r.Name + ": a merged row");
                Equal(row.Merge!.Of(row.Parts!.Select(p => partDefaults[p.Key]).ToArray()), row.Default, r.Name + ": default (its parts')");
            }
            else
            {
                Check(!row.IsMerged && GameOptionsSchema.IniKey(r.Name) == row.Key, r.Name + ": its own line, key " + row.Key);
                Equal(Dflt(r.Value["&opts.".Length..]), row.Default, r.Name + ": default");
            }
        }
        Equal(string.Join("|", names), string.Join("|", GameOptionsSchema.All.Select(r => r.Name)), "the rows, in the menu's order");
        // (the lines the game's save drops, merged_rows.h kDropped: kept keys, read once to move them)
        var mr = File.ReadAllText(Path.Combine(dir!, "merged_rows.h"));
        Check(mr.Contains("kVersion = 8;"), "merged rows retain stock version 8");
        var sizes = File.ReadAllText(Path.Combine(dir!, "output_sizes.h"));
        Check(sizes.Contains("#define OUTPUT_OPTIONS_VERSION " + GameOptionsSchema.CurrentVersion), "output_sizes.h owns CurrentVersion");
        var dropped = Regex.Match(mr, @"kDropped\[\]\s*=\s*\{([^}]*)\}").Groups[1].Value;
        foreach (Match d in Regex.Matches(dropped, "\"([^\"]+)\""))
            Check(GameOptionsSchema.KeptKeys.ContainsKey(d.Groups[1].Value) && GameOptionsSchema.ByKey(d.Groups[1].Value) == null, d.Groups[1].Value + ": dropped by the game, a kept key here");
        // (the Debug tab's keys, and the Layout preset's, are the KeptKeys: each with its reason)
        foreach (var r in table.Where(r => r.Value != "nullptr" && !r.Heading && (r.Tab == "TAB_DEBUG" || r.Value == "&opts.pad_layout")))
            Check(GameOptionsSchema.KeptKeys.ContainsKey(GameOptionsSchema.IniKey(r.Name)), r.Name + "'s key " + GameOptionsSchema.IniKey(r.Name) + " is a kept key");
    }

    // ---- keys and labels ----

    static void GameOptionsLabels()
    {
        var all = GameOptionsSchema.All;
        Equal(all.Count, all.Select(r => r.Key).Distinct().Count(), "keys are unique");
        Check(all.All(r => r.Key.Length <= 31 && !r.Key.Contains(' ')), "keys as ini_key makes them");
        Equal("frame_rate_cap", GameOptionsSchema.Get("frame_rate_cap").Key, "renamed row keeps its key");
        Equal("Frame rate cap", GameOptionsSchema.Get("frame_rate_cap").Name, "by key");
        // ((Triforce, options_version 8) the rows renamed into their groups keep their keys; a merged row has none of its own)
        Equal("ultrawide", GameOptionsSchema.ByName("Aspect ratio")!.Key, "Aspect ratio's key");
        Equal("hdr_paper_white", GameOptionsSchema.ByName("Paper white")!.Key, "Paper white's key");
        Equal("renodx_bloom", GameOptionsSchema.ByName("Bloom")!.Key, "Bloom's key");
        Equal(GameOptionsSchema.LatencyKey, GameOptionsSchema.ByName("Low latency")!.Key, "Low latency: a merged row");
        Equal("nvidia_reflex,amd_anti-lag_2", string.Join(",", GameOptionsSchema.ByName("Low latency")!.Parts!.Select(p => p.Key)), "its parts' keys");
        Equal(null, GameOptionsSchema.ByKey("amd_anti-lag_2"), "a part is no row");
        Check(GameOptionsSchema.Part("amd_anti-lag_2") != null && GameOptionsSchema.IsValueKey("amd_anti-lag_2"), "but a value");
        Check(!GameOptionsSchema.IsValueKey(GameOptionsSchema.HdrKey), "a merged row's own key is no line's");
        foreach (var gone in new[] { "Quality preset", "Window scaling filter", "Reflex frame limit", "Handheld profile", "Stick dead zone", "Robust buffers" })
            Equal(null, GameOptionsSchema.ByName(gone), gone + ": no row (options_version 8)");
        Equal("tail_early", GameOptionsSchema.IniKey("Start next frame early"), "Start next frame early's key");
        Equal("export_save_for_a_bug_report", GameOptionsSchema.IniKey("Export save for a bug report"), "a long name: 28 letters");
        Equal("abcdefghijklmnopqrstuvwxyzabcde", GameOptionsSchema.IniKey("ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGH"), "cut at 31");
        Equal(null, GameOptionsSchema.ByKey("Fullscreen"), "keys are exact");
        Throws<KeyNotFoundException>(() => GameOptionsSchema.Get("nope"), "an unknown key");

        foreach (var r in all)
        {
            foreach (var text in new[] { r.Name, r.Help }.Concat(r.Choices.Select(c => c.Label)).Concat(new[] { r.Label(r.Lo), r.Label(r.Hi), r.Label(r.Default) }))
                Check(!text.Contains("hookshot", StringComparison.OrdinalIgnoreCase), r.Name + ": no Hookshot in \"" + text + "\"");
            Check(r.Help.Length > 10, r.Name + ": has its help");
            Check(r.Default >= r.Lo && r.Default <= r.Hi, r.Name + ": default in range");
            Equal(r.Default, r.Clamp(r.Default), r.Name + ": default on its steps");
            if (r.Kind == GameOptionKind.Choice)
            {
                Check(r.Key == GameOptionsSchema.GpuKey || r.Choices.Count >= 2, r.Name + ": choices");
                Check(r.Key == GameOptionsSchema.GpuKey || r.Choices.Any(c => c.Value == r.Default), r.Name + ": its default is a choice");
                Equal(r.Choices.Count, r.Choices.Select(c => c.Label).Distinct().Count(), r.Name + ": labels differ");
            }
            else Equal(0, r.Choices.Count, r.Name + ": a slider has no choice list");
        }
        Equal("Screen,Ultrawide,HUD,HDR,RenoDX,Accessibility,Overlay", string.Join(",", GameOptionsSchema.Sections(GameOptionTab.Display)), "Display's sections");
        Equal("Evil HD,This PC,Upscaling,Anti-aliasing,N64 Classic,Frame generation,Frame rate & latency,Textures,Post-processing,Detail,Advanced", string.Join(",", GameOptionsSchema.Sections(GameOptionTab.Graphics)), "Graphics' sections");
        Equal("Controller,Mouse & keyboard,Rumble,Gameplay,Motion,Hold to toggle,Controls", string.Join(",", GameOptionsSchema.Sections(GameOptionTab.Controls)), "Controls' sections");
        Equal("Sound,Microphone,Controller speaker", string.Join(",", GameOptionsSchema.Sections(GameOptionTab.Audio)), "Audio's sections");
        Equal("Achievements,Game,Saves & reports,Online", string.Join(",", GameOptionsSchema.Sections(GameOptionTab.System)), "System's sections (with rows)");

        string L(string key, int v) => GameOptionsSchema.Get(key).Label(v);
        string Cs(string key) => string.Join("|", GameOptionsSchema.Get(key).Choices.Select(c => c.Value + "=" + c.Label));
        Equal("-3=30|-2=40|-1=45|0=60 (the console's)|1=90|2=120|3=144|4=165|5=240|6=Monitor's rate|7=Uncapped", Cs("frame_rate_cap"), "fps cap");
        Equal("7=1536x864 (handheld)|3=1920x1080|0=2048x1152|1=2560x1440|2=3840x2160|4=5120x1440|6=5120x2160|5=5120x2880|8=Screen|9=Custom (2560x1440)", Cs("output_res"),
            "output sizes, smallest first, then Screen and Custom");
        Equal("0=Game|1=NVIDIA DLSS|3=AMD FSR 3.1|4=AMD FSR 4", Cs("dlss"), "upscalers: the engines, in the menu's order");
        Equal("0=Auto (dynamic)|1=100% (2048x1152)|2=75% (1536x864)|3=67% (1366x768)|4=50% (1024x576)", Cs("resolution"), "render resolution, the game's own");
        Equal("0=Off|1=Default", Cs("microphone"), "microphone without devices");
        Equal("0=Game SMAA|1=Off|2=FXAA|3=SMAA Ultra", Cs("anti-aliasing"), "anti-aliasing");
        Equal("0=Off|1=Auto|2=2x|3=3x|4=4x|5=5x|6=6x|7=7x|8=8x|9=AMD FSR|10=NVIDIA DLSS 2x|11=NVIDIA DLSS 3x|12=NVIDIA DLSS 4x", Cs(GameOptionsSchema.FrameGenKey), "frame generation, DLSS's merged in");
        Equal("0=Off|1=Expanded|2=Native|3=Native + RenoDX", Cs(GameOptionsSchema.HdrKey), "HDR, RenoDX merged in");
        Equal("0=Off|1=Even|2=Steady, any rate|3=Steady, refresh steps", Cs(GameOptionsSchema.PacingKey), "frame pacing, steady merged in");
        Equal("0=Auto|1=Switch|2=Xbox|3=PlayStation 4|4=PlayStation 5|5=Steam Deck|6=Keyboard & mouse", Cs("button_prompts"), "prompts");
        Equal("0=Insert or F1|1=F1 only|2=Insert, F1 or Esc|3=Insert, F1 or touchpad|4=Insert, F1, Esc or touchpad", Cs("menu_shortcut"), "menu shortcut");
        // (Low latency by the card's maker: NVIDIA's Reflex where it is not known)
        var vendorBefore = GameOptionsSchema.LatencyVendorOf;
        try
        {
            GameOptionsSchema.LatencyVendorOf = null;
            Equal("0=Off|1=On|2=On + Boost", Cs(GameOptionsSchema.LatencyKey), "low latency, not known: Reflex's");
            Equal(2, GameOptionsSchema.Get(GameOptionsSchema.LatencyKey).Default, "Reflex's default On + Boost");
            GameOptionsSchema.LatencyVendorOf = () => LatencyVendor.Amd;
            Equal("0=Off|1=On", Cs(GameOptionsSchema.LatencyKey), "AMD: Anti-Lag 2's");
            Equal(0, GameOptionsSchema.Get(GameOptionsSchema.LatencyKey).Default, "Anti-Lag 2's default Off");
            GameOptionsSchema.LatencyVendorOf = () => LatencyVendor.None;
            Equal("0=Off", Cs(GameOptionsSchema.LatencyKey), "neither");
        }
        finally { GameOptionsSchema.LatencyVendorOf = vendorBefore; }
        Equal("1.25", L("mouse_sensitivity", 125), "sensitivity");
        Equal("0.51", L("walk_scale", 51), "walk scale");
        Equal("10000 nits", L("hdr_peak_brightness", 10000), "nits");
        Equal("Muted", L("master_volume", 0), "volume 0");
        Equal("85%", L("master_volume", 85), "volume");
        Equal("Off", L("menu_sounds", 0), "menu sounds 0");
        Equal("Off", L("rumble_strength", 0), "rumble 0");
        Equal("Default (24%)", L("left_stick_dead_zone", -1), "own dead zone's default");
        Equal("0%", L("right_stick_dead_zone", 0), "own dead zone 0");
        Equal("50", L("renodx_bloom", 50), "grade");
        Equal("Normal", L("text_speed", 7), "past the row: its first");
        Equal("16:9", L("ultrawide", 0), "ultrawide");
        Equal("1536x864 (handheld)", L("output_res", 7), "the handheld profile is an Output resolution");
        Equal("NVIDIA DLSS", L("dlss", 2), "DLAA reads as its engine");
        Equal("AMD FSR 3.1", L("dlss", 6), "FSR 3.1's native AA too");
        Equal("Native (100%)", L("resolution", GameOptionsSchema.NativeStep), "the Render resolution's Native");
        Equal("3440", L("output_width", 3440), "Custom's width, in pixels");

        // (the Output resolution is the picture's size, output_sizes.h: Screen and Custom show theirs as the game takes it, a size
        // that is not 16:9 has its own shape, which the Ultrawide row then shows with nothing to choose, and the Render
        // resolution's sizes are the picture's)
        var wide = GameOptionsFile.Load(NewGameFolder("game-options-wide", "output_res=8\nultrawide=2\nresolution=2\noptions_version=9\n"), (3840, 1600));
        Equal("Screen (3840x1600)", wide.Label("output_res"), "Screen: the main monitor's size");
        Equal("2.40:1 (3840x1600)", wide.Label("ultrawide"), "its own shape, not the row's 21:9");
        Equal("2=2.40:1 (3840x1600)", string.Join("|", wide.ChoicesOf("ultrawide").Select(c => c.Value + "=" + c.Label)), "nothing to choose there");
        Equal("75% (2880x1200)", wide.Label("resolution"), "the 3D's size is the picture's share");
        Check(wide.ChoicesOf("output_res").Any(c => c.Label == "Custom (2560x1440)"), "Custom before its rows are set");
        wide.Set("output_res", 9);
        wide.Set("output_width", 3437);
        Equal(3440, wide.Get("output_width"), "the width on its steps of 8");
        wide.Set("output_height", 1440);
        Equal("Custom (3440x1440)", wide.Label("output_res"), "Custom: its rows' size");
        Equal("2.39:1 (3440x1440)", wide.Label("ultrawide"), "3440x1440 is not 64:27");
        wide.Set("output_width", 7680);
        wide.Set("output_height", 2880);
        Equal("Custom (6248x2344)", wide.Label("output_res"), "more pixels than 5120x2880's: smaller, in its shape");
        wide.Set("output_res", 4);
        Equal("32:9 (5120x1440)", wide.Label("ultrawide"), "5120x1440 is a 32:9 picture by itself");
        wide.Set("output_res", 6);
        Equal("21:9 (5120x2160)", wide.Label("ultrawide"), "5120x2160 a 21:9 one");
        Equal("75% (3840x1620)", wide.Label("resolution"), "of the whole 5120x2160");
        wide.Set("output_res", 2);
        Equal("21:9", wide.Label("ultrawide"), "a 16:9 size: the row's shape");
        Equal(5, wide.ChoicesOf("ultrawide").Count, "and its five choices (4:3 since N64 Classic)");
        Equal("75% (3312x1398)", wide.Label("resolution"), "the row's 21:9 at the 4K output: kept to 3840x2160's pixels");
        wide.Set("ultrawide", 0);
        Equal("75% (2880x1620)", wide.Label("resolution"), "the game's own picture");
        wide.Set("output_res", 8);
        wide.Set("output_res", 7);
        Equal("16:9", wide.Label("ultrawide"), "the handheld profile runs the game's own output: the row's shape");
        // (output_custom_size: the Custom size the game's menu keeps while a screen's size is in the two rows. A kept key; a
        // Custom size written here is the entered one from now on and empties it, so the menu does not offer both; another
        // Output resolution chosen takes it back into the rows, as walking the menu's row does; any other change leaves it)
        Check(GameOptionsSchema.IsKept("output_custom_size"), "output_custom_size is a kept key");
        const string screenChosen = "output_res=9\noutput_width=3840\noutput_height=1600\noutput_custom_size=3437x1440\noptions_version=9\n";
        var kept = NewGameFolder("game-options-kept", screenChosen);
        var kf = GameOptionsFile.Load(kept);
        Equal("", string.Join(",", kf.UnknownKeys), "no key nobody knows");
        Equal((3437, 1440), kf.EnteredCustomSize!.Value, "the entered size, as the menu reads it");
        kf.Set("sharpness", 30);
        kf.Save();
        Check(File.ReadAllText(Path.Combine(kept, GameOptionsSchema.FileName)).Contains("output_custom_size=3437x1440\n"), "another row: the line as it was");
        kf.Set("output_width", 3440);
        kf.Set("output_height", 1440);
        Equal(null, kf.EnteredCustomSize, "used up by a size written here");
        kf.Save();
        Equal("output_res=9\noutput_width=3440\noutput_height=1440\noutput_custom_size=\nsharpness=30\noptions_version=9\n",
            File.ReadAllText(Path.Combine(kept, GameOptionsSchema.FileName)), "a Custom size written by the launcher: the kept one emptied");
        var left = NewGameFolder("game-options-left", screenChosen);
        var lf = GameOptionsFile.Load(left);
        lf.Set("output_res", 1);
        Equal(3437, lf.Get("output_width"), "leaving Custom: the entered size back in the rows");
        lf.Save();
        Equal("output_res=1\noutput_width=3437\noutput_height=1440\noutput_custom_size=\noptions_version=9\n",
            File.ReadAllText(Path.Combine(left, GameOptionsSchema.FileName)), "and the line emptied");
        // (read under any Output resolution, as the menu does: under a fixed size with a screen's size in the rows, Custom
        // is the size kept aside, and choosing it, or another fixed size, takes it back into the rows)
        const string fixedChosen = "output_res=1\noutput_width=3840\noutput_height=1600\noutput_custom_size=3437x1440\noptions_version=9\n";
        var ff = GameOptionsFile.Load(NewGameFolder("game-options-kept-fixed", fixedChosen));
        Equal((3437, 1440), ff.EnteredCustomSize!.Value, "read under a fixed size too");
        Check(ff.ChoicesOf("output_res").Any(c => c.Value == 9 && c.Label == "Custom (3440x1440)"), "Custom offered as the size it takes back, not the screen's in the rows");
        ff.Set("output_res", 9);
        Equal("Custom (3440x1440)", ff.Label("output_res"), "chosen: that size");
        Equal(3437, ff.Get("output_width"), "as entered, in the rows");
        ff.Save();
        Equal("output_res=9\noutput_width=3437\noutput_height=1440\noutput_custom_size=\noptions_version=9\n", File.ReadAllText(ff.Path), "written, the line emptied");
        var f2 = GameOptionsFile.Load(NewGameFolder("game-options-kept-fixed2", fixedChosen));
        f2.Set("output_res", 3);
        f2.Save();
        Equal("output_res=3\noutput_width=3437\noutput_height=1440\noutput_custom_size=\noptions_version=9\n", File.ReadAllText(f2.Path), "another fixed size: taken back as well");
        var f3 = GameOptionsFile.Load(NewGameFolder("game-options-kept-fixed3", fixedChosen));
        f3.Set("sharpness", 30);
        f3.Save();
        Check(File.ReadAllText(f3.Path).Contains("output_width=3840\noutput_height=1600\noutput_custom_size=3437x1440\n"), "any other row: all three as they were");
        Equal(null, GameOptionsFile.Load(NewGameFolder("game-options-kept-bad", "output_res=9\noutput_custom_size=100x100\noptions_version=9\n")).EnteredCustomSize,
            "nor a size the rows cannot hold");
        var none = NewGameFolder("game-options-kept-none", "output_res=9\noutput_width=3840\noutput_height=1600\noptions_version=9\n");
        var nf8 = GameOptionsFile.Load(none);
        nf8.Set("output_width", 3440);
        nf8.Save();
        Check(!File.ReadAllText(Path.Combine(none, GameOptionsSchema.FileName)).Contains("output_custom_size"), "no line where the file has none");

        // (a size keeps its shape: one past the rows' ends is made smaller in it, as the game reads the file's two numbers)
        var tall = GameOptionsFile.Load(NewGameFolder("game-options-tall", "output_res=9\noutput_width=10000\noutput_height=5000\noptions_version=9\n"));
        Equal("Custom (5424x2712)", tall.Label("output_res"), "10000x5000 is 2:1 at 5120x2880's pixels");
        Equal(5424, tall.Get("output_width"), "and the rows hold that size");
        Equal("2.00:1 (5424x2712)", tall.Label("ultrawide"), "its shape kept");
        // (the pair is shown as the game takes it, so one side changed is written with the other as shown: 3840 beside the
        // file's 4320 would be 16:18 by the file, 5:4 for the game, where the launcher showed 3840x2880)
        var pair = NewGameFolder("game-options-pair", "output_res=9\noutput_width=7680\noutput_height=4320\noptions_version=9\n");
        var pf = GameOptionsFile.Load(pair);
        Equal("Custom (5120x2880)", pf.Label("output_res"), "7680x4320 in the file: 5120x2880");
        Equal(2880, pf.Get("output_height"), "the rows hold the size taken");
        pf.Set("output_width", 3840);
        Equal("Custom (3840x2880)", pf.Label("output_res"), "the width changed, beside the height shown");
        pf.Save();
        Equal("output_res=9\noutput_width=3840\noutput_height=2880\noptions_version=9\n", File.ReadAllText(Path.Combine(pair, GameOptionsSchema.FileName)),
            "both sides written: the size shown");
        Equal("Custom (3840x2880)", GameOptionsFile.Load(pair).Label("output_res"), "and read back as shown");
        var one = NewGameFolder("game-options-one-side", "output_res=9\noutput_height=1600\noptions_version=9\n");
        var of1 = GameOptionsFile.Load(one);
        of1.Set("output_height", 1440);
        of1.Save();
        Equal("output_res=9\noutput_height=1440\noutput_width=2560\noptions_version=9\n", File.ReadAllText(Path.Combine(one, GameOptionsSchema.FileName)),
            "a side the file has no line for: written too");
        Equal("Screen (5120x2880)", GameOptionsFile.Load(NewGameFolder("game-options-8k", "output_res=8\noptions_version=9\n"), (7680, 4320)).Label("output_res"),
            "a 7680x4320 screen: 16:9 still");
        Equal("Custom (2560x1440)", GameOptionsFile.Load(NewGameFolder("game-options-nosize", "output_res=9\noutput_width=0\noutput_height=-3\noptions_version=9\n")).Label("output_res"),
            "a side that is not a size: its default");
        Equal("Screen", GameOptionsFile.Load(NewGameFolder("game-options-noscreen", "output_res=8\noptions_version=9\n")).Label("output_res"),
            "Screen where the launcher does not know the monitor");
        Equal("Screen (1368x768)", GameOptionsFile.Load(NewGameFolder("game-options-1366", "output_res=8\noptions_version=9\n"), (1366, 768)).Label("output_res"),
            "a 16:9 screen: the game's frame at its height");

        // (the GPU device row: the names the launcher gives it)
        var before = GameOptionsSchema.GpuNames;
        try
        {
            GameOptionsSchema.GpuNames = null;
            Equal("Auto", L("gpu_device", 0), "gpu 0");
            Equal("1: Device 1", L("gpu_device", 2), "gpu without names");
            Equal("0=Auto", Cs("gpu_device"), "gpu choices without names");
            GameOptionsSchema.GpuNames = () => new[] { "NVIDIA GeForce RTX 4070", "AMD Radeon(TM) Graphics" };
            Equal("0=Auto|1=0: NVIDIA GeForce RTX 4070|2=1: AMD Radeon(TM) Graphics", Cs("gpu_device"), "gpu choices");
            Equal("0: NVIDIA GeForce RTX 4070", L("gpu_device", 1), "gpu 1");
            GameOptionsSchema.UseSystemGpus();   // (not asked here: the tests do not read this PC's registry)
            Check(GameOptionsSchema.GpuNames != null, "the hook is set");
            // ((Triforce) 11-19) the game's own order, from its triforce_gpus.txt: Windows lists the Intel first on that laptop,
            // Vulkan the NVIDIA, and the row's values are Vulkan's
            var g = NewRoot("gpulist");
            File.WriteAllText(Path.Combine(g, GameOptionsSchema.GpuListFile), "1\tNVIDIA GeForce RTX 3050 6GB Laptop GPU\n2\tIntel(R) UHD Graphics 770\n");
            GameOptionsSchema.UseGameGpus(() => g);
            Equal("0: NVIDIA GeForce RTX 3050 6GB Laptop GPU", L("gpu_device", 1), "the game's first card is the row's 1");
            Equal("1: Intel(R) UHD Graphics 770", L("gpu_device", 2), "and its second the row's 2");
            File.WriteAllText(Path.Combine(g, GameOptionsSchema.GpuListFile), "garbage\n3\tout of order\n");
            GameOptionsSchema.UseGameGpus(() => g);
            Check(GameOptionsSchema.GpuNames!() != null, "a file with nothing usable: Windows' list (no throw)");
            // ((Triforce) 11-20) Save writes the card's name with its number (gpu_device_name: the game finds it by the name
            // first), and an empty one for Auto
            GameOptionsSchema.GpuNames = () => new[] { "AMD Radeon(TM) 860M Graphics", "NVIDIA GeForce RTX 5060 Laptop GPU" };
            Equal("NVIDIA GeForce RTX 5060 Laptop GPU", GameOptionsSchema.GpuNameOf(2), "the name of the row's 2");
            Equal(null, GameOptionsSchema.GpuNameOf(0), "Auto has no name");
            var nf = NewRoot("gpuname");
            var opt = GameOptionsFile.Load(nf);
            opt.Set(GameOptionsSchema.GpuKey, 2);
            opt.Save();
            var text = File.ReadAllText(Path.Combine(nf, GameOptionsSchema.FileName));
            Check(text.Contains("gpu_device=2") && text.Contains("gpu_device_name=NVIDIA GeForce RTX 5060 Laptop GPU"),
                  "the number and the name saved: " + text.Replace("\n", " | "));
            opt.Set(GameOptionsSchema.GpuKey, 0);
            opt.Save();
            text = File.ReadAllText(Path.Combine(nf, GameOptionsSchema.FileName));
            Check(text.Contains("gpu_device=0") && text.Contains("gpu_device_name=\r\n") || text.Contains("gpu_device_name=\n"),
                  "Auto: the name emptied: " + text.Replace("\n", " | "));
            // ((Triforce) 11-22) a number saved before 11-20 has no name: the row's card chosen again (the same value) writes it,
            // where nothing was written and the number alone decided; chosen again with its name there: nothing to write
            GameOptionsSchema.GpuNames = () => new[] { "AMD Radeon(TM) Graphics", "AMD Radeon RX 6600" };
            var old = NewRoot("gpuold");
            File.WriteAllText(Path.Combine(old, GameOptionsSchema.FileName), "gpu_device=2\r\noptions_version=8\r\n");
            opt = GameOptionsFile.Load(old);
            opt.Set(GameOptionsSchema.GpuKey, 2);
            Check(opt.Changes.ContainsKey(GameOptionsSchema.GpuKey), "the same card again without its name: a change");
            opt.Save();
            text = File.ReadAllText(Path.Combine(old, GameOptionsSchema.FileName));
            Check(text.Contains("gpu_device=2\r\n") && text.Contains("gpu_device_name=AMD Radeon RX 6600\r\n"),
                  "the name written beside the old number: " + text.Replace("\r\n", " | "));
            opt = GameOptionsFile.Load(old);
            opt.Set(GameOptionsSchema.GpuKey, 2);
            Equal(0, opt.Changes.Count, "the same card again with its name: nothing to write");
            File.WriteAllText(Path.Combine(old, GameOptionsSchema.FileName), "gpu_device=2\r\ngpu_device_name=AMD Radeon(TM) Graphics\r\noptions_version=8\r\n");
            opt = GameOptionsFile.Load(old);
            opt.Set(GameOptionsSchema.GpuKey, 2);
            opt.Save();
            text = File.ReadAllText(Path.Combine(old, GameOptionsSchema.FileName));
            Check(text.Contains("gpu_device_name=AMD Radeon RX 6600\r\n") && !text.Contains("Radeon(TM)"),
                  "another card's name beside the number: the row's card's: " + text.Replace("\r\n", " | "));
            File.WriteAllText(Path.Combine(old, GameOptionsSchema.FileName), "gpu_device=0\r\noptions_version=8\r\n");
            opt = GameOptionsFile.Load(old);
            opt.Set(GameOptionsSchema.GpuKey, 0);
            Equal(0, opt.Changes.Count, "Auto again: nothing to write");
        }
        finally { GameOptionsSchema.GpuNames = before; }
    }

    // ---- the real file ----

    static void GameOptionsRealFile()
    {
        var path = Path.Combine(RealGame, GameOptionsSchema.FileName);
        Check(File.Exists(path), "the real options file is there: " + path);
        var info = new FileInfo(path);
        var (len, time) = (info.Length, info.LastWriteTimeUtc);
        var f = GameOptionsFile.Load(RealGame);
        // (the game writes 10 since 11-24, a version the launcher leaves as it is: CurrentVersion)
        Check(f.Exists && f.Version >= GameOptionsSchema.CurrentVersion, "read, version " + f.Version);
        // (every key is a row or a kept one: these, knowingly. options_version: the format; menu_size: the old Menu size row;
        // layout_preset: rebinds the pad_ lines in the game; the Debug tab's; pad_* and key_*: the Controls page's bindings)
        Equal("", string.Join(",", f.UnknownKeys), "no key nobody knows");
        var kept = f.OtherLines.Select(o => o.Key).Where(k => !k.StartsWith("pad_") && !k.StartsWith("key_")).ToList();
        foreach (var k in kept) Check(GameOptionsSchema.KeptKeys.ContainsKey(k), k + " is a kept key");
        Check(f.OtherLines.Any(o => o.Key.StartsWith("key_")), "the bindings are other lines");
        foreach (var r in GameOptionsSchema.All)
        {
            var v = f.Get(r.Key);
            var label = f.Label(r.Key);
            Check(label.Length > 0 && !label.Contains("Device"), r.Name + ": label \"" + label + "\"");
            if (r.Kind == GameOptionKind.Choice)
                Check(f.ChoicesOf(r.Key).Any(c => c.Value == v && c.Label == label), r.Name + ": " + v + " = \"" + label + "\" is one of its choices");
            else
                Check(Regex.IsMatch(label, @"^(-?\d+( nits|%| ms)?|\d\.\d\d|Off|Muted|Default \(24%\)|(TV|Controller) waits \d+ ms|100% \(the game's\))$"), r.Name + ": a slider's label \"" + label + "\"");
            Check(r.IsMerged || v == GameOptionsSchema.NativeStep || f.Raw(r.Key) == null || v == r.AsRead(GameOptionsFile.Atoi(f.Raw(r.Key)!)),
                r.Name + ": the file's value as the game reads it");
        }
        // (the merged rows' parts: each its line's value, in its range; the game writes every one)
        foreach (var p in GameOptionsSchema.Parts.Values)
        {
            Check(f.Raw(p.Key) != null, p.Key + ": the game wrote its line");
            Equal(p.AsRead(GameOptionsFile.Atoi(f.Raw(p.Key)!)), f.Get(p.Key), p.Key + ": as the game reads it");
        }
        info.Refresh();
        Equal(len, info.Length, "the real file is not written");
        Equal(time, info.LastWriteTimeUtc, "the real file's time is the same");
        Check(!File.Exists(path + ".new"), "nothing beside it");
    }

    /// <summary>The real file's lines as of 11-19 (version 7, CRLF), for the exact checks: the real one changes as he plays.</summary>
    const string OptionsFixture = "fullscreen=0\r\noutput_res=1\r\ngpu_device=0\r\nultrawide=0\r\nultrawide_hud=0\r\nultrawide_menus=1\r\nframe_rate_cap=0\r\n" +
        "fps_counter=1\r\nhdr=0\r\nhdr_paper_white=400\r\nhdr_peak_brightness=4000\r\nrenodx_midgray=2\r\nrenodx_color_space=2\r\nquality_preset=0\r\n" +
        "resolution=1\r\ntexture_detail=1\r\ndlss=0\r\ndlss_model=1\r\nanti-aliasing=1\r\nsharpness=50\r\nupscaling=2\r\nframe_pacing=1\r\nnvidia_reflex=0\r\n" +
        "robust_buffers=1\r\nmicrophone=1\r\nmouse_sensitivity=125\r\ncontroller_in_background=1\r\nlayout_preset=1\r\nbutton_prompts=2\r\ndebug_tools=0\r\n" +
        "replay_helper_threads=0\r\ntail_early=1\r\noptions_version=9\r\nmenu_size=1\r\npad_a=0\r\nkey_a=69,0\r\nkey_cam_right=39,76\r\n";

    static string NewGameFolder(string name, string content)
    {
        var game = Path.Combine(NewRoot(name), "game");
        Directory.CreateDirectory(game);
        File.WriteAllText(Path.Combine(game, GameOptionsSchema.FileName), content, Encoding.Latin1);
        return game;
    }

    static void GameOptionsWrite()
    {
        // (a copy of the real file, in a test root)
        var root = NewRoot("game-options");
        var game = Path.Combine(root, "game");
        Directory.CreateDirectory(game);
        var path = Path.Combine(game, GameOptionsSchema.FileName);
        File.Copy(Path.Combine(RealGame, GameOptionsSchema.FileName), path);
        var original = File.ReadAllBytes(path);
        var f = GameOptionsFile.Load(game);
        f.Save();
        Check(File.ReadAllBytes(path).SequenceEqual(original), "nothing changed: nothing written");
        f.Set("hdr", f.Get("hdr"));
        Equal(0, f.Changes.Count, "set to what it is: no change");
        f.Save();
        Check(File.ReadAllBytes(path).SequenceEqual(original), "still the same bytes");

        // (one row changed: that line alone)
        var sens = f.Get("mouse_sensitivity") == 200 ? 300 : 200;
        f.Set("mouse_sensitivity", sens);
        f.Save();
        var before = Encoding.Latin1.GetString(original).Split("\r\n");
        var after = File.ReadAllText(path, Encoding.Latin1).Split("\r\n");
        Equal(before.Length, after.Length, "as many lines, CRLF kept");
        for (var i = 0; i < before.Length; i++)
            Equal(before[i].StartsWith("mouse_sensitivity=") ? "mouse_sensitivity=" + sens : before[i], after[i], "line " + i);
        Equal(sens, GameOptionsFile.Load(game).Get("mouse_sensitivity"), "read back");
        Check(!File.Exists(path + ".new"), "no .new left");

        // (exact labels on the fixture)
        var fx = GameOptionsFile.Load(NewGameFolder("game-options-fixture", OptionsFixture));
        string Lb(string k) => fx.Label(k);
        Equal("2560x1440", Lb("output_res"), "output");
        Equal("100% (2560x1440)", Lb("resolution"), "render resolution at 2560x1440");
        Equal("1.25", Lb("mouse_sensitivity"), "mouse sensitivity 125");
        Equal("4000 nits", Lb("hdr_peak_brightness"), "peak");
        Equal("400 nits", Lb("hdr_paper_white"), "paper white");
        Equal("Off", Lb("anti-aliasing"), "aa");
        Equal("Xbox", Lb("button_prompts"), "prompts");
        Equal("On", Lb("fps_counter"), "fps counter");
        Equal("DCI-P3", Lb("renodx_color_space"), "colour space");
        Equal("Eye adaptation", Lb("renodx_midgray"), "midgray");
        Equal("Transformer 2 (M)", Lb("dlss_model"), "dlss model");
        Equal("50%", Lb("sharpness"), "sharpness");
        Equal("Default", Lb("microphone"), "microphone");
        Equal("Full", Lb("texture_detail"), "texture detail");
        Equal("Off", Lb(GameOptionsSchema.LatencyKey), "low latency: reflex 0");
        Equal("Even", Lb(GameOptionsSchema.PacingKey), "frame pacing on, no steady");
        Equal("Off", Lb(GameOptionsSchema.HdrKey), "hdr 0");
        Equal("Off", Lb(GameOptionsSchema.FrameGenKey), "no frame generation");
        Equal("Per frame", GameOptionsSchema.Get("game_speed").Label(0), "game speed 0");
        Equal("Real time", Lb("game_speed"), "game speed: its default without a line");
        Equal("80%", Lb("menu_sounds"), "menu sounds' default");
        Equal("Middle", Lb("ultrawide_hud"), "wide HUD");
        Equal("Centred, blurred sides", Lb("ultrawide_menus"), "wide menus");
        Equal("Default (24%)", Lb("left_stick_dead_zone"), "a stick's own dead zone: its default");
        // (a v0.5.1 file, options_version 7: the rows that went are other lines, kept for the game to drop)
        Equal("quality_preset,upscaling,robust_buffers,layout_preset,debug_tools,replay_helper_threads,tail_early,options_version,menu_size,pad_a,key_a,key_cam_right",
            string.Join(",", fx.OtherLines.Select(o => o.Key)), "other lines in the file's order");
        Equal("", string.Join(",", fx.UnknownKeys), "each one known");
        Equal("69,0", fx.OtherLines.Single(o => o.Key == "key_a").Value, "a binding's value as it is");
        // ((Triforce, options_version 8) the Upscaler's engines and the Render resolution's Native (upscaler_rows.h step_engine):
        // the game's own at 100% is the 3D at full size, so DLSS from it is DLSS's native AA, DLAA)
        fx.Set("dlss", 1);
        Equal(2, fx.Get("dlss"), "DLSS from the game's own at 100%: DLAA");
        Equal("NVIDIA DLSS", fx.Label("dlss"), "shown as its engine");
        Equal("Native (100%)", fx.Label("resolution"), "at Native");
        Equal(GameOptionsSchema.NativeStep, fx.Get("resolution"), "the row's Native step");
        Equal("DLSS's own", fx.Label("anti-aliasing"), "aa with DLSS");
        Equal("0,-1,3,5,4,6", string.Join(",", fx.ChoicesOf("resolution").Select(c => c.Value)), "DLSS's steps, Native among them");
        Equal("0,2,3,4", string.Join(",", fx.ChoicesOf("dlss").Select(c => c.Value)), "the engines, DLSS by its saved value");
        fx.Set("resolution", 3);
        Equal(1, fx.Get("dlss"), "a mode: DLSS again");
        Equal("Quality (67%)", fx.Label("resolution"), "DLSS's Quality");
        fx.Set("resolution", GameOptionsSchema.NativeStep);
        Equal(2, fx.Get("dlss"), "Native: DLAA");
        Equal(3, fx.Changes["resolution"], "the saved resolution left as it was, for the other steps");
        fx.Set("dlss", 3);
        Equal(6, fx.Get("dlss"), "FSR 3.1 from DLAA: FSR 3.1's native AA");
        Equal("FSR's own", fx.Label("anti-aliasing"), "aa with FSR");
        fx.Set("dlss", 0);
        Equal(0, fx.Get("dlss"), "the game's own from a native AA");
        Equal("100% (2560x1440)", fx.Label("resolution"), "at 100%");
        fx.Set("output_res", GameOptionsSchema.HandheldOutput);
        Equal("100% (1536x864)", fx.Label("resolution"), "the handheld profile's size");
        fx.Set("resolution", 4);
        fx.Set("dlss", 4);
        Equal(4, fx.Get("dlss"), "FSR 4 from 50%: the engine");
        Equal("Performance (50%)", fx.Label("resolution"), "its mode");

        // (the merge: a line changed outside since Load stays; the launcher's own change goes in; an unknown line stays in place)
        var m = NewGameFolder("game-options-merge", OptionsFixture);
        var mp = Path.Combine(m, GameOptionsSchema.FileName);
        var a = GameOptionsFile.Load(m);
        a.Set("fullscreen", 1);
        a.Set("sharpness", 70);
        var outside = File.ReadAllText(mp, Encoding.Latin1).Replace("hdr=0\r\n", "hdr=2\r\nzz_tool_line=5\r\n").Replace("sharpness=50", "sharpness=20");
        File.WriteAllText(mp, outside, Encoding.Latin1);
        a.Save();
        var merged = File.ReadAllText(mp, Encoding.Latin1);
        Check(merged.Contains("\r\nhdr=2\r\nzz_tool_line=5\r\n"), "the outside change and its new line kept in place");
        Check(merged.StartsWith("fullscreen=1\r\n"), "the launcher's change in its line");
        Check(merged.Contains("\r\nsharpness=70\r\n"), "a row changed on both sides: the launcher's (the later writer)");
        Equal(outside.Replace("fullscreen=0", "fullscreen=1").Replace("sharpness=20", "sharpness=70").Replace("options_version=7", "options_version=9"), merged,
            "every other line as the file had it (the version 7 file brought up to 8: nothing of it moves)");
        Equal("zz_tool_line", a.UnknownKeys.Single(), "an unknown key, kept");
        Equal(2, a.Get("hdr"), "this object holds the file as written");

        // (a row with no line goes in before options_version; duplicates all take the value)
        var d = NewGameFolder("game-options-dup", "sharpness=10\nsharpness=20\n#note\noptions_version=9\nmenu_size=1\n");
        var df = GameOptionsFile.Load(d);
        Equal(20, df.Get("sharpness"), "the last line wins, as the game reads it");
        df.Set("sharpness", 30);
        df.Set("vsync", 0);
        df.Save();
        Equal("sharpness=30\nsharpness=30\n#note\nvsync=0\noptions_version=9\nmenu_size=1\n", File.ReadAllText(Path.Combine(d, GameOptionsSchema.FileName)), "LF kept, line added, comment kept");

        // (a device's name in UTF-8: its bytes as they were, its label as text)
        var mic = "microphone_device=Mikrofon (Ä USB)";
        var micBytes = Encoding.UTF8.GetBytes("microphone=2\r\n" + mic + "\r\noptions_version=9\r\n");
        var mg = Path.Combine(NewRoot("game-options-mic"), "game");
        Directory.CreateDirectory(mg);
        File.WriteAllBytes(Path.Combine(mg, GameOptionsSchema.FileName), micBytes);
        var mf = GameOptionsFile.Load(mg);
        Equal("Mikrofon (Ä USB)", mf.Label("microphone"), "the device's name");
        Equal("0=Off|1=Default|2=Mikrofon (Ä USB)", string.Join("|", mf.ChoicesOf("microphone").Select(c => c.Value + "=" + c.Label)), "its choices");
        mf.Set("fullscreen", 1);
        mf.Save();
        var micAfter = File.ReadAllBytes(Path.Combine(mg, GameOptionsSchema.FileName));
        Check(micAfter.AsSpan().IndexOf(Encoding.UTF8.GetBytes(mic)) >= 0, "the name's UTF-8 bytes kept");

        // (atomic: the .new cannot be made, the file is as it was and the error is the caller's)
        var w = NewGameFolder("game-options-atomic", OptionsFixture);
        var wp = Path.Combine(w, GameOptionsSchema.FileName);
        Directory.CreateDirectory(wp + ".new");
        var wf = GameOptionsFile.Load(w);
        wf.Set("vsync", 0);
        Throws<Exception>(() => wf.Save(), "a failed write throws");
        Equal(OptionsFixture, File.ReadAllText(wp, Encoding.Latin1), "the old file whole");
        Equal(1, wf.Changes.Count, "the change is still to be saved");
        Directory.Delete(wp + ".new");
        wf.Save();
        Equal(0, GameOptionsFile.Load(w).Get("vsync"), "saved once it can be");
        Check(!File.Exists(wp + ".new") && !Directory.Exists(wp + ".new"), "nothing left beside it");
    }

    static void GameOptionsSetRules()
    {
        var f = GameOptionsFile.Load(NewGameFolder("game-options-set", OptionsFixture));
        Equal(10000, f.Set("hdr_peak_brightness", 12345), "past the end: the end");
        Equal(130, f.Set("mouse_sensitivity", 125), "onto the steps: the nearest, the larger on a tie");
        Equal(50, f.Set("rumble_strength", 60), "rumble on 25s");
        Equal(0, f.Set("output_res", 10), "an output past the list: the first");
        Equal(7, f.Set("output_res", 7), "the handheld profile's output");
        Equal(-1, f.Set("left_stick_dead_zone", -7), "a range below 0");
        Equal(-3, f.Set("frame_rate_cap", -3), "the cap's 30");

        // ((Triforce, options_version 8) a merged row sets its parts (merged_rows.h *_set): one of a pair chosen, the other Off)
        string Parts(string key) => string.Join(",", GameOptionsSchema.Get(key).Parts!.Select(p => p.Key + "=" + f.Get(p.Key)));
        f.Set(GameOptionsSchema.FrameGenKey, 11);
        Equal("frame_generation=0,dlss_frame_generation=2", Parts(GameOptionsSchema.FrameGenKey), "NVIDIA DLSS 3x");
        f.Set(GameOptionsSchema.FrameGenKey, 4);
        Equal("frame_generation=4,dlss_frame_generation=0", Parts(GameOptionsSchema.FrameGenKey), "4x, DLSS's off");
        Equal(12, f.Set(GameOptionsSchema.FrameGenKey, 40), "past the end: DLSS 4x");
        f.Set(GameOptionsSchema.HdrKey, 3);
        Equal("hdr=2,renodx_hdr=1", Parts(GameOptionsSchema.HdrKey), "Native + RenoDX");
        f.Set(GameOptionsSchema.HdrKey, 1);
        Equal("hdr=1,renodx_hdr=0", Parts(GameOptionsSchema.HdrKey), "Expanded, RenoDX off");
        f.Set(GameOptionsSchema.PacingKey, 3);
        Equal("frame_pacing=1,steady_frame_rate=2", Parts(GameOptionsSchema.PacingKey), "Steady, refresh steps: pacing on");
        f.Set(GameOptionsSchema.PacingKey, 0);
        Equal("frame_pacing=0,steady_frame_rate=0", Parts(GameOptionsSchema.PacingKey), "Off");
        var vendorBefore = GameOptionsSchema.LatencyVendorOf;
        try
        {
            GameOptionsSchema.LatencyVendorOf = () => LatencyVendor.Nvidia;
            f.Set(GameOptionsSchema.LatencyKey, 1);
            Equal("nvidia_reflex=1,amd_anti-lag_2=0", Parts(GameOptionsSchema.LatencyKey), "NVIDIA: Reflex On");
            GameOptionsSchema.LatencyVendorOf = () => LatencyVendor.Amd;
            Equal(0, f.Get(GameOptionsSchema.LatencyKey), "AMD: Anti-Lag 2's Off (Reflex's line is NVIDIA's)");
            Equal(1, f.Set(GameOptionsSchema.LatencyKey, 2), "AMD: On, its last");
            Equal("nvidia_reflex=1,amd_anti-lag_2=1", Parts(GameOptionsSchema.LatencyKey), "Anti-Lag 2 on, Reflex as it was");
            GameOptionsSchema.LatencyVendorOf = () => LatencyVendor.None;
            f.Set(GameOptionsSchema.LatencyKey, 1);
            Equal("nvidia_reflex=1,amd_anti-lag_2=1", Parts(GameOptionsSchema.LatencyKey), "neither: nothing changes");
        }
        finally { GameOptionsSchema.LatencyVendorOf = vendorBefore; }
        Equal(2, f.Set("steady_frame_rate", 5), "a part by its own key: in its range");
        Equal(3, f.Get(GameOptionsSchema.PacingKey), "and the row shows it");
        // (a pair the old launcher could save both of: the row as the game shows it)
        var both = GameOptionsFile.Load(NewGameFolder("game-options-both", "frame_generation=3\ndlss_frame_generation=1\nhdr=1\nrenodx_hdr=1\nframe_pacing=0\nsteady_frame_rate=1\noptions_version=8\n"));
        Equal("NVIDIA DLSS 2x", both.Label(GameOptionsSchema.FrameGenKey), "DLSS's frame generation over the renderer's");
        Equal("Expanded", both.Label(GameOptionsSchema.HdrKey), "RenoDX only with Native");
        Equal("Steady, any rate", both.Label(GameOptionsSchema.PacingKey), "steady over pacing off");

        // (the Upscaler: an engine; the Render resolution's Native goes with it, upscaler_rows.h step_engine)
        var u = GameOptionsFile.Load(NewGameFolder("game-options-up", OptionsFixture));   // (dlss=0, resolution=1: 100%)
        u.Set("dlss", 3);
        Equal(6, u.Get("dlss"), "FSR 3.1 from 100%: its native AA");
        u.Set("resolution", 4);
        Equal(3, u.Get("dlss"), "a mode: FSR 3.1");
        u.Set("dlss", 1);
        Equal(1, u.Get("dlss"), "DLSS from 50%: DLSS");
        Equal(4, u.Get("resolution"), "50% is DLSS's Performance");
        u.Set("dlss", 0);
        u.Set("resolution", 2);
        u.Set("dlss", 3);
        Equal(3, u.Get("resolution"), "75% with FSR 3.1: 67%");
        u.Set("dlss", 0);
        u.Set("resolution", GameOptionsSchema.NativeStep);
        Equal(1, u.Get("resolution"), "the game's own at Native: 100%");
        Equal(2, u.Set("dlss", 2), "DLAA by its saved value: as it is");

        // (Apply: each with Set's rules)
        var b = GameOptionsFile.Load(NewGameFolder("game-options-apply", OptionsFixture));
        var got = b.Apply(new Dictionary<string, int> { [GameOptionsSchema.FrameGenKey] = 2, ["steady_frame_rate"] = 2, ["sharpness"] = 30 });
        Equal(2, got[GameOptionsSchema.FrameGenKey], "frame generation set");
        Equal(2, got["steady_frame_rate"], "a part by its key");
        Equal(30, got["sharpness"], "sharpness");
        var changes = b.Changes.Count;
        Throws<KeyNotFoundException>(() => b.Apply(new Dictionary<string, int> { ["vsync"] = 0, ["descriptor_reuse"] = 0 }), "a key that is no row");
        Throws<KeyNotFoundException>(() => b.Apply(new Dictionary<string, int> { ["quality_preset"] = 3 }), "the Quality preset is gone");
        Equal(changes, b.Changes.Count, "nothing set then");
        Equal(1, b.Get("vsync"), "vsync untouched");
        b.Save();
        var back = GameOptionsFile.Load(Path.GetDirectoryName(b.Path)!);
        Equal(30, back.Get("sharpness"), "saved");
        Equal(2, back.Get("frame_generation"), "saved");
        Equal("Steady, refresh steps", back.Label(GameOptionsSchema.PacingKey), "saved");
        Equal(0, back.Changes.Count, "a fresh read has no changes");
    }

    static void GameOptionsOldVersion()
    {
        // (options_version 5: Frame pacing's and Start next frame early's old off defaults, Ultrawide's 1 the monitor's shape)
        var g = NewGameFolder("game-options-v5", "frame_pacing=0\r\nultrawide=1\r\nnvidia_reflex=0\r\nsharpness=20\r\noptions_version=5\r\npad_a=0\r\n");
        var f = GameOptionsFile.Load(g, (2560, 1080));
        Equal(5, f.Version, "version");
        Equal(1, f.Get("frame_pacing"), "pacing on, as the game reads a file before 7");
        Equal(2, f.Get("ultrawide"), "the monitor's shape at 2560x1080: 21:9");
        Equal(0, f.Get("nvidia_reflex"), "Reflex as saved from 5 on");
        // (without the screen, as the launcher is off Windows: the row is the game's to read, which knows its screen and reads
        // 21:9 on this one. Not shown as a guess; and a save keeps the file at its version with its old lines, where it
        // wrote ultrawide=0 and the current version, which the game then took as the player's 16:9)
        var blind = NewGameFolder("game-options-v5-blind", "frame_pacing=0\r\nultrawide=1\r\noutput_res=4\r\nsharpness=20\r\noptions_version=5\r\n");
        var bf = GameOptionsFile.Load(blind);
        Equal(1, bf.Get("ultrawide"), "without the screen: the row as the file has it, for the game");
        Equal(4, bf.Get("output_res"), "and the 5120x1440 that depends on it");
        Equal(1, bf.Get("frame_pacing"), "the file's other old rules still read");
        bf.Set("sharpness", 30);
        bf.Save();
        Equal("frame_pacing=0\r\nultrawide=1\r\noutput_res=4\r\nsharpness=30\r\noptions_version=5\r\n",
            File.ReadAllText(Path.Combine(blind, GameOptionsSchema.FileName)), "saved at its version: nothing guessed, nothing migrated");
        Equal(5, GameOptionsFile.Load(blind).Version, "still 5");
        // (the row set here is a choice among the current shapes: the file is brought up to date with it)
        bf.Set("ultrawide", 2);
        bf.Save();
        Equal("frame_pacing=1\r\nultrawide=2\r\noutput_res=4\r\nsharpness=30\r\noptions_version=9\r\n",
            File.ReadAllText(Path.Combine(blind, GameOptionsSchema.FileName)).Replace("tail_early=1\r\n", ""),
            "the row chosen here: up to date, beside the 5120x1440 the launcher showed");
        // (with the screen known nothing waits, as before; nor from version 6 on, where 1 is 16:10)
        Equal(1, GameOptionsFile.Load(NewGameFolder("game-options-v6-blind", "ultrawide=1\noptions_version=6\n")).Get("ultrawide"), "from 6 on: 16:10");
        var v6 = GameOptionsFile.Load(NewGameFolder("game-options-v6-save", "ultrawide=1\nsharpness=20\noptions_version=6\n"));
        v6.Set("sharpness", 30);
        v6.Save();
        Check(File.ReadAllText(v6.Path).Contains("options_version=9"), "a version 6 file is brought up to date without a screen");
        f.Set("sharpness", 30);
        f.Save();
        Equal("frame_pacing=1\r\nultrawide=2\r\nnvidia_reflex=0\r\nsharpness=30\r\noptions_version=9\r\npad_a=0\r\n",
            File.ReadAllText(Path.Combine(g, GameOptionsSchema.FileName)).Replace("tail_early=1\r\n", ""), "brought up to 8 as the game would read it");
        Check(File.ReadAllText(Path.Combine(g, GameOptionsSchema.FileName)).Contains("tail_early=1\r\noptions_version=9"), "the Debug tab's tail_early too, before the version");
        var again = GameOptionsFile.Load(g);
        Equal(9, again.Version, "now 8");
        again.Set(GameOptionsSchema.PacingKey, 0);
        again.Save();
        Equal(0, GameOptionsFile.Load(g).Get("frame_pacing"), "and from 7 on the choice is read as it is");

        // ((Triforce, options_version 8) a v0.5.1 file (7, the old rows' lines in it): the handheld profile becomes the Output
        // resolution's 1536x864, the shared stick dead zone each stick's own that had none (merged_rows.h migrate)
        var h = NewGameFolder("game-options-v7", "output_res=1\nhandheld_profile=1\nstick_dead_zone=3\nright_stick_dead_zone=12\nquality_preset=4\nupscaling=2\noptions_version=7\n");
        var hf = GameOptionsFile.Load(h);
        Equal(7, hf.Get("output_res"), "the handheld profile: the handheld output");
        Equal("1536x864 (handheld)", hf.Label("output_res"), "its label");
        Equal(15, hf.Get("left_stick_dead_zone"), "the shared 15% into the left stick's own");
        Equal(12, hf.Get("right_stick_dead_zone"), "the right stick's own kept");
        Equal("", string.Join(",", hf.UnknownKeys), "the old rows' lines: known");
        hf.Set("vsync", 0);
        hf.Save();
        Equal("output_res=7\nhandheld_profile=1\nstick_dead_zone=3\nright_stick_dead_zone=12\nquality_preset=4\nupscaling=2\nvsync=0\nleft_stick_dead_zone=15\noptions_version=9\n",
            File.ReadAllText(Path.Combine(h, GameOptionsSchema.FileName)), "brought up to 8: the moved values written, the old lines left for the game to drop");
        var h8 = GameOptionsFile.Load(h);
        h8.Set("output_res", 1);
        h8.Save();
        Equal(1, GameOptionsFile.Load(h).Get("output_res"), "from 8 on the old handheld_profile line moves nothing");
        // (a 436f9ac-based build's 7: none of those lines, nothing moves)
        var n7 = GameOptionsFile.Load(NewGameFolder("game-options-n7", "output_res=3\nleft_stick_dead_zone=-1\noptions_version=7\n"));
        Equal(3, n7.Get("output_res"), "no handheld line: the output as it is");
        Equal(-1, n7.Get("left_stick_dead_zone"), "no shared line: the default");
        // (options_version 7: 5120x1440 and 5120x2160 were the game's frame, and the Ultrawide row gave the picture's shape there
        // too. With the row on another shape than theirs: the 16:9 size of their height, the same picture; else as they are)
        var w7 = NewGameFolder("game-options-v7", "output_res=4\r\nultrawide=2\r\nsharpness=20\r\noptions_version=7\r\n");
        var wf7 = GameOptionsFile.Load(w7);
        Equal(1, wf7.Get("output_res"), "5120x1440 with the row on 21:9: 2560x1440, whose 21:9 picture it was");
        Equal("21:9", wf7.Label("ultrawide"), "and the row's shape still");
        wf7.Set("sharpness", 30);
        wf7.Save();
        Equal("output_res=1\r\nultrawide=2\r\nsharpness=30\r\noptions_version=9\r\n", File.ReadAllText(Path.Combine(w7, GameOptionsSchema.FileName)),
            "written as the game reads it, at 8");
        Equal(4, GameOptionsFile.Load(NewGameFolder("game-options-v7b", "output_res=4\nultrawide=3\noptions_version=7\n")).Get("output_res"), "its own shape: as it is");
        Equal(4, GameOptionsFile.Load(NewGameFolder("game-options-v7c", "output_res=4\nultrawide=0\noptions_version=7\n")).Get("output_res"), "16:9 there: as it is, now its picture");
        Equal(2, GameOptionsFile.Load(NewGameFolder("game-options-v7d", "output_res=6\nultrawide=3\noptions_version=7\n")).Get("output_res"), "5120x2160 with 32:9: 3840x2160");
        Equal(6, GameOptionsFile.Load(NewGameFolder("game-options-v7e", "output_res=6\nultrawide=2\noptions_version=7\n")).Get("output_res"), "5120x2160 with its 21:9");
        Equal(4, GameOptionsFile.Load(NewGameFolder("game-options-v8", "output_res=4\nultrawide=2\noptions_version=9\n")).Get("output_res"), "from 8 on as chosen: the row is not read there");
        Equal(4, GameOptionsFile.Load(NewGameFolder("game-options-v5b", "output_res=4\nultrawide=1\noptions_version=5\n"), (5120, 1440)).Get("output_res"),
            "before 6 the row's 1 was the monitor's shape: 32:9 on a 5120x1440 one, 5120x1440's own");

        // (no options_version line: Game speed real time; no resolution line but the old dynamic_resolution)
        var o = NewGameFolder("game-options-v0", "game_speed=0\ndynamic_resolution=0\n");
        var of = GameOptionsFile.Load(o);
        Equal(1, of.Get("game_speed"), "the old default real time");
        Equal(1, of.Get("resolution"), "dynamic_resolution 0: 100%");
        Equal(2, of.Get("nvidia_reflex"), "Reflex On + Boost before 5");

        // (no file: the defaults; a Save makes it with the changed values, in the menu's order, and the version)
        var n = Path.Combine(NewRoot("game-options-new"), "game");
        Directory.CreateDirectory(n);
        var nf = GameOptionsFile.Load(n);
        Check(!nf.Exists, "no file");
        Equal(1, nf.Get("vsync"), "default");
        Equal("Off", nf.Label("fullscreen"), "default label");
        Equal("Even", nf.Label(GameOptionsSchema.PacingKey), "frame pacing's default");
        nf.Save();
        Check(!File.Exists(nf.Path), "nothing to write: no file made");
        nf.Set("master_volume", 83);
        nf.Set("vsync", 0);
        nf.Set(GameOptionsSchema.PacingKey, 3);
        nf.Save();
        var nl = OperatingSystem.IsWindows() ? "\r\n" : "\n";
        Equal("vsync=0" + nl + "steady_frame_rate=2" + nl + "master_volume=85" + nl + "options_version=9" + nl, File.ReadAllText(nf.Path),
            "a new file: the values in the menu's order (a merged row's parts at its place; frame_pacing at its default not written), then the version");
        Check(nf.Exists, "now there");
    }
}
