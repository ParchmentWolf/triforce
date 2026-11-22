using System.Diagnostics;
using System.Text.Json.Nodes;
using Triforce.Logic;
using static Triforce.LogicTests.T;

namespace Triforce.LogicTests;

static partial class Tests
{
    const string TestGame = @"D:\src\triforce-test-game";
    const string Nup = @"D:\NX2navi-dump\The Legend of Zelda Ocarina of Time [0400486024dec000][v131072].nup";

    static void Protocol()
    {
        var t0 = new DateTime(2026, 11, 19, 10, 0, 0, DateTimeKind.Utc);
        var now = t0;
        var tr = new BuildTracker(() => now);
        var changes = new List<string>();
        tr.StageChanged += (was, to) => changes.Add((was ?? "-") + ">" + to);
        var events = new List<BuildEvent>();
        tr.Event += events.Add;
        foreach (var raw in Fakes.Transcript.Split('\n'))
        {
            now = now.AddSeconds(10);
            tr.Feed(raw.TrimEnd('\r').Replace("{OUT}", @"C:\Games\Triforce"));
        }
        tr.End();
        Equal("->read|read>lift|lift>compile|compile>finish|finish>shaders", string.Join("|", changes), "the stages in order");
        Equal<(int, int)?>((12, 579), tr.Plan, "@@plan");
        Equal(2, tr.FilesBuilt, "@@file new + again");
        Equal(300, events.OfType<BuildEvent.Eta>().Single().Seconds, "@@eta");
        Equal<int?>(null, tr.EtaSeconds, "the eta cleared when the compile ended");
        Equal(2460, tr.Times!.TotalSeconds, "@@times total");
        Equal<int?>(2700, tr.Times.PreviousSeconds, "@@times previous");
        Equal(@"C:\Games\Triforce", tr.DoneFolder, "@@done");
        Equal(92.0, tr.ReportedSteps!["read"], "make_game's own step times");
        Equal(77.0, tr.ReportedSteps["finish"], "finish 1:17");
        Equal(40.0, tr.StageSeconds["read"], "read: four lines of 10 s");
        Check(tr.StageSeconds.ContainsKey("shaders"), "the last stage's time at the end");
        Equal(1.0, tr.StageProgress, "shader progress");
        Check(events.OfType<BuildEvent.Plain>().Any(p => p.Line.StartsWith("lift: ")), "plain lines are Plain");
        Equal(new BuildEvent.Check(false, "This is build deadbeef. Triforce supports build e0f3ccfa."),
            BuildProtocol.Parse("@@check bad This is build deadbeef. Triforce supports build e0f3ccfa."), "@@check bad");
        Equal(new BuildEvent.Error("The builder stopped on an error it did not expect: x"), BuildProtocol.Parse("@@error The builder stopped on an error it did not expect: x"), "@@error");
        Equal(new BuildEvent.Times(10, 5, null), BuildProtocol.Parse("@@times 10 5 -1"), "@@times without a previous build");
        Check(BuildProtocol.Parse("the shaders were not prepared now (\"Prepare shaders now\" is unticked): the game prepares them at its first start") is BuildEvent.NotPrepared, "NOT_PREPARED");
        Equal(new BuildEvent.Progress(0.25), BuildProtocol.Parse("@@progress 0.250"), "progress, invariant culture");
        Check(BuildProtocol.Parse("@@progress x") is BuildEvent.Plain, "a bad number is a plain line");
        Equal(3723.0, BuildProtocol.ParseSteps("compile 1:02:03")["compile"], "h:mm:ss");
    }

