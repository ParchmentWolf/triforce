using System.Text;
using System.Text.RegularExpressions;

namespace Triforce.Logic;

/// <summary>What a player copies after a build that stopped, to paste where they ask for help: what the launcher knows of the
/// build, the build's last lines and setup.log's. The folder of the player's account, which carries their name and is in most
/// paths of a log, reads %USERPROFILE% in it (old Guard.cs Report).</summary>
public static class Report
{
    /// <summary>How many of its last lines each log gives.</summary>
    public const int Lines = 200;

    /// <summary>The last lines of a text, at most so many, without the empty ones at its end.</summary>
    public static string Tail(string text, int lines)
    {
        var all = text.Replace("\r", "").TrimEnd('\n', ' ').Split('\n');
        return string.Join(Environment.NewLine, all.Skip(Math.Max(0, all.Length - lines)));
    }

    /// <summary>The text with each of the folders (the account's own, and its short name) read as %USERPROFILE%: in any case of
    /// its letters, with either slash or doubled ones between its parts, as a build's tools print paths. A folder that only
    /// begins with the same letters (C:\Users\Ann and C:\Users\Anna) is another one and stays.</summary>
    public static string NoName(string text, params string?[] folders)
    {
        foreach (var folder in folders.Where(f => !string.IsNullOrWhiteSpace(f)).OrderByDescending(f => f!.Length))
        {
            var parts = folder!.Split(new[] { '\\', '/' }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 2) continue;   // (a whole drive is nobody's name)
            var pattern = (folder.StartsWith("\\") || folder.StartsWith("/") ? @"[\\/]+" : "") + string.Join(@"[\\/]+", parts.Select(Regex.Escape)) + @"(?![\p{L}\p{N}])";
            text = Regex.Replace(text, pattern, "%USERPROFILE%", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        }
        return text;
    }

    /// <summary>The report: what the launcher knows, then the last lines of what the build said and of setup.log.</summary>
    public static string Compose(IEnumerable<string> known, string build, string log, params string?[] folders)
    {
        var s = new StringBuilder();
        foreach (var line in known) s.AppendLine(line);
        s.AppendLine().AppendLine("---- the build's last lines ----").AppendLine(Tail(build, Lines));
        s.AppendLine().AppendLine("---- setup.log's last lines ----").AppendLine(Tail(log, Lines));
        return NoName(s.ToString(), folders);
    }

    /// <summary>((Triforce) 11-24) The PC as a problem report asks for it, beside the OS: the CPU's threads and the RAM, what a
    /// build's compile needs most of.</summary>
    public static string Pc()
    {
        var ram = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
        return "PC: " + Environment.ProcessorCount + " threads" + (ram > 0 ? ", " + ((ram + (1L << 29)) >> 30) + " GB of RAM" : "");
    }

    /// <summary>((Triforce) 11-24) The switches set in the launcher's environment that the build and the game read (RX_, HOS_,
    /// HOOKSHOT_, TRIFORCE_), by their names alone: a value can be a path or something private, and is never in a report.</summary>
    public static string Switches(IEnumerable<string> names)
    {
        var set = names.Where(n => new[] { "RX_", "HOS_", "HOOKSHOT_", "TRIFORCE_" }.Any(p => n.Length > p.Length && n.StartsWith(p, StringComparison.Ordinal)))
                       .Distinct().OrderBy(n => n, StringComparer.Ordinal).ToList();
        return "Switches set: " + (set.Count == 0 ? "none" : string.Join(", ", set) + " (their values are left out)");
    }

    /// <summary>The report for a build that stopped (old Shell.cs CopyTheReport): the launcher's and tools' versions, the OS, the
    /// step it stopped at, why, the command, the game folder and the install with their free space, the PC and the switches
    /// set, then the logs.</summary>
    public static string ForBuild(TriforceContext ctx, BuildResult? result, string buildLines, string? toolsVersion, string? failure = null)
    {
        string Room(string folder) => ctx.FreeBytes(folder) is { } free ? " (" + ctx.Platform.Disk(folder) + " has " + (free >> 30) + " GB free)" : "";
        var step = result?.StoppedAt is { } s && BuildStages.Find(s) is { } st ? "\"" + st.Text + "\"" : "its start";
        var known = new[]
        {
            "Triforce " + BuildInfo.Version + ", tools " + (toolsVersion ?? "none") + ", " + Environment.OSVersion.VersionString,
            result == null && failure != null
                ? "It stopped before the build itself: " + failure
                : "The build stopped at " + step + " after " + BuildClock.Span(result?.Elapsed ?? TimeSpan.Zero) + ": " + (result?.Failure ?? failure ?? "no reason given"),
            result?.CommandLine ?? "",
            "Game folder: " + (result?.OutFolder ?? "") + (result?.OutFolder is { } o ? Room(o) : ""),
            "Launcher: " + ctx.Home + Room(ctx.Home),
            Pc(),
            Switches(Environment.GetEnvironmentVariables().Keys.Cast<object>().Select(k => k.ToString() ?? "")),
        };
        var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        string? shortName = null;
        if (OperatingSystem.IsWindows()) shortName = WindowsPlatform.ShortName(profile);
        return Compose(known, buildLines, ctx.Log.ReadAll(), profile, shortName);
    }
}
