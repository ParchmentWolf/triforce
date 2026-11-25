using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace Triforce.Logic;

/// <summary>((Triforce, 11-25) Evil HD's texture pack: one part of the download (an uncompressed zip of whole textures).</summary>
public sealed record TexturePackPart(string Name, long Size, string Sha256, int Files, long Unpacked);

/// <summary>The pack's manifest (manifest.json beside its parts, made by the release's pack_textures.ps1).</summary>
public sealed record TexturePackManifest(string Id, int Textures, int Files, long Unpacked, long Download, IReadOnlyList<TexturePackPart> Parts);

/// <summary>How far an install is: the part (1-based) of how many, that part's download 0..1, the whole install 0..1, words.</summary>
public readonly record struct TexturePackProgress(int Part, int Parts, double PartFraction, double Fraction, string Text);

/// <summary>What the game folder has of the pack: none, some parts of one (an install stopped part way), or one whole.</summary>
public enum TexturePackHave { None, Partial, Installed }

/// <summary>((Triforce, 11-25) Evil HD's remastered textures, downloaded into the game folder's triforce_texpack, where the game's
/// renderer finds them (gpu/vk/vk_texture.cpp texpack: &lt;key&gt;.png and its &lt;key&gt;_mN.png levels). The pack is made from the game's
/// own textures, so it is hosted apart from the release (BuildInfo.TexturePackBase) and never ships with Triforce.
///
/// One part at a time: downloaded into the launcher's downloads folder (Downloader: a stopped download goes on from its .part),
/// its SHA-256 checked against the manifest, unpacked into the folder, then deleted. The folder's .pack.json names the pack and
/// the parts in it, so a stopped install goes on at the next part, and needs about one part of room beyond the pack. A part
/// whose hash is wrong is deleted and fetched anew at the next try. Only names a pack file has (16 hex digits, an optional _mN,
/// .png) are written, flat in the folder: nothing in a zip can reach outside it.</summary>
public sealed class TexturePack
{
    public const string FolderName = "triforce_texpack";
    public const string StateName = ".pack.json";
    static readonly Regex FileName = new(@"^[0-9a-f]{16}(_m\d{1,2})?\.png$", RegexOptions.CultureInvariant);
    static readonly Regex PartName = new(@"^[A-Za-z0-9._-]{1,80}\.zip$", RegexOptions.CultureInvariant);

    readonly TriforceContext ctx;
    readonly Downloader downloader;
    public TexturePack(TriforceContext ctx, Downloader? downloader = null)
    {
        this.ctx = ctx;
        this.downloader = downloader ?? new Downloader(ctx);
    }

    /// <summary>Where the pack's manifest and parts are: TRIFORCE_TEXPACK_URL over BuildInfo's (a test's own server).</summary>
    public static string BaseUrl
    {
        get
        {
            var e = Environment.GetEnvironmentVariable("TRIFORCE_TEXPACK_URL");
            return (string.IsNullOrWhiteSpace(e) ? BuildInfo.TexturePackBase : e.Trim()).TrimEnd('/');
        }
    }

    public static string Folder(string game) => Path.Combine(game, FolderName);

    /// <summary>The manifest's JSON as a manifest; FormatException for one that is not whole (no parts, a part without a size,
    /// a hash or a plain name).</summary>
    public static TexturePackManifest Parse(string json)
    {
        var o = JsonNode.Parse(json) as JsonObject ?? throw new FormatException("the pack's manifest is not an object");
        var parts = new List<TexturePackPart>();
        foreach (var p in o["parts"] as JsonArray ?? new JsonArray())
        {
            var name = (string?)p?["name"] ?? "";
            var sha = ((string?)p?["sha256"] ?? "").ToLowerInvariant();
            var size = (long?)p?["size"] ?? 0;
            if (!PartName.IsMatch(name) || sha.Length != 64 || size <= 0) throw new FormatException("the pack's manifest has a part it cannot use: " + name);
            parts.Add(new TexturePackPart(name, size, sha, (int?)p?["files"] ?? 0, (long?)p?["unpacked"] ?? 0));
        }
        var id = (string?)o["id"] ?? "";
        if (parts.Count == 0 || !Regex.IsMatch(id, @"^[A-Za-z0-9._-]{1,60}$")) throw new FormatException("the pack's manifest names no pack or no parts");
        return new TexturePackManifest(id, (int?)o["textures"] ?? 0, (int?)o["files"] ?? 0, (long?)o["unpacked"] ?? parts.Sum(x => x.Unpacked),
            (long?)o["download"] ?? parts.Sum(x => x.Size), parts);
    }

