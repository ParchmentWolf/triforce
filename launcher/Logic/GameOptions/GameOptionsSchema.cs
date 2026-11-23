// The game's Options menu as data: gpu/vk/vk_menu.cpp's Row table (rows[]), the tx_* functions that label its values, the
// keys ini_key gives them, the defaults of vk_menu.h's Options, and (options_version 8) the merged rows of merged_rows.h. Every
// row the game keeps in triforce_options.ini is here except the ones KeptKeys names (the Debug tab, the Layout preset, the
// lines options_version 8 dropped); the Game language is language.txt's, not this file's (Languages.cs). Labels are the menu's
// own words: players compare them. Where the menu's label depends on this PC (the display's refresh, a gyroscope, what the
// driver runs) the label here is the one the menu shows when it knows nothing of it. When vk_menu.cpp's table changes, change
// this one: the test "game options: schema matches vk_menu.cpp" reads the table and says what differs.
using System.Globalization;

namespace Triforce.Logic;

/// <summary>Whose low-latency library the Low latency row stands for (merged_rows.h Vendor): NVIDIA Reflex, AMD Anti-Lag 2,
/// or neither (the game hides the row there).</summary>
public enum LatencyVendor { None, Nvidia, Amd }

public static class GameOptionsSchema
{
    /// <summary>The file the game reads at its start and writes at every change in its menu, in the game folder.</summary>
    public const string FileName = "triforce_options.ini";
    /// <summary>The options_version the game writes (vk_menu.cpp save): the file's format, which menu_init's rules read.</summary>
    public const int CurrentVersion = 9;

    public const string OutputResKey = "output_res";
    public const string OutputWidthKey = "output_width";
    public const string OutputHeightKey = "output_height";
    public const string UltrawideKey = "ultrawide";
    /// <summary>The Custom size the player entered, &lt;w&gt;x&lt;h&gt;, kept by the game's menu while a screen's size is in
    /// output_width and output_height (vk_menu.cpp remembered_custom); empty or absent when there is none. The menu reads
    /// it under any Output resolution, and so does GameOptionsFile. No row.</summary>
    public const string CustomSizeKey = "output_custom_size";
    public const string ResolutionKey = "resolution";
    public const string UpscalerKey = "dlss";
    public const string RumbleKey = "rumble_strength";
    public const string GpuKey = "gpu_device";
    public const string MicKey = "microphone";
    public const string VersionKey = "options_version";
    public const string MicDeviceKey = "microphone_device";
    /// <summary>The merged rows' keys (the launcher's alone: no line has them, their Parts' keys are the file's).</summary>
    public const string HdrKey = "@hdr", FrameGenKey = "@frame_generation", PacingKey = "@frame_pacing", LatencyKey = "@low_latency";

    /// <summary>The names of the graphics cards, in the order the game counts them (its GPU device row's 1 is the first),
    /// for the GPU device row's labels. The launcher sets it (UseSystemGpus: Gpus.List()). The game lists the cards
    /// Vulkan gives it, which is usually but not always the order Windows lists them in. Null: "1: Device 1" and so on, as
    /// the menu shows a card it has no name for.</summary>
    public static Func<IReadOnlyList<string>>? GpuNames { get; set; }

    /// <summary>GpuNames from Gpus.List() (this PC's display adapters).</summary>
    public static void UseSystemGpus() => GpuNames = () => Gpus.List().Select(g => g.Name).ToList();

    /// <summary>((Triforce) 11-19, ticket "GPU read issue") GpuNames as the game counts them: the game folder's
    /// triforce_gpus.txt ("&lt;value&gt;\t&lt;name&gt;" lines, gpu/vk/vk_main.cpp pick_device), which the game writes at every
    /// start. Windows' order of the display adapters (Gpus.List()) is not Vulkan's on every PC: on a laptop with an Intel UHD
    /// 770 and an RTX 3050 the launcher's "1: NVIDIA" saved the value the game reads as the Intel. Without the file (a game
    /// that has not started since v0.5.3): Windows' order, as before.</summary>
    public static void UseGameGpus(Func<string?> gameFolder) => GpuNames = () =>
    {
        try
        {
            if (gameFolder() is { } g && File.Exists(Path.Combine(g, GpuListFile)))
            {
                var names = new List<string>();
                foreach (var line in File.ReadAllLines(Path.Combine(g, GpuListFile)))
                {
                    var tab = line.IndexOf('\t');
                    if (tab > 0 && int.TryParse(line.AsSpan(0, tab), out var v) && v == names.Count + 1) names.Add(line[(tab + 1)..].Trim());
                }
                if (names.Count > 0) return names;
            }
        }
        catch (Exception) { }
        return Gpus.List().Select(x => x.Name).ToList();
    };
    public const string GpuListFile = "triforce_gpus.txt";

    /// <summary>((Triforce, options_version 8) Whose library the Low latency row is, as the game decides it by the card it runs
    /// on (vk_menu.cpp latency_vendor: Reflex on an NVIDIA card, Anti-Lag 2 on an AMD one). Null: NVIDIA's, the row's widest
    /// (Off, On, On + Boost). The launcher sets it (UseSystemLatency).</summary>
    public static Func<LatencyVendor>? LatencyVendorOf { get; set; }
    /// <summary>LatencyVendorOf from the card that most likely runs the game (Gpus.Main(): an NVIDIA or AMD one before an
    /// integrated Intel one).</summary>
    public static void UseSystemLatency() => LatencyVendorOf = () => Gpus.Main()?.Vendor switch
    {
        GpuVendor.Nvidia => LatencyVendor.Nvidia, GpuVendor.Amd => LatencyVendor.Amd, _ => LatencyVendor.None,
    };
    static LatencyVendor LatencyNow()
    {
        try { return LatencyVendorOf?.Invoke() ?? LatencyVendor.Nvidia; } catch (Exception) { return LatencyVendor.Nvidia; }
    }
    /// <summary>merged_rows.h latency_hi: the Low latency row's last value for this vendor (2 Reflex's On + Boost, 1 Anti-Lag 2's On).</summary>
    public static int LatencyHi(LatencyVendor v) => v == LatencyVendor.Nvidia ? 2 : v == LatencyVendor.Amd ? 1 : 0;

    // ---- the keys ----

    /// <summary>vk_menu.cpp ini_key: a few rows keep the keys they were first saved with (the rows renamed since, options_version
    /// 8's groups among them); every other row's key is its name lower-cased, its spaces as '_', cut to 31 characters.</summary>
    public static string IniKey(string name) => name switch
    {
        "Output resolution" => OutputResKey,
        "Render resolution" => ResolutionKey,
        "Frame rate cap" => "frame_rate_cap",
        "Upscaler" => UpscalerKey,
        "Start next frame early" => "tail_early",
        "Aspect ratio" => "ultrawide", "HUD position" => "ultrawide_hud", "Menu sides" => "ultrawide_menus",
        "Paper white" => "hdr_paper_white", "Peak brightness" => "hdr_peak_brightness", "UI brightness" => "renodx_ui_brightness",
        "Tonemapper" => "renodx_tonemapper", "Gamma correction" => "renodx_gamma_correction", "Color space" => "renodx_color_space",
        "Exposure" => "renodx_exposure", "Middle gray" => "renodx_midgray", "Match tone slope" => "renodx_match_tone_slope",
        "Tone slope" => "renodx_tone_slope", "Hue clip" => "renodx_hue_clip", "Highlight saturation" => "renodx_highlight_saturation",
        "Blowout" => "renodx_blowout", "Flare" => "renodx_flare", "Hue correction" => "renodx_hue_correction",
        "Color grading" => "renodx_color_grading", "Highlights" => "renodx_highlights", "Shadows" => "renodx_shadows",
        "Contrast" => "renodx_contrast", "Saturation" => "renodx_saturation", "Bloom" => "renodx_bloom",
        _ => Cut(new string(name.Select(c => c == ' ' ? '_' : c is >= 'A' and <= 'Z' ? (char)(c + 32) : c).ToArray()), 31),
    };
    static string Cut(string s, int n) => s.Length > n ? s[..n] : s;

    // ---- the labels (the tx_* functions) ----

    static int V(IGameOptionValues? o, string key, int dflt) => o?.Get(key) ?? dflt;
    static string Pick(string[] t, int v) => t[Math.Clamp(v, 0, t.Length - 1)];
    static string OrFirst(string[] t, int v) => v >= 0 && v < t.Length ? t[v] : t[0];
    static string Pct(int v) => v.ToString(CultureInfo.InvariantCulture) + "%";

