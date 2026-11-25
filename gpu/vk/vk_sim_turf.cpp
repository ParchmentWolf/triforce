// ((Triforce) simulated turf, 11-24) The Graphics tab's Simulated turf page (sim_turf.h): the page's state and edits are
// sim_turf_settings.h's, its rows vk_menu.cpp's. The rows' values are changed by the menu (arrows, the mouse, a drag): each
// tick takes what changed since the last one and applies it, so no row needs a hook of its own
#include <array>
#include <cstdint>
#include <cstdio>
#include <string>

#include "vk_loader.h"
#include "vk_api.h"
#include "vk_internal.h"
#include "file_whole.h"
#include "sim_turf.h"
#include "sim_turf_settings.h"   // (its one inclusion in the renderer)

namespace mkwvk {
namespace sim_turf_settings {
bool write_config(const std::string& path, const std::string& text) { return file_writers::write_whole(path, text); }
}  // namespace sim_turf_settings

namespace {
namespace st = sim_turf_settings;
int seen_global = 0;
std::array<int, st::count> seen_multipliers{st::one, st::one, st::one, st::one}, seen_values{};
void seen_now() { seen_global = st::global, seen_multipliers = st::multipliers, seen_values = st::values; }
}  // namespace

void sim_turf_init(const std::string& options_ini) {
    const size_t slash = options_ini.find_last_of("\\/");
    st::config_file = (slash == std::string::npos ? std::string{} : options_ini.substr(0, slash + 1)) + "sim_turf_settings.ini";
    st::load_config();
    seen_now();
}

bool sim_turf_tick(int64_t now) {
    bool redraw = false;
    // (what the rows changed since the last tick: the mode, a multiplier, an area's value (only while an area is loaded:
    // otherwise the row goes back, as it is locked))
    if (st::global != seen_global) st::mode_changed(), redraw = true;
    for (size_t i = 0; i < st::count; ++i)
        if (st::multipliers[i] != seen_multipliers[i]) st::multipliers[i] = std::clamp(st::multipliers[i], 0, st::max_factor), st::multiplier_changed();
    for (size_t i = 0; i < st::count; ++i)
        if (st::values[i] != seen_values[i]) {
            if (st::matches()) {
                st::values[i] = std::clamp(st::values[i], st::fields[i].minimum, st::fields[i].maximum);
                st::area_changed(i);
            } else {
                st::values[i] = seen_values[i], redraw = true;
            }
        }
    redraw |= st::tick(now);
    seen_now();
    return redraw;
}

void sim_turf_flush() { st::flush_config(); }
bool sim_turf_ready() { return st::ready; }
bool sim_turf_can_reset() { return st::can_reset_area(); }
bool sim_turf_reset() {
    const bool done = st::reset_area();
    seen_now();
    return done;
}
void sim_turf_area_byte(int c) { st::area_byte(c); }
void sim_turf_area_end(int said) { st::area_end(said); }
bool sim_turf_edited() { return st::edited_now.load(std::memory_order_relaxed); }

namespace {
const char* keep_text(const std::string& s) {
    static thread_local char text[32];
    snprintf(text, sizeof text, "%s", s.c_str());
    return text;
}
}  // namespace
const char* sim_turf_text_multiplier(int v) { return keep_text(st::decimal(v, 10, 1, true)); }
const char* sim_turf_text_fade(int v) { return keep_text(st::decimal(v, 10, 1)); }
const char* sim_turf_text_count(int v) { return keep_text(st::decimal(v, 1, 0)); }
const char* sim_turf_text_power(int v) { return keep_text(st::decimal(v, 100, 2)); }
const char* sim_turf_area_note() { return st::area_note; }
}  // namespace mkwvk
