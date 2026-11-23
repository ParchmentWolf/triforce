using System.Text.Json.Nodes;
using Triforce.Logic;

namespace Triforce.Launcher;

/// <summary>Settings > Find my best settings. The game runs its own benchmark mode (it loads the newest save by itself, flies
/// through four scenes with its panel on screen, writes its results and quits: Triforce.Logic.Benchmark.RunOnceAsync); the
/// launcher says beforehand what will happen, shows that it is running, then the results and what to change. "Compare with
/// DLSS" (or FSR 3.1) is a second run on request, not a hidden one.</summary>
public sealed partial class Backend
{
    CancellationTokenSource? benchCts;
    BenchRun? benchRun, benchRun2;
    (int upscaler, string name)? benchSecond;
    IReadOnlyList<SettingChange>? benchRecs;
    string? benchLast;

    void RegisterBench()
    {
        On("bench", _ => BenchAsk());
        OnAsync("bench.go", m => (string?)m["id"] switch
        {
            "go" => RunBench(compare: false),
            "helpers" => RunBench(compare: false, helperTest: true),   // ((Triforce) 11-22: with the helper-thread test)
            _ => Task.CompletedTask,
        });
        OnAsync("bench.compare", _ => RunBench(compare: true));
        On("benchstop", _ => { try { benchCts?.Cancel(); } catch { } });
        On("benchapply", _ => ApplyBench());
        new Benchmark(ctx).RestoreIfLeft();   // (a run cut off last time: the player's options back first)
    }

    /// <summary>The benchmark card's state for the Settings page.</summary>
    JsonObject BenchState()
    {
        var g = GameDir;
        var exe = g != null ? new Game(ctx).FindExe(g) : null;
        var ready = exe != null && new Benchmark(ctx).Ready(exe);
        return new JsonObject
        {
            ["available"] = g != null, ["ready"] = ready,
            ["last"] = !ready && g != null ? "Comes with the next update: your game was built before the benchmark existed." : benchLast ?? "Not run yet on this PC",
        };
    }

    void BenchAsk()
    {
        var g = GameDir;
        if (g == null) { Toast("Build the game first.", "error"); return; }
        if (benchCts != null) { Go("brun"); return; }
        var exe = new Game(ctx).FindExe(g);
        if (exe == null || !new Benchmark(ctx).Ready(exe)) { Toast("The benchmark comes with the next update: your game was built before it existed.", "error"); return; }
        Ask("Find my best settings",
            "<p>The game opens full screen, loads your newest save by itself and flies through four places: Hyrule Field, " +
            "Castle Town Market, Kokiri Forest and Lake Hylia. Its own panel shows where it is and the frame rate.</p>" +
            "<p><b>About 2 minutes.</b> Leave the controls alone meanwhile. Esc in the game stops it.</p>" +
            "<p>Your saves are not touched, and your settings are put back as they were. Then this window shows what it found.</p>" +
            "<p><b>With the helper-thread test</b> it measures each place twice, with the replay helper threads off and on, and " +
            "says which your PC runs faster (about 1 minute more).</p>",
            "bench.go", new[] { ("no", "Not now", false), ("helpers", "With the helper-thread test", false), ("go", "Start", true) });
    }

