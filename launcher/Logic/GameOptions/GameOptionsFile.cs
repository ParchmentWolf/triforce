// triforce_options.ini in a game folder, read and written as the game does it (gpu/vk/vk_menu.cpp menu_init and save,
// ini_merge.h, file_whole.h): plain key=value lines; a row's value is the last line with its key, as an int the way atoi
// reads it, kept in its range; a row with no line has its default. Every line that is not a row of GameOptionsSchema is kept
// as it is, in its place.
//
// The game writes the whole file at every change in its menu, and reads it once at its start. So the launcher must not write
// it while the game runs: the game's next save would merge (it keeps a line changed outside unless it changed that row
// itself), but the running game would not take the launcher's values until its next start, and its menu would show its own.
// Refusing to write while Game.IsRunning(folder) is the caller's job: this class does not look at processes.
using System.Globalization;
using System.Text;

namespace Triforce.Logic;

public sealed class GameOptionsFile : IGameOptionValues
{
    /// <summary>The file's path: the game folder's triforce_options.ini.</summary>
    public string Path { get; }
    readonly (int W, int H)? mainScreen;
    List<string> lines = new();          // (the file as last read or written, each line without its line end)
    Dictionary<string, string> raw = new(StringComparer.Ordinal);   // (each key's last value, trimmed as ini_merge.h does)
    Dictionary<string, int> read = new(StringComparer.Ordinal);     // (each row's value as the game reads this file)
    readonly Dictionary<string, int> set = new(StringComparer.Ordinal);   // (the rows the launcher changed: their new values)

    GameOptionsFile(string path, (int W, int H)? mainScreen)
    {
        Path = path;
        this.mainScreen = mainScreen;
        Reload();
    }

    /// <summary>The game folder's options. mainScreen: the main monitor's size in pixels, for a file from before
    /// options_version 6 whose Ultrawide is 1 (then "Monitor's shape": the game reads it as the shape nearest the main
    /// monitor's); without it such a 1 is read as 16:9, as the game does where it cannot ask. A missing file is all defaults.</summary>
    public static GameOptionsFile Load(string gameFolder, (int W, int H)? mainScreen = null) =>
        new(System.IO.Path.Combine(gameFolder, GameOptionsSchema.FileName), mainScreen);

    /// <summary>The file was there when it was last read.</summary>
    public bool Exists { get; private set; }
    /// <summary>Its options_version (0: none, a file from before the line, or no file).</summary>
    public int Version { get; private set; }

    /// <summary>Reads the file again: the launcher's changes not yet saved are dropped.</summary>
    public void Reload()
    {
        Exists = File.Exists(Path);
        var text = Exists ? File.ReadAllText(Path, Encoding.Latin1) : "";
        Parse(text);
        set.Clear();
    }