    static void Estimates()
    {
        var root = NewRoot("estimates");
        var none = BuildEstimator.Estimate(BuildHistory.Load(Path.Combine(root, "nothing")), false, 8, GpuVendor.Nvidia);
        Check(!none.Measured, "no history: a stated range");
        Equal(TimeSpan.FromSeconds(1890), none.Of("compile")!.Low, "compile's share of the 8-thread range");
        Check(none.Text.Contains(" to "), "a range in words: " + none.Text);
        var amd = BuildEstimator.Estimate(BuildHistory.Load(root), false, 16, GpuVendor.Amd);
        Equal(TimeSpan.FromMinutes(120), amd.Of("shaders")!.High, "AMD's shader step up to 2 hours");
        var intel = BuildEstimator.Estimate(BuildHistory.Load(root), false, 12, GpuVendor.Intel);
        Equal(TimeSpan.FromMinutes(240), intel.Of("shaders")!.High, "Intel's shader step up to 4 hours (an A750: 4.3 h on v0.6.0)");
        File.WriteAllText(Path.Combine(root, "build_times.json"), new JsonObject
        {
            ["format"] = 1,
            ["builds"] = new JsonArray(new JsonObject { ["when"] = "2026-11-18 21:00:00", ["kind"] = "build", ["modules"] = 579, ["compiled"] = 579, ["compile_seconds"] = 1800.0, ["total_seconds"] = 2400.0 }),
            ["seconds"] = new JsonObject(),
        }.ToJsonString());
        var h = BuildHistory.Load(root);
        Equal(1, h.Builds.Count, "build_times.json read");
        var est = BuildEstimator.Estimate(h, false, 8, GpuVendor.Nvidia);
        Check(est.Measured, "measured from build_times.json");
        Equal(TimeSpan.FromSeconds(1800), est.Of("compile")!.Low, "the compile's own time");
        Equal(100, (int)Math.Round(est.Of("read")!.Low.TotalSeconds), "the rest split by the stages' weights (600 s * 5/30)");
        BuildHistory.RecordStages(root, "build", new Dictionary<string, double> { ["read"] = 90, ["lift"] = 130, ["compile"] = 1500, ["finish"] = 70, ["shaders"] = 600 });
        var est2 = BuildEstimator.Estimate(BuildHistory.Load(root), false, 8, GpuVendor.Nvidia);
        Equal(TimeSpan.FromSeconds(1500), est2.Of("compile")!.Low, "the stage record wins");
        Equal(TimeSpan.FromSeconds(600), est2.Of("shaders")!.High, "the shader step measured too");
        var upd = BuildEstimator.Estimate(BuildHistory.Load(root), true, 8, GpuVendor.Intel);
        Equal(TimeSpan.FromSeconds(600), upd.Of("shaders")!.High, "an update with no update on record: the build's measured shader step, not the stated range");
        Equal("About 40 minutes", est2.Text, "one time in words");
        var tr = new BuildTracker();
        tr.Feed("@@stage compile Compiling");
        tr.Feed("@@eta 300");
        var left = BuildClock.Remaining(est2, tr);
        Equal(TimeSpan.FromSeconds(300 + 70 + 600), left, "time left: the compile's eta, then finish and shaders");
        Equal("About 16 minutes left", BuildClock.LeftText(left), "in words");
        Equal("Almost done", BuildClock.LeftText(TimeSpan.FromSeconds(20)), "under a minute");
        Equal("1 h 5 min", BuildClock.Span(TimeSpan.FromMinutes(65)), "span");
    }

    static BuildEstimate OneStage(string stage, double low, double high, bool measured) =>
        new(new[] { new StageEstimate(stage, TimeSpan.FromSeconds(low), TimeSpan.FromSeconds(high), measured) }, measured);

    /// <summary>A stage run second by second on a fake clock: progress(t) said as the game says it (each time the tenth of a percent
    /// moves), the shown time left asked each second as the App's tick does. The shown seconds at each second.</summary>
    static double[] RunStage(BuildEstimate est, string stage, Func<double, double> progress, int seconds)
    {
        var t0 = new DateTime(2026, 11, 22, 10, 0, 0, DateTimeKind.Utc);
        var now = t0;
        var tr = new BuildTracker(() => now);
        tr.Feed("@@stage " + stage + " x");
        var shown = new double[seconds + 1];
        var said = 0.0;
        for (var t = 0; t <= seconds; t++)
        {
            now = t0.AddSeconds(t);
            var p = Math.Floor(Math.Clamp(progress(t), 0, 1) * 1000) / 1000;
            if (p > said) { said = p; tr.Feed("@@progress " + p.ToString("0.000", System.Globalization.CultureInfo.InvariantCulture)); }
            shown[t] = BuildClock.Remaining(est, tr).TotalSeconds;
        }
        return shown;
    }

