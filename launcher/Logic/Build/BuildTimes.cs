// How long a build takes on this PC (DESIGN 3 rule 4: "a wait never shows without a time": this PC's own last build, or, with
// none, a stated range). make_game.py keeps <work>\build_times.json (format 1: the last 20 builds' totals and compile times,
// each module's seconds; nx2/make_game.py:203-256): read here, never written (make_game rewrites it whole and drops what it
// does not know). The time of each stage is not in it: the launcher keeps its own record beside it, launcher_stages.json,
// from the @@stage lines' times of its builds that ended well (make_game's own "the build's steps:" line when it said one).
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Triforce.Logic;

public sealed record PastBuild(DateTime When, string Kind, int Modules, int Compiled, double CompileSeconds, double TotalSeconds);

public sealed record PastStages(DateTime When, string Kind, IReadOnlyDictionary<string, double> Seconds);

public sealed record StageEstimate(string Stage, TimeSpan Low, TimeSpan High, bool Measured)
{
    public TimeSpan Mid => (Low + High) / 2;
}

public sealed record BuildEstimate(IReadOnlyList<StageEstimate> Stages, bool Measured)
{
    public TimeSpan Low => Stages.Aggregate(TimeSpan.Zero, (a, s) => a + s.Low);
    public TimeSpan High => Stages.Aggregate(TimeSpan.Zero, (a, s) => a + s.High);
    public StageEstimate? Of(string stage) => Stages.FirstOrDefault(s => s.Stage == stage);
    /// <summary>"About 45 minutes" (measured) or "40 to 70 minutes" (a range).</summary>
    public string Text => BuildClock.About(Low, High);
}

public sealed class BuildHistory
{
    public const string TimesFile = "build_times.json", StagesFile = "launcher_stages.json";
    const int Keep = 20;

    public IReadOnlyList<PastBuild> Builds { get; init; } = Array.Empty<PastBuild>();
    public IReadOnlyList<PastStages> Stages { get; init; } = Array.Empty<PastStages>();

    /// <summary>Both records of a work folder; empty ones when missing, half written, or of another format.</summary>
    public static BuildHistory Load(string work)
    {
        var builds = new List<PastBuild>();
        try
        {
            var root = JsonNode.Parse(File.ReadAllText(Path.Combine(work, TimesFile)));
            if (root?["format"]?.GetValue<int>() == 1 && root["builds"] is JsonArray list)
                foreach (var b in list.OfType<JsonObject>())
                {
                    if (b["total_seconds"] is not JsonValue tv || !tv.TryGetValue<double>(out var total)) continue;
                    DateTime.TryParse(b["when"]?.GetValue<string>(), out var when);
                    builds.Add(new PastBuild(when, b["kind"]?.GetValue<string>() ?? "build", Int(b["modules"]), Int(b["compiled"]), Dbl(b["compile_seconds"]), total));
                }
        }
        catch (Exception) { }
        var stages = new List<PastStages>();
        try
        {
            var root = JsonNode.Parse(File.ReadAllText(Path.Combine(work, StagesFile)));
            if (root?["format"]?.GetValue<int>() == 1 && root["builds"] is JsonArray list)
                foreach (var b in list.OfType<JsonObject>())
                {
                    if (b["seconds"] is not JsonObject secs) continue;
                    DateTime.TryParse(b["when"]?.GetValue<string>(), out var when);
                    stages.Add(new PastStages(when, b["kind"]?.GetValue<string>() ?? "build",
                        secs.Where(kv => kv.Value is JsonValue).ToDictionary(kv => kv.Key, kv => Dbl(kv.Value))));
                }
        }
        catch (Exception) { }
        return new BuildHistory { Builds = builds, Stages = stages };
    }

    static int Int(JsonNode? n) { try { return n?.GetValue<int>() ?? 0; } catch (Exception) { try { return (int)(n?.GetValue<double>() ?? 0); } catch (Exception) { return 0; } } }
    static double Dbl(JsonNode? n) { try { return n?.GetValue<double>() ?? 0; } catch (Exception) { try { return n?.GetValue<int>() ?? 0; } catch (Exception) { return 0; } } }