    static string TxOnoff(int v, IGameOptionValues? o) => v != 0 ? "On" : "Off";
    static string TxMenuShortcut(int v, IGameOptionValues? o) => v != 0 ? "F1 only" : "Insert or F1";
    static string TxHdr(int v) => v == 1 ? "Expanded" : v == 2 ? "Native" : "Off";
    /// <summary>tx_hdr_mode: the HDR row, opts.hdr with RenoDX HDR as its fourth value.</summary>
    static string TxHdrMode(int v, IGameOptionValues? o) => v == HdrRenodx ? "Native + RenoDX" : TxHdr(Math.Clamp(v, 0, 2));
    static string TxNits(int v, IGameOptionValues? o) => v.ToString(CultureInfo.InvariantCulture) + " nits";
    /// <summary>tx_fps_cap. 6, Monitor's rate, shows the display's rate in the game ("Monitor's rate (144)") once it knows it.</summary>
    static string TxFpsCap(int v, IGameOptionValues? o)
    {
        if (v < 0) return v == -1 ? "45" : v == -2 ? "40" : "30";
        if (v >= 6) return "Monitor's rate";
        return new[] { "60 (the console's)", "90", "120", "144", "165", "240" }[v];
    }
    static string TxSteadyFps(int v) => v == 1 ? "Any rate" : v == 2 ? "Refresh steps" : "Off";
    /// <summary>tx_pacing: Frame pacing and Steady frame rate in one row.</summary>
    static string TxPacing(int v, IGameOptionValues? o) => Pick(new[] { "Off", "Even", "Steady, any rate", "Steady, refresh steps" }, v);
    /// <summary>tx_gyro without a controller's answer (the game adds "(gyro found)" and the like).</summary>
    static string TxGyro(int v, IGameOptionValues? o) => v != 0 ? "On" : "Off";
    static string TxMousecam(int v, IGameOptionValues? o) => v != 0 ? "Native" : "As the stick";
    static string TxSens(int v, IGameOptionValues? o) =>
        (v < 0 ? "-" : "") + (Math.Abs(v) / 100).ToString(CultureInfo.InvariantCulture) + "." + (Math.Abs(v) % 100).ToString("00", CultureInfo.InvariantCulture);
    static readonly string[] LatencyNames = { "Off", "On", "On + Boost" };
    /// <summary>tx_latency: the Low latency row by the card's maker (with DLSS frame generation the game shows Reflex's Off as
    /// On: Streamline's Reflex is always on).</summary>
    static string TxLatency(int v, IGameOptionValues? o) => LatencyNames[Math.Clamp(v, 0, LatencyHi(LatencyNow()))];
    static readonly string[] Engines = { "Game", "NVIDIA DLSS", "NVIDIA DLSS", "AMD FSR 3.1", "AMD FSR 4", "AMD FSR 4", "AMD FSR 3.1" };
    /// <summary>tx_upscaler: the engine alone (options_version 8: DLAA and the native AAs are the Render resolution's Native
    /// (100%)); the game names FSR 4 by the version AMD's library runs once it has asked ("AMD FSR 4.1").</summary>
    static string TxUpscaler(int v, IGameOptionValues? o) => Engines[Engine(v)];
    /// <summary>tx_dlss_model without RX_VK_DLSS_PRESET.</summary>
    static string TxDlssModel(int v, IGameOptionValues? o) => Pick(new[] { "Transformer (K)", "Transformer 2 (M)", "Transformer 2 (L)", "NVIDIA default" }, v);
    static string TxAniso(int v, IGameOptionValues? o) => OrFirst(new[] { "Game", "2x", "4x", "8x", "16x" }, v);
    /// <summary>tx_tex_detail: the game adds the level Automatic gives ("Automatic (Full)") once its first texture is made.</summary>
    static string TxTexDetail(int v, IGameOptionValues? o) => OrFirst(new[] { "Automatic", "Full", "Reduced", "Low" }, v);
    static string TxPercent(int v, IGameOptionValues? o) => Pct(v);
    static string TxRdxTonemap(int v, IGameOptionValues? o) => v == 2 ? "RenoDRT" : v != 0 ? "PsychoV35" : "Vanilla";
    static string TxRdxGamma(int v, IGameOptionValues? o) => v == 1 ? "2.2" : v == 2 ? "BT.1886 (2.4)" : "Off";
    static string TxRdxMidgray(int v, IGameOptionValues? o) => v == 1 ? "Vanilla" : v == 2 ? "Eye adaptation" : "Render";
    static string TxRdxSpace(int v, IGameOptionValues? o) => v == 1 ? "BT.709" : v == 2 ? "DCI-P3" : "Vanilla";
    static string TxRdxGrade(int v, IGameOptionValues? o) => v.ToString(CultureInfo.InvariantCulture);
    static string TxSpeed(int v, IGameOptionValues? o) => v != 0 ? "Real time" : "Per frame";
    static string TxTextSpeed(int v, IGameOptionValues? o) => OrFirst(new[] { "Normal", "2x", "4x", "Instant" }, v);
    static readonly string[] Shapes = { "16:9", "16:10", "21:9", "32:9" };
    /// <summary>tx_shape: the row's choice, or the shape of an Output resolution that has its own (the row then has nothing
    /// to choose) with its size. (The game shows HOS_ASPECT's there while it is set.)</summary>
    static string TxUltrawide(int v, IGameOptionValues? o)
    {
        if (!OutputShaped(o)) return Pick(Shapes, v);
        var (w, h) = OutputSizeOf(V(o, OutputResKey, 0), o);
        return ShapeName((double)w / h) + " (" + w + "x" + h + ")";
    }
    /// <summary>shape_name: one of the Ultrawide row's where it is that one, else its width for a height of 1 (2.40:1).</summary>
    static string ShapeName(double ratio)
    {
        for (var row = 1; row <= 3; row++)
            if (Math.Abs(ratio / UltrawideRatio(row) - 1.0) < 0.001) return Shapes[row];
        return ratio.ToString("0.00", CultureInfo.InvariantCulture) + ":1";
    }
    static string TxPixels(int v, IGameOptionValues? o) => v.ToString(CultureInfo.InvariantCulture);
    static string TxWideHud(int v, IGameOptionValues? o) => v != 0 ? "Screen edges" : "Middle";
    static string TxWideMenus(int v, IGameOptionValues? o) => Pick(new[] { "Full width", "Centred, blurred sides", "Centred, black bars" }, v);
    static string TxPrompts(int v, IGameOptionValues? o) =>
        Pick(new[] { "Auto", "Switch", "Xbox", "PlayStation 4", "PlayStation 5", "Steam Deck", "Keyboard & mouse" }, v);
    static string TxRumble(int v, IGameOptionValues? o) => v != 0 ? Pct(v) : "Off";
    static string TxVolume(int v, IGameOptionValues? o) => v != 0 ? Pct(v) : "Muted";
    static string TxMenuSounds(int v, IGameOptionValues? o) => v != 0 ? Pct(v) : "Off";
    static string TxSprint(int v, IGameOptionValues? o) => v == 1 ? "Left stick click" : v == 2 ? "B" : "Off";
    static string TxSprintMode(int v, IGameOptionValues? o) => v != 0 ? "Hold" : "Toggle";
    /// <summary>tx_own_dead_zone: -1 is XInput's own (~24%), the Default (options_version 8: the shared Stick dead zone is gone).</summary>
    static string TxOwnDeadZone(int v, IGameOptionValues? o) => v < 0 ? "Default (24%)" : Pct(v);
    static string TxWalkKey(int v, IGameOptionValues? o) => OrFirst(new[] { "Off", "Caps Lock", "Shift", "Ctrl", "Tab" }, v);
    static string TxAudioOutput(int v, IGameOptionValues? o) => OrFirst(new[] { "Auto", "Stereo", "5.1" }, v);
    static string TxDeadzone(int v, IGameOptionValues? o) => Pick(new[] { "Low", "Standard", "High" }, v);
    static string TxMesh(int v, IGameOptionValues? o) => v == 1 ? "Compute fallback" : "Auto";
    static string TxPerf(int v, IGameOptionValues? o) => v == 1 ? "On" : v >= 2 ? "Full" : "Off";
    static string TxDlssg(int v) => v == 1 ? "2x" : v == 2 ? "3x" : v == 3 ? "4x" : "Off";
    /// <summary>tx_framegen where AMD's library can make the frames, before it has said its version (the game then shows
    /// "AMD FSR (4.0.2)" and the like; elsewhere a saved 9 as 2x).</summary>
    static string TxFramegen(int v) => Pick(new[] { "Off", "Auto", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "AMD FSR" }, v);
    /// <summary>tx_framegen_row: the renderer's own and AMD's (opts.framegen), then NVIDIA DLSS 2x to 4x (opts.dlssg).</summary>
    static string TxFramegenRow(int v, IGameOptionValues? o) =>
        v >= FgDlss ? new[] { "NVIDIA DLSS 2x", "NVIDIA DLSS 3x", "NVIDIA DLSS 4x" }[Math.Clamp(v - FgDlss, 0, 2)] : TxFramegen(v);
    /// <summary>tx_gpu: 0 "Auto", then "&lt;n&gt;: &lt;name&gt;" counted from 0 (GpuNames), "&lt;n&gt;: Device &lt;n&gt;" without a name.</summary>
    static string TxGpu(int v, IGameOptionValues? o)
    {
        if (v <= 0) return "Auto";
        var idx = v - 1;
        var names = GpuNamesNow();
        return idx < names.Count ? idx + ": " + names[idx] : idx + ": Device " + idx;
    }
    static IReadOnlyList<string> GpuNamesNow()
    {
        try { return GpuNames?.Invoke() ?? Array.Empty<string>(); } catch (Exception) { return Array.Empty<string>(); }
    }
    /// <summary>((Triforce) 11-20) The GPU device row's card for a value, by the name the row shows for it (GpuNames): what
    /// GameOptionsFile.Save writes as gpu_device_name beside the number, so that the game finds the card the player clicked
    /// whatever order the list was in (gpu/vk/gpu_choice.h pick). Null for Auto or a value with no name.</summary>
    public static string? GpuNameOf(int v)
    {
        if (v <= 0) return null;
        var names = GpuNamesNow();
        return v - 1 < names.Count && names[v - 1].Trim() is { Length: > 0 } n ? n : null;
    }
    public const string GpuNameKey = "gpu_device_name";
    /// <summary>tx_mic without the game's device list: Off, Default, and a device by the name the file keeps
    /// (microphone_device), "Microphone" without one.</summary>
    static string TxMic(int v, IGameOptionValues? o)
    {
        if (v <= 0) return "Off";
        if (v == 1) return "Default";
        var name = o?.Raw(MicDeviceKey) is { } raw ? MicName(raw) : "";
        return name.Length > 0 ? name : "Microphone";
    }
    /// <summary>The microphone_device line's name as text: the file's bytes are UTF-8 (read here as Latin-1, byte for byte).</summary>
    internal static string MicName(string raw) => System.Text.Encoding.UTF8.GetString(System.Text.Encoding.Latin1.GetBytes(raw)).Trim();