    static void EtaSlowStart()
    {
        // (an Intel-like shader step of an hour: the compute pipelines, the first 14 %, take 52 minutes; the rest 8. The rate since
        // the stage began said 4 hours and more there)
        static double P(double t) => t < 3120 ? 0.14 * t / 3120 : 0.14 + 0.86 * (t - 3120) / 480;
        foreach (var (est, what) in new[] { (OneStage("shaders", 600, 2400, false), "the stated range"), (OneStage("shaders", 3600, 3600, true), "this PC's last time") })
        {
            var shown = RunStage(est, "shaders", P, 3600);
            for (var t = 300; t <= 3600; t++)
            {
                Check(shown[t] < 90 * 60, what + ": no hours after the first minutes (" + BuildClock.LeftText(TimeSpan.FromSeconds(shown[t])) + " at " + t + " s)");
                Check(shown[t] <= shown[t - 1] + 1, what + ": never up by more than a second a second (" + shown[t - 1] + " to " + shown[t] + " at " + t + " s)");
            }
            Check(shown[3540] < 180, what + ": near the end it says so: " + shown[3540]);
        }
        // (this PC's own time knows the hour: it is told within a quarter of an hour all the way)
        var measured = RunStage(OneStage("shaders", 3600, 3600, true), "shaders", P, 3600);
        for (var t = 0; t <= 3600; t += 60) Check(Math.Abs(measured[t] - (3600 - t)) < 15 * 60, "measured: " + measured[t] + " at " + t + " s");
    }

    static void EtaStall()
    {
        // (a 20 minute stage, steady, that sits 10 minutes on one item at 400 s)
        static double P(double t) => t < 400 ? t / 1200 : t < 1000 ? 400.0 / 1200 : (t - 600) / 1200;
        var shown = RunStage(OneStage("shaders", 1200, 1200, true), "shaders", P, 1800);
        var before = shown[400];
        var most = shown.Skip(400).Take(900).Max();
        Check(most - before <= 4 * 60, "the stall and the steps after it add at most 4 minutes: " + before + " to " + most);
        Check(shown.Skip(400).Take(600).Min() >= before - 120, "it holds while nothing moves: " + shown.Skip(400).Take(600).Min());
        Check(Math.Abs(shown[1500] - 300) < 120, "back on time once it moves again: " + shown[1500]);
        Check(shown[1790] < 60, "done at the end: " + shown[1790]);
    }

    static void EtaSteady()
    {
        var shown = RunStage(OneStage("shaders", 1200, 1200, true), "shaders", t => t / 1200, 1200);
        for (var t = 60; t + 60 <= 1200; t += 60)
        {
            var fell = shown[t] - shown[t + 60];
            Check(fell is > 45 and < 75, "a minute a minute (" + fell + " s at " + t + " s)");
            Check(Math.Abs(shown[t] - (1200 - t)) < 60, "on time: " + shown[t] + " at " + t + " s");
        }
        // (slower than the stated range said: the measured rate takes over and it is told right by the middle)
        var slow = RunStage(OneStage("shaders", 600, 2400, false), "shaders", t => t / 2400.0, 2400);
        for (var t = 1200; t <= 2340; t += 60) Check(Math.Abs(slow[t] - (2400 - t)) < 0.2 * (2400 - t) + 60, "slow but steady: " + slow[t] + " at " + t + " s");
        for (var t = 1; t <= 2400; t++) Check(slow[t] <= slow[t - 1] + 0.5, "never up by more than half a second a second at " + t + " s");
    }

    static void EtaOtherStages()
    {
        var est = new BuildEstimate(new[]
        {
            new StageEstimate("read", TimeSpan.FromSeconds(90), TimeSpan.FromSeconds(90), true), new StageEstimate("lift", TimeSpan.FromSeconds(130), TimeSpan.FromSeconds(130), true),
            new StageEstimate("compile", TimeSpan.FromSeconds(1500), TimeSpan.FromSeconds(1500), true), new StageEstimate("finish", TimeSpan.FromSeconds(70), TimeSpan.FromSeconds(70), true),
            new StageEstimate("shaders", TimeSpan.FromSeconds(600), TimeSpan.FromSeconds(600), true),
        }, true);
        var t0 = new DateTime(2026, 11, 22, 10, 0, 0, DateTimeKind.Utc);
        var now = t0;
        var tr = new BuildTracker(() => now);
        Equal(TimeSpan.FromSeconds(2390), BuildClock.Estimated(est, tr), "before the first stage: every stage");
        tr.Feed("@@stage lift Translating");
        now = t0.AddSeconds(30);
        Equal(TimeSpan.FromSeconds(100 + 1500 + 70 + 600), BuildClock.Estimated(est, tr), "no progress: its estimate less its time");
        Equal(TimeSpan.FromSeconds(100 + 1500 + 70 + 600), BuildClock.Remaining(est, tr), "shown as it is");
        now = t0.AddSeconds(40);
        Equal(TimeSpan.FromSeconds(90 + 1500 + 70 + 600), BuildClock.Remaining(est, tr), "and counted down");
        now = t0.AddSeconds(400);
        Equal(TimeSpan.FromSeconds(13 + 0.25 * 270 + 1500 + 70 + 600), BuildClock.Estimated(est, tr), "past its estimate: a tenth of it and a quarter of the time over");
        // (steady progress: by its rate)
        var lift = new BuildTracker(() => now);
        now = t0;
        lift.Feed("@@stage lift Translating");
        for (var t = 1; t <= 65; t++) { now = t0.AddSeconds(t); lift.Feed("@@progress " + (t / 130.0).ToString("0.000", System.Globalization.CultureInfo.InvariantCulture)); }
        Check(Math.Abs(BuildClock.Estimated(est, lift).TotalSeconds - (65 + 1500 + 70 + 600)) < 3, "half way at its pace: " + BuildClock.Estimated(est, lift));
        // (the compile by its @@eta, as before; the eta goes with the stage)
        lift.Feed("@@stage compile Compiling");
        lift.Feed("@@eta 300");
        Equal(TimeSpan.FromSeconds(300 + 70 + 600), BuildClock.Estimated(est, lift), "the compile's eta");
        lift.Feed("@@stage finish Putting");
        Equal(TimeSpan.FromSeconds(70 + 600), BuildClock.Estimated(est, lift), "the eta ends with the compile");
        Equal(1, lift.Recent.Count, "a new stage starts its samples over");
    }