    /// <summary>One build's stage times, kept (the last 20), written whole through a .new file.</summary>
    public static void RecordStages(string work, string kind, IReadOnlyDictionary<string, double> seconds)
    {
        try
        {
            var file = Path.Combine(work, StagesFile);
            JsonArray list = new();
            try
            {
                var old = JsonNode.Parse(File.ReadAllText(file));
                if (old?["format"]?.GetValue<int>() == 1 && old["builds"] is JsonArray l) list = (JsonArray)l.DeepClone();
            }
            catch (Exception) { }
            var secs = new JsonObject();
            foreach (var (k, v) in seconds) secs[k] = Math.Round(v, 1);
            list.Add(new JsonObject { ["when"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), ["kind"] = kind, ["seconds"] = secs });
            while (list.Count > Keep) list.RemoveAt(0);
            Directory.CreateDirectory(work);
            File.WriteAllText(file + ".new", new JsonObject { ["format"] = 1, ["builds"] = list }.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
            File.Move(file + ".new", file, true);
        }
        catch (Exception) { }
    }
}

public static class BuildEstimator
{
    /// <summary>A full build's range (read to finish, without the shaders) by the CPU's threads, for a PC with no build behind it.
    /// A STATED RANGE, not a measurement (DESIGN 3 rule 4): from the "about 45 minutes" the old Setup told everyone, widened by the
    /// CPU. Tune once players' build_times.json are seen.</summary>
    public static (TimeSpan Low, TimeSpan High) FullBuildRange(int threads) => threads switch
    {
        >= 16 => (TimeSpan.FromMinutes(25), TimeSpan.FromMinutes(45)),
        >= 12 => (TimeSpan.FromMinutes(35), TimeSpan.FromMinutes(60)),
        >= 8 => (TimeSpan.FromMinutes(45), TimeSpan.FromMinutes(75)),
        >= 6 => (TimeSpan.FromMinutes(60), TimeSpan.FromMinutes(100)),
        _ => (TimeSpan.FromMinutes(80), TimeSpan.FromMinutes(150)),
    };

    /// <summary>The shader step by the graphics card, stated (research/02 3.2: "an hour or more on AMD GPUs"; DESIGN 6: "1 to 2 hours
    /// on an RX 6800 XT", "About 13 min on an RTX 4070").</summary>
    public static (TimeSpan Low, TimeSpan High) ShaderRange(GpuVendor? gpu) => gpu switch
    {
        GpuVendor.Nvidia => (TimeSpan.FromMinutes(5), TimeSpan.FromMinutes(20)),
        GpuVendor.Amd => (TimeSpan.FromMinutes(30), TimeSpan.FromMinutes(120)),
        // ((Triforce, 11-22) Intel's Arc cards: an A750's preparation took 4.3 h on v0.6.0 (#bug-tracker "Intel Arc A750 current
        // state", 12 threads), an A770's 11 h; with the compute warm cut to the listed programs (RX_VK_WARM_COMPUTES) a
        // re-preparation is over an hour shorter. The 10 to 40 minutes before had the time left show minutes for hours)
        GpuVendor.Intel => (TimeSpan.FromMinutes(60), TimeSpan.FromMinutes(240)),
        _ => (TimeSpan.FromMinutes(10), TimeSpan.FromMinutes(40)),
    };

    /// <summary>Each stage's time for a build (update: --update of a folder, mods rebuilds too). This PC's last build of that kind
    /// (its stage record; else build_times.json's total and compile, the rest split by the stages' weights), else the stated
    /// ranges. shaders: whether the shader step runs (Windows prepares them in every build; Linux unless unticked).</summary>
    public static BuildEstimate Estimate(BuildHistory history, bool update, int threads, GpuVendor? gpu, bool shaders = true)
    {
        var kind = update ? "update" : "build";
        var list = new List<StageEstimate>();
        var stages = history.Stages.LastOrDefault(s => s.Kind == kind) ?? (update ? null : history.Stages.LastOrDefault());
        var past = history.Builds.LastOrDefault(b => b.Kind == kind) ?? (update ? null : history.Builds.LastOrDefault());
        var (low, high) = FullBuildRange(threads);
        if (update) low = TimeSpan.FromMinutes(5);   // (an update compiles what changed; a new translation stamp makes it a whole compile)
        var measured = stages != null || past != null;
        foreach (var st in BuildStages.All)
        {
            if (st.Id == "shaders")
            {
                if (!shaders) continue;
                if (stages != null && stages.Seconds.TryGetValue("shaders", out var ss) && ss > 0) { list.Add(Exact(st.Id, ss)); continue; }
                // ((Triforce, 11-22) an update with no update of its own on record: the shader step this PC measured in its
                // last build of any kind, before the stated range (an update after a full build prepares the same shaders)
                if (history.Stages.LastOrDefault(r => r.Seconds.TryGetValue("shaders", out var any) && any > 0) is { } anyRec)
                {
                    list.Add(Exact(st.Id, anyRec.Seconds["shaders"]));
                    continue;
                }
                var (sl, sh) = ShaderRange(gpu);
                list.Add(new StageEstimate(st.Id, sl, sh, false));
                continue;
            }
            if (stages != null && stages.Seconds.TryGetValue(st.Id, out var s)) { list.Add(Exact(st.Id, s)); continue; }
            if (past != null)
            {
                var rest = Math.Max(0, past.TotalSeconds - past.CompileSeconds);
                var secs = st.Id == "compile" ? past.CompileSeconds : rest * st.Weight / (1 - BuildStages.Find("compile")!.Weight);
                list.Add(Exact(st.Id, secs));
                continue;
            }
            list.Add(new StageEstimate(st.Id, TimeSpan.FromSeconds(Math.Round(low.TotalSeconds * st.Weight)), TimeSpan.FromSeconds(Math.Round(high.TotalSeconds * st.Weight)), false));
        }
        return new BuildEstimate(list, measured);
    }

