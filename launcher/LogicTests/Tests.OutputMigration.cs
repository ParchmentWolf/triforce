using Triforce.Logic;
using static Triforce.LogicTests.T;

namespace Triforce.LogicTests;

static partial class Tests
{
    static void OutputMigration()
    {
        foreach (var (name, text, output) in new[]
        {
            ("launcher-profile", "handheld_profile=1\noptions_version=9\n", 7),
            ("stock-stale-profile", "output_res=1\nhandheld_profile=1\noptions_version=8\n", 1),
            ("stock-handheld", "output_res=7\noptions_version=8\n", 7),
            ("stock-wide", "output_res=4\nultrawide=2\noptions_version=8\n", 1),
            ("native-screen", "output_res=7\noutput_width=2560\noutput_height=1440\noptions_version=8\n", 8),
            ("native-wide", "output_res=4\nultrawide=2\noutput_width=2560\noutput_height=1440\noptions_version=8\n", 4),
            ("player", "output_res=8\noutput_width=3840\noutput_height=1600\noutput_custom_size=2560x1440\nultrawide=2\noptions_version=8\n", 9),
        })
        {
            var folder = NewGameFolder("migration-" + name, text);
            var file = GameOptionsFile.Load(folder, (3840, 1600));
            Equal(output, file.Get("output_res"), name + " read");
            file.Set("sharpness", 25);
            file.Save();
            var again = GameOptionsFile.Load(folder, (3840, 1600));
            Equal(9, again.Version, name + " version");
            Equal(output, again.Get("output_res"), name + " round trip");
            if (name == "player")
            {
                Equal(3840, again.Get("output_width"), "player active width");
                Equal(1600, again.Get("output_height"), "player active height");
                Check(File.ReadAllText(again.Path).Contains("output_custom_size=2560x1440"), "remembered pair retained");
            }
        }
        var handheld = GameOptionsFile.Load(NewGameFolder("migration-handheld", "output_res=7\nhandheld_profile=1\noptions_version=9\n"));
        handheld.Set("output_res", 0);
        handheld.Save();
        Equal(0, GameOptionsFile.Load(Path.GetDirectoryName(handheld.Path)!).Get("output_res"), "leaving native handheld round trip");
        Check(File.ReadAllText(handheld.Path).Contains("handheld_profile=0"), "old native profile follows the output row");
    }
}