    public async Task<TexturePackManifest> ManifestAsync(HttpClient http, CancellationToken token)
    {
        using var r = await http.GetAsync(BaseUrl + "/manifest.json", token).ConfigureAwait(false);
        r.EnsureSuccessStatusCode();
        return Parse(await r.Content.ReadAsStringAsync(token).ConfigureAwait(false));
    }

    sealed record State(string Id, List<string> Done, bool Whole);

    static State? ReadState(string game)
    {
        try
        {
            var o = JsonNode.Parse(File.ReadAllText(Path.Combine(Folder(game), StateName))) as JsonObject;
            if (o == null) return null;
            var done = (o["done"] as JsonArray ?? new JsonArray()).Select(x => (string?)x ?? "").Where(x => x.Length > 0).ToList();
            return new State((string?)o["id"] ?? "", done, (bool?)o["whole"] ?? false);
        }
        catch (Exception) { return null; }
    }

    static void WriteState(string game, State s)
    {
        var o = new JsonObject { ["id"] = s.Id, ["whole"] = s.Whole, ["done"] = new JsonArray(s.Done.Select(x => (JsonNode)JsonValue.Create(x)!).ToArray()) };
        var path = Path.Combine(Folder(game), StateName);
        File.WriteAllText(path + ".new", o.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        File.Move(path + ".new", path, true);
    }

    /// <summary>What the folder has: Installed only with every part of a pack in it (by its own list; a manifest, when given,
    /// must be the same pack). A folder of pictures with no list (the pack moved in by hand) counts as Installed too.</summary>
    public TexturePackHave Have(string game, TexturePackManifest? m = null)
    {
        var s = ReadState(game);
        if (s == null)
        {
            try { return Directory.Exists(Folder(game)) && Directory.EnumerateFiles(Folder(game), "*.png").Any() ? TexturePackHave.Installed : TexturePackHave.None; }
            catch (Exception) { return TexturePackHave.None; }
        }
        if (m != null && s.Id != m.Id) return s.Done.Count > 0 ? TexturePackHave.Partial : TexturePackHave.None;
        return s.Whole ? TexturePackHave.Installed : s.Done.Count > 0 ? TexturePackHave.Partial : TexturePackHave.None;
    }

    /// <summary>The bytes the install still downloads, for a manifest (the parts not in the folder yet).</summary>
    public long Remaining(string game, TexturePackManifest m)
    {
        var s = ReadState(game);
        var done = s != null && s.Id == m.Id ? s.Done : new List<string>();
        return m.Parts.Where(p => !done.Contains(p.Name)).Sum(p => p.Size);
    }

    /// <summary>Downloads and unpacks the parts the folder does not have yet. Another pack in the folder (an older one) is
    /// removed first. The game must not be running (its renderer lists the folder at its start).</summary>
    public async Task InstallAsync(HttpClient http, string game, TexturePackManifest m, Action<TexturePackProgress>? progress, CancellationToken token)
    {
        var folder = Folder(game);
        var s = ReadState(game);
        if (s != null && s.Id != m.Id) { Remove(game); s = null; }
        else if (s == null && Directory.Exists(folder)) Remove(game);   // (pictures with no list: not this pack's for sure)
        Directory.CreateDirectory(folder);
        s ??= new State(m.Id, new List<string>(), false);
        if (s.Whole && m.Parts.All(p => s.Done.Contains(p.Name))) return;
        s = s with { Whole = false };
        WriteState(game, s);
        var cache = Path.Combine(ctx.DownloadsFolder, "texpack");
        Directory.CreateDirectory(cache);
        var left = m.Parts.Where(p => !s.Done.Contains(p.Name)).ToList();
        var need = left.Sum(p => p.Unpacked > 0 ? p.Unpacked : p.Size) + (left.Count > 0 ? left.Max(p => p.Size) : 0);
        if (ctx.SpaceProblem("Evil HD's textures (" + (m.Download >> 30) + " GB)", need, folder) is { } none) throw new NoRoomException(none);
        long before = m.Parts.Where(p => s.Done.Contains(p.Name)).Sum(p => p.Size), total = Math.Max(1, m.Parts.Sum(p => p.Size));
        for (var i = 0; i < m.Parts.Count; i++)
        {
            var p = m.Parts[i];
            if (s.Done.Contains(p.Name)) continue;
            token.ThrowIfCancellationRequested();
            var n = i + 1;
            var zip = Path.Combine(cache, p.Name);
            var start = before;
            void Say(double f, string text) => progress?.Invoke(new TexturePackProgress(n, m.Parts.Count, f, Math.Min(1, (start + f * p.Size) / total), text));
            if (!(File.Exists(zip) && new FileInfo(zip).Length == p.Size))
                await downloader.ToFileAsync(http, BaseUrl + "/" + p.Name, zip, p.Size,
                    d => Say(d.Fraction * 0.9, "Downloading part " + n + " of " + m.Parts.Count), token).ConfigureAwait(false);
            Say(0.9, "Checking part " + n + " of " + m.Parts.Count);
            var sha = await Task.Run(() => { using var f = File.OpenRead(zip); return Convert.ToHexStringLower(SHA256.HashData(f)); }, token).ConfigureAwait(false);
            if (sha != p.Sha256)
            {
                try { File.Delete(zip); } catch (Exception) { }
                throw new InvalidDataException("Part " + n + " of Evil HD's textures did not download whole. Try again: it is fetched anew.");
            }
            Say(0.95, "Unpacking part " + n + " of " + m.Parts.Count);
            await Task.Run(() => Unpack(zip, folder), CancellationToken.None).ConfigureAwait(false);
            s.Done.Add(p.Name);
            WriteState(game, s);
            try { File.Delete(zip); } catch (Exception) { }
            before += p.Size;
            ctx.Log.Write("texture pack " + m.Id + ": part " + n + " of " + m.Parts.Count + " in (" + p.Name + ")");
        }
        WriteState(game, s with { Whole = true });
        progress?.Invoke(new TexturePackProgress(m.Parts.Count, m.Parts.Count, 1, 1, "Evil HD's textures are in"));
        ctx.Log.Write("texture pack " + m.Id + ": installed in " + folder);
    }

    /// <summary>A part's pictures into the folder, each through name.new then into place (a stop leaves no half picture).</summary>
    static void Unpack(string zip, string folder)
    {
        using var z = ZipFile.OpenRead(zip);
        foreach (var e in z.Entries)
        {
            if (e.FullName.EndsWith('/')) continue;
            if (!FileName.IsMatch(e.FullName)) throw new InvalidDataException("a file Evil HD's textures do not have: " + e.FullName);
            var dst = Path.Combine(folder, e.FullName);
            e.ExtractToFile(dst + ".new", true);
            File.Move(dst + ".new", dst, true);
        }
    }

    /// <summary>The folder gone (the pack's pictures and its list); the game then draws its own textures.</summary>
    public void Remove(string game)
    {
        var f = Folder(game);
        if (!Directory.Exists(f)) return;
        // (a link to a folder elsewhere, the lab's: only the link goes)
        if (new DirectoryInfo(f).LinkTarget != null) { Directory.Delete(f); return; }
        Directory.Delete(f, true);
    }
}