    // ---- the Output resolution, the picture it gives, and the Render resolution ----

    /// <summary>The Output resolution's fixed sizes by their saved value (kOutputs); 6 came after the others so that saved
    /// values keep their sizes. 9 is Custom, any size (gpu/vk/output_sizes.h): the size is the picture's, the game's frame
    /// 16:9 at its height, and a size that is not 16:9 is a wider or narrower picture by itself. The game's menu lists the
    /// size of every connected screen by its name and saves the one chosen as Custom's size, so here such a choice is
    /// Custom with that size. 8 is Screen, the size of the screen the game's window opens on: what an older file has, and
    /// still read; the game's menu saves it as that size.</summary>
    public static readonly IReadOnlyList<(int W, int H)> Outputs = new[] { (2048, 1152), (2560, 1440), (3840, 2160), (1920, 1080), (5120, 1440), (5120, 2880), (5120, 2160), (1536, 864) };
    public const int HandheldOutput = 7;
    public const int OutputScreen = 8, OutputCustom = 9;
    /// <summary>The order the launcher lists them in: the fixed sizes smallest to largest, then Screen and Custom. (The menu
    /// puts the screens' sizes and Custom among the fixed ones by their sizes, output_entries.)</summary>
    public static readonly IReadOnlyList<int> OutputOrder = new[] { 7, 3, 0, 1, 2, 4, 6, 5, OutputScreen, OutputCustom };
    static int OutputChoice(int v) => v >= 0 && v <= OutputCustom ? v : 0;

