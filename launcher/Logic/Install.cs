// A per-user install, as the old Setup made it (research/02 1.1-1.5): the exe copied into %LOCALAPPDATA%\Programs\Triforce,
// the Apps-list entry under HKCU, the shortcuts; and the uninstall that takes it away again (game folders and saves stay).
using System.Diagnostics;

namespace Triforce.Logic;

public sealed class Installer
{
    readonly TriforceContext ctx;
    public Installer(TriforceContext ctx) { this.ctx = ctx; }

    /// <summary>The folder an install goes to when the player changes nothing.</summary>
    public string DefaultDir => ctx.Platform.DefaultInstallDir;

    /// <summary>The line under the install folder (old Shell.cs InstallSpaceText): "about 2 GB", red at 3 GiB free or less.</summary>
    public (string Text, bool Low) SpaceLine(string dir)
    {
        try
        {
            var disk = ctx.Platform.Disk(dir);
            if (ctx.FreeBytes(dir) is not { } free) return ("Triforce and its tools take about 2 GB.", false);
            return ("Triforce and its tools take about 2 GB. " + disk + " has " + (free >> 30) + " GB free.", free <= (3L << 30));
        }
        catch (Exception) { return ("Triforce and its tools take about 2 GB.", false); }
    }

    /// <summary>Copies this exe into the folder, registers it in the Apps list and makes the shortcuts. Returns the installed exe.
    /// ("Triforce" opens the launcher, not the game: every start goes through the update question first, then Play.)</summary>
    public string Run(string dir, bool desktop, bool startMenu)
    {
        dir = Path.GetFullPath(dir);
        ctx.Require(dir);
        Directory.CreateDirectory(dir);
        var exe = Path.Combine(dir, BuildInfo.SetupAsset);
        if (ctx.IsWindows)
        {
            // ((Triforce) through <exe>.partial, renamed into place once complete: a copy cut off in the middle left a Setup that
            // does not start under the name every shortcut starts. Partial)
            if (!TriforceContext.SamePath(exe, ctx.SelfPath)) new Partial(ctx.Platform).CopyFile(ctx.SelfPath, exe);
            var s = ctx.Platform.Settings;
            if (!ctx.NoWrites)
            {
                s.SetUninstall("DisplayName", BuildInfo.AppName);
                s.SetUninstall("DisplayIcon", exe + ",0");
                s.SetUninstall("DisplayVersion", BuildInfo.Version);
                s.SetUninstall("Publisher", "Triforce");
                s.SetUninstall("InstallLocation", dir);
                s.SetUninstall("UninstallString", "\"" + exe + "\" --uninstall");
                s.SetUninstall("QuietUninstallString", "\"" + exe + "\" --uninstall --quiet");
                s.SetUninstall("URLInfoAbout", BuildInfo.Home);
                s.SetUninstallNumber("NoModify", 1);
                s.SetUninstallNumber("NoRepair", 1);
            }
        }
        else exe = ctx.Env("APPIMAGE") ?? ctx.SelfPath;   // (Linux: the AppImage stays where the player keeps it; only the menu entries are made)
        ctx.Settings.Desktop = desktop;
        ctx.Settings.StartMenu = startMenu;
        try
        {
            var link = new Shortcut(exe, "", ctx.IsWindows ? dir : Path.GetDirectoryName(exe)!, exe, "Play Triforce");
            if (startMenu) ctx.Platform.CreateShortcut(ShortcutPlace.StartMenu, link);
            if (desktop) ctx.Platform.CreateShortcut(ShortcutPlace.Desktop, link);
        }
        catch (Exception e) { ctx.Log.Write("shortcuts: " + e.Message); }
        ctx.Log.Write("installed " + BuildInfo.Version + " to " + dir);
        return exe;
    }

    /// <summary>Starts a launcher exe with arguments (each one as is; quoted by .NET with the MSVC rules), in its own folder.</summary>
    public static Process? Start(string exe, IEnumerable<string> args)
    {
        var si = new ProcessStartInfo(exe) { UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(exe)! };
        foreach (var a in args) si.ArgumentList.Add(a);
        return Process.Start(si);
    }
}

