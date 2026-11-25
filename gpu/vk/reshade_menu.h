// ((Triforce) 11-24) The Graphics tab's Post-processing group: the ReShade preset row and the rows that go with it, and the
// preset's comparison (the options hidden but a bar at the foot of the screen, the game seen whole with the preset on or off,
// each preset tried in turn; Back puts the saved one back). Included by vk_menu.cpp alone, after the headers it needs: the rows
// themselves are in its table (rows[]), which calls these. The presets run in reshade/fx_runtime.cpp
#pragma once
#include <algorithm>
#include <string>
#include <vector>

#include "reshade/fx_builtin.h"
#include "reshade/fx_runtime.h"
#include "vk_menu.h"
#include "vk_menu_hit.h"
#include "vk_ui.h"

namespace mkwvk {

void reshade_user_rows(int hi);   // (vk_menu.cpp: the User preset file row's last choice, its files' count)

// (the two rows that act: their names, which the rows and the menu's presses compare by address, as kTestMic's)
constexpr const char* kReshadeCompare = "Compare ReShade Preset";
constexpr const char* kReshadeRescan = "Rescan ReShade presets";

namespace reshade_menu {

constexpr const char* kCompare = kReshadeCompare;
constexpr const char* kRescan = kReshadeRescan;

// (the User preset file row: 1 + its file's place in user_names, 0 none. The file itself is reshade/selected.txt, the
// runtime's: this number only places the row on it, filled from that file when the row is first shown. Not kept in the
// options file: ini_row)
inline int user_pick = 0;
inline std::vector<std::string> user_names;
inline bool user_listed = false;   // (user_names read: at the row's first showing, then again by each Rescan)

/// The ReShade preset row's choices, in the order of their numbers (reshade/fx_builtin.h: the Clarity looks last)
inline const std::vector<const char*>& preset_choices() {
    static const auto choices = [] {
        std::vector<const char*> values{"Off", "Warm", "Cool", "User", "HDR Vibrance", "Depth View", "Depth Haze"};
        for (const auto& preset : reshade::clarity_presets) values.push_back(preset.name);
        return values;
    }();
    return choices;
}
inline const char* tx_preset(int v) {
    const auto& t = preset_choices();
    return t[(size_t)std::clamp(v, 0, (int)t.size() - 1)];
}
/// (under the help: what the preset does now, the runtime's line. Nothing for Off, nor for the menu's height)
inline const char* hn_preset(int v, int variant) {
    static thread_local std::string hint;
    if (!v || variant >= 0) return nullptr;
    hint = reshade::status();
    return hint.empty() ? nullptr : hint.c_str();
}

inline void list_user_presets() {
    user_names = reshade::user_presets();
    const auto current = std::ranges::find(user_names, reshade::user_selection());
    user_pick = current == user_names.end() ? 0 : static_cast<int>(current - user_names.begin()) + 1;
    reshade_user_rows(static_cast<int>(user_names.size()));
    user_listed = true;
}
/// The User preset file row's text: the file chosen (the list read at the row's first showing, the row put on the file in use)
inline const char* tx_user(int choice) {
    static std::string text;
    if (!user_listed) list_user_presets();
    text = choice > 0 && static_cast<size_t>(choice) <= user_names.size() ? user_names[(size_t)choice - 1] : "Choose a preset";
    return text.c_str();
}
/// (set_row: the ReShade preset row changed)
inline void preset_chosen() { reshade::select(opts.reshade); }
/// (set_row: the User preset file row changed: its file into reshade/selected.txt, and the preset again if it is the one in use)
inline void user_picked() {
    if (user_pick > 0 && static_cast<size_t>(user_pick) <= user_names.size()) {
        reshade::select_user(user_names[(size_t)user_pick - 1]);
        if (opts.reshade == reshade::user_preset) reshade::select(reshade::user_preset);
    }
}
/// (row_shown: the User preset file and Rescan rows with User chosen)
inline bool user_row(const char* name, const int* value) {
    return value == &user_pick || name == kRescan;
}

// ---- the comparison ----
enum CompareControl { Enabled, Back, Preset, UserFile };
struct Comparison {
    bool open = false;
    bool enabled = true;
    CompareControl focus = Enabled;
    int preset = 1;
    bool files_scanned = false;
    std::vector<std::string> files;
    size_t file = 0;
    bool has_user_row() const { return preset == reshade::user_preset; }
};
inline Comparison comparison;

inline void preview_preset() {
    std::string name;
    if (comparison.has_user_row()) {
        if (!comparison.files_scanned) {
            comparison.files = reshade::user_presets();
            const auto current = std::ranges::find(comparison.files, reshade::user_selection());
            if (current != comparison.files.end()) comparison.file = (size_t)(current - comparison.files.begin());
            comparison.files_scanned = true;
        }
        if (!comparison.files.empty()) name = comparison.files[comparison.file];
    }
    reshade::preview_select(comparison.preset, std::move(name));
    logf("vk: ReShade comparison preset %d, user file %zu/%zu", comparison.preset,
         comparison.has_user_row() && !comparison.files.empty() ? comparison.file + 1 : 0,
         comparison.has_user_row() ? comparison.files.size() : 0);
}
inline void start_comparison() {
    comparison = {};
    comparison.open = true;
    comparison.enabled = opts.reshade != 0;
    comparison.preset = std::clamp(opts.reshade, 1, reshade::last_builtin_preset);
    reshade::preview_bypass(!comparison.enabled);
    preview_preset();
    logf("vk: ReShade comparison opened");
}
inline bool comparing() { return comparison.open; }
/// (closed: by its Back, or by the options shutting another way) the saved preset again
inline void end_comparison() {
    if (!comparison.open) return;
    comparison.open = false;
    reshade::preview_end(opts.reshade);
    logf("vk: ReShade comparison closed");
}

/// A row of the group that acts when confirmed (menu_tick): the comparison opened, or the user presets read again. false: not one
inline bool act(const char* name) {
    if (name == kCompare) return start_comparison(), true;
    if (name == kRescan) {
        list_user_presets();
        if (opts.reshade == reshade::user_preset) reshade::select(reshade::user_preset);
        return true;
    }
    return false;
}
/// Its button's word (draw_options), nullptr for another row
inline const char* action_label(const char* name) { return name == kCompare ? "Compare" : name == kRescan ? "Rescan" : nullptr; }

/// The comparison's keys and clicks: horizontal -1 left, 1 right; vertical -1 up, 1 down. true: something changed
inline bool update_comparison(int horizontal, int vertical, bool confirm, bool cancel, const menu_hit::Hit& click) {
    auto next = comparison.focus;
    const bool clicked = click.part == menu_hit::kButton && click.index >= Enabled &&
                         click.index <= (comparison.has_user_row() ? UserFile : Preset);
    if (clicked) {
        next = static_cast<CompareControl>(click.index);
        horizontal = click.side;
        confirm = true;
    } else if (vertical) {
        const int rows = comparison.has_user_row() ? 3 : 2;
        const int row = next >= Preset ? next - Preset + 1 : 0;
        const CompareControl first[] = {Enabled, Preset, UserFile};
        next = first[(row + vertical + rows) % rows];
        horizontal = 0;
    } else if (horizontal && next < Preset) {
        next = horizontal > 0 ? Back : Enabled;
    }
    if (cancel || (confirm && next == Back)) return end_comparison(), true;
    const bool moved = next != comparison.focus;
    comparison.focus = next;
    if (next == Enabled && confirm) {
        comparison.enabled = !comparison.enabled;
        reshade::preview_bypass(!comparison.enabled);
        logf("vk: ReShade comparison: %s", comparison.enabled ? "Enabled" : "Disabled");
        return true;
    }
    if (next == Preset && horizontal) {
        const int count = reshade::last_builtin_preset;
        comparison.preset = 1 + (comparison.preset - 1 + horizontal + count) % count;
        preview_preset();
        return true;
    }
    if (next == UserFile && horizontal && comparison.files.size() > 1) {
        const size_t count = comparison.files.size();
        comparison.file = (comparison.file + (horizontal > 0 ? 1 : count - 1)) % count;
        preview_preset();
        return true;
    }
    return moved;
}

/// The comparison's bar at the foot of the window, in the window's pixels (c), its controls into hits
inline void draw_comparison(ui::Ctx& c, menu_hit::Map& hits) {
    const float s = c.s, width = std::min(660.0f * s, c.w - 2 * c.safe);
    const float row = 34 * s, gap = 5 * s;
    const float height = (row + gap) * (comparison.has_user_row() ? 3 : 2) + gap;
    const float x = (c.w - width) * 0.5f, y = c.h - c.safe - height;
    const ImVec2 start(x, y), end(x + width, y + height);
    c.d->AddRectFilled(start, end, ui::kBox, 4 * s);
    c.d->AddRect(start, end, ui::kEdge, 4 * s);
    hits.clear(start.x, start.y, end.x, end.y);
    c.d->PushClipRect(start, end, true);
    auto control = [&](CompareControl id, ImVec2 a, ImVec2 b, const char* label, bool arrows = false) {
        const bool focused = id == comparison.focus;
        if (focused) ui::gold(c, a, b);
        else c.d->AddRectFilled(a, b, ui::kCellName);
        c.d->AddRect(a, b, focused ? ui::kGoldHi : ui::kEdge, 0, std::max(1.0f, s));
        const ImU32 ink = focused ? ui::kGoldInk : ui::kInk;
        const float arrow = arrows ? std::min(38 * s, (b.x - a.x) * 0.22f) : 0;
        c.d->PushClipRect(ImVec2(a.x + arrow, a.y), ImVec2(b.x - arrow, b.y), true);
        ui::text_mid_centre(c, c.f.strong, 16 * s, (a.x + b.x) * 0.5f, (a.y + b.y) * 0.5f, ink, label);
        c.d->PopClipRect();
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, id);
        if (arrows) {
            const float mid = (a.y + b.y) * 0.5f;
            ui::text_mid_centre(c, c.f.strong, 18 * s, a.x + arrow * 0.5f, mid, ink, "<");
            ui::text_mid_centre(c, c.f.strong, 18 * s, b.x - arrow * 0.5f, mid, ink, ">");
            hits.add(a.x, a.y, a.x + arrow, b.y, menu_hit::kButton, id, 0, 0, 0, 0, -1);
            hits.add(b.x - arrow, a.y, b.x, b.y, menu_hit::kButton, id, 0, 0, 0, 0, 1);
        }
    };
    const float top = y + gap, middle = x + width * 0.5f;
    control(Enabled, {x + gap, top}, {middle - gap * 0.5f, top + row}, comparison.enabled ? "Enabled · On" : "Enabled · Off");
    control(Back, {middle + gap * 0.5f, top}, {end.x - gap, top + row}, "Back");
    const float second = top + row + gap;
    control(Preset, {x + gap, second}, {end.x - gap, second + row}, tx_preset(comparison.preset), true);
    if (comparison.has_user_row()) {
        const float third = second + row + gap;
        const auto& files = comparison.files;
        const char* label = files.empty() ? "No user presets" : files[comparison.file].c_str();
        control(UserFile, {x + gap, third}, {end.x - gap, third + row}, label, files.size() > 1);
    }
    c.d->PopClipRect();
    if (comparison.enabled && (!comparison.has_user_row() || !comparison.files.empty())) {
        const auto status = reshade::status();
        if (!status.empty() && !status.starts_with("Ready")) {
            const ImVec2 a(x, y - 28 * s), b(end.x, y - gap);
            c.d->AddRectFilled(a, b, ui::kBox, 4 * s);
            c.d->PushClipRect(a, b, true);
            ui::text_mid_centre(c, c.f.body, 13 * s, middle, (a.y + b.y) * 0.5f, ui::kSoft, status.c_str());
            c.d->PopClipRect();
        }
    }
}

}  // namespace reshade_menu
}  // namespace mkwvk
