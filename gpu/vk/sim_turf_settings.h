// ((Triforce) simulated turf, 11-24) The Simulated turf page's state and its edits of the game's turf resource
// (vk_sim_turf.cpp includes it once; tests/sim_turf_settings_test.cpp includes it over a small host stand-in).
//
// The large-scale simulated turf (the broad field grass the game's fluid simulation moves: the carpet that bends around Link)
// is set by a resource of each area's: its fade start, density, fewest blades and far power, four words of it, each with a
// flag saying the area has its own value (else its parent's). The page shows the area's values and changes them in the
// game's memory while the area is loaded; sim_turf_settings.ini (beside triforce_options.ini) keeps each area's edits, and
// the global multipliers that scale every area's own values instead. Nothing is written while no edit asks for it: an area
// without one keeps the game's values (and a value written by the page is put back to the game's own when its edit goes).
// Fade start 0 and Minimum blades 0 leave an area no simulated turf, for slower PCs. The renderer's own turf lists take what
// more an edit asks for (vk_draw.cpp sim_turf_private_binding, while edited() says so).
// The area is the map's name, which the host says (vk_menu.cpp menu_option_set, HOS_OPT_SIM_TURF_AREA)
#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iomanip>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>

namespace mkwvk::sim_turf_settings {

struct Field {
    uint64_t offset, flag;   // (the value's and its own-value flag's place in the resource)
    int scale, minimum, maximum;   // (the row's steps: value * scale)
    bool integer;
};
constexpr Field fields[] = {
    {0x7c, 0xb0, 10, 0, 649, false},   // Fade start (m, 0.1 steps)
    {0x68, 0x9c, 1, 1, 500, false},    // Turf density (a divisor in the game's programs: higher is sparser)
    {0x70, 0x9d, 1, 0, 128, true},     // Minimum blades
    {0x6c, 0xb1, 100, 0, 400, false},  // Far power (0.01 steps)
};
constexpr size_t count = std::size(fields);
constexpr uint64_t vtable = 0x84b43228;   // (the resource's type)
constexpr int one = 10, max_factor = 100;   // (the multipliers in tenths: 10 is 1.0x)
constexpr char area_note[] = "Each area has its own values. Go to an area to tune its simulated turf. Changes are kept at once.";

// (the page's rows' values: vk_menu.cpp's Simulated turf rows point at them; the menu's thread alone reads and writes them)
int global = 0;
std::array<int, count> multipliers{one, one, one, one};
std::array<int, count> values{};

struct Preset {
    unsigned changed = 0;   // (a bit a field: the area's own edit)
    std::array<int, count> values{};
};
std::map<std::string, Preset> presets;
bool ready = false;
bool config_dirty = false;
bool save_failed = false;
int64_t dirty_at = 0;
std::string config_file;   // (sim_turf_settings.ini, beside the options file: init)
std::atomic<bool> edited_now{false};   // (an edit applies to the area loaded now: the renderer's turf lists, edited())

// (the area Link is in, as the host last said it: menu_option_set's thread writes it, tick reads it)
std::mutex area_mu;
std::string area_said, area_text;

/// The host's word, a byte a call, then the end (said: 1 a name, 0 no map)
inline void area_byte(int c) {
    std::lock_guard lk(area_mu);
    if (c > 0 && c < 256 && area_text.size() < 96) area_text += (char)c;
}
inline void area_end(int said) {
    std::lock_guard lk(area_mu);
    area_said = said ? area_text : std::string{};
    area_text.clear();
}
inline std::string area_now() {
    std::lock_guard lk(area_mu);
    return area_said;
}

template <class T> bool read(uint64_t address, T& out) {
    if (!host || !host->guest_base || !host->guest_size) return false;
    const uint64_t size = host->guest_size();
    if (size < sizeof(T) || address > size - sizeof(T)) return false;
#ifdef _WIN32
    SIZE_T got = 0;   // (a page the game has not committed: no fault)
    return ReadProcessMemory(GetCurrentProcess(), host->guest_base() + address, &out, sizeof(T), &got) && got == sizeof(T);
#else
    // (on Linux the guest window is one mapping that stays readable: decommitted pages read as zero, host/posix/win32_posix.c)
    std::memcpy(&out, host->guest_base() + address, sizeof(T));
    return true;
#endif
}

template <class T> bool write(uint64_t address, const T& value) {
    if (!host || !host->guest_base || !host->guest_size) return false;
    const uint64_t size = host->guest_size();
    if (size < sizeof(T) || address > size - sizeof(T)) return false;
    uint8_t* target = host->guest_base() + address;
#ifdef _WIN32
    SIZE_T wrote = 0;
    if (!WriteProcessMemory(GetCurrentProcess(), target, &value, sizeof(T), &wrote) || wrote != sizeof(T)) return false;
#else
    std::memcpy(target, &value, sizeof(T));
#endif
    if (host->mark_written) host->mark_written(target, sizeof(T));
    return true;
}

struct Scene {
    uint64_t address = 0, identity = 0;
    bool operator==(const Scene&) const = default;
};

/// The turf resource of the area loaded now: the game's manager, its native part, the holder, the resource of the right type
inline Scene scene() {
    uint64_t manager = 0, native = 0, holder = 0, resource = 0, type = 0, identity = 0;
    if (!read(0x84e42540, manager) || !manager || !read(manager + 0xf0, native) || !native ||
        !read(native + 0x2a90, holder) || !holder || !read(holder + 0x150, resource) || !resource ||
        !read(resource, type) || type != vtable || !read(resource + 8, identity)) return {};
    return {resource, identity};
}

struct Location {
    Scene scene;
    std::string area;
    bool operator==(const Location&) const = default;
};
Location location;

inline Location observe() {
    const Scene current = scene();
    if (!current.address) return {};
    std::string area = area_now();
    return area.empty() ? Location{} : Location{current, std::move(area)};
}

struct Word {
    uint32_t value = 0;
    uint8_t flag = 0;
    bool operator==(const Word&) const = default;
};
struct Resource {
    Scene scene;
    std::array<Word, count> original{}, applied{};
    std::array<double, count> baseline{};
};
std::unordered_map<uint64_t, Resource> resources;

inline bool read_word(uint64_t address, const Field& field, Word& word) {
    return read(address + field.offset, word.value) && read(address + field.flag, word.flag);
}

/// The resource a value without its own flag comes from: its parent, through the handle and its generation
inline uint64_t parent(uint64_t address) {
    uint64_t handle = 0, link = 0, found = 0, type = 0;
    uint32_t generation = 0, linked_generation = 0;
    if (!read(address + 0x10, handle) || !handle || !read(address + 0x18, link) || !link ||
        !read(address + 0x20, generation) || !read(link + 0xc, linked_generation) || generation != linked_generation ||
        !read(link, found) || !found || !read(found, type) || type != vtable) return 0;
    return found;
}

inline double original_value(uint64_t address, const Field& field, Word word) {
    for (int depth = 0; depth < 8 && !(word.flag & 1); ++depth) {
        const uint64_t inherited_from = parent(address);
        Word inherited;
        if (!inherited_from || inherited_from == address || !read_word(inherited_from, field, inherited)) break;
        address = inherited_from;
        word = inherited;
    }
    if (field.integer) return static_cast<int32_t>(word.value);
    float value = 0;
    std::memcpy(&value, &word.value, sizeof value);
    return value;
}

inline bool capture(const Scene& current) {
    std::array<Word, count> observed;
    for (size_t i = 0; i < count; ++i)
        if (!read_word(current.address, fields[i], observed[i])) return false;
    if (!(scene() == current)) return false;
    // (a map can use a resource it had again: the game's values are kept for the fields that still hold the page's writes)
    Resource& resource = resources[current.address];
    for (size_t i = 0; i < count; ++i) {
        if (!(resource.scene == current) || !(observed[i] == resource.applied[i])) {
            resource.original[i] = observed[i];
            resource.baseline[i] = original_value(current.address, fields[i], observed[i]);
        }
    }
    resource.scene = current;
    resource.applied = observed;
    return true;
}

inline void load_config() {
    FILE* f = config_file.empty() ? nullptr : std::fopen(config_file.c_str(), "rb");
    if (!f) return;
    std::string text;
    char buf[4096];
    for (size_t n; (n = std::fread(buf, 1, sizeof buf, f)) > 0;) text.append(buf, n);
    std::fclose(f);
    std::istringstream in(text);
    std::string key;
    int version = 0;
    if (!(in >> key >> version) || key != "version" || version != 1) return;
    while (in >> key) {
        if (key == "global") {
            int enabled = 0;
            auto factors = multipliers;
            if (!(in >> enabled >> factors[0] >> factors[1] >> factors[2] >> factors[3])) break;
            global = enabled == 1;
            for (size_t i = 0; i < count; ++i) multipliers[i] = std::clamp(factors[i], 0, max_factor);
        } else if (key == "area") {
            std::string area;
            Preset preset;
            auto& v = preset.values;
            if (!(in >> std::quoted(area) >> preset.changed >> v[0] >> v[1] >> v[2] >> v[3])) break;
            if (area.empty() || area.size() >= 100 || preset.changed >= (1u << count)) continue;
            for (size_t i = 0; i < count; ++i) v[i] = std::clamp(v[i], fields[i].minimum, fields[i].maximum);
            presets[std::move(area)] = preset;
        } else {
            std::getline(in, key);
        }
    }
}

inline void mark_dirty() {
    config_dirty = true;
    dirty_at = host && host->now_ns ? host->now_ns() : 0;
}

bool write_config(const std::string& path, const std::string& text);   // (vk_sim_turf.cpp: file_whole.h; the test's own)

inline void flush_config() {
    if (!config_dirty) return;
    if (config_file.empty()) {
        save_failed = true;
        return;
    }
    std::ostringstream out;
    out << "version 1\nglobal " << global;
    for (const int factor : multipliers) out << ' ' << factor;
    out << '\n';
    for (const auto& [area, preset] : presets) {
        out << "area " << std::quoted(area) << ' ' << preset.changed;
        for (const int value : preset.values) out << ' ' << value;
        out << '\n';
    }
    save_failed = !write_config(config_file, out.str());
    if (!save_failed) {
        config_dirty = false;
        return;
    }
    logf("simulated turf: could not save %s", config_file.c_str());
}

inline bool matches() { return ready && observe() == location; }

inline std::array<double, count> scaled(const std::array<double, count>& base) {
    const auto factor = [](size_t i) { return double(multipliers[i]) / one; };
    // (the density divides the programs' density terms: a large divisor stands for none)
    const double density = multipliers[1] == 0 ? std::max(base[1], 1'000'000.0) : std::max(1.0, base[1] / factor(1));
    return {std::clamp(base[0] * factor(0), 0.0, 64.9), density, std::clamp(std::round(base[2] * factor(2)), 0.0, 128.0),
            std::clamp(base[3] * factor(3), 0.0, 20.0)};
}

inline const Preset& area_preset() {
    static constexpr Preset defaults;
    const auto saved = presets.find(location.area);
    return saved == presets.end() ? defaults : saved->second;
}

inline bool can_reset_area() { return ready && !global && area_preset().changed != 0; }

/// Whether an edit changes the turf of the area loaded now (global multipliers not all 1.0x, or the area's own edits)
inline bool edits_area() {
    if (!ready) return false;
    if (global) return multipliers != std::array<int, count>{one, one, one, one};
    return area_preset().changed != 0;
}

inline void apply() {
    if (!matches()) return;
    Resource& resource = resources.at(location.scene.address);
    const Preset& preset = area_preset();
    const auto adjusted = scaled(resource.baseline);
    for (size_t i = 0; i < count; ++i) {
        const Field& field = fields[i];
        Word target = resource.original[i];
        const bool edit = global ? multipliers[i] != one : (preset.changed & (1u << i)) != 0;
        const double value = global ? adjusted[i] : double(preset.values[i]) / field.scale;
        if (edit && std::isfinite(value) && (!global || (std::isfinite(resource.baseline[i]) && (i != 1 || resource.baseline[i] > 0)))) {
            if (field.integer) target.value = static_cast<uint32_t>(value);
            else {
                const float real = static_cast<float>(value);
                std::memcpy(&target.value, &real, sizeof real);
            }
            target.flag |= 1;
        }
        if (target == resource.applied[i] || !(scene() == location.scene)) continue;
        const uint64_t address = resource.scene.address;
        if (!write(address + field.offset, target.value)) continue;
        if (write(address + field.flag, target.flag)) resource.applied[i] = target;
        else if (scene() == location.scene) write(address + field.offset, resource.applied[i].value);
    }
    edited_now.store(edits_area(), std::memory_order_relaxed);
}

inline void display_values() {
    if (!ready) return;
    const auto& stock = resources.at(location.scene.address).baseline;
    const Preset& preset = area_preset();
    for (size_t i = 0; i < count; ++i) {
        const Field& field = fields[i];
        const double base = std::isfinite(stock[i]) ? stock[i] * field.scale : field.minimum;
        values[i] = preset.changed & (1u << i) ? preset.values[i]
                                               : int(std::lround(std::clamp(base, double(field.minimum), double(field.maximum))));
    }
}

/// Reset current area: the area's edits gone, its own values back (true: done)
inline bool reset_area() {
    if (!can_reset_area() || !matches()) return false;
    auto previous = presets.extract(location.area);
    mark_dirty();
    flush_config();
    if (save_failed) {
        presets.insert(std::move(previous));
        return false;
    }
    display_values();
    apply();
    return true;
}

/// Every 250 ms: the area followed (a new one taken once the same for 750 ms), the file kept. True when the page's rows changed
inline bool tick(int64_t now) {
    if (config_dirty && (!dirty_at || now - dirty_at >= 250'000'000)) flush_config();
    static int64_t next_sample = 0, stable_since = 0;
    static Location candidate;
    if (now < next_sample) return false;
    next_sample = now + 250'000'000;
    const Location observed = observe();
    if (!(observed == candidate)) {
        candidate = observed;
        stable_since = now;
        const bool was_ready = ready;
        ready = false;
        if (!observed.scene.address) location = {};
        edited_now.store(false, std::memory_order_relaxed);
        return was_ready;
    }
    if (!observed.scene.address || now - stable_since < 750'000'000 || ready) return false;
    if (!capture(candidate.scene)) return false;
    if (!(location == candidate)) {
        location = candidate;
        logf("simulated turf: %s (%s)", location.area.c_str(),
             global ? "global multipliers" : area_preset().changed ? "this area's own edits" : "the game's values");
    }
    ready = true;
    display_values();
    apply();
    return true;
}

inline void mode_changed() {
    if (ready && !global) display_values();
    mark_dirty();
    apply();
}

inline void multiplier_changed() {
    mark_dirty();
    apply();
}

inline void area_changed(size_t index) {
    if (!matches() || index >= count) return;
    Preset& preset = presets[location.area];
    preset.changed |= 1u << index;
    preset.values[index] = values[index];
    mark_dirty();
    apply();
}

inline std::string decimal(int value, int scale, int decimals, bool multiplier = false) {
    if (!multiplier && !ready) return "Go to an area";
    char text[24];
    snprintf(text, sizeof text, "%.*f%s", decimals, double(value) / scale, multiplier ? "x" : "");
    return text;
}

}  // namespace mkwvk::sim_turf_settings