/// <summary>What an uninstall removes and what it keeps, said before it is done (DESIGN 6 Settings: "says what goes and what stays").</summary>
public sealed record UninstallPlan(IReadOnlyList<string> Removes, IReadOnlyList<string> Keeps);

/// <summary>Removes the launcher, its tools and the shortcuts (old Setup.cs Install.Uninstall). Game folders and saves are the
/// player's and stay. The question ("Remove Triforce and its tools from this PC?") is the App's; --quiet asks nothing.</summary>
public sealed class Uninstaller
{
    readonly TriforceContext ctx;
    public Uninstaller(TriforceContext ctx) { this.ctx = ctx; }

    // ((Triforce, 11-21, ticket "Downloads folder got deleted while uninstalling the Triforce launcher") The uninstall took its
    // folder away whole (rmdir /s), and that folder was the install folder or, for a Setup never installed, the folder it ran
    // from: a TriforceSetup.exe run from Downloads took the player's whole Downloads folder with it. Now only the launcher's own
    // entries go (OwnFiles, and OwnFolders where the folder is the launcher's alone: Dedicated), then the folder itself only
    // if nothing else is left in it (rmdir without /s), and a Setup that is not the installed one removes nothing of its folder.

    /// <summary>The launcher's own files in its folder (del patterns): its exe, the copies an update or a handover leaves
    /// (TriforceSetup.old.exe, TriforceSetup.exe.partial), and its log.</summary>
    public static readonly string[] OwnFiles = { "TriforceSetup*.exe", "TriforceSetup*.exe.*", "setup.log", "setup.log.*" };
    /// <summary>The folders it makes there (TriforceContext ToolsFolder, DownloadsFolder, NgxSdkFolder); save-backups stays (saves).</summary>
    public static readonly string[] OwnFolders = { "tools", "downloads", "ngx-sdk" };