    // (gpu/vk/output_sizes.h, as plain code)
    const int OutputMinW = 640, OutputMinH = 360, OutputMaxW = 7680, OutputMaxH = 2880;
    const double OutputMaxPixels = 5120.0 * 2880.0, OutputRowPixels = 3840.0 * 2160.0, ShapeMin = 5.0 / 4.0, ShapeMax = 32.0 / 9.0;
    static int OutputFrameWidth(int height) => (height * 16 + 36) / 72 * 8;
    static bool ShapeIsGame(double shape) => !(shape > 16.0 / 9.0 * 1.01 || shape < 16.0 / 9.0 * 0.99);
    static bool SizeShaped((int W, int H) s) => s.W > 0 && s.H > 0 && !ShapeIsGame((double)s.W / s.H);
    /// <summary>ultrawide_row_ratio: the Ultrawide row's shape, 0 for the game's own 16:9.</summary>
    static double UltrawideRatio(int row) => row <= 0 ? 0 : row == 1 ? 1.6f : row == 2 ? (float)(64.0 / 27.0) : (float)(32.0 / 9.0);
    /// <summary>output_width_range: the widths, whole multiples of 8, a picture of height h can have on one side of 16:9:
    /// within 5:4 to 32:9 and outside the 1% beside 16:9, within the width's ends and the pixels. Lo above Hi: none.</summary>
    static (int Lo, int Hi) OutputWidthRange(int h, bool wide)
    {
        const double game = 16.0 / 9.0;
        var edge = h * game * (wide ? 1.01 : 0.99);
        var least = wide ? Math.Floor(edge / 8.0) * 8.0 + 8.0 : Math.Ceiling(h * ShapeMin / 8.0) * 8.0;
        var most = wide ? Math.Floor(h * ShapeMax / 8.0) * 8.0 : Math.Ceiling(edge / 8.0) * 8.0 - 8.0;
        var pixels = Math.Floor(OutputMaxPixels / h / 8.0) * 8.0;
        least = Math.Max(least, OutputMinW);
        most = Math.Min(Math.Min(most, OutputMaxW), pixels);
        return ((int)least, most < 0 ? 0 : (int)most);
    }
    /// <summary>output_size_used: a size from outside (the screen's, Custom's) as the game takes it, null for none. Its
    /// shape first (5:4 to 32:9), then into the limits in that shape: 7680x4320 is 5120x2880. The width is the multiple of
    /// 8 nearest the shape's among those OutputWidthRange allows, so what comes out is taken as itself when given again.</summary>
    internal static (int W, int H)? OutputSizeUsed(long w, long h)
    {
        if (w <= 0 || h <= 0) return null;
        var shape = Math.Clamp((double)w / h, ShapeMin, ShapeMax);
        if (ShapeIsGame(shape))
        {
            var gh = (int)Math.Clamp(h, OutputMinH, OutputMaxH);
            return (OutputFrameWidth(gh), gh);
        }
        var wide = shape > 16.0 / 9.0;
        double fh = h, scale = 1.0;
        var fw = fh * shape;
        if (fh * scale > OutputMaxH) scale = OutputMaxH / fh;
        if (fw * scale > OutputMaxW) scale = OutputMaxW / fw;
        if (fw * fh * scale * scale > OutputMaxPixels) scale = Math.Sqrt(OutputMaxPixels / (fw * fh));
        int uh;
        if (scale < 1.0) uh = (int)(fh * scale / 8.0) * 8;
        else
        {
            if (fh < OutputMinH) fh = OutputMinH;
            if (fh * shape < OutputMinW) fh = OutputMinW / shape;
            uh = (int)Math.Ceiling(fh);
        }
        var (lo, hi) = OutputWidthRange(uh, wide);
        if (lo > hi)
        {
            uh = (uh - 1) / 8 * 8;
            (lo, hi) = OutputWidthRange(uh, wide);
        }
        return (Math.Clamp((int)(uh * shape / 8.0 + 0.5) * 8, lo, hi), uh);
    }
    /// <summary>custom_rows_read: the Output width and Output height rows' values for the file's two numbers (0: no line): a
    /// side that is not a size is its default; as written where the rows can hold them, else the size the game takes.</summary>
    internal static (int W, int H) CustomRowsRead(long w, long h)
    {
        if (w <= 0) w = 2560;
        if (h <= 0) h = 1440;
        var held = w >= OutputMinW && w <= OutputMaxW && h >= OutputMinH && h <= OutputMaxH;
        return held ? ((int)w, (int)h) : OutputSizeUsed(w, h)!.Value;
    }
    /// <summary>output_picture: the picture for the frame's height and a shape, null for the game's own 16:9 picture.</summary>
    internal static (int W, int H)? OutputPicture(int frameH, double want, bool sized)
    {
        if (!(want > 1.0) || ShapeIsGame(want)) return null;
        var r = Math.Clamp(want, ShapeMin, ShapeMax);
        var most = sized ? OutputMaxPixels : OutputRowPixels;
        int oh = frameH, ow = (int)(oh * r / 8 + 0.5) * 8;
        if ((double)ow * oh > most)
        {
            oh = (int)(Math.Sqrt(most / r) / 8) * 8;
            ow = (int)(oh * r / 8) * 8;
        }
        return (ow, oh);
    }
    /// <summary>output_res_read: output_res as a file of an older options_version holds it, with its Ultrawide row. Before 8,
    /// 5120x1440 (4) and 5120x2160 (6) were the game's frame: with the row on another shape than theirs, the 16:9 size of
    /// their height, which gives the same picture.</summary>
    internal static int OutputResRead(int v, int version, int ultrawide)
    {
        if (version >= 8) return v;
        if (v == 4 && ultrawide != 0 && ultrawide != 3) return 1;
        if (v == 6 && ultrawide != 0 && ultrawide != 2) return 2;
        return v;
    }
    /// <summary>row_size: the size a choice shows, null for a Screen that is not known.</summary>
    static (int W, int H)? RowSize(int v, IGameOptionValues? o)
    {
        v = OutputChoice(v);
        if (v < OutputScreen) return Outputs[v];
        if (v == OutputScreen) return o?.Screen is { } s ? OutputSizeUsed(s.W, s.H) : null;
        // (under another choice with a size kept aside, Custom is that size: choosing it takes it back, as in the menu, where
        // only the kept pair is offered then, output_entries)
        if (V(o, OutputResKey, 0) != OutputCustom && o?.EnteredCustomSize is { } entered) return OutputSizeUsed(entered.W, entered.H);
        return OutputSizeUsed(V(o, OutputWidthKey, 2560), V(o, OutputHeightKey, 1440));
    }
    /// <summary>output_size_of: the size a choice runs at (2560x1440 for a Screen that is not known, as the game).</summary>
    static (int W, int H) OutputSizeOf(int v, IGameOptionValues? o) => RowSize(v, o) ?? Outputs[1];
    /// <summary>output_shaped: the Output resolution chosen has a shape of its own (docked), so the Ultrawide row does not apply.</summary>
    internal static bool OutputShaped(IGameOptionValues? o) =>
        o != null && V(o, OutputResKey, 0) != HandheldOutput && SizeShaped(OutputSizeOf(V(o, OutputResKey, 0), o));
    /// <summary>output_picture_of: the picture the options give, the size's own or its height in the Ultrawide row's shape.</summary>
    static (int W, int H) PictureOf(IGameOptionValues? o)
    {
        var v = OutputChoice(V(o, OutputResKey, 0));
        var size = OutputSizeOf(v, o);
        var frameH = v == 0 ? Outputs[1].H : size.H;
        var sized = SizeShaped(size);
        var want = sized ? (double)size.W / size.H : UltrawideRatio(Math.Clamp(V(o, UltrawideKey, 0), 0, 3));
        if (OutputPicture(frameH, want, sized) is not { } p) return v == 0 ? Outputs[0] : size;
        return v == 0 ? (p.W * 4 / 5, p.H * 4 / 5) : p;
    }
    /// <summary>tx_output_res: a fixed size, "Screen (WxH)" with the main monitor's size where the launcher knows it (the
    /// game shows the monitor's it opens on), "Custom (WxH)" with the Output width and Output height rows' size as the game
    /// takes it.</summary>
    static string TxOutputRes(int v, IGameOptionValues? o)
    {
        v = OutputChoice(v);
        var size = RowSize(v, o);
        if (v == 7) return "1536x864 (handheld)";
        if (v < OutputScreen) return size!.Value.W + "x" + size.Value.H;
        var name = v == OutputScreen ? "Screen" : "Custom";
        return size is { } s ? name + " (" + s.W + "x" + s.H + ")" : name;
    }

    // (upscaler_rows.h)
    const int Game = 0, Dlss = 1, Dlaa = 2, Fsr3 = 3, Fsr4 = 4, Fsr4Aa = 5, Fsr3Aa = 6;
    /// <summary>The engines in the order the Upscaler row shows them (kEngines): an engine's native anti-aliasing (DLAA, FSR's
    /// Native AA) is the Render resolution's Native (100%) from options_version 8, its saved value as before.</summary>
    public static readonly IReadOnlyList<int> UpscalerOrder = new[] { Game, Dlss, Fsr3, Fsr4 };
    /// <summary>upscaler_rows.h engine: DLAA is DLSS's, FSR 4's and FSR 3.1's native AA their own.</summary>
    public static int Engine(int up) => up == Dlaa ? Dlss : up == Fsr4Aa ? Fsr4 : up == Fsr3Aa ? Fsr3 : up is >= Game and <= Fsr3Aa ? up : Game;
    /// <summary>upscaler_rows.h native_of: an engine's native anti-aliasing (the game's own has none: itself).</summary>
    public static int NativeOf(int engine) => engine == Dlss ? Dlaa : engine == Fsr4 ? Fsr4Aa : engine == Fsr3 ? Fsr3Aa : engine;
    /// <summary>The Render resolution row's Native (100%) with DLSS or FSR (upscaler_rows.h kNativeStep): its value here while
    /// the Upscaler is an engine's native AA (GameOptionsFile.Get). Chosen, the Upscaler becomes that native AA and the
    /// saved resolution stays as it is.</summary>
    public const int NativeStep = -1;
    static readonly int[] Percents = { 0, 100, 75, 67, 50, 58, 33 };
    static int Percent(int v) => v > 0 && v < Percents.Length ? Percents[v] : 0;
    public static bool FullScale(int up) => up == Dlaa || up == Fsr4Aa || up == Fsr3Aa;
    static bool ScalesByMode(int up) => up == Dlss || up == Fsr3 || up == Fsr4;
    /// <summary>upscaler_rows.h native_size: the 3D at the output's full size (an engine's native AA, or the game's own at 100%).</summary>
    public static bool NativeSize(int up, int resolution) => FullScale(up) || (up == Game && Percent(resolution) == 100);
    static readonly int[] GameSteps = { 0, 1, 2, 3, 4 }, DlssSteps = { 0, 3, 5, 4, 6 }, TemporalSteps = { 0, NativeStep, 3, 5, 4, 6 };
    /// <summary>The Render resolution values the menu steps through with this Upscaler: the game's own its shares; DLSS and
    /// FSR (and their native AAs) Auto, Native (100%) and their modes (upscaler_rows.h kTemporalSteps).</summary>
    public static IReadOnlyList<int> ResolutionSteps(int upscaler) => ScalesByMode(Engine(upscaler)) ? TemporalSteps : GameSteps;
    /// <summary>upscaler_rows.h snap: v as one of the upscaler's steps, the nearest in size (the larger on a tie); Auto stays,
    /// and with a full-size upscaler v is kept for the next.</summary>
    public static int SnapResolution(int upscaler, int v)
    {
        if (FullScale(upscaler) || Percent(v) == 0) return Percent(v) == 0 ? 0 : v;
        var steps = ScalesByMode(upscaler) ? DlssSteps : GameSteps;
        int best = v, bestD = 1000;
        foreach (var s in steps)
        {
            if (s == v) return v;
            if (Percent(s) == 0) continue;
            var d = Math.Abs(Percent(s) - Percent(v));
            if (d < bestD || (d == bestD && Percent(s) > Percent(best))) { best = s; bestD = d; }
        }
        return best;
    }
    static string ModeName(int v) => Percent(v) switch { 67 => "Quality", 58 => "Balanced", 50 => "Performance", 33 => "Ultra Performance", _ => "" };
    /// <summary>tx_resolution: by the Upscaler chosen, and the size the game draws the 3D at for a fixed share of the
    /// picture (the Output resolution's own, or its height in the Ultrawide row's shape; the handheld profile's 1536x864),
    /// a twelfth of it as the game takes it.</summary>
    static string TxResolution(int v, IGameOptionValues? o)
    {
        var up = V(o, UpscalerKey, 0);
        if (FullScale(up) || v == NativeStep) return "Native (100%)";
        var p = Percent(v);
        if (p == 0) return "Auto (dynamic)";
        if (ScalesByMode(up) && ModeName(v).Length > 0) return ModeName(v) + " (" + p + "%)";
        var (ow, oh) = (V(o, OutputResKey, 0) == HandheldOutput) ? (1536, 864) : PictureOf(o);
        var k = Math.Min(Math.Max((int)(p / 100.0f * 12.0f + 0.5f), 1), 12);
        return p + "% (" + (ow * k + 11) / 12 + "x" + oh * k / 12 + ")";
    }
    static readonly string[] AaNames = { "Game SMAA", "Off", "FXAA", "SMAA Ultra" };
    /// <summary>tx_aa: the choice, or whose anti-aliasing the picture has while DLSS or FSR draws (the row does not apply).</summary>
    static string TxAa(int v, IGameOptionValues? o)
    {
        var up = V(o, UpscalerKey, 0);
        if (up == Dlss || up == Dlaa) return "DLSS's own";
        if (up != Game) return "FSR's own";
        return OrFirst(AaNames, v);
    }