    async Task RunBench(bool compare, bool helperTest = false)
    {
        var g = GameDir;
        if (g == null || benchCts != null) return;
        if (compare && benchRun == null) return;
        using var cts = benchCts = new CancellationTokenSource();
        var pic = new Saves(ctx).Newest(g) is { } newest ? SavePicUrl(newest) : null;
        var bm = new Benchmark(ctx);
        (int, string)? second = null;
        if (compare)
        {
            second = benchSecond ?? bm.SecondPass(g, BenchIni.Read(Path.Combine(g, GameOptionsSchema.FileName)));
            if (second == null) { Toast("You already use an upscaler: there is nothing to compare it with.", "error"); return; }
        }
        var t0 = DateTime.UtcNow;
        void Running(string line) => Send(new JsonObject
        {
            ["t"] = "bench", ["phase"] = "run",
            ["pass"] = compare ? "Comparing with " + second!.Value.Item2 : helperTest ? "Finding your best settings · with the helper-thread test" : "Finding your best settings",
            ["frac"] = Math.Min(0.97, (DateTime.UtcNow - t0).TotalSeconds / (helperTest ? 220 : 150)), ["fps"] = null,
            ["place"] = new JsonObject { ["name"] = "Running in the game window", ["img"] = pic },
            ["line"] = line + " · " + BuildClock.Span(DateTime.UtcNow - t0),
        });
        Running("Starting the game");
        var last = DateTime.MinValue;
        var progress = new Progress<BenchmarkProgress>(p =>
        {
            if ((DateTime.UtcNow - last).TotalMilliseconds < 900) return;
            last = DateTime.UtcNow;
            Running(BenchLine(p.Text));
        });
        try
        {
            var run = await bm.RunOnceAsync(g, second, progress, cts.Token, helperTest);
            if (compare) { benchRun2 = run; benchSecond = second; }
            else { benchRun = run; benchRun2 = null; benchSecond = bm.SecondPass(g, BenchIni.Read(Path.Combine(g, GameOptionsSchema.FileName))); }
            benchLast = "Last run " + DateTime.Now.ToString("d MMM, HH:mm");
            SendBenchResults();
            Sfx("success");
            host.Activate();
        }
        catch (OperationCanceledException) { Send(new JsonObject { ["t"] = "bench", ["phase"] = "stopped" }); Toast("Benchmark stopped · your settings are as they were"); host.Activate(); }
        catch (BenchmarkException e) { Send(new JsonObject { ["t"] = "bench", ["phase"] = "stopped" }); Toast(H(e.Message), "error"); host.Activate(); }
        catch (Exception e) { Log.Write("benchmark: " + e); Send(new JsonObject { ["t"] = "bench", ["phase"] = "stopped" }); Toast("The benchmark stopped: " + H(e.Message), "error"); host.Activate(); }
        finally { benchCts = null; RefreshSettingsState(); }
    }

    /// <summary>The game's progress lines in plain words ("boot", "scene 2/4 Castle Town Market", "teleport ..."): kept short.</summary>
    static string BenchLine(string s)
    {
        if (string.IsNullOrWhiteSpace(s)) return "Starting the game";
        s = s.Trim();
        return s.Length > 70 ? s[..70] + "…" : s;
    }

    void SendBenchResults()
    {
        var g = GameDir;
        if (g == null || benchRun == null) return;
        var now = BenchIni.Read(Path.Combine(g, GameOptionsSchema.FileName));
        var r1 = benchRun; var r2 = benchRun2;
        // ((Triforce) 11-22) after the helper-thread test the other rows are judged by the frame rates of the way it recommends
        var helpers = Benchmark.RecommendHelpers(now, r1.Scenes);
        var p1 = helpers == null ? r1.Scenes : Benchmark.AsRecommended(r1.Scenes, helpers.To);
        var recs0 = Benchmark.Recommend(now, p1, r2?.Scenes, r2 != null ? benchSecond : null, Benchmark.DisplayHz());
        if (helpers != null) recs0.Add(helpers);
        benchRecs = recs0;
        var use2 = r2 != null && benchRecs.Any(c => c.Key == Benchmark.KUpscaler && c.Changes);
        var tested = r2 == null && r1.Scenes.Any(s => s.Helpers != null);   // (the helper-thread test's halves side by side)
        var places = new JsonArray();
        for (var i = 0; i < r1.Scenes.Count; i++)
        {
            var a = r1.Scenes[i];
            var b = r2?.Scenes.ElementAtOrDefault(i);
            var o = new JsonObject
            {
                ["name"] = a.Place, ["fps"] = Math.Round(a.AverageFps), ["low"] = Math.Round(a.OnePercentLow), ["img"] = null,
                ["graph"] = Graph(a.FrameTimes),
            };
            if (b != null) { o["fps2"] = Math.Round(b.AverageFps); o["low2"] = Math.Round(b.OnePercentLow); o["graph2"] = Graph(b.FrameTimes); }
            else if (tested && a.Helpers is { } h)
            {
                o["fps"] = Math.Round(h.OffFps); o["low"] = Math.Round(h.OffLow); o["graph"] = Graph(h.OffTimes);
                o["fps2"] = Math.Round(h.OnFps); o["low2"] = Math.Round(h.OnLow); o["graph2"] = Graph(h.OnTimes);
            }
            places.Add(o);
        }
        var recs = new JsonArray();
        foreach (var c in benchRecs)
            recs.Add(new JsonObject { ["name"] = c.Label, ["from"] = BenchLabel(c.Key, c.From, benchRecs), ["to"] = BenchLabel(c.Key, c.To, benchRecs, true), ["same"] = !c.Changes });
        var gpu = r1.Gpu ?? Gpus.Main()?.Name;
        Send(new JsonObject
        {
            ["t"] = "bench", ["phase"] = "done", ["places"] = places, ["recs"] = recs,
            ["verdict"] = Benchmark.Summary(r1.Scenes, r2?.Scenes, r2 != null ? benchSecond?.name : null) + Benchmark.SkippedNote(r1.Skipped) +
                          Benchmark.HelperNote(r1),
            ["eb"] = "Benchmark finished · " + BuildClock.Span(r1.Took + (r2?.Took ?? TimeSpan.Zero)) + (gpu != null ? " · " + gpu : ""),
            ["compare"] = r2 == null && benchSecond != null ? "Compare with " + benchSecond.Value.name : null,
            ["second"] = r2 != null ? benchSecond?.name : tested ? "Helpers on" : null,
            ["first"] = tested ? "Helpers off" : r1.Scenes.Any(s => s.Helpers != null) ? "Your settings, helpers off" : null,
            ["apply"] = benchRecs.Any(c => c.Changes),
        });
    }