    /// <summary>Is dir a folder of the launcher's alone, where its folders' names (downloads, tools) can only be its own? The
    /// default install folder, or one named Triforce that is not a drive's root, the account's folder or one above it, nor one
    /// of the account's known folders. Elsewhere (a player who installed into Downloads, D:\Games or their own folder) its
    /// folders' names may be the player's: only its files go there.</summary>
    public static bool Dedicated(string dir, string defaultDir, IEnumerable<string> known)
    {
        try
        {
            var full = Path.GetFullPath(dir).TrimEnd('\\', '/');
            if (TriforceContext.SamePath(full, defaultDir)) return true;
            if (Path.GetPathRoot(full) is { } root && TriforceContext.SamePath(full, root)) return false;
            foreach (var k in known)
                if (!string.IsNullOrEmpty(k) && (TriforceContext.SamePath(full, k) || TriforceContext.Inside(full, k))) return false;
            return string.Equals(Path.GetFileName(full), "Triforce", StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception) { return false; }
    }

    /// <summary>The account's folders an install folder must never be (nor hold): its own, Desktop, Documents, Downloads and the
    /// other known ones, AppData's roots, Program Files.</summary>
    public static IEnumerable<string> KnownFolders()
    {
        var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        foreach (var f in new[] { Environment.SpecialFolder.UserProfile, Environment.SpecialFolder.DesktopDirectory, Environment.SpecialFolder.MyDocuments,
                     Environment.SpecialFolder.MyMusic, Environment.SpecialFolder.MyPictures, Environment.SpecialFolder.MyVideos,
                     Environment.SpecialFolder.ApplicationData, Environment.SpecialFolder.LocalApplicationData, Environment.SpecialFolder.ProgramFiles,
                     Environment.SpecialFolder.ProgramFilesX86, Environment.SpecialFolder.Windows })
            yield return Environment.GetFolderPath(f);
        if (!string.IsNullOrEmpty(profile))
        {
            yield return Path.Combine(profile, "Downloads");
            yield return Path.Combine(profile, "OneDrive");
        }
    }

    /// <summary>The short-lived cmd's line that removes the launcher from dir once this process is gone: its files, its folders
    /// where dir is Dedicated, then dir itself only when empty.</summary>
    public static string RemoveCommand(string dir, bool dedicated)
    {
        var d = Path.GetFullPath(dir).TrimEnd('\\', '/');
        var line = "/c timeout /t 2 /nobreak >nul";
        foreach (var f in OwnFiles) line += " & del /f /q \"" + Path.Combine(d, f) + "\" 2>nul";
        if (dedicated)
            foreach (var f in OwnFolders) line += " & rmdir /s /q \"" + Path.Combine(d, f) + "\" 2>nul";
        return line + " & rmdir \"" + d + "\" 2>nul";
    }

    public UninstallPlan Describe()
    {
        var dir = ctx.InstalledDir;
        var removes = new List<string>
        {
            dir != null ? "Triforce and its tools (" + dir + ")" : "Triforce's settings and Apps-list entry",
            "the shortcuts",
            "the build's work folder and compile cache (" + ctx.WorkFolder + ", made again by a build)",
            "the launcher's settings",
        };
        if (!ctx.IsWindows) removes[0] = "the launcher's updates and NVIDIA's SDK (" + ctx.Platform.DefaultInstallDir + ")";
        var keeps = new List<string> { "your game folders" + (ctx.Settings.GameFolder is { } g ? " (" + g + ")" : ""), "your saves" };
        if (ctx.IsWindows && dir == null) keeps.Add("this Setup file and everything beside it (" + ctx.SelfDir + "): delete the file yourself");
        else if (ctx.IsWindows && dir != null && !Dedicated(dir, ctx.Platform.DefaultInstallDir, KnownFolders()))
            keeps.Add("everything in " + dir + " that is not Triforce's own files");
        return new UninstallPlan(removes, keeps);
    }

    /// <summary>Does it. The launcher's own files go once this process is gone (Windows: a short-lived cmd waits 2 s, then
    /// removes them: RemoveCommand; Linux: removed now, a running binary can be unlinked).</summary>
    public void Run()
    {
        // (the installed launcher's folder only: never the folder a Setup that is not installed runs from, Downloads)
        var dir = ctx.IsWindows ? ctx.InstalledDir : ctx.Home;
        ctx.Log.Write("uninstall: " + (dir ?? "(not installed: nothing removed from " + ctx.SelfDir + ")"));
        ctx.Platform.RemoveShortcuts();
        // (the build's work folder and compile cache, nx2/make_game.py --work: several GB, made again by a build)
        var work = ctx.WorkFolder;
        try { if (Directory.Exists(work) && ctx.Allowed(work)) Directory.Delete(work, true); } catch (Exception) { }
        ctx.Platform.Settings.RemoveUninstall();
        ctx.Platform.Settings.RemoveAll();
        if (ctx.IsWindows)
        {
            // (this exe is running from the folder: a short-lived cmd removes it once we are gone)
            if (dir != null && File.Exists(Path.Combine(dir, BuildInfo.SetupAsset)) && ctx.Allowed(dir))
            {
                var dedicated = Dedicated(dir, ctx.Platform.DefaultInstallDir, ctx.TestRoot != null ? Array.Empty<string>() : KnownFolders());
                ctx.Log.Write("uninstall: " + (dedicated ? "its files and folders" : "its files alone (the folder is not Triforce's alone)"));
                Process.Start(new ProcessStartInfo("cmd.exe", RemoveCommand(dir, dedicated))
                    { CreateNoWindow = true, UseShellExecute = false, WorkingDirectory = Path.GetTempPath() })?.Dispose();
            }
        }
        else
        {
            var root = ctx.Platform.DefaultInstallDir;
            try { if (Directory.Exists(root) && ctx.Allowed(root)) Directory.Delete(root, true); } catch (Exception) { }
        }
    }
}