    // ---- the merged rows (merged_rows.h) ----

    const int HdrRenodx = 3, FgDlss = 10;
    /// <summary>The saved values the merged rows stand for (vk_menu.cpp's TAB_HIDDEN rows), by key: each keeps its line.</summary>
    public static readonly IReadOnlyDictionary<string, GameOptionPart> Parts = new GameOptionPart[]
    {
        new("hdr", 0, 2, 0, TxHdr), new("renodx_hdr", 0, 1, 0, v => v != 0 ? "On" : "Off"),
        new("frame_generation", 0, 9, 0, TxFramegen), new("dlss_frame_generation", 0, 3, 0, TxDlssg),
        new("frame_pacing", 0, 1, 1, v => v != 0 ? "On" : "Off"), new("steady_frame_rate", 0, 2, 0, TxSteadyFps),
        new("nvidia_reflex", 0, 2, 2, v => Pick(LatencyNames, v)), new("amd_anti-lag_2", 0, 1, 0, v => v != 0 ? "On" : "Off"),
    }.ToDictionary(p => p.Key, StringComparer.Ordinal);
    /// <summary>A saved value a merged row stands for, by its key; null for any other key.</summary>
    public static GameOptionPart? Part(string key) => Parts.GetValueOrDefault(key);

    static (string[] Parts, GameOptionMerge Merge) MergeHdr => (new[] { "hdr", "renodx_hdr" }, new GameOptionMerge(
        p => p[0] == 2 && p[1] != 0 ? HdrRenodx : Math.Clamp(p[0], 0, 2),
        (row, _) => new[] { row >= HdrRenodx ? 2 : Math.Max(row, 0), row >= HdrRenodx ? 1 : 0 }));
    static (string[] Parts, GameOptionMerge Merge) MergeFramegen => (new[] { "frame_generation", "dlss_frame_generation" }, new GameOptionMerge(
        p => p[1] is >= 1 and <= 3 ? FgDlss + p[1] - 1 : p[0],
        (row, _) => row >= FgDlss ? new[] { 0, Math.Min(row - FgDlss + 1, 3) } : new[] { Math.Max(row, 0), 0 }));
    static (string[] Parts, GameOptionMerge Merge) MergePacing => (new[] { "frame_pacing", "steady_frame_rate" }, new GameOptionMerge(
        p => p[1] == 1 ? 2 : p[1] == 2 ? 3 : p[0] != 0 ? 1 : 0,
        (row, _) => new[] { row != 0 ? 1 : 0, row == 2 ? 1 : row == 3 ? 2 : 0 }));
    static (string[] Parts, GameOptionMerge Merge) MergeLatency => (new[] { "nvidia_reflex", "amd_anti-lag_2" }, new GameOptionMerge(
        p => LatencyNow() switch { LatencyVendor.Nvidia => Math.Clamp(p[0], 0, 2), LatencyVendor.Amd => p[1] != 0 ? 1 : 0, _ => 0 },
        (row, now) => LatencyNow() switch
        {
            LatencyVendor.Nvidia => new[] { Math.Clamp(row, 0, 2), now[1] },
            LatencyVendor.Amd => new[] { now[0], row > 0 ? 1 : 0 },
            _ => now.ToArray(),
        }));

    // ---- the rows ----

    static GameOptionRow Row(GameOptionTab tab, string? section, string name, int lo, int hi, int step, int dflt, GameOptionKind kind,
        Func<int, IGameOptionValues?, string> format, bool restart, bool exempt, string help)
    {
        var key = IniKey(name);
        Func<IReadOnlyList<GameOptionChoice>>? list = null;
        if (kind == GameOptionKind.Choice)
        {
            IEnumerable<int> values = key switch
            {
                OutputResKey => OutputOrder,
                UpscalerKey => UpscalerOrder,
                ResolutionKey => GameSteps,
                MicKey => new[] { 0, 1 },
                _ => Enumerable.Range(lo, hi - lo + 1),
            };
            if (key == GpuKey)
                list = () => new[] { new GameOptionChoice(0, "Auto") }
                    .Concat(GpuNamesNow().Take(hi).Select((n, i) => new GameOptionChoice(i + 1, i + ": " + n))).ToList();
            else
            {
                var fixedList = values.Select(v => new GameOptionChoice(v, format(v, null))).ToList();
                list = () => fixedList;
            }
        }
        return new GameOptionRow
        {
            Tab = tab, Section = section, Name = name, Key = key, Lo = lo, Hi = hi, Step = step, Default = dflt, Kind = kind,
            Format = format, ChoiceList = list, Restart = restart, PresetExempt = exempt, Help = help,
        };
    }

    /// <summary>A merged row (merged_rows.h): a Choice row with no line of its own, a view of its parts. Low latency's choices
    /// follow the card's maker (LatencyVendorOf).</summary>
    static GameOptionRow Merged(GameOptionTab tab, string section, string name, int lo, int hi, int step,
        (string[] Parts, GameOptionMerge Merge) merge, Func<int, IGameOptionValues?, string> format, bool restart, bool exempt, string help)
    {
        var key = name switch { "HDR" => HdrKey, "Frame generation" => FrameGenKey, "Frame pacing" => PacingKey, _ => LatencyKey };
        Func<IReadOnlyList<GameOptionChoice>> list = key == LatencyKey
            ? () => Enumerable.Range(0, LatencyHi(LatencyNow()) + 1).Select(v => new GameOptionChoice(v, format(v, null))).ToList()
            : () => Enumerable.Range(lo, hi - lo + 1).Select(v => new GameOptionChoice(v, format(v, null))).ToList();
        return new GameOptionRow
        {
            Tab = tab, Section = section, Name = name, Key = key, Lo = lo, Hi = hi, Step = step, Kind = GameOptionKind.Choice,
            Format = format, ChoiceList = list, Restart = restart, PresetExempt = exempt, Help = help,
            Parts = merge.Parts.Select(k => Parts[k]).ToList(), Merge = merge.Merge,
        };
    }

