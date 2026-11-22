/* Which GPU the Insert menu's GPU device row asks for (vk_main.cpp's pick_device). RX_VK_DEVICE, when set, wins over it
   there. */
#pragma once

#include <cctype>
#include <string>
#include <vector>

namespace mkwvk::gpu_choice {

/// The row's choice as a position in the Vulkan 1.3 devices (0-based), or -1 for Auto. menu: opts.gpu_device (0 Auto,
/// n the n-th usable device); usable: how many there are now. A choice past them (a GPU taken out since) is Auto.
inline int menu_device(int menu, int usable) { return menu > 0 && menu <= usable ? menu - 1 : -1; }

/// ((Triforce) 11-20) A device's name as the choice compares it: lower case, every run of white space one space, none at
/// either end. Windows and Vulkan name the same card alike but not always to the space ("AMD  Radeon RX 7800 XT" from one
/// AMD driver, "AMD Radeon RX 7800 XT" from the other)
inline std::string name_key(const std::string& s) {
    std::string out;
    bool space = false;
    for (unsigned char c : s) {
        if (std::isspace(c) || c < 0x20) { space = !out.empty(); continue; }
        if (space) out += ' ', space = false;
        out += (char)std::tolower(c);
    }
    return out;
}

/// ((Triforce) 11-20, tickets "iGPU used on laptop with dGPU to compile shaders", "Launcher choosing the wrong GPU when
/// compiling shaders" and two more) The device a choice means: by its name when one was saved (triforce_options.ini
/// gpu_device_name, which the launcher and the menu write with the number), else by the number as before (menu_device).
/// The launcher numbered the cards in Windows' order before the game had ever run (no triforce_gpus.txt yet), and Vulkan's
/// is often the other way round on a laptop: its "2: RTX 5060" was the game's 2, the 860M, and the build prepared every
/// shader there. A name that matches several cards (two of the same) takes the numbered one when its name is that name,
/// else the first. No name, or none matching (the card taken out): the number decides. Auto (menu 0) is Auto whatever name
/// the file still has. names: the usable devices' names in the game's order. Returns a position in them (0-based) or -1 for Auto
inline int pick(const std::string& want, const std::vector<std::string>& names, int menu) {
    if (menu <= 0) return -1;   // (Auto: a name left in the file chooses nothing)
    const std::string key = name_key(want);
    if (!key.empty()) {
        const int numbered = menu_device(menu, (int)names.size());
        if (numbered >= 0 && name_key(names[(size_t)numbered]) == key) return numbered;
        for (size_t i = 0; i < names.size(); i++)
            if (name_key(names[i]) == key) return (int)i;
    }
    return menu_device(menu, (int)names.size());
}

/// ((Triforce) 11-22, tickets "igpu targeted for shader cache", "Launcher \"GPU device\" setting is non-functional" (RX 6600
/// with a Ryzen 5600G's graphics) and on 0.6.0 "still picking IGPU for building shaders") The choice that pick takes by its
/// number alone (no saved name, or a name no card has here) when that number is the processor's graphics while a card of its
/// own is listed: not taken, Auto instead. Such a number comes from an options file written before 11-20, when the launcher
/// numbered the cards in Windows' order (the display class's driver keys: the processor graphics' driver first on a 5600G)
/// and saved no name with it; the update to 0.6.0 still prepared its shaders there and the game started there, as no name
/// came with the number until the row was chosen again. A choice saved with its name (the launcher and the menu since 11-20)
/// is taken as it is, the processor graphics too. types: the usable devices' VkPhysicalDeviceType (1 integrated, 2 discrete),
/// in the game's order, as names
inline bool unnamed_integrated(const std::string& want, const std::vector<std::string>& names, const std::vector<int>& types,
                               int menu) {
    const int k = pick(want, names, menu);
    if (k < 0 || (size_t)k >= types.size() || types[(size_t)k] != 1) return false;
    const std::string key = name_key(want);
    if (!key.empty() && name_key(names[(size_t)k]) == key) return false;   // (chosen by its name)
    for (const int t : types)
        if (t == 2) return true;
    return false;
}

} // namespace mkwvk::gpu_choice
