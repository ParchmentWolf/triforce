using System.Text.Json.Nodes;
using Triforce.Logic;

namespace Triforce.Launcher;

/// <summary>((Triforce, 11-25) The Play screen's Remastered textures row, under the Evil HD switch: Evil HD's texture pack
/// downloaded into the game folder (Triforce.Logic.TexturePack), stopped and gone on with, or removed. The pack is hosted apart
/// from the release; the game shows it while Evil HD is on, from its next start.</summary>
public sealed partial class Backend
{
    CancellationTokenSource? packCts;
    TexturePackManifest? packManifest;
    string packLine = "";
    double packFrac;

    void RegisterTexturePack()
    {
        OnAsync("texpack", _ => PackAsk());
        OnAsync("texpack.go", m => (string?)m["id"] switch
        {
            "go" => RunPack(),
            "rm" => RemovePack(),
            _ => Task.CompletedTask,
        });
        On("texpackstop", _ => { try { packCts?.Cancel(); } catch { } });
    }

    static string PackGb(long bytes) => (bytes / (double)(1L << 30)).ToString("0.0") + " GB";

    /// <summary>The row's state for the Play screen.</summary>
    JsonObject PackState()
    {
        var g = GameDir;
        if (g == null) return new JsonObject { ["have"] = "nogame" };
        var have = new TexturePack(ctx).Have(g, packManifest);
        return new JsonObject
        {
            ["have"] = have switch { TexturePackHave.Installed => "installed", TexturePackHave.Partial => "partial", _ => "none" },
            ["busy"] = packCts != null, ["frac"] = packFrac, ["line"] = packLine,
            ["size"] = packManifest != null ? PackGb(packManifest.Download) : "18 GB",
        };
    }

    void SendPack() => SendState(new JsonObject { ["texpack"] = PackState() });

    async Task PackAsk()
    {
        var g = GameDir;
        if (g == null) { Toast("Build the game first.", "error"); return; }
        if (packCts != null) return;
        var tp = new TexturePack(ctx);
        try { packManifest = await tp.ManifestAsync(http, CancellationToken.None); }
        catch (Exception e)
        {
            Log.Write("texture pack: no manifest from " + TexturePack.BaseUrl + ": " + e.Message);
            Toast(tp.Have(g) == TexturePackHave.Installed ? "The remastered textures are installed. (The download page could not be reached to check for a newer pack.)"
                : "The remastered textures could not be reached. Check your internet connection and try again.", "error");
            return;
        }
        var m = packManifest;
        var have = tp.Have(g, m);
        SendPack();
        if (have == TexturePackHave.Installed)
        {
            Ask("Remastered textures",
                "<p>Evil HD's remastered textures are installed in your game folder. The game shows them while <b>Evil HD</b> is on.</p>" +
                "<p>Remove them to free " + PackGb(m.Unpacked) + ". You can download them again any time.</p>",
                "texpack.go", new[] { ("no", "Keep them", true), ("rm", "Remove", false) });
            return;
        }
        var left = tp.Remaining(g, m);
        var mins = (int)Math.Ceiling(left / (100e6 / 8) / 60);   // (at 100 Mbit/s)
        Ask("Remastered textures",
            "<p>" + m.Textures.ToString("N0") + " of the game's textures, remastered at twice the detail with their own grain kept. " +
            "The game shows them while <b>Evil HD</b> is on, from its next start.</p>" +
            "<p><b>" + PackGb(left) + " to download</b>" + (have == TexturePackHave.Partial ? " to finish" : "") +
            " (about " + mins + " minutes at 100 Mbit/s), unpacked into your game folder as it comes. " +
            "You can stop any time: it goes on where it stopped.</p>" +
            "<p>They take more video memory: best with a graphics card of 10 GB or more.</p>",
            "texpack.go", new[] { ("no", "Not now", false), ("go", have == TexturePackHave.Partial ? "Continue" : "Download", true) });
    }

    async Task RunPack()
    {
        var g = GameDir;
        if (g == null || packCts != null || packManifest == null) return;
        if (new Game(ctx).IsRunning(g)) { Toast("Close the game first: it reads the textures when it starts.", "error"); return; }
        using var cts = packCts = new CancellationTokenSource();
        packFrac = 0; packLine = "Starting the download";
        SendPack();
        var last = DateTime.MinValue;
        try
        {
            await new TexturePack(ctx).InstallAsync(http, g, packManifest, p =>
            {
                packFrac = p.Fraction; packLine = p.Text;
                if ((DateTime.UtcNow - last).TotalMilliseconds < 500) return;
                last = DateTime.UtcNow;
                SendPack();
            }, cts.Token);
            Toast("<b>&#9670;</b> Remastered textures installed · turn on <b>Evil HD</b> to see them", "success");
            Sfx("success");
        }
        catch (OperationCanceledException) { Toast("Download stopped · it goes on where it stopped next time"); }
        catch (NoRoomException e) { Toast(H(e.Message), "error"); }
        catch (Exception e) { Log.Write("texture pack: " + e); Toast("The textures' download stopped: " + H(e.Message), "error"); }
        finally { packCts = null; packLine = ""; SendPack(); }
    }

    Task RemovePack()
    {
        var g = GameDir;
        if (g == null || packCts != null) return Task.CompletedTask;
        if (new Game(ctx).IsRunning(g)) { Toast("Close the game first.", "error"); return Task.CompletedTask; }
        try { new TexturePack(ctx).Remove(g); Toast("Remastered textures removed"); }
        catch (Exception e) { Log.Write("texture pack: remove: " + e); Toast("Could not remove them: " + H(e.Message), "error"); }
        SendPack();
        return Task.CompletedTask;
    }
}