    /// <summary>Every row, in the menu's order (as vk_menu.cpp's table has them: Display, Graphics, System's Game, Audio,
    /// System's Online, Controls; the Motion page's rows and Button prompts after the Controls tab's own).</summary>
    public static readonly IReadOnlyList<GameOptionRow> All = new[]
    {
        Row(GameOptionTab.Display, "Screen", "Fullscreen", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, false, true,
            "The game fills the whole screen, without the window's border. F10 and Alt+Enter do the same."),
        Row(GameOptionTab.Display, "Screen", "Output resolution", 0, 9, 1, 0, GameOptionKind.Choice, TxOutputRes, true, false,
            "The picture's size, before it is scaled to the window: the fixed sizes, and the size of each connected screen by its name. A size that is not 16:9 is a wider or narrower picture: the HUD, menus and story movies keep their 16:9 shape at its height. Docked only. Applies after a restart."),
        Row(GameOptionTab.Display, "Screen", "Output width", 640, 7680, 8, 2560, GameOptionKind.Slider, TxPixels, true, false,
            "The output resolution's width in pixels, where it is a screen's size or Custom; hold Left or Right to move faster. Output resolution shows the size the game takes: 5:4 to 32:9 in shape, at most the pixels of 5120x2880. Applies after a restart."),
        Row(GameOptionTab.Display, "Screen", "Output height", 360, 2880, 8, 1440, GameOptionKind.Slider, TxPixels, true, false,
            "The output resolution's height in pixels, where it is a screen's size or Custom; hold Left or Right to move faster. Output resolution shows the size the game takes: 5:4 to 32:9 in shape, at most the pixels of 5120x2880. Applies after a restart."),
        Row(GameOptionTab.Display, "Screen", "GPU device", 0, 8, 1, 0, GameOptionKind.Choice, TxGpu, true, true,
            "Which graphics card the game runs on. Applies after a restart."),
        Row(GameOptionTab.Display, "Ultrawide", "Aspect ratio", 0, 3, 1, 0, GameOptionKind.Choice, TxUltrawide, true, false,
            "The picture's shape for a 16:9 Output resolution: the game's own 16:9, or a fixed 16:10, 21:9 or 32:9 at the same height, for a screen or a window of that shape. A screen of another shape shows the picture between black bars. An Output resolution that is not 16:9 has its own shape, shown here. Applies after a restart."),
        Row(GameOptionTab.Display, "Ultrawide", "HUD position", 0, 1, 1, 0, GameOptionKind.Choice, TxWideHud, true, true,
            "With a picture wider than 16:9: where corner HUD elements, tips and notices sit. Middle: in the middle 16:9, as on a normal screen. Screen edges: out in the screen's corners. Applies after a restart."),
        Row(GameOptionTab.Display, "Ultrawide", "Menu sides", 0, 2, 1, 1, GameOptionKind.Choice, TxWideMenus, false, false,
            "With a picture wider than 16:9: the pause, item and map menus, and what shows beside them. Loading screens and story movies, which draw no world either, get the same sides (the title's movie fills the picture up to 12:5); a fade always covers the whole screen. Changes at once."),
        Merged(GameOptionTab.Display, "HDR", "HDR", 0, 3, 1, MergeHdr, TxHdrMode, true, true,
            "HDR10 on an HDR display (Windows: Use HDR on in the display settings). Native + RenoDX applies after a restart."),
        Row(GameOptionTab.Display, "HDR", "Paper white", 80, 400, 10, 200, GameOptionKind.Slider, TxNits, false, true,
            "How bright white is: around 200 nits for a normal room, higher for a bright one."),
        Row(GameOptionTab.Display, "HDR", "Peak brightness", 400, 10000, 100, 1000, GameOptionKind.Slider, TxNits, false, true,
            "The brightest highlights: set it to your display's peak brightness."),
        Row(GameOptionTab.Display, "HDR", "UI brightness", 80, 400, 10, 200, GameOptionKind.Slider, TxNits, false, true,
            "How bright the HUD's and the menus' white is with RenoDX. The scene's white is Paper white."),
        Row(GameOptionTab.Display, "RenoDX", "Tonemapper", 0, 2, 1, 1, GameOptionKind.Choice, TxRdxTonemap, false, true,
            "How the scene's light is brought to the display. Vanilla: the game's own curve. PsychoV35: keeps hue and saturation into the highlights. RenoDRT: carries the game's SDR look up to the peak brightness."),
        Row(GameOptionTab.Display, "RenoDX", "Gamma correction", 0, 2, 1, 0, GameOptionKind.Choice, TxRdxGamma, false, true,
            "Shows the picture as a 2.2 or BT.1886 (2.4) display would, as the game was made to be seen: darker shadows. Off keeps the sRGB curve."),
        Row(GameOptionTab.Display, "RenoDX", "Color space", 0, 2, 1, 1, GameOptionKind.Choice, TxRdxSpace, false, true,
            "The colors the picture is taken to be in. Vanilla: the game's own. BT.709: as the SDR picture. DCI-P3: more saturated."),
        Row(GameOptionTab.Display, "RenoDX", "Exposure", 0, 200, 5, 100, GameOptionKind.Slider, TxPercent, false, true,
            "The scene's brightness before tone mapping. 100% is the game's."),
        Row(GameOptionTab.Display, "RenoDX", "Middle gray", 0, 2, 1, 1, GameOptionKind.Choice, TxRdxMidgray, false, true,
            "What the scene's middle gray is held to. Render: as rendered. Vanilla: where the game's curve puts it. Eye adaptation: it follows what is on screen over a few seconds."),
        Row(GameOptionTab.Display, "RenoDX", "Match tone slope", 0, 1, 1, 1, GameOptionKind.Choice, TxOnoff, false, true,
            "PsychoV35: the mid tones get the contrast of the game's own curve. Off: PsychoV35's own, softer."),
        Row(GameOptionTab.Display, "RenoDX", "Tone slope", 0, 100, 1, 50, GameOptionKind.Slider, TxRdxGrade, false, true,
            "PsychoV35: how steep the tone curve is through middle gray. 50 leaves it unchanged."),
        Row(GameOptionTab.Display, "RenoDX", "Hue clip", 0, 100, 5, 50, GameOptionKind.Slider, TxPercent, false, true,
            "PsychoV35: how much bright colors turn as they do where the SDR picture clips, fire towards yellow and white. 0% keeps their hue."),
        Row(GameOptionTab.Display, "RenoDX", "Highlight saturation", 0, 100, 1, 50, GameOptionKind.Slider, TxRdxGrade, false, true,
            "RenoDRT: how strong the colors of the brightest parts are. 50 leaves them unchanged."),
        Row(GameOptionTab.Display, "RenoDX", "Blowout", 0, 100, 1, 0, GameOptionKind.Slider, TxRdxGrade, false, true,
            "RenoDRT: turns the brightest parts towards white. 0 keeps their color."),
        Row(GameOptionTab.Display, "RenoDX", "Flare", 0, 100, 1, 0, GameOptionKind.Slider, TxRdxGrade, false, true,
            "RenoDRT: lifts the darkest parts as a little stray light would. 0 keeps black black."),
        Row(GameOptionTab.Display, "RenoDX", "Hue correction", 0, 100, 5, 100, GameOptionKind.Slider, TxPercent, false, true,
            "RenoDRT: how much bright colors keep the hue they had before tone mapping."),
        Row(GameOptionTab.Display, "RenoDX", "Color grading", 0, 100, 5, 100, GameOptionKind.Slider, TxPercent, false, true,
            "RenoDRT: how much of the game's own color grading is kept. 0% is the scene without it."),
        Row(GameOptionTab.Display, "RenoDX", "Highlights", 0, 100, 5, 50, GameOptionKind.Slider, TxRdxGrade, false, true,
            "The bright parts of the scene. 50 is neutral."),
        Row(GameOptionTab.Display, "RenoDX", "Shadows", 0, 100, 5, 50, GameOptionKind.Slider, TxRdxGrade, false, true,
            "The dark parts of the scene. 50 is neutral."),
        Row(GameOptionTab.Display, "RenoDX", "Contrast", 0, 100, 5, 50, GameOptionKind.Slider, TxRdxGrade, false, true,
            "The scene's contrast. 50 is neutral."),
        Row(GameOptionTab.Display, "RenoDX", "Saturation", 0, 100, 5, 50, GameOptionKind.Slider, TxRdxGrade, false, true,
            "The scene's color. 50 is neutral."),
        Row(GameOptionTab.Display, "RenoDX", "Bloom", 0, 100, 5, 50, GameOptionKind.Slider, TxRdxGrade, false, true,
            "The glow around bright things. 50 is the game's. RenoDX is by Carlos Lopez (clshortfuse), under the MIT license."),
        Row(GameOptionTab.Display, "Overlay", "FPS counter", 0, 2, 1, 0, GameOptionKind.Choice, TxPerf, false, true,
            "Frames per second in the top right corner. Full: a performance panel in its place: the GPU's and the CPU's load, temperatures and memory, the frame rate and its lows, the frame times and their graph, the waits per frame and the picture's settings."),
        Row(GameOptionTab.Graphics, "Upscaling", "Upscaler", 0, 6, 1, 0, GameOptionKind.Choice, TxUpscaler, false, false,
            "What draws the 3D up to the Output resolution."),
        Row(GameOptionTab.Graphics, "Upscaling", "DLSS model", 0, 3, 1, 0, GameOptionKind.Choice, TxDlssModel, false, true,
            "Which of NVIDIA's DLSS networks draws the picture."),
        Row(GameOptionTab.Graphics, "Upscaling", "Render resolution", 0, 6, 1, 0, GameOptionKind.Choice, TxResolution, true, false,
            "The size the 3D is drawn at; the upscaler fills in the rest. Applies after a restart."),
        Row(GameOptionTab.Graphics, "Upscaling", "Upscale before bloom", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, true, true,
            "On: the upscaler works on the scene before the game's glow and tone mapping, which are then made at full size. Applies after a restart."),
        Row(GameOptionTab.Graphics, "Upscaling", "Sharpness", 0, 100, 10, 0, GameOptionKind.Slider, TxPercent, false, false,
            "With DLSS, DLAA or AMD FSR as the Upscaler, the 3D before the HUD (FSR's own sharpening; AMD's RCAS for DLSS); with the game's own upscaler, the picture at the window. 0 is off. Too much shows halos around edges."),
        Row(GameOptionTab.Graphics, "Anti-aliasing", "Anti-aliasing", 0, 3, 1, 0, GameOptionKind.Choice, TxAa, false, true,
            "How the 3D's edges are smoothed: the game's own SMAA, none, FXAA, or SMAA at its Ultra preset. Changes at once."),
        Merged(GameOptionTab.Graphics, "Frame generation", "Frame generation", 0, 12, 1, MergeFramegen, TxFramegenRow, true, true,
            "Makes frames between the game's own, for smoother motion, at a little input delay. Fast motion and camera cuts can show artifacts. NVIDIA DLSS applies after a restart."),
        Row(GameOptionTab.Graphics, "Frame rate & latency", "Frame rate cap", -3, 6, 1, 0, GameOptionKind.Choice, TxFpsCap, true, true,
            "The most frames the game renders a second; made frames come on top. 60 is the safe choice: past it some cutscenes and bosses can misbehave. 30, 40 and 45 are for a PC that holds one of them where 60 swings. Monitor's rate: the refresh rate of the screen the game starts on. Applies after a restart."),
        Row(GameOptionTab.Graphics, "Frame rate & latency", "VSync", 0, 1, 1, 1, GameOptionKind.Choice, TxOnoff, false, true,
            "Whether a finished frame waits for the screen's next refresh. Off: a little less delay, and the picture can tear. Changes at once."),
        Merged(GameOptionTab.Graphics, "Frame rate & latency", "Frame pacing", 0, 3, 1, MergePacing, TxPacing, true, false,
            "When each frame is shown. Steady paces the game to a rate this PC holds where you are: steadier, at some frame rate."),
        Merged(GameOptionTab.Graphics, "Frame rate & latency", "Low latency", 0, 2, 1, MergeLatency, TxLatency, false, false,
            "Each frame starts as late as it can, for less input delay: NVIDIA Reflex on NVIDIA cards, AMD Anti-Lag 2 on AMD ones."),
        Row(GameOptionTab.Graphics, "Textures", "Texture filtering", 0, 4, 1, 0, GameOptionKind.Choice, TxAniso, false, false,
            "Keeps ground, paths and walls sharp where they slope away from the camera. Game: what the game asks for; 16x is the sharpest, at a small cost."),
        Row(GameOptionTab.Graphics, "Textures", "Texture detail", 0, 3, 1, 0, GameOptionKind.Choice, TxTexDetail, true, false,
            "How large the game's textures are kept in video memory. Automatic suits the graphics card. Applies after a restart."),
        Row(GameOptionTab.Graphics, "Advanced", "Mesh shaders", 0, 1, 1, 0, GameOptionKind.Choice, TxMesh, true, false,
            "How the game's mesh-shader draws run. Try Compute fallback on an AMD card that shows glowing walls or loses the GPU. Applies after a restart."),
        Row(GameOptionTab.System, "Game", "Text speed", 0, 3, 1, 0, GameOptionKind.Choice, TxTextSpeed, false, false,
            "How fast the letters of dialogue and other messages appear."),
        Row(GameOptionTab.System, "Game", "Game speed", 0, 1, 1, 1, GameOptionKind.Choice, TxSpeed, false, false,
            "How the game keeps time when it runs below 60 fps."),
        Row(GameOptionTab.Audio, "Sound", "Master volume", 0, 100, 5, 100, GameOptionKind.Slider, TxVolume, false, true,
            "How loud the game is, in percent of its own volume."),
        Row(GameOptionTab.Audio, "Sound", "Menu sounds", 0, 100, 5, 80, GameOptionKind.Slider, TxMenuSounds, false, true,
            "How loud these options' own sounds are, the game's interface sounds from your game files."),
        Row(GameOptionTab.Audio, "Sound", "Audio output", 0, 2, 1, 0, GameOptionKind.Choice, TxAudioOutput, true, true,
            "The speakers the game mixes its sound for. Applies after a restart."),
        Row(GameOptionTab.Audio, "Microphone", "Microphone", 0, 18, 1, 1, GameOptionKind.Choice, TxMic, false, true,
            "What the ocarina hears when the game's microphone option is on (playing an instrument, or humming)."),
        Row(GameOptionTab.System, "Online", "Discord status", 0, 1, 1, 1, GameOptionKind.Choice, TxOnoff, false, true,
            "Shows \"Playing Triforce\" and the time played in your Discord status, while Discord runs on this PC."),
        Row(GameOptionTab.Controls, "Controller", "Controller in background", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, false, false,
            "Whether the controller plays the game while another window has the focus."),
        Row(GameOptionTab.Controls, "Controller", "Left stick dead zone", -1, 50, 1, -1, GameOptionKind.Slider, TxOwnDeadZone, false, true,
            "How far the left stick moves before the game sees it, in percent of its travel on each axis: lower for a precise stick, higher for one that drifts. The game's own dead zone still follows."),
        Row(GameOptionTab.Controls, "Controller", "Right stick dead zone", -1, 50, 1, -1, GameOptionKind.Slider, TxOwnDeadZone, false, true,
            "How far the right stick moves before the game sees it, in percent of its travel on each axis: lower for a precise stick, higher for one that drifts. The game's own dead zone still follows."),
        Row(GameOptionTab.Controls, "Controller", "Camera speed", 25, 300, 5, 100, GameOptionKind.Slider, TxSens, true, true,
            "How fast the right stick turns the camera, times the game's own speed. Applies after a restart."),
        Row(GameOptionTab.Controls, "Controller", "Invert camera X", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, false, true,
            "Swaps left and right for the right stick's camera."),
        Row(GameOptionTab.Controls, "Controller", "Invert camera Y", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, false, true,
            "Swaps up and down for the right stick's camera."),
        Row(GameOptionTab.Controls, "Mouse & keyboard", "Mouse camera", 0, 1, 1, 0, GameOptionKind.Choice, TxMousecam, false, true,
            "How the captured mouse turns the camera."),
        Row(GameOptionTab.Controls, "Mouse & keyboard", "Mouse sensitivity", 10, 500, 10, 100, GameOptionKind.Slider, TxSens, false, true,
            "How far the camera turns for a mouse movement. The - and = keys change it in game too."),
        Row(GameOptionTab.Controls, "Mouse & keyboard", "Invert mouse vertical", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, false, true,
            "Swaps up and down for the mouse."),
        Row(GameOptionTab.Controls, "Mouse & keyboard", "Walk key", 0, 4, 1, 0, GameOptionKind.Choice, TxWalkKey, false, true,
            "A key that makes Link walk: held with the movement keys, they push the stick only as far as Walk scale. While it is chosen the key presses nothing else."),
        Row(GameOptionTab.Controls, "Mouse & keyboard", "Walk scale", 20, 90, 1, 51, GameOptionKind.Slider, TxSens, false, true,
            "How far the movement keys push the stick while the Walk key is held: 1.00 would be all the way."),
        Row(GameOptionTab.Controls, "Mouse & keyboard", "Menu shortcut", 0, 1, 1, 0, GameOptionKind.Choice, TxMenuShortcut, false, true,
            "Which keys open and close these options from anywhere. F1 always does; F1 only leaves Insert free for an overlay."),
        Row(GameOptionTab.Controls, "Rumble", "Rumble strength", 0, 300, 25, 100, GameOptionKind.Slider, TxRumble, false, true,
            "How strongly the controller rumbles, in percent of the game's rumble. Off turns it off."),
        Row(GameOptionTab.Controls, "Rumble", "Vibration curve", 20, 150, 5, 100, GameOptionKind.Slider, TxSens, false, true,
            "Shapes the rumble: 1.00 is the game's. Lower makes the many weak rumbles easier to feel; higher quiets them. A Switch controller's HD rumble is not changed."),
        Row(GameOptionTab.Controls, "Rumble", "Trigger vibration", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, false, true,
            "Xbox One and Series controllers: the motors in the triggers rumble too."),
        Row(GameOptionTab.Controls, "Gameplay", "Sprint button", 0, 2, 1, 0, GameOptionKind.Choice, TxSprint, false, true,
            "Link sprints from a button press, without rolling first. Left stick click: the game has no other use for it. B: sprints while Link moves (with the game's Swap Jump Controls B is the jump: use the stick's click)."),
        Row(GameOptionTab.Controls, "Gameplay", "Sprint mode", 0, 1, 1, 0, GameOptionKind.Choice, TxSprintMode, false, true,
            "Toggle: a press starts the sprint, the next press or stopping ends it. Hold: Link sprints while the button is held."),
        Row(GameOptionTab.Controls, "Motion", "Motion controls", 0, 1, 1, 1, GameOptionKind.Choice, TxGyro, false, true,
            "Aims and looks with the controller's gyroscope where the game uses motion, as on the Switch: Switch Pro controllers and pads in Switch mode, DualSense and DualShock 4."),
        Row(GameOptionTab.Controls, "Motion", "Motion sensitivity X", 10, 600, 10, 100, GameOptionKind.Slider, TxPercent, false, true,
            "How far the aim moves left and right for a turn of the controller. 100% is the console's."),
        Row(GameOptionTab.Controls, "Motion", "Motion sensitivity Y", 10, 300, 10, 100, GameOptionKind.Slider, TxPercent, false, true,
            "How far the aim moves up and down for a tilt of the controller. 100% is the console's."),
        Row(GameOptionTab.Controls, "Motion", "Invert motion X", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, false, true,
            "Swaps the motion aim's left and right."),
        Row(GameOptionTab.Controls, "Motion", "Invert motion Y", 0, 1, 1, 0, GameOptionKind.Choice, TxOnoff, false, true,
            "Swaps the motion aim's up and down."),
        Row(GameOptionTab.Controls, "Motion", "Motion deadzone", 0, 2, 1, 1, GameOptionKind.Choice, TxDeadzone, false, true,
            "How slow a turn counts as none, the console's three settings: Standard is its own. High steadies a pad that jitters; Low keeps the smallest movements."),
        Row(GameOptionTab.Controls, "Controls", "Button prompts", 0, 6, 1, 0, GameOptionKind.Choice, TxPrompts, true, true,
            "The button icons the game shows in its texts and menus: those of this controller, or the keyboard's and the mouse's."),
    };