    /// <summary>A test root with fake tools: tools\nx2\make_game.py, and this program as tools\python\python.exe.</summary>
    static TriforceContext FakeTools(string root)
    {
        var ctx = Ctx(root);
        Directory.CreateDirectory(Path.Combine(ctx.ToolsFolder, "nx2"));
        File.WriteAllText(Path.Combine(ctx.ToolsFolder, "nx2", "make_game.py"), "# fake: the test program plays it");
        File.WriteAllText(Path.Combine(ctx.ToolsFolder, "version.txt"), "v9.9.9\n");
        CopySelf(Path.Combine(ctx.ToolsFolder, "python"), "python.exe");
        return ctx;
    }

    static GameSource FakeSource(string root)
    {
        var src = Path.Combine(root, "dump");
        Directory.CreateDirectory(Path.Combine(src, "romfs"));
        Directory.CreateDirectory(Path.Combine(src, "exefs"));
        var main = new byte[0x60];
        "NSO0"u8.CopyTo(main);
        Convert.FromHexString("e0f3ccfaf50065ae").CopyTo(main, 0x40);
        File.WriteAllBytes(Path.Combine(src, "exefs", "main"), main);
        return GameIntake.Normalize(src)!;
    }

    static async Task RunnerDone()
    {
        var root = NewRoot("runner");
        var ctx = FakeTools(root);
        var notes = new List<LauncherNotification>();
        ctx.Platform.NotificationRequested += (_, n) => notes.Add(n);
        var src = FakeSource(root);
        var outDir = Path.Combine(root, "Games", "Triforce");
        var runner = new BuildRunner(ctx);
        var stages = new List<string>();
        runner.StageChanged += (_, to) => stages.Add(to);
        var lines = 0;
        runner.Line += _ => Interlocked.Increment(ref lines);
        var r = await runner.RunAsync(BuildRequest.New(src, outDir, "de"));
        Check(r.Success, "the build ended well: " + r.Failure + " / " + runner.Details);
        Equal(outDir, r.Folder, "@@done's folder");
        Equal("read,lift,compile,finish,shaders", string.Join(",", stages), "stage events");
        Equal(outDir, ctx.Settings.GameFolder, "GameFolder kept");
        Equal(outDir + "|", ctx.Settings.ModsBuilt, "the mods marked as built (none)");
        Check(notes.Count == 1, "a notification for the App");
        var args = File.ReadAllText(Path.Combine(root, "fake-make-game-args.txt")).Split('\n');
        Equal("--romfs|" + src.Romfs + "|--exefs|" + src.Exefs + "|--out|" + outDir + "|--language|de|--fsr|--work|" + Path.Combine(root, "build"), string.Join("|", args), "make_game's arguments");
        Check(File.ReadAllText(Path.Combine(outDir, "triforce_version.txt")).Contains("builder=" + ctx.BuilderExe), "HOOKSHOT_BUILDER_EXE passed");
        Check(File.ReadAllText(runner.LogFile).Contains("@@progress 0.500"), "the log file keeps every line");
        Check(!runner.Details.Contains("@@progress"), "the details leave progress out");
        Check(File.Exists(Path.Combine(ctx.WorkFolder, BuildHistory.StagesFile)), "stage times recorded");
        Equal(2460, r.Times!.TotalSeconds, "times");
        Check(lines > 20, "lines came");
        // (an update of the folder: --update, kind update)
        var u = await new BuildRunner(ctx).RunAsync(BuildRequest.Update(outDir));
        Check(u.Success, "the update ended well: " + u.Failure);
        Equal("--update|" + outDir + "|--fsr|--work|" + Path.Combine(root, "build"), string.Join("|", File.ReadAllText(Path.Combine(root, "fake-make-game-args.txt")).Split('\n')), "update arguments");
        Check(BuildHistory.Load(ctx.WorkFolder).Stages.Any(s => s.Kind == "update"), "an update's times kept as an update's");
        // (DLSS chosen: the licence's flags; the update of a folder built with DLSS keeps it)
        Directory.CreateDirectory(Path.Combine(outDir, "ngx"));
        File.WriteAllText(Path.Combine(outDir, "ngx", "nvngx_dlss.dll"), "");
        Check(new Dlss(ctx).ForBuild(outDir) && ctx.Settings.Dlss, "a folder built with DLSS is updated with it, and the choice kept");
        Check(BuildRunner.Arguments(ctx, BuildRequest.Update(outDir), true).Contains("--accept-nvidia-license"), "the licence flag");
    }