    /// <summary>A scene's frame times as a small graph's points (ms; at most 120).</summary>
    static JsonArray Graph(IReadOnlyList<double> ft)
    {
        var a = new JsonArray();
        if (ft.Count == 0) return a;
        var step = Math.Max(1, ft.Count / 120.0);
        for (double i = 0; i < ft.Count; i += step) a.Add(Math.Round(ft[(int)i], 2));
        return a;
    }

    void ApplyBench()
    {
        var g = GameDir;
        if (g == null || benchRecs == null) { Go("settings"); return; }
        if (new Game(ctx).IsRunning(g)) { Toast("Close the game first: it keeps its own settings while it runs.", "error"); return; }
        new Benchmark(ctx).Apply(g, benchRecs);
        Log.Write("benchmark: applied " + string.Join(", ", benchRecs.Where(c => c.Changes).Select(c => c.Key + "=" + c.To)));
        benchLast = (benchLast ?? "Last run") + " · applied";
        RefreshSettingsState();
        Go("settings");
        Toast("<b>&#9670;</b> Applied · the game uses them the next time you play", "success");
    }

    void RefreshSettingsState()
    {
        var s = new JsonObject();
        AddSettingsState(s);
        SendState(s);
    }

    /// <summary>The menu's own words for the values the benchmark touches (Triforce.Logic.GameOptionsSchema).</summary>
    static string BenchLabel(string key, int v, IReadOnlyList<SettingChange> all, bool after = false)
    {
        if (key == Benchmark.KHelpers)   // ((Triforce) 11-22: the Debug tab's row, not one of the schema's; gpu/vk/vk_menu.cpp tx_replay_threads)
            return v == Benchmark.HelpersOff ? "Off" : v is >= 1 and <= 7 ? $"Auto, {v + 1} threads" : "Automatic";
        if (GameOptionsSchema.ByKey(key) is not { } row) return GameOptionsSchema.Part(key)?.Label(v) ?? v.ToString();   // ((Triforce, options_version 8) a merged row's part: Steady frame rate, Frame generation)
        if (key == Benchmark.KResolution)
        {
            // (its label follows the Upscaler: "Quality (67%)" with DLSS / FSR, "67%" without)
            var up = all.FirstOrDefault(c => c.Key == Benchmark.KUpscaler) is { } u ? (after ? u.To : u.From) : 0;
            return row.Label(v, new OneValue(Benchmark.KUpscaler, up));
        }
        return row.Label(v);
    }

    sealed class OneValue(string key, int value) : IGameOptionValues
    {
        public int Get(string k) => k == key ? value : GameOptionsSchema.ByKey(k)?.Default ?? 0;
        public string? Raw(string k) => k == key ? value.ToString() : null;
    }
}