    static readonly Dictionary<string, GameOptionRow> byKey = All.ToDictionary(r => r.Key, StringComparer.Ordinal);
    static readonly Dictionary<string, GameOptionRow> byName = All.ToDictionary(r => r.Name, StringComparer.Ordinal);

    /// <summary>The row of a key (a triforce_options.ini key, exact as the game compares them, or a merged row's own '@' key),
    /// null for any other key. A merged row's parts' keys are no row's: Part has them.</summary>
    public static GameOptionRow? ByKey(string key) => byKey.GetValueOrDefault(key);
    /// <summary>The row of a key; KeyNotFoundException for a key no row has.</summary>
    public static GameOptionRow Get(string key) => ByKey(key) ?? throw new KeyNotFoundException("no Options row has the key " + key);
    /// <summary>The row by its name as the menu shows it.</summary>
    public static GameOptionRow? ByName(string name) => byName.GetValueOrDefault(name);
    /// <summary>A tab's rows, in order.</summary>
    public static IReadOnlyList<GameOptionRow> RowsOf(GameOptionTab tab) => All.Where(r => r.Tab == tab).ToList();
    /// <summary>A tab's sections that have rows here, in order.</summary>
    public static IReadOnlyList<string> Sections(GameOptionTab tab) => RowsOf(tab).Select(r => r.Section).OfType<string>().Distinct().ToList();
    /// <summary>A key the launcher reads and writes as a value of its own line: a row's (not a merged row's), or a merged
    /// row's part.</summary>
    public static bool IsValueKey(string key) => ByKey(key) is { IsMerged: false } || Parts.ContainsKey(key);
    /// <summary>The row a file key belongs to: its own row, or the merged row a part is of (null for any other key).</summary>
    public static GameOptionRow? RowOfLine(string key) =>
        ByKey(key) is { IsMerged: false } r ? r : All.FirstOrDefault(m => m.Parts?.Any(p => p.Key == key) == true);

