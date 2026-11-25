using System.Security.Cryptography;
using System.Text;
using Triforce.Logic;
using static Triforce.LogicTests.T;

namespace Triforce.LogicTests;

static partial class Tests
{
    // ((Triforce, 11-25) Evil HD's texture pack: the launcher's download into the game folder (Logic/TexturePack.cs))
    static string PackManifest(string id, params (string Name, byte[] Zip, int Files)[] parts)
    {
        var ps = string.Join(",", parts.Select(p => "{\"name\":\"" + p.Name + "\",\"size\":" + p.Zip.Length + ",\"sha256\":\"" +
            Convert.ToHexStringLower(SHA256.HashData(p.Zip)) + "\",\"files\":" + p.Files + ",\"unpacked\":" + p.Zip.Length + "}"));
        return "{\"id\":\"" + id + "\",\"textures\":3,\"files\":4,\"unpacked\":100,\"download\":" + parts.Sum(p => p.Zip.Length) + ",\"parts\":[" + ps + "]}";
    }

    static async Task TexturePackInstall()
    {
        using var s = new FakeServer();
        var root = NewRoot("texpack");
        var ctx = Ctx(root);
        var game = Path.Combine(root, "game");
        Directory.CreateDirectory(game);
        var p1 = Zip(("00000000000000a1.png", "one"), ("00000000000000a1_m1.png", "one-1"));
        var p2 = Zip(("00000000000000b2.png", "two"));
        var p3 = Zip(("00000000000000c3.png", "three"));
        var json = PackManifest("pack-1", ("pack-1-01.zip", p1, 2), ("pack-1-02.zip", p2, 1), ("pack-1-03.zip", p3, 1));
        s.Add("/manifest.json", json);
        s.Add("/pack-1-01.zip", p1);
        s.Add("/pack-1-03.zip", p3);   // (part 2 not there yet: the install stops at it)
        var before = Environment.GetEnvironmentVariable("TRIFORCE_TEXPACK_URL");
        Environment.SetEnvironmentVariable("TRIFORCE_TEXPACK_URL", s.Url);
        try
        {
            using var http = Downloader.CreateHttp();
            var tp = new TexturePack(ctx);
            Equal(TexturePackHave.None, tp.Have(game), "nothing yet");
            var m = await tp.ManifestAsync(http, CancellationToken.None);
            Equal(3, m.Parts.Count, "the manifest's parts");
            Equal(p1.Length + p2.Length + p3.Length, (int)tp.Remaining(game, m), "all of it to download");
            var failed = false;
            try { await tp.InstallAsync(http, game, m, null, CancellationToken.None); } catch (HttpRequestException) { failed = true; }
            Check(failed, "a missing part stops the install");
            Equal(TexturePackHave.Partial, tp.Have(game, m), "part 1 in: partial");
            Equal("one", File.ReadAllText(Path.Combine(TexturePack.Folder(game), "00000000000000a1.png")), "part 1's pictures unpacked");
            Check(!File.Exists(Path.Combine(ctx.DownloadsFolder, "texpack", "pack-1-01.zip")), "a part's zip goes once it is unpacked");
            // (the part comes: the install goes on from it, part 1 not fetched again)
            s.Add("/pack-1-02.zip", p2);
            var asked = s.Seen.Count(x => x.Contains("pack-1-01.zip"));
            var seen = new List<TexturePackProgress>();
            await tp.InstallAsync(http, game, m, seen.Add, CancellationToken.None);
            Equal(asked, s.Seen.Count(x => x.Contains("pack-1-01.zip")), "part 1 not downloaded again");
            Equal(TexturePackHave.Installed, tp.Have(game, m), "every part in: installed");
            Equal("three", File.ReadAllText(Path.Combine(TexturePack.Folder(game), "00000000000000c3.png")), "the last part's pictures");
            Check(seen.Count > 0 && seen[^1].Fraction == 1, "progress ends at 1");
            Check(!Directory.EnumerateFiles(TexturePack.Folder(game), "*.new").Any(), "no half-written picture left");

            // (a part whose bytes are not the manifest's: refused, its zip deleted, the folder left as it was)
            var game2 = Path.Combine(root, "game2");
            Directory.CreateDirectory(game2);
            var good = Zip(("00000000000000d4.png", "four"));
            var bad = PackManifest("pack-2", ("pack-2-01.zip", good, 1));
            var hurt = (byte[])good.Clone();
            hurt[hurt.Length / 2] ^= 0x5a;   // (the same size, one byte changed: only the hash tells)
            s.Add("/pack-2-01.zip", hurt);
            var m2 = TexturePack.Parse(bad);
            Throws<InvalidDataException>(() => tp.InstallAsync(http, game2, m2, null, CancellationToken.None).GetAwaiter().GetResult(), "a wrong hash");
            Check(!File.Exists(Path.Combine(ctx.DownloadsFolder, "texpack", "pack-2-01.zip")), "the bad part is deleted, to be fetched anew");
            Check(!File.Exists(Path.Combine(TexturePack.Folder(game2), "00000000000000d4.png")), "nothing unpacked from it");

            // (a zip with a name a pack has not: nothing is written outside the folder)
            var game3 = Path.Combine(root, "game3");
            Directory.CreateDirectory(game3);
            var evil = Zip(("../escape.png", "x"));
            s.Add("/pack-3-01.zip", evil);
            var m3 = TexturePack.Parse(PackManifest("pack-3", ("pack-3-01.zip", evil, 1)));
            Throws<InvalidDataException>(() => tp.InstallAsync(http, game3, m3, null, CancellationToken.None).GetAwaiter().GetResult(), "a file a pack does not have");
            Check(!File.Exists(Path.Combine(game3, "escape.png")), "nothing escapes the folder");

            // (another pack in the folder is replaced; Remove takes the folder away)
            await tp.InstallAsync(http, game, TexturePack.Parse(PackManifest("pack-4", ("pack-1-03.zip", p3, 1))), null, CancellationToken.None);
            Check(!File.Exists(Path.Combine(TexturePack.Folder(game), "00000000000000a1.png")), "the older pack's pictures go");
            Equal(TexturePackHave.Installed, tp.Have(game), "the new pack installed");
            tp.Remove(game);
            Equal(TexturePackHave.None, tp.Have(game), "removed");
            Throws<FormatException>(() => TexturePack.Parse("{\"id\":\"x\",\"parts\":[]}"), "a manifest with no parts");
            Throws<FormatException>(() => TexturePack.Parse("{\"id\":\"x\",\"parts\":[{\"name\":\"../a.zip\",\"size\":1,\"sha256\":\"" + new string('0', 64) + "\"}]}"), "a part named outside");
        }
        finally { Environment.SetEnvironmentVariable("TRIFORCE_TEXPACK_URL", before); }
    }