    void Parse(string text)
    {
        lines = SplitLines(text);
        raw = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var l in lines)
            if (KeyOf(l) is { } k) raw[k] = Trim(l[(k.Length + 1)..]);
        Version = raw.TryGetValue(GameOptionsSchema.VersionKey, out var ver) ? Atoi(ver) : 0;
        read = Effective(raw, Exists);
    }

    // ---- reading as the game does ----

    /// <summary>The key of a key=value line (all before the first '='; none for a line without one or starting with it).</summary>
    static string? KeyOf(string line)
    {
        var eq = line.IndexOf('=');
        return eq > 0 ? line[..eq] : null;
    }
    static string Trim(string v) => v.Trim(' ', '\t', '\r', '\n');
    /// <summary>C's atoi: spaces, a sign, digits, the rest ignored; 0 without digits (and the int's end past it).</summary>
    internal static int Atoi(string s)
    {
        int i = 0;
        while (i < s.Length && (s[i] == ' ' || s[i] is >= '\t' and <= '\r')) i++;
        var neg = false;
        if (i < s.Length && (s[i] == '+' || s[i] == '-')) neg = s[i++] == '-';
        long v = 0;
        while (i < s.Length && s[i] is >= '0' and <= '9' && v <= int.MaxValue) v = v * 10 + (s[i++] - '0');
        v = neg ? -v : v;
        return (int)Math.Clamp(v, int.MinValue, int.MaxValue);
    }

    /// <summary>Each saved value as the game reads the file at its start (menu_init), by its key (every row's with a line of its
    /// own, and the merged rows' parts): the last line's, in its range; then the rules for a file of an older options_version
    /// (the defaults that changed: such a file wrote the old one whether chosen or not; version 8's moves of the rows that
    /// went), the old dynamic_resolution key, the Microphone without a device's name.</summary>
    Dictionary<string, int> Effective(Dictionary<string, string> lines, bool exists)
    {
        var v = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var r in GameOptionsSchema.All.Where(r => !r.IsMerged))
            v[r.Key] = exists && lines.TryGetValue(r.Key, out var s) ? r.AsRead(Atoi(s)) : r.Default;
        foreach (var p in GameOptionsSchema.Parts.Values)
            v[p.Key] = exists && lines.TryGetValue(p.Key, out var s) ? p.AsRead(Atoi(s)) : p.Default;
        if (!exists) return v;
        foreach (var (key, value) in Migrated(lines)) if (v.ContainsKey(key)) v[key] = value;
        if (!lines.ContainsKey(GameOptionsSchema.ResolutionKey) && lines.TryGetValue("dynamic_resolution", out var dyn))
            v[GameOptionsSchema.ResolutionKey] = Atoi(dyn) != 0 ? 0 : 1;
        if (!lines.ContainsKey(GameOptionsSchema.MicDeviceKey) && v[GameOptionsSchema.MicKey] >= 2) v[GameOptionsSchema.MicKey] = 1;
        return v;
    }

    /// <summary>menu_init's rules for a file of an older options_version, as key and the value the game takes in its place
    /// (only the keys whose value it changes). The Debug tab's keys too: the game's readers before the menu take the same rules.</summary>
    List<(string Key, int Value)> Migrated(Dictionary<string, string> lines)
    {
        var list = new List<(string, int)>();
        var hasVersion = lines.TryGetValue(GameOptionsSchema.VersionKey, out var vs);
        var version = hasVersion ? Atoi(vs!) : 0;
        void Force(string key, int value)
        {
            if (!lines.TryGetValue(key, out var s) || Atoi(s) != value) list.Add((key, value));
        }
        // ((Triforce, options_version 8) merged_rows.h migrate: the handheld profile is the Output resolution's 1536x864, the
        // shared stick dead zone each stick's own where it had none of its own. The other rows that went move nothing; their
        // lines stay until the game's next save drops them. A 436f9ac-based build's 7 has none of these lines: nothing moves)
        if (version < 8)
        {
            if (lines.TryGetValue("handheld_profile", out var hh) && Atoi(hh) != 0) Force(GameOptionsSchema.OutputResKey, GameOptionsSchema.HandheldOutput);
            var old = lines.TryGetValue("stick_dead_zone", out var sz) ? Atoi(sz) : 0;
            var shared = old is > 0 and < 6 ? GameOptionsSchema.SharedZone[old] : -1;
            foreach (var key in new[] { "left_stick_dead_zone", "right_stick_dead_zone" })
            {
                var own = lines.TryGetValue(key, out var s) ? GameOptionsSchema.Get(key).AsRead(Atoi(s)) : -1;
                if (own < 0 && shared != own) list.Add((key, shared));
            }
        }
        if (!hasVersion) Force("game_speed", 1);
        if (version < 4) Force("descriptor_reuse", 1);
        if (version < 5)
        {
            Force("sampler_cache", 1); Force("fast_pipeline_link", 1); Force("lazy_write-back", 1); Force("opaque_textures_as_bc1", 1);
            Force("nvidia_reflex", 2);
        }
        if (version < 6)
        {
            Force("tail_early", 1);
            if (lines.TryGetValue("ultrawide", out var uw) && Atoi(uw) == 1) Force("ultrawide", NearestShape(mainScreen));
        }
        if (version < 7) Force("frame_pacing", 1);
        return list;
    }

    /// <summary>ultrawide_rows.h ultrawide_row_nearest: the Ultrawide value whose shape is nearest the screen's; 16:9 unknown.</summary>
    internal static int NearestShape((int W, int H)? screen)
    {
        if (screen is not { } s || s.W <= 0 || s.H <= 0) return 0;
        var r = (double)s.W / s.H;
        double[] shapes = { 16.0 / 9.0, 1.6, 64.0 / 27.0, 32.0 / 9.0 };
        int best = 0;
        double bestD = 0;
        for (var i = 0; i < shapes.Length; i++)
        {
            var d = r > shapes[i] ? r / shapes[i] : shapes[i] / r;
            if (i == 0 || d < bestD) { best = i; bestD = d; }
        }
        return best;
    }

    // ---- the values ----

    /// <summary>A saved value by its key (a row's own line or a merged row's part): the launcher's change, else what the game
    /// reads from the file (its default without a line).</summary>
    int Value(string key) => set.TryGetValue(key, out var v) ? v : read[key];

    /// <summary>A row's value as the game's menu shows it: the launcher's change, else what the game reads from the file (its
    /// default without a line). A merged row's: the view of its parts (merged_rows.h); the Render resolution's: NativeStep while
    /// the Upscaler is an engine's native AA (its saved value is then left for the engine's other steps). A merged row's part
    /// by its own key: its saved value. KeyNotFoundException for any other key (Raw has those).</summary>
    public int Get(string key)
    {
        if (GameOptionsSchema.Part(key) != null) return Value(key);
        var row = GameOptionsSchema.Get(key);
        if (row.Merge != null) return row.Merge.Of(row.Parts!.Select(p => Value(p.Key)).ToArray());
        if (key == GameOptionsSchema.ResolutionKey && GameOptionsSchema.FullScale(Value(GameOptionsSchema.UpscalerKey))) return GameOptionsSchema.NativeStep;
        return Value(key);
    }

    /// <summary>A line's value as the file has it (the last line with that key, trimmed), null without one. Any key.</summary>
    public string? Raw(string key) => raw.GetValueOrDefault(key);

    /// <summary>A row's value's label as the game's menu shows it, the other rows as they are here (the Render resolution's
    /// sizes, the Anti-aliasing while an upscaler draws, the Microphone's device).</summary>
    public string Label(string key) => GameOptionsSchema.Get(key).Label(Get(key), this);

    /// <summary>The values a row offers with the other rows as they are here: the Upscaler's engines (the one chosen by its
    /// saved value: an engine's native AA is its engine here), the Render resolution's steps for the Upscaler chosen (Native
    /// (100%), NativeStep, among DLSS's and FSR's), the Microphone's saved device, the row's own Choices otherwise. The value it
    /// has now is always in the list (a hand-edited one where it would sit).</summary>
    public IReadOnlyList<GameOptionChoice> ChoicesOf(string key)
    {
        var row = GameOptionsSchema.Get(key);
        if (row.Kind == GameOptionKind.Slider) return Array.Empty<GameOptionChoice>();
        var now = Get(key);
        var values = key switch
        {
            GameOptionsSchema.ResolutionKey => GameOptionsSchema.ResolutionSteps(Value(GameOptionsSchema.UpscalerKey)).ToList(),
            GameOptionsSchema.UpscalerKey => GameOptionsSchema.UpscalerOrder.Select(e => e == GameOptionsSchema.Engine(now) ? now : e).ToList(),
            GameOptionsSchema.MicKey => Raw(GameOptionsSchema.MicDeviceKey) is { Length: > 0 } ? new List<int> { 0, 1, 2 } : new List<int> { 0, 1 },
            _ => row.Choices.Select(c => c.Value).ToList(),
        };
        if (!values.Contains(now)) values.Add(now);
        if (key == GameOptionsSchema.GpuKey)
        {
            var gpus = row.Choices.ToList();
            if (!gpus.Any(c => c.Value == now)) gpus.Add(new GameOptionChoice(now, row.Label(now)));
            return gpus;
        }
        if (key == GameOptionsSchema.MicKey && now >= 2) values = values.Where(v => v < 2 || v == now).ToList();
        return values.Select(v => new GameOptionChoice(v, row.Label(v, this))).ToList();
    }

    /// <summary>The saved values the launcher changed since the file was read, by their keys in the file (a merged row's are
    /// its parts'), with their new values (Save writes these).</summary>
    public IReadOnlyDictionary<string, int> Changes => set;

    /// <summary>The file's lines that are no value here, in order, as (key, value): the KeptKeys and pad_/key_ lines, and
    /// any key nobody knows (kept as it is). Lines without a key (blank, a comment) are kept too but not listed.</summary>
    public IReadOnlyList<(string Key, string Value)> OtherLines =>
        lines.Select(l => (Key: KeyOf(l), Line: l)).Where(x => x.Key != null && !GameOptionsSchema.IsValueKey(x.Key))
            .Select(x => (x.Key!, x.Line[(x.Key!.Length + 1)..])).ToList();

    /// <summary>OtherLines' keys that neither the schema nor KeptKeys knows.</summary>
    public IReadOnlyList<string> UnknownKeys => OtherLines.Select(o => o.Key).Where(k => !GameOptionsSchema.IsKept(k)).Distinct().ToList();

    /// <summary>Sets a row as the game's menu would (set_row): the value inside its range and on its steps (GameOptionRow.Clamp).
    /// A merged row sets its parts (merged_rows.h *_set: one of a pair chosen, the other Off). The Upscaler takes an engine as
    /// upscaler_rows.h step_engine does: the Render resolution's Native (100%) goes with it (the game's own at 100% becomes the
    /// engine's native AA and back), the Render resolution then on the engine's nearest step; an engine's native AA value
    /// (DLAA 2, FSR 4's 5, FSR 3.1's 6) is set as it is. The Render resolution's NativeStep makes the Upscaler its engine's
    /// native AA (the game's own: 100%); another step with a native AA makes it the engine again (step_resolution). A merged
    /// row's part by its own key: in its range. Returns the row's value afterwards. Nothing is written until Save.
    /// (options_version 8: no Quality preset turns back to Custom.)</summary>
    public int Set(string key, int value)
    {
        if (GameOptionsSchema.Part(key) is { } part)
        {
            Put(key, part.AsRead(value));
            return Value(key);
        }
        var row = GameOptionsSchema.Get(key);
        if (row.Merge != null)
        {
            var parts = row.Parts!;
            var split = row.Merge.Split(row.Clamp(value), parts.Select(p => Value(p.Key)).ToArray());
            for (var i = 0; i < parts.Count; i++) Put(parts[i].Key, parts[i].AsRead(split[i]));
            return Get(key);
        }
        const string Up = GameOptionsSchema.UpscalerKey, Res = GameOptionsSchema.ResolutionKey;
        if (key == Up)
        {
            var v = row.Clamp(value);
            var e = GameOptionsSchema.Engine(v);
            if (!GameOptionsSchema.FullScale(v) && e != GameOptionsSchema.Engine(Value(Up)) && GameOptionsSchema.NativeSize(Value(Up), Value(Res)))
            {
                if (e == 0) Put(Res, 1);   // (the game's own at 100%)
                else v = GameOptionsSchema.NativeOf(e);
            }
            else if (!GameOptionsSchema.FullScale(v) && e == GameOptionsSchema.Engine(Value(Up))) v = Value(Up);   // (its engine already: as it is)
            Put(Up, v);
            Put(Res, GameOptionsSchema.SnapResolution(v, Value(Res)));
            return Get(key);
        }
        if (key == Res)
        {
            var up = Value(Up);
            if (value == GameOptionsSchema.NativeStep)
            {
                if (GameOptionsSchema.Engine(up) == 0) Put(Res, 1);
                else Put(Up, GameOptionsSchema.NativeOf(GameOptionsSchema.Engine(up)));
                return Get(key);
            }
            if (GameOptionsSchema.FullScale(up)) Put(Up, GameOptionsSchema.Engine(up));
            Put(Res, row.Clamp(value));
            return Get(key);
        }
        Put(key, row.Clamp(value));
        return Get(key);
    }

    void Put(string key, int v)
    {
        // (what the game reads from the file already: nothing to write. ((Triforce) 11-22) But for the GPU device row's card chosen
        // again while the file has no name for it, or another one (a number saved before 11-20, in Windows' order): its number and
        // name are written, as the game finds the card by the name first; nothing was written before and the number decided)
        if (read[key] == v && !(key == GameOptionsSchema.GpuKey && GpuNameDiffers(v))) set.Remove(key);
        else set[key] = v;
    }

    bool GpuNameDiffers(int v) =>
        GameOptionsSchema.GpuNameOf(v) is { } name && (Raw(GameOptionsSchema.GpuNameKey) ?? "").Trim() != name;

    /// <summary>The benchmark's recommendations (key to value), each with Set's rules, in the order given. KeyNotFoundException,
    /// and nothing set, for a key that is no row (nor a merged row's part). Returns the values afterwards, for the keys given.
    /// Nothing is written until Save.</summary>
    public IReadOnlyDictionary<string, int> Apply(IReadOnlyDictionary<string, int> values)
    {
        foreach (var k in values.Keys) if (GameOptionsSchema.Part(k) == null) GameOptionsSchema.Get(k);
        foreach (var (k, v) in values) Set(k, v);
        return values.Keys.ToDictionary(k => k, Get, StringComparer.Ordinal);
    }
    public IReadOnlyDictionary<string, int> Apply(Dictionary<string, int> values) => Apply((IReadOnlyDictionary<string, int>)values);

    // ---- writing ----

    /// <summary>Writes the launcher's changes into the file as it is NOW on disk (read again here): each changed row's lines
    /// get its value, every other line stays exactly as the file has it (so a line changed outside since Load is kept, as
    /// the game's merge keeps it), a changed row the file has no line for is added before options_version. A file of an
    /// older options_version is brought up to the current one as the game would read it (the values its rules give are
    /// written, options_version=8), so the game does not read the launcher's values by the old rules. The whole file is
    /// written beside it as .new and then put in its place: a reader never meets half a file, and a failure leaves the old
    /// one (IOException). Nothing to write: nothing written. The caller refuses while the game runs (Game.IsRunning).
    /// Afterwards this object holds the file as written.</summary>
    public void Save()
    {
        if (set.Count == 0) return;
        var exists = File.Exists(Path);
        var text = exists ? File.ReadAllText(Path, Encoding.Latin1) : "";
        var disk = SplitLines(text);
        var nl = text.Contains("\r\n") ? "\r\n" : text.Contains('\n') ? "\n" : OperatingSystem.IsWindows() ? "\r\n" : "\n";
        var diskRaw = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var l in disk)
            if (KeyOf(l) is { } k) diskRaw[k] = Trim(l[(k.Length + 1)..]);

        var write = new Dictionary<string, string>(StringComparer.Ordinal);
        var hasVersion = diskRaw.TryGetValue(GameOptionsSchema.VersionKey, out var vs);
        if (exists && (!hasVersion || Atoi(vs!) < GameOptionsSchema.CurrentVersion))
        {
            foreach (var (k, v) in Migrated(diskRaw)) write[k] = v.ToString(CultureInfo.InvariantCulture);
            if (!diskRaw.ContainsKey(GameOptionsSchema.ResolutionKey) && diskRaw.TryGetValue("dynamic_resolution", out var dyn))
                write[GameOptionsSchema.ResolutionKey] = (Atoi(dyn) != 0 ? 0 : 1).ToString(CultureInfo.InvariantCulture);
        }
        foreach (var (k, v) in set) write[k] = v.ToString(CultureInfo.InvariantCulture);
        // ((Triforce) 11-20) the GPU device row's card by its name too: the game finds it by the name first, so the number
        // counted in Windows' order (no triforce_gpus.txt before the game's first run) no longer picks another card. Auto: empty
        if (set.TryGetValue(GameOptionsSchema.GpuKey, out var gpu))
            write[GameOptionsSchema.GpuNameKey] = (GameOptionsSchema.GpuNameOf(gpu) ?? "").Replace('\r', ' ').Replace('\n', ' ');
        var bump = !exists || !hasVersion || Atoi(vs!) < GameOptionsSchema.CurrentVersion;
        if (bump) write[GameOptionsSchema.VersionKey] = GameOptionsSchema.CurrentVersion.ToString(CultureInfo.InvariantCulture);

        var outLines = new List<string>(disk.Count + write.Count);
        var done = new HashSet<string>(StringComparer.Ordinal);
        foreach (var l in disk)
        {
            var k = KeyOf(l);
            if (k != null && write.TryGetValue(k, out var v)) { outLines.Add(k + "=" + v); done.Add(k); }
            else outLines.Add(l);
        }
        var missing = write.Keys.Where(k => !done.Contains(k) && k != GameOptionsSchema.VersionKey)
            .OrderBy(k => GameOptionsSchema.RowOfLine(k) is { } r ? IndexOf(r) : int.MaxValue).Select(k => k + "=" + write[k]).ToList();
        var at = outLines.FindIndex(l => KeyOf(l) == GameOptionsSchema.VersionKey);
        if (at < 0) at = outLines.Count;
        outLines.InsertRange(at, missing);
        if (bump && !done.Contains(GameOptionsSchema.VersionKey))
            outLines.Insert(at + missing.Count, GameOptionsSchema.VersionKey + "=" + GameOptionsSchema.CurrentVersion);

        var sb = new StringBuilder();
        foreach (var l in outLines) sb.Append(l).Append(nl);   // (every line ends, as the game writes them)
        WriteWhole(Path, Encoding.Latin1.GetBytes(sb.ToString()));
        Exists = true;
        Parse(sb.ToString());
        set.Clear();
    }

    static int IndexOf(GameOptionRow r)
    {
        for (var i = 0; i < GameOptionsSchema.All.Count; i++) if (ReferenceEquals(GameOptionsSchema.All[i], r)) return i;
        return int.MaxValue;
    }

    /// <summary>The file's lines without their line ends (\r\n or \n).</summary>
    static List<string> SplitLines(string text)
    {
        var list = new List<string>();
        var start = 0;
        while (start < text.Length)
        {
            var nl = text.IndexOf('\n', start);
            var end = nl < 0 ? text.Length : nl;
            var line = text[start..end];
            if (line.EndsWith('\r')) line = line[..^1];
            list.Add(line);
            start = nl < 0 ? text.Length : nl + 1;
        }
        return list;
    }

    /// <summary>file_whole.h's write_whole: &lt;path&gt;.new written, flushed to the disk and closed, then moved over path;
    /// on any failure the .new is removed, path is as it was, and the IOException goes to the caller.</summary>
    internal static void WriteWhole(string path, byte[] data)
    {
        var part = path + ".new";
        try
        {
            using (var f = new FileStream(part, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                f.Write(data);
                f.Flush(true);
            }
            File.Move(part, path, true);
        }
        catch (Exception)
        {
            try { File.Delete(part); } catch (Exception) { }
            throw;
        }
    }
}