    static StageEstimate Exact(string id, double seconds) => new(id, TimeSpan.FromSeconds(Math.Round(seconds)), TimeSpan.FromSeconds(Math.Round(seconds)), true);
}

/// <summary>Times in words, and the time left while a build runs.</summary>
public static class BuildClock
{
    /// <summary>The old Shell.cs Span: "1 h 5 min", "12 min", "40 s".</summary>
    public static string Span(TimeSpan t) => t.TotalHours >= 1 ? (int)t.TotalHours + " h " + t.Minutes + " min" : t.TotalMinutes >= 1 ? t.Minutes + " min" : t.Seconds + " s";

    /// <summary>"About 45 minutes" for one time, "40 to 70 minutes" (or "1 to 2 hours") for a range.</summary>
    public static string About(TimeSpan low, TimeSpan high)
    {
        static string M(TimeSpan t) => t.TotalMinutes < 90 ? Math.Max(1, (int)Math.Round(t.TotalMinutes)) + "" : Math.Round(t.TotalHours, 1).ToString(System.Globalization.CultureInfo.InvariantCulture);
        static string Unit(TimeSpan t) => t.TotalMinutes < 90 ? "minutes" : "hours";
        if (Math.Abs((high - low).TotalMinutes) < 2) return "About " + M(high) + " " + Unit(high);
        return Unit(low) == Unit(high) ? M(low) + " to " + M(high) + " " + Unit(high) : M(low) + " " + Unit(low) + " to " + M(high) + " " + Unit(high);
    }

    /// <summary>The time left as shown: Estimated, smoothed. Each call counts the shown time down by the time since the last one and
    /// moves it toward the new estimate: down within seconds (FallSeconds), up slowly (RiseSeconds) and never faster than half a
    /// second a second, so one odd moment never makes it jump. The first call of a build shows the estimate itself. Never below
    /// zero; "Almost done" is the App's words under a minute.</summary>
    public static TimeSpan Remaining(BuildEstimate estimate, BuildTracker tracker)
    {
        var raw = Estimated(estimate, tracker).TotalSeconds;
        lock (tracker.Gate)
        {
            var now = tracker.Now;
            var shown = raw;
            if (tracker.Shown is { } was)
            {
                var dt = Math.Max(0, (now - was.At).TotalSeconds);
                var counted = Math.Max(0, was.Seconds - dt);
                shown = raw < counted ? counted + (raw - counted) * (1 - Math.Exp(-dt / FallSeconds))
                    : Math.Min(counted + (raw - counted) * (1 - Math.Exp(-dt / RiseSeconds)), was.Seconds + MaxRise * dt);
            }
            tracker.Shown = (shown, now);
            return TimeSpan.FromSeconds(Math.Max(0, shown));
        }
    }

    const double FallSeconds = 15, RiseSeconds = 30, MaxRise = 0.5;