    static async Task RunnerStop()
    {
        var root = NewRoot("runnerstop");
        var ctx = FakeTools(root);
        var runner = new BuildRunner(ctx);
        var reading = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        runner.StageChanged += (_, to) => { if (to == "read") reading.TrySetResult(); };
        var sw = Stopwatch.StartNew();
        var run = runner.RunAsync(BuildRequest.New(FakeSource(root), Path.Combine(root, "Games", "SLOW"), "en-US"));
        await Task.WhenAny(reading.Task, Task.Delay(20000));
        Check(reading.Task.IsCompleted, "the build reached its first stage");
        Check(runner.Running, "running");
        runner.Stop();
        var r = await run;
        Check(r.Cancelled && r.Failure == "cancelled" && !r.Success, "stopped: " + r.Failure);
        Equal("read", r.StoppedAt, "stopped in its first stage");
        Check(sw.Elapsed < TimeSpan.FromSeconds(30), "stopped at once, not after the fake's minute");
        var left = Process.GetProcessesByName("python").Where(p => { try { return p.MainModule!.FileName.StartsWith(root, StringComparison.OrdinalIgnoreCase); } catch (Exception) { return false; } });
        Check(!left.Any(), "no fake make_game left running");
    }

    static async Task RunnerFail()
    {
        var root = NewRoot("runnerfail");
        var ctx = FakeTools(root);
        var runner = new BuildRunner(ctx);
        var r = await runner.RunAsync(BuildRequest.New(FakeSource(root), Path.Combine(root, "Games", "FAIL"), "en-US"));
        Check(!r.Success && !r.Cancelled, "failed");
        Equal("The disk is full.", r.Failure, "@@error's text");
        Equal("compile", r.StoppedAt, "where");
        Check(runner.Details.Contains("clang: error"), "stderr in the details");
        var report = Report.ForBuild(ctx, r, runner.Details, "v9.9.9");
        Check(report.Contains("The build stopped at \"Compiling\"") && report.Contains("---- the build's last lines ----"), "the report");
        var elsewhere = await new BuildRunner(ctx).RunAsync(BuildRequest.New(FakeSource(root), Path.Combine(Path.GetTempPath(), "not-in-root"), "en-US"));
        Equal(ctx.TestOnly, elsewhere.Failure, "a test run builds only inside its root");
        var noTools = await new BuildRunner(Ctx(NewRoot("runner-notools"))).RunAsync(BuildRequest.Update(Path.Combine(root, "x")));
        Check(noTools.Failure!.Contains("tools"), "no tools: said");
    }

    static void GameFolder()
    {
        var ctx = Ctx(NewRoot("game"));
        var game = new Game(ctx);
        Equal(Path.Combine(TestGame, "Triforce.exe"), game.FindExe(TestGame), "Triforce.exe");
        var info = game.Describe(TestGame);
        Equal("v0.1.0", info.Version, "triforce_version.txt");
        Check(info.Kept, "keeps .triforce_exefs and romfs");
        Check(!info.Dlss, "no DLSS");
        Check(info.Language == null || Languages.Find(info.Language) != null, "language.txt");
        Check(!game.IsRunning(TestGame), "not running (test root: only programs inside it count)");
        Equal(null, game.Play(TestGame), "Play refused outside the test root");
        Equal(null, game.FindExe(Path.Combine(TestGame, "romfs")), "no game in romfs");
    }