    /// <summary>The real pack end to end, only with TEXPACK_E2E=&lt;its address&gt; (and TEXPACK_E2E_REF=&lt;a pack folder&gt; to compare a
    /// sample with): installed into a test game folder, every file there, the sample's bytes the same. Skipped otherwise.</summary>
    static async Task TexturePackRealPack()
    {
        var url = Environment.GetEnvironmentVariable("TEXPACK_E2E");
        if (string.IsNullOrEmpty(url)) { Console.WriteLine("      (skipped: TEXPACK_E2E not set)"); return; }
        var root = NewRoot("texpack-e2e");
        var ctx = Ctx(root);
        var game = Path.Combine(root, "game");
        Directory.CreateDirectory(game);
        var before = Environment.GetEnvironmentVariable("TRIFORCE_TEXPACK_URL");
        Environment.SetEnvironmentVariable("TRIFORCE_TEXPACK_URL", url);
        try
        {
            using var http = Downloader.CreateHttp();
            var tp = new TexturePack(ctx);
            var m = await tp.ManifestAsync(http, CancellationToken.None);
            var t0 = DateTime.UtcNow;
            var lastPart = 0;
            await tp.InstallAsync(http, game, m, p => { if (p.Part != lastPart) { lastPart = p.Part; Console.WriteLine("      " + p.Text + " (" + (int)(p.Fraction * 100) + "%)"); } }, CancellationToken.None);
            Console.WriteLine("      installed in " + (int)(DateTime.UtcNow - t0).TotalSeconds + " s");
            var files = Directory.GetFiles(TexturePack.Folder(game), "*.png");
            Equal(m.Files, files.Length, "every picture of the pack");
            Equal(TexturePackHave.Installed, tp.Have(game, m), "installed");
            var reference = Environment.GetEnvironmentVariable("TEXPACK_E2E_REF");
            if (!string.IsNullOrEmpty(reference))
                foreach (var f in files.Where((_, i) => i % 997 == 0))
                    Check(File.ReadAllBytes(f).AsSpan().SequenceEqual(File.ReadAllBytes(Path.Combine(reference, Path.GetFileName(f)))), Path.GetFileName(f) + ": the same bytes");
        }
        finally
        {
            Environment.SetEnvironmentVariable("TRIFORCE_TEXPACK_URL", before);
            try { Directory.Delete(root, true); } catch (Exception) { }
        }
    }
}