    /// <summary>The time left now, unsmoothed: the stages after this one by the estimate, and this one by @@eta (compile), else by
    /// StageLeft. Never below zero.</summary>
    public static TimeSpan Estimated(BuildEstimate estimate, BuildTracker tracker)
    {
        var at = tracker.Stage is { } s ? BuildStages.IndexOf(s) : -1;
        var left = TimeSpan.Zero;
        foreach (var st in estimate.Stages)
            if (BuildStages.IndexOf(st.Stage) > at) left += st.Mid;
        if (at >= 0 && estimate.Of(tracker.Stage!) is { } cur)
        {
            var here = tracker.Stage == "compile" && tracker.EtaSeconds is { } eta ? TimeSpan.FromSeconds(eta)
                : StageLeft(cur.Mid, tracker.Recent, tracker.StageStarted, tracker.Now);
            left += here < TimeSpan.Zero ? TimeSpan.Zero : here;
        }
        return left;
    }

    /// <summary>A stage's time left by its progress. The work per step is uneven (the shader step: on AMD and Intel cards the first
    /// part, the compute pipelines, can be most of its time, an Arc A750 spent 5175 s of 5858 s on them; one slow shader holds it
    /// for minutes), so the rate since the stage began says hours where there is an hour. Instead:
    ///   the rate of the last WindowSeconds of progress, each wait between two steps counted as at most 4 times the usual one (and
    ///   at least half a minute), so one slow item is one step late, not a new pace;
    ///   blended with the estimate's own pace (what it leaves of the stage, at least a tenth of it, and past it a quarter of the
    ///   time over too), trusting the measured rate more as the stage goes (all of it from TrustFrom of the way);
    ///   reckoned at the last step: between steps it counts down for one usual wait, then holds, and after a long stall (2
    ///   minutes, or 4 waits) rises by a quarter of the time.
    /// No progress yet: the estimate less the time run (the same floor).</summary>
    public static TimeSpan StageLeft(TimeSpan expected, IReadOnlyList<(DateTime At, double Progress)> samples, DateTime began, DateTime now)
    {
        var e = expected.TotalSeconds;
        static double Prior(double e, double run) => Math.Max(e - run, 0.1 * e + 0.25 * Math.Max(0, run - e));
        if (samples.Count < 2 || samples[^1].Progress <= 0) return TimeSpan.FromSeconds(Prior(e, Math.Max(0, (now - began).TotalSeconds)));
        var (last, p) = samples[^1];
        if (p >= 1) return TimeSpan.Zero;
        var run = Math.Max(0, (last - began).TotalSeconds);
        var rateHere = (1 - p) / Math.Max(1, Prior(e, run));
        var recent = RecentRate(samples);
        var w = recent == null ? 0 : Math.Clamp(p / TrustFrom, 0, 1);
        var rate = w * (recent?.Rate ?? 0) + (1 - w) * rateHere;
        var atStep = (1 - p) / rate;
        var wait = recent?.Wait ?? 0;
        var stall = Math.Max(0, (now - last).TotalSeconds);
        var left = atStep - Math.Min(stall, wait) + 0.25 * Math.Max(0, stall - Math.Max(120, 4 * wait));
        return TimeSpan.FromSeconds(Math.Max(0, left));
    }

    const double WindowSeconds = 180, TrustFrom = 0.3;

    /// <summary>Progress a second over the last WindowSeconds (each wait capped), and the usual wait between steps (the median of
    /// the last 64); null with no step yet.</summary>
    static (double Rate, double Wait)? RecentRate(IReadOnlyList<(DateTime At, double Progress)> s)
    {
        if (s.Count < 2) return null;
        var waits = new List<double>();
        for (var i = s.Count - 1; i >= 1 && waits.Count < 64; i--) waits.Add((s[i].At - s[i - 1].At).TotalSeconds);
        waits.Sort();
        var usual = waits[waits.Count / 2];
        var cap = Math.Max(30, 4 * usual);
        double span = 0, moved = 0;
        for (var i = s.Count - 1; i >= 1 && span < WindowSeconds; i--)
        {
            span += Math.Min(cap, (s[i].At - s[i - 1].At).TotalSeconds);
            moved += s[i].Progress - s[i - 1].Progress;
        }
        return span <= 0 || moved <= 0 ? null : (moved / span, usual);
    }

    /// <summary>"About 31 minutes left"; "Almost done" under a minute (DESIGN 6 Build).</summary>
    public static string LeftText(TimeSpan left) =>
        left.TotalSeconds < 60 ? "Almost done" : left.TotalMinutes < 90 ? "About " + (int)Math.Round(left.TotalMinutes) + " minutes left" : "About " + (int)left.TotalHours + " h " + left.Minutes + " min left";
}
