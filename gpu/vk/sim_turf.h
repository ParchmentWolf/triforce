// ((Triforce) simulated turf, 11-24) The Graphics tab's Simulated turf page (vk_sim_turf.cpp, sim_turf_settings.h): what
// vk_menu.cpp's rows and vk_draw.cpp's turf lists ask of it
#pragma once
#include <array>
#include <cstdint>
#include <string>

namespace mkwvk {
namespace sim_turf_settings {
// (the page's rows' values, on the menu's thread: Use global multipliers; the four multipliers in tenths; the area's four values)
extern int global;
extern std::array<int, 4> multipliers;
extern std::array<int, 4> values;
}  // namespace sim_turf_settings

/// The page's file, sim_turf_settings.ini beside the options file (options_ini: its path), read once at the menu's start
void sim_turf_init(const std::string& options_ini);
/// Each menu tick (the menu's thread): the rows' changes applied, the area followed, the file kept; true: draw the page again
bool sim_turf_tick(int64_t now);
void sim_turf_flush();   // (the file written now, when anything is waiting)
bool sim_turf_ready();   // (an area is loaded whose turf the page can change)
bool sim_turf_can_reset();   // (Reset current area has edits to take away)
bool sim_turf_reset();   // (Reset current area)
/// The host's word of the area (vk_menu.cpp menu_option_set: HOS_OPT_SIM_TURF_AREA_TEXT, a byte a call; HOS_OPT_SIM_TURF_AREA, the end)
void sim_turf_area_byte(int c);
void sim_turf_area_end(int said);
/// Whether the page changes the turf of the area loaded now: the renderer's own turf lists are then in use (vk_draw.cpp
/// sim_turf_private_on). Any thread
bool sim_turf_edited();
/// The rows' words: a multiplier (tenths), Fade start (tenths of a metre), a plain number, Far power (hundredths)
const char* sim_turf_text_multiplier(int v);
const char* sim_turf_text_fade(int v);
const char* sim_turf_text_count(int v);
const char* sim_turf_text_power(int v);
const char* sim_turf_area_note();
}  // namespace mkwvk