    static void Intake()
    {
        var root = NewRoot("intake");
        var s = GameIntake.Normalize(TestGame)!;
        Equal(SourceKind.Folders, s.Kind, "a built game folder is a source");
        Equal(Path.Combine(TestGame, ".triforce_exefs"), s.Exefs, "its kept exefs");
        var q = GameIntake.Quick(s);
        Check(q.Ok && q.BuildId!.StartsWith("e0f3ccfa") && q.Final, "the supported build, read without tools: " + q.Text);
        var viaRomfs = GameIntake.Normalize(Path.Combine(TestGame, "romfs"))!;
        Equal(s.Exefs, viaRomfs.Exefs, "the romfs folder finds its exefs");
        var n = GameIntake.Normalize(Nup)!;
        Equal(SourceKind.Nup, n.Kind, ".nup");
        var nq = GameIntake.Quick(n);
        Check(nq.Ok && nq.Titles!.Any(t => t.Id == "0400486024dec000"), "the .nup's header reads: " + nq.Text);
        Check(!nq.Final, "a .nup still needs the tools' check");
        Equal(131072u, nq.Titles![0].Version, "the newest title first (v131072, the file name says)");
        // (NX2navi's packed romfs)
        var navi = Path.Combine(root, "navi");
        Directory.CreateDirectory(Path.Combine(navi, "romfs"));
        Directory.CreateDirectory(Path.Combine(navi, "exefs"));
        File.WriteAllText(Path.Combine(navi, "romfs", "romfs.bin"), "packed");
        File.Copy(Path.Combine(TestGame, ".triforce_exefs", "main"), Path.Combine(navi, "exefs", "main"));
        Equal(GameIntake.PackedRomfs, GameIntake.Quick(GameIntake.Normalize(navi)!).Text, "packed romfs refused");
        // (another build)
        var other = Path.Combine(root, "other");
        Directory.CreateDirectory(Path.Combine(other, "romfs"));
        Directory.CreateDirectory(Path.Combine(other, "exefs"));
        var main = new byte[0x60];
        "NSO0"u8.CopyTo(main);
        Convert.FromHexString("deadbeef").CopyTo(main, 0x40);
        File.WriteAllBytes(Path.Combine(other, "exefs", "main"), main);
        var oq = GameIntake.Quick(GameIntake.Normalize(other)!);
        Equal("This is build deadbeef. Triforce supports build e0f3ccfa.", oq.Text, "the wrong version, in make_game's words");
        Check(GameIntake.IsWrongVersion(oq.Text), "said as the wrong version");
        var half = GameIntake.Normalize(Path.Combine(other, "romfs"))!;
        Check(half.Complete, "romfs with its exefs beside it");
        var lonely = Path.Combine(root, "lonely", "romfs");
        Directory.CreateDirectory(lonely);
        var l = GameIntake.Normalize(lonely)!;
        Equal("exefs", l.Missing, "the exefs is still to be chosen");
        Equal(null, GameIntake.Normalize(Path.Combine(root, "nothing-here")), "nothing");
        var notNup = Path.Combine(root, "x.nup");
        File.WriteAllText(notNup, "not a package at all, longer than the header is......................................................................................................................");
        Check(!GameIntake.Quick(GameIntake.Normalize(notNup)!).Ok, "a file that is no .nup");
        var space = new GameIntake(Ctx(root)).Space(root);
        Check(space.Free > 0 && space.Text.StartsWith("Takes 60 GB while building, about 24 GB after."), space.Text);
    }

    static async Task IntakeCheck()
    {
        var root = NewRoot("intakecheck");
        var noTools = await new GameIntake(Ctx(NewRoot("intake-notools"))).CheckAsync(GameIntake.Normalize(TestGame)!);
        Check(noTools.ToolsMissing && !noTools.Ok, "no tools: said so");
        var ctx = FakeTools(root);
        var r = await new GameIntake(ctx).CheckAsync(GameIntake.Normalize(TestGame)!);
        Check(r.Ok && r.BuildId == "e0f3ccfa", "make_game --check's @@check ok: " + r.Text);
    }
}