    // ---- the keys of the file that are not rows here ----

    /// <summary>The file's keys the launcher knowingly leaves as they are (GameOptionsFile keeps their lines, in order), and why.
    /// Besides these: every pad_* and key_* line (KeptPrefixes).</summary>
    public static readonly IReadOnlyDictionary<string, string> KeptKeys = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        [VersionKey] = "the file's format: the rules the game reads an older file by (GameOptionsFile.Save writes 8 when it brings an older file up to date)",
        [MicDeviceKey] = "the Microphone row's device, by its name: the game's to choose from the devices it lists",
        [GpuNameKey] = "the GPU device row's card by its name (11-20): Save writes it with the row; the game finds the card by it first",
        [CustomSizeKey] = "the Custom size entered before a screen's size was chosen in the game's Output resolution row: the game's to keep; GameOptionsFile empties it when it writes another Custom size, and takes it back into the rows when the Output resolution is changed",
        ["layout_preset"] = "the Controls page's Layout preset: choosing one in the game rebinds the pad_ lines, which a changed value alone would not do",
        ["debug_tools"] = "the Debug tab (not ported)",
        ["descriptor_reuse"] = "the Debug tab's Developer rows (not ported)",
        ["fast_pipeline_link"] = "the Debug tab's Developer rows (not ported)",
        ["sampler_cache"] = "the Debug tab's Developer rows (not ported)",
        ["lazy_write-back"] = "the Debug tab's Developer rows (not ported)",
        ["replay_helper_threads"] = "the Debug tab's Developer rows (not ported)",
        ["tail_early"] = "the Debug tab's Start next frame early (not ported)",
        ["opaque_textures_as_bc1"] = "the Debug tab's Developer rows (not ported)",
        ["robust_buffers"] = "the Debug tab's Developer rows from options_version 8, the Graphics tab's before (not ported)",
        ["quality_preset"] = "a row gone in options_version 8 (merged_rows.h kDropped: its memory limits are the card's own): the game reads nothing from it and drops the line at its next save",
        ["upscaling"] = "the Window scaling filter, gone in options_version 8 (the sizes choose the filter: upscaler_rows.h auto_filter): dropped at the game's next save",
        ["reflex_frame_limit"] = "a row gone in options_version 8 (off, its old default): dropped at the game's next save",
        ["handheld_profile"] = "a row gone in options_version 8: a file before 8 with it on gets the Output resolution's 1536x864 (handheld) once (GameOptionsFile), then the game drops the line",
        ["stick_dead_zone"] = "a row gone in options_version 8: a file before 8 gets its share in each stick's own dead zone that had none (GameOptionsFile), then the game drops the line",
        ["menu_size"] = "the old Menu size row, gone from the menu (the game's menus have one size): the game keeps the line and reads nothing from it",
        ["dynamic_resolution"] = "the Render resolution's old key: read once by the game where the file has no resolution line",
        ["debug_tab"] = "an old line (Alt+G's Debug tab): the game drops it at its next save",
        ["rivatuner_limit"] = "an old test builds' line: the game drops it at its next save",
        ["discord_app_id"] = "the Discord status's application, for a test application (host/discord_rpc.c): no row",
    };
    /// <summary>The binding lines of the Controls page's grid: pad_&lt;button&gt;=&lt;input&gt; and key_&lt;button&gt;=&lt;key&gt;,&lt;key&gt;.</summary>
    public static readonly IReadOnlyList<string> KeptPrefixes = new[] { "pad_", "key_" };
    /// <summary>A key that is not a value here but is known (KeptKeys, KeptPrefixes): kept in the file as it is.</summary>
    public static bool IsKept(string key) => KeptKeys.ContainsKey(key) || KeptPrefixes.Any(p => key.StartsWith(p, StringComparison.Ordinal));

    /// <summary>merged_rows.h kSharedZone: the old shared Stick dead zone's shares in percent, by its saved value (-1 XInput's
    /// own, each stick's Default), for a file before options_version 8.</summary>
    public static readonly IReadOnlyList<int> SharedZone = new[] { -1, 5, 10, 15, 20, 30 };
}
