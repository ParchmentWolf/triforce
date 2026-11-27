// VR through OpenXR (vk_xr.h), the Insert menu's VR row on at start. The picture the window shows, the menu over it, on a
// screen floating in front of the headset, 2.5 m away: VR_SCREEN_SIZE degrees of the view wide, curved around the head
// (VR_SCREEN_CURVE, a cylinder layer where the runtime has one) or flat; with the head's view (VR_VIEW) the game's camera
// follows the headset, each eye's picture made from the scene and its depth or drawn in turn (VR_STEREO).
//
// The loader is opened at run time (libopenxr_loader.so.1, openxr_loader.dll), so a PC without it starts as before.
// XR_KHR_vulkan_enable: the runtime names the Vulkan instance and device extensions it needs and the GPU it draws with;
// vk_main.cpp adds the extensions, prefers that GPU and makes the device with one more queue of the graphics family for
// VR's copies, so the session's thread never waits on the replay's queue lock.
//
// Each present copies the window's image into one of three images of VR's own (the boxes, vk_xr_capture), and the
// present's submit signals a timeline semaphore with the copy's number. The session's thread copies the newest box into
// the OpenXR swapchain on VR's queue, its submit waiting for that number, and shows it as a quad in the LOCAL space. A
// box the thread reads is never written, and neither is the newest, so three are enough; the headset's frames go on at
// its own rate, the last picture shown again until a newer one is there.
//
// The scene's depth and camera come from the gameplay upscale (vk_draw.cpp xr_stand_in, vk_temporal.cpp's camera); the
// game's side (host/vr_game.c) calls in through the renderer's table (vk_xr_table, vk_api.h MkwVkXr).
#define XR_NO_PROTOTYPES
#define XR_USE_GRAPHICS_API_VULKAN
#include "xr_port.h"

#include "../../third_party/openxr/include/openxr/openxr.h"
#include "../../third_party/openxr/include/openxr/openxr_platform.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <cctype>
#include <string>
#include <vector>
#ifndef _WIN32
#include <dirent.h>
#include <unistd.h>
#endif

#include "vk_pace.h"
#include "vk_paths.h"
#include "vk_present_rect.h"
#include "shaders/xr_aim_comp_spv.h"
#include "shaders/xr_depth_keep_comp_spv.h"
#include "shaders/xr_depth_comp_spv.h"
#include "shaders/xr_flat3d_comp_spv.h"
#include "shaders/xr_desat_comp_spv.h"
#include "shaders/xr_flat3d_conv_comp_spv.h"
#include "shaders/xr_hud_comp_spv.h"
#include "vk_work.h"

// the picture's place in a window of dw x dh, as the present puts a cw x ch picture there (vk_replay.cpp present_rect)
static void gfx_fit_rect(int cw, int ch, int dw, int dh, int out[4]) {
    const mkwvk::PresentAspect aspect{mkwvk::host && mkwvk::host->aspect_ratio ? mkwvk::host->aspect_ratio() : 0.0f};
    const mkwvk::PresentRect r = mkwvk::present_rect((uint32_t)cw, (uint32_t)ch, nullptr, (uint32_t)dw, (uint32_t)dh, aspect);
    out[0] = (int)r.x, out[1] = (int)r.y, out[2] = (int)r.w, out[3] = (int)r.h;
}

namespace {

#define XR_FUNCS(X)                                                                                                    \
    X(xrDestroyInstance) X(xrGetInstanceProperties) X(xrGetSystem) X(xrGetSystemProperties) X(xrPollEvent)            \
    X(xrCreateSession) X(xrBeginSession) X(xrEndSession) X(xrWaitFrame) X(xrBeginFrame) X(xrEndFrame)                 \
    X(xrCreateReferenceSpace) X(xrEnumerateSwapchainFormats) X(xrCreateSwapchain) X(xrEnumerateSwapchainImages)       \
    X(xrAcquireSwapchainImage) X(xrWaitSwapchainImage) X(xrReleaseSwapchainImage) X(xrGetVulkanInstanceExtensionsKHR) \
    X(xrGetVulkanDeviceExtensionsKHR) X(xrGetVulkanGraphicsDeviceKHR) X(xrGetVulkanGraphicsRequirementsKHR)          \
    X(xrLocateViews) X(xrLocateSpace) X(xrStringToPath) X(xrPathToString) X(xrCreateActionSet) X(xrCreateAction)   \
    X(xrSuggestInteractionProfileBindings) X(xrAttachSessionActionSets) X(xrSyncActions) X(xrGetActionStateBoolean)  \
    X(xrGetActionStateFloat) X(xrGetActionStateVector2f) X(xrCreateActionSpace) X(xrGetCurrentInteractionProfile)    \
    X(xrApplyHapticFeedback) X(xrStopHapticFeedback)

// Tangents of a lens's four edges (left and down negative), as OpenXR's angles are
struct Lens {
    float l = -1, r = 1, u = 1, d = -1;
};
struct Pose {
    float q[4] = {0, 0, 0, 1};   // x, y, z, w
    float p[3] = {0, 0, 0};
};
// What a picture was drawn from: the head's pose in the LOCAL space and the lens; tracked false: the game's own view,
// shown on the screen
struct Drawn {
    bool tracked = false;
    bool hud = false;      // the HUD apart: the box holds the scene without it, the HUD box its panel
    bool stereo = false;   // depth stereo: the box holds the left eye's picture, the right box the right eye's
    bool menu = false;     // the game paused (its menus): the boxes hold the world as it last was, the HUD box the
                           // game's picture, its menu, shown on the HUD's panel
    Pose pose;             // the head's, between the eyes
    Lens lens;
    float scale = 1.0f;    // the lens the game drew with over the one shown (VR_VIEW_SCALE)
    float ipd = 0.064f;    // the eyes' distance, metres
    int eye = -1;          // Stereo Balanced (eyes in turn): the eye the picture was drawn from (0 left, 1 right)
    Pose eye_pose[2];      // with stereo then: each eye's picture's own pose (stereo's boxes hold the two latest)
    // where the LOCAL space sat in the game's world for this picture: world = base + right * x + up * y + back * z,
    // right (bz, 0, -bx), back (bx, 0, bz) (Balanced: the older eye's picture is put in the newer one's LOCAL space)
    double base[3]{}, bx = 0, bz = 1;
    bool aim = false;      // Link aims: the game's camera's ray (aim_o, aim_d) in the head's view (x right, y up, z back)
    float aim_o[3]{}, aim_d[3]{};
};


struct Xr {
    bool tried = false, ok = false;
    bool psvr2 = false;   // the headset is a PSVR2 (its system name): its Options cannot reach OpenXR, so L3+R3 are the Menu
    PFN_xrGetInstanceProcAddr gipa = nullptr;
#define XR_DECLARE(f) PFN_##f f = nullptr;
    XR_FUNCS(XR_DECLARE)
#undef XR_DECLARE
    XrInstance instance = XR_NULL_HANDLE;
    XrSystemId system = XR_NULL_SYSTEM_ID;
    std::string instance_exts, device_exts;   // the runtime's lists, split in place: the pointers below point into them
    std::vector<const char *> instance_list, device_list;
    const float screen_distance = 2.5f;
    bool cylinder = false;   // the runtime has XR_KHR_composition_layer_cylinder (enabled)
    // the device (vk_xr_device_ready)
    VkInstance vk_instance = VK_NULL_HANDLE;
    VkPhysicalDevice phys = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    uint32_t family = 0, queue_index = UINT32_MAX;
    VkQueue queue = VK_NULL_HANDLE;
    VkSemaphore timeline = VK_NULL_HANDLE;
    // the swapchain's size (the window's, from the first capture) and order; ready once the session's thread made it
    std::atomic<uint32_t> want_w{0}, want_h{0};
    std::atomic<bool> ready{false}, rgba{true};
    uint32_t width = 0, height = 0;
    // the boxes (mu): the present's thread writes one, the session's thread reads the newest
    std::mutex mu;
    VkImage boxes[3]{}, boxes_r[3]{};   // (the right eye's, depth stereo)
    uint64_t box_value[3]{};
    int latest = -1, reading = -1, next_slot = 0, pending = -1;
    bool boxes_made = false, boxes_failed = false;
    uint64_t next_value = 0;   // the present's thread alone
    Drawn box_drawn[3];
    // the head (the session's thread writes, the game's threads read)
    std::mutex head_mu;
    bool have_head = false;
    Pose head;
    Lens eyes;   // both eyes' lenses together
    float ipd = 0.064f;
    std::atomic<bool> running{false};
    // the view now (each present): the head's on the game's camera, or the screen (VR_VIEW, the menu open)
    std::atomic<bool> head_view{false};
    std::atomic<float> picture_ratio{16.0f / 9.0f};
    // this frame's (frame_mu): taken at the gameplay camera's update (vk_xr_camera), its lens given at the angle's
    // load (vk_xr_lens), kept for the next picture (vk_xr_capture)
    std::mutex frame_mu;
    bool frame_on = false;
    Drawn drawn;
    float render_scale = 1.0f;   // the lens the game draws with over the one shown (VR_VIEW_SCALE)
    bool aim_on = false;         // vr_game.c vk_xr_aim: Link aims, along the game's own camera's ray (world)
    // pointed aim (vr_game.c vk_xr_aim_freeze): the view's base yaw held where it was while the controller steers the
    // game's aim (else the view would turn with the aim it chases); the yaw now (cur) for the controller's ray
    bool aim_freeze = false, frozen_ok = false;
    int turn = 0;   // Stereo Balanced: the eye the next camera update draws from (frame_mu)
    // the last camera updates' pictures to be (frame_mu), with the camera's place in the world each gave, and the place
    // the last scene was drawn from (vk_xr_scene_camera): a picture is matched to its own update by the nearest
    struct Given {
        Drawn d;
        double at[3];
        bool used;
    } given[6];
    int given_next = 0;
    double scene_at[3]{};
    bool scene_new = false;
    double frozen_bx = 0, frozen_bz = 1, cur_bx = 0, cur_bz = 1;
    double aim_o[3]{}, aim_d[3]{};
    std::atomic<uint32_t> camera_given{0}, lens_given{0}, tracked_pictures{0};
    // the gameplay camera's updates since the last picture, and the pictures in a row with none: a paused game (the
    // inventory) draws flat pictures while the camera stands still, and those go on the screen
    std::atomic<uint32_t> updates{0};
    int stale = 0;   // the present's thread alone
    int moving = 0;   // (so is this: the pictures since the game's camera last stood still)
    // the HUD's panel. The game draws its HUD over its upscaled scene in one float target; the
    // scene as the upscaler left it is kept (vk_xr_scene_image, the replay's stream), and at the present, when the
    // target holds the HUD too, shaders/xr_hud.comp makes the scene without the HUD and the HUD's panel from the two
    std::mutex hud_mu;
    VkImage hud_target = VK_NULL_HANDLE, scene = VK_NULL_HANDLE, scene8 = VK_NULL_HANDLE, panel8 = VK_NULL_HANDLE;
    VkImageView target_view = VK_NULL_HANDLE, scene_view = VK_NULL_HANDLE, scene8_view = VK_NULL_HANDLE, panel8_view = VK_NULL_HANDLE;
    VkImage target_viewed = VK_NULL_HANDLE;   // the target target_view is of
    VkImage layer = VK_NULL_HANDLE;   // ((Triforce VR) the HUD drawn apart, over black and over white (vk_xr_hud_layer)
    VkImageView layer_view = VK_NULL_HANDLE;
    std::atomic<bool> item_bar{false};    // vr_game.c: the game's item bar is open
    std::atomic<bool> bar_drawn{false};   // the paused frame's item bar drawn into the layer (vk_xr_item_bar_layer), not shown yet
    uint32_t hud_w = 0, hud_h = 0;
    VkFormat hud_format = VK_FORMAT_UNDEFINED;
    uint64_t kept = 0, used = 0;   // scenes kept, and the last one a panel was made from
    // Stereo Accurate: the renderer draws the frame a second time for the right eye (vk_replay.cpp run_submit). Before that
    // pass the target with the left eye's picture and HUD is copied to target_l; the pass's scene before the HUD goes to
    // scene_r (second_now while it runs); acc_ready once both are there for this frame's picture
    VkImage target_l = VK_NULL_HANDLE, scene_r = VK_NULL_HANDLE;
    VkImageView target_l_view = VK_NULL_HANDLE, scene_r_view = VK_NULL_HANDLE;
    bool second_now = false, acc_ready = false;
    std::atomic<float> acc_shift{0.0f};   // metres the right eye's camera is from the left's (vk_xr_camera)
    // Flatscreen 3D (FLAT3D, no headset; hud_mu): the eyes made as depth stereo's from the game's own camera, put together
    // into one picture for the window (shaders/xr_flat3d.comp) at the screen's distance (xr_flat3d_conv.comp)
    VkDescriptorSetLayout flat_set = VK_NULL_HANDLE, conv_set = VK_NULL_HANDLE;
    VkPipelineLayout flat_layout = VK_NULL_HANDLE, conv_layout = VK_NULL_HANDLE;
    VkPipeline flat_pipe = VK_NULL_HANDLE, conv_pipe = VK_NULL_HANDLE;
    bool flat_tried = false;
    VkBuffer screen = VK_NULL_HANDLE;   // the screen's 1 / distance, eased (xr_flat3d_conv.comp)
    VkImage flat8 = VK_NULL_HANDLE;
    VkImageView flat8_view = VK_NULL_HANDLE;
    uint32_t flat_w = 0, flat_h = 0;
    int flat_age = 1000;   // presents since the last picture was made
    // Stereo Accurate: the right eye's picture a little less saturated and darker (shaders/xr_desat.comp, desat_right)
    VkDescriptorSetLayout desat_set = VK_NULL_HANDLE;
    VkPipelineLayout desat_layout = VK_NULL_HANDLE;
    VkPipeline desat_pipe = VK_NULL_HANDLE;
    bool desat_tried = false;
    VkDescriptorSetLayout hud_set = VK_NULL_HANDLE;
    VkPipelineLayout hud_layout = VK_NULL_HANDLE;
    VkPipeline hud_pipe = VK_NULL_HANDLE;
    VkSampler nearest = VK_NULL_HANDLE;
    PFN_vkCmdPushDescriptorSetKHR push_set = nullptr;
    bool hud_tried = false;
    VkImage hud_boxes[3]{};
    std::atomic<uint32_t> panels{0};
    std::atomic<uint32_t> scenes_kept{0}, depths_kept{0}, upscales{0}, upscales_vr{0}, panel_no_scene{0}, panel_not_new{0};
    std::atomic<uint32_t> pic_w{0}, pic_h{0};   // the game's presented picture's size: the HUD's target is the scene upscaled to it
    // depth stereo (VR_DEPTH, hud_mu): shaders/xr_depth.comp makes each eye's picture from the scene the HUD's
    // shader leaves and the scene's depth kept by vk_xr_keep_depth
    VkImage eye8[2]{};
    VkImageView eye8_view[2]{};
    uint32_t eye8_w = 0, eye8_h = 0;
    // the scene's depth as it was when the scene was drawn (vk_xr_keep_depth): the game reuses its target for smaller
    // passes before the present
    VkImage depth = VK_NULL_HANDLE;   // R32F
    VkImageView depth_view = VK_NULL_HANDLE;
    uint32_t depth_w = 0, depth_h = 0;
    uint64_t depth_kept = 0;
    VkBuffer rows = VK_NULL_HANDLE;   // each depth row's least then greatest depth (shaders/xr_depth_keep.comp)
    VkDescriptorSetLayout keep_set = VK_NULL_HANDLE;
    VkPipelineLayout keep_layout = VK_NULL_HANDLE;
    VkPipeline keep_pipe = VK_NULL_HANDLE;
    VkSampler keep_sampler = VK_NULL_HANDLE;
    PFN_vkCmdPushDescriptorSetKHR keep_push = nullptr;
    bool keep_tried = false;
    VkDescriptorSetLayout depth_set = VK_NULL_HANDLE;
    VkPipelineLayout depth_layout = VK_NULL_HANDLE;
    VkPipeline depth_pipe = VK_NULL_HANDLE;
    VkSampler linear = VK_NULL_HANDLE;
    bool depth_tried = false;
    std::mutex gear_mu;
    char held_item[96]{};   // vr_game.c: the item in Link's hand (vk_xr_hand_item), "" none or the sword
    // Stereo Balanced (hud_mu): each eye's latest picture and its pose, and the desktop's left eye kept for the right's
    // presents (the window's picture region, in the window's format)
    // ([2]: the left eye's picture, waiting for its right one, both shown together)
    VkImage acc8[3]{};
    VkImageView acc8_view[3]{};
    uint32_t acc_w = 0, acc_h = 0;
    Pose acc_pose[3];
    double acc_base[3][3]{}, acc_bx[3]{}, acc_bz[3]{1, 1, 1};
    bool acc_have[3]{};
    Pose pair_pose[2];   // the eyes' poses of the pair shown now
    bool pair_ok = false;
    VkImage win_left = VK_NULL_HANDLE;
    uint32_t win_left_w = 0, win_left_h = 0;
    VkFormat win_left_format = VK_FORMAT_UNDEFINED;
    bool win_left_have = false;
    // the aiming reticle (shaders/xr_aim.comp, hud_mu) drawn into scene8 where the aim lands
    VkDescriptorSetLayout aim_set = VK_NULL_HANDLE;
    VkPipelineLayout aim_layout = VK_NULL_HANDLE;
    VkPipeline aim_pipe = VK_NULL_HANDLE;
    bool aim_tried = false;
    std::atomic<uint32_t> stereo_pictures{0}, stereo_missed{0}, menu_pictures{0};
    // the hand controllers (hands_mu; the session's thread writes, the game's input reads): their buttons as the pad's
    // (input_map.h bits) and sticks, and the grips' poses in the LOCAL space
    std::mutex hands_mu;
    uint64_t hand_buttons = 0;
    bool hand_menu = false;      // the buttons are a menu's (labelled, not play's): vk_xr_menu_buttons gives them to this menu
    float hand_sticks[2][2]{};   // left, right; x right, y up
    Pose grip[2];
    Pose aim_pose[2];   // the controllers' aim poses (their pointing rays, -z), as their own pointers use
    bool aim_ok[2]{};
    bool grip_ok[2]{};
    uint64_t hands_at = 0;   // when they were last read (plat_now_ns), 0 never
    std::atomic<bool> ocarina{false};   // vr_game.c: Link plays the ocarina (the controllers' Ocarina mode)
    std::atomic<bool> weapon_out{false};   // vr_game.c: Link holds his sword and shield (or another weapon) out
    std::atomic<bool> child{true};         // vr_game.c: Link is a child (his hands' model)
    std::atomic<bool> two_handed_sword{false};   // ((Triforce VR) vr_game.c: his sword is the Biggoron's
    std::atomic<bool> game_paused{false};        // ((Triforce VR) vr_game.c: the game paused by its menus (no fade looked for)
    std::atomic<int> hud_hidden{0};        // ((Triforce VR) vr_game.c: no HUD panel now (a load zone's transition)
    std::atomic<int> head_worn{0};
    std::atomic<bool> carrying{false};     // ((Triforce VR) vr_game.c: Link has something of the world's in his hands
    std::atomic<bool> airborne{false};     // ((Triforce VR) vr_game.c: Link in the air (jumping, falling)
    std::atomic<int> combo_want{-1};       // ((Triforce VR) the gesture-chosen slash's combo counter (vr_game.c takes it): -1 none
    std::atomic<int> head_request{0};      // ((Triforce VR) the gestures' ask for his head (vr_game.c takes it): 1 mask on, 2 Lens on, 3 off         // ((Triforce VR) vr_game.c: 0 nothing on his head, 1 a mask, 2 the Lens of Truth)
    std::atomic<bool> in_play{false};      // vr_game.c: play (not a menu, a pause, an event): the grips' and swing's play roles
    // the last picture drawn from the head whose world scene8 and eye8 still hold (the present's thread alone): a paused
    // game's menus go on the HUD's panel in front of that world, frozen as it was
    Drawn frozen;
};

// ((Triforce VR) the sword's hand as the last draw by both grips chose it (the higher hand): -1 none yet, 0 left, 1 right;
// the host's mirror reads it as VR_SWORD_HAND (vk_menu.cpp vk_xr_cfg))
static std::atomic<int> g_live_sword{-1};
extern "C" int vk_xr_live_sword(void) { return g_live_sword.load(); }
// ((Triforce VR) Link's animation mirrored for what the hands did last: -1 not yet, 0 as made, 1 mirrored (VR_MIRROR))
static std::atomic<int> g_live_mirror{-1};
// ((Triforce VR) the hand holding the item out (the one that pulled it), -1 none: the aim's pointer is that hand's)
static std::atomic<int> g_item_hand{-1};
// ((Triforce VR) the bow's and the slingshot's draw: while drawn, the aim is from the drawing hand to the holding hand (LOCAL
// space, the grips' places), not where a controller points; g_draw_on 1 while it holds)
static std::atomic<bool> g_draw_on{false};
static float g_draw_dir[3];   // (under hands_mu)
// ((Triforce VR) both his hands on what one holds: the hammer's or the Deku Stick's hand (0 left, 1 right), -1 neither out; 2 the
// shield raised alone, until the sword is swung or drawn: a two-handed sword on his back is not in them
static std::atomic<int> g_two_hands{-1};
extern "C" int vk_xr_two_hands(void) { return g_two_hands.load(); }
extern "C" int vk_xr_live_mirror(void) { return g_live_mirror.load(); }
// ((Triforce VR) what Link holds in his right hand mirrored (1) or as made (0), by the item's name; the left hand the other.
// Her table: the shield, Deku Nuts, the business seed, the slingshot and the bow as made; the rest mirrored. (Bombs: as made,
// the Deku Stick and the hammer mirrored, until looked at in the headset)
static std::atomic<bool> g_gaze_aim{false};   // ((Triforce VR) the boomerang out: its aim the head's gaze (vk_xr_pointer)
// ((Triforce VR) the last shot (ZR let go), and the pointer's ways just before it (vk_xr_pointer): kShotHoldNs after a shot
// the aim is the way it was kShotBeforeNs before it
static std::atomic<uint64_t> g_shot_at{0};
// ((Triforce VR) the Turn vignette: Smooth turning's strength as vr_game.c last said it, and when
static std::atomic<float> g_turning{0.0f};
static std::atomic<uint64_t> g_turning_at{0};
// ((Triforce VR) and how fast first person's eyes are carried through the world (a run, a roll, a knockback), 0 to 1: vk_xr_camera
static std::atomic<float> g_moving{0.0f};
// ((Triforce VR) nn_hid.c's rumble, each side's strength (0 to 1) and when it came: Controls::rumble
static std::atomic<float> g_rumble[2];
static std::atomic<uint64_t> g_rumble_at[2];
// ((Triforce VR) the hammer's last swing (its ZR): his arms the game's own swing for kHammerSwingNs after it (vk_xr_arms_own)
static std::atomic<uint64_t> g_hammer_swung{0};
static constexpr uint64_t kHammerSwingNs = 900000000ull;
static constexpr uint64_t kShotHoldNs = 350000000ull, kShotBeforeNs = 150000000ull;
static int item_mirrored_right(const char *it) {
    static const char *const as_made[] = {"Shield", "ScrubBusinessSeed", "Slingshot", "SlingShot", "Pachinko", "Bow", "Bomb", "Hammer"};
    for (const char *n : as_made)
        if (strstr(it, n)) return 0;
    return 1;
}
Xr &xr() {
    static Xr x;
    return x;
}

// "a b c" into its names, the string's spaces made ends
void split(std::string &s, std::vector<const char *> &out) {
    out.clear();
    for (char &ch : s)
        if (ch == ' ') ch = 0;
    for (size_t i = 0; i < s.size();) {
        if (s[i]) out.push_back(s.c_str() + i), i += std::strlen(s.c_str() + i);
        else i++;
    }
}

}   // namespace

// vr= in triforce_options.ini: VR is decided when the instance is made, before the menu reads the file
extern "C" int vk_xr_row_on(void) {
    char exe[MAX_PATH];
    const DWORD n = mkwvk::game_module_path(exe, MAX_PATH);
    const std::string dir(exe, n);
    const std::string path = dir.substr(0, dir.find_last_of("\\/") + 1) + "triforce_options.ini";
    int v = 0;
    if (FILE *f = fopen(path.c_str(), "r")) {
        char line[160];
        while (fgets(line, sizeof line, f))
            if (!strncmp(line, "vr=", 3)) v = atoi(line + 3);
        fclose(f);
    }
    return v != 0;
}

#ifndef _WIN32
namespace {
/// ((Triforce VR) Linux: the VR server running now and its own runtime manifest, read through the process (/proc/<pid>/root, so
/// a Flatpak's as a system install's): WiVRn and Monado keep it at <bin>/../share/openxr/1/, SteamVR (ALVR streams through it)
/// at <SteamVR>/steamxr_linux64.json beside bin/linux64/vrserver. The oldest server of a kind: a second one is a leftover.
/// False: none runs
bool running_runtime(std::string &manifest, std::string &who) {
    struct Kind { const char *comm, *name; int up; const char *file; };
    static const Kind kinds[] = {{"wivrn-server", "WiVRn", 1, "share/openxr/1/"}, {"monado-service", "Monado", 1, "share/openxr/1/"},
                                 {"vrserver", "SteamVR", 3, "steamxr_linux64.json"}};
    DIR *proc = opendir("/proc");
    if (!proc) return false;
    long best_pid = 0;
    int best_kind = -1;
    while (dirent *e = readdir(proc)) {
        char *end;
        const long pid = strtol(e->d_name, &end, 10);
        if (*end || pid <= 0) continue;
        char path[64], comm[32] = "";
        snprintf(path, sizeof path, "/proc/%ld/comm", pid);
        if (FILE *f = fopen(path, "r")) {
            if (!fgets(comm, sizeof comm, f)) comm[0] = 0;
            fclose(f);
        }
        comm[strcspn(comm, "\n")] = 0;
        for (int k = 0; k < (int)(sizeof kinds / sizeof kinds[0]); k++)
            if (!strcmp(comm, kinds[k].comm) && (best_kind < 0 || k < best_kind || (k == best_kind && pid < best_pid)))
                best_kind = k, best_pid = pid;
    }
    closedir(proc);
    if (best_kind < 0) return false;
    const Kind &k = kinds[best_kind];
    who = k.name;
    char link[64], exe[1024];
    snprintf(link, sizeof link, "/proc/%ld/exe", best_pid);
    const ssize_t n = readlink(link, exe, sizeof exe - 1);
    if (n <= 0) return true;   // (running, its manifest not found: the loader's own choice)
    exe[n] = 0;
    std::string dir(exe);
    for (int i = 0; i < k.up + 1 && dir.find('/') != std::string::npos; i++) dir.erase(dir.find_last_of('/'));
    // (a Flatpak's server runs from /app: where that is on the disk, its .flatpak-info's app-path. A runtime loaded through
    // /proc/<pid>/root instead came up without its Vulkan extension)
    if (dir.compare(0, 5, "/app/") == 0 || dir == "/app") {
        const std::string info = "/proc/" + std::to_string(best_pid) + "/root/.flatpak-info";
        if (FILE *f = fopen(info.c_str(), "r")) {
            char line[1024];
            while (fgets(line, sizeof line, f))
                if (!strncmp(line, "app-path=", 9)) {
                    line[strcspn(line, "\r\n")] = 0;
                    dir = std::string(line + 9) + dir.substr(4);
                    break;
                }
            fclose(f);
        }
    }
    const std::string plain = dir + "/" + k.file;
    const std::string at = plat_file_exists(plain.c_str()) ? plain : "/proc/" + std::to_string(best_pid) + "/root" + plain;
    if (at.back() != '/') {
        if (plat_file_exists(at.c_str())) manifest = at;
        return true;
    }
    if (DIR *d = opendir(at.c_str())) {   // (the first manifest there)
        while (dirent *f = readdir(d))
            if (strstr(f->d_name, ".json")) {
                manifest = at + f->d_name;
                break;
            }
        closedir(d);
    }
    return true;
}
}   // namespace
bool make_flat_pipelines();   // ((Triforce VR) below, for VR's desktop 3D too
#endif

namespace {

bool init() {
    Xr &x = xr();
    if (x.tried) return x.ok;
    x.tried = true;
    if (!vk_xr_row_on()) return false;
#ifdef _WIN32
    // The loader beside the game first: Khronos's build is openxr_loader.dll, MSYS2's libopenxr_loader.dll (the one the
    // builders copy). A bare name loads from System32 only, where SteamVR puts no loader.
    void *lib = NULL;
    char beside[PLAT_PATH_MAX];
    char *sep = plat_exe_path(beside, sizeof beside) ? plat_last_sep(beside) : NULL;
    static const char *const names[] = {"openxr_loader.dll", "libopenxr_loader.dll"};
    for (const char *name : names) {
        if (!sep || lib) break;
        if ((size_t)(sep + 1 - beside) + strlen(name) + 1 > sizeof beside) continue;
        strcpy(sep + 1, name);
        if (plat_file_exists(beside)) {
            lib = plat_lib_open(beside);
            rt_log("vr: OpenXR loader %s %s", beside, lib ? "opened" : "did not open (a DLL it needs is missing?)");
        }
    }
    if (!lib) lib = plat_lib_open("openxr_loader.dll");
#else
    // ((Triforce VR) The VR server running decides (running_runtime), waited for up to 5 s: none, and the game starts on the
    // flat screen rather than wait on a runtime with no server (the loader's choice can hang there). Its own manifest is used,
    // so a Flatpak's WiVRn, which registers no runtime outside its sandbox, works as a system one. XR_RUNTIME_JSON set: as named
    char named[8];
    if (!plat_getenv("XR_RUNTIME_JSON", named, sizeof named)) {
        std::string manifest, who;
        bool found = false;
        for (int i = 0; i < 50 && !(found = running_runtime(manifest, who)); i++) {
            if (!i) rt_log("vr: no VR server running (WiVRn, Monado, SteamVR or ALVR): waiting up to 5 s");
            usleep(100000);
        }
        if (!found) {
            rt_log("vr: no VR server running after 5 s: the flat screen (start WiVRn, Monado, SteamVR or ALVR before the game)");
            return false;
        }
        if (!manifest.empty()) plat_setenv("XR_RUNTIME_JSON", manifest.c_str());
        rt_log("vr: %s runs: its runtime %s", who.c_str(), manifest.empty() ? "as the system registers it" : manifest.c_str());
    }
    void *lib = plat_lib_open("libopenxr_loader.so.1");
#endif
    if (lib) x.gipa = (PFN_xrGetInstanceProcAddr)plat_lib_sym(lib, "xrGetInstanceProcAddr");
    if (!x.gipa) {
        rt_log("vr: no OpenXR loader: VR off");
        return false;
    }
    PFN_xrCreateInstance create = nullptr;
    PFN_xrEnumerateInstanceExtensionProperties enumerate = nullptr;
    x.gipa(XR_NULL_HANDLE, "xrCreateInstance", (PFN_xrVoidFunction *)&create);
    x.gipa(XR_NULL_HANDLE, "xrEnumerateInstanceExtensionProperties", (PFN_xrVoidFunction *)&enumerate);
    if (!create || !enumerate) {
        rt_log("vr: the OpenXR loader lacks xrCreateInstance: VR off");
        return false;
    }
    uint32_t n = 0;
    enumerate(nullptr, 0, &n, nullptr);
    std::vector<XrExtensionProperties> exts(n, {XR_TYPE_EXTENSION_PROPERTIES});
    enumerate(nullptr, n, &n, exts.data());
    bool vulkan = false;
    for (const auto &e : exts) {
        vulkan |= !std::strcmp(e.extensionName, XR_KHR_VULKAN_ENABLE_EXTENSION_NAME);
        x.cylinder |= !std::strcmp(e.extensionName, XR_KHR_COMPOSITION_LAYER_CYLINDER_EXTENSION_NAME);
    }
    if (!x.cylinder) rt_log("vr: the runtime has no %s: the screen stays flat", XR_KHR_COMPOSITION_LAYER_CYLINDER_EXTENSION_NAME);
    if (!vulkan) {
        rt_log("vr: the OpenXR runtime has no %s (is its server running?): VR off", XR_KHR_VULKAN_ENABLE_EXTENSION_NAME);
        return false;
    }
    const char *want[] = {XR_KHR_VULKAN_ENABLE_EXTENSION_NAME, XR_KHR_COMPOSITION_LAYER_CYLINDER_EXTENSION_NAME};
    XrInstanceCreateInfo ci{XR_TYPE_INSTANCE_CREATE_INFO};
    std::strcpy(ci.applicationInfo.applicationName, "Triforce");
    std::strcpy(ci.applicationInfo.engineName, "Triforce");
    ci.applicationInfo.apiVersion = XR_MAKE_VERSION(1, 0, 0);
    ci.enabledExtensionCount = x.cylinder ? 2 : 1;
    ci.enabledExtensionNames = want;
    XrResult r = create(&ci, &x.instance);
    if (XR_FAILED(r)) {
        rt_log("vr: xrCreateInstance failed (%d; is the runtime's server running and the headset connected?): VR off", (int)r);
        return false;
    }
#define XR_LOAD(f) x.gipa(x.instance, #f, (PFN_xrVoidFunction *)&x.f);
    XR_FUNCS(XR_LOAD)
#undef XR_LOAD
    XrInstanceProperties ip{XR_TYPE_INSTANCE_PROPERTIES};
    x.xrGetInstanceProperties(x.instance, &ip);
    XrSystemGetInfo sg{XR_TYPE_SYSTEM_GET_INFO};
    sg.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    r = x.xrGetSystem(x.instance, &sg, &x.system);
    if (XR_FAILED(r)) {
        rt_log("vr: %s %u.%u.%u: no headset (%d): VR off", ip.runtimeName, XR_VERSION_MAJOR(ip.runtimeVersion),
               XR_VERSION_MINOR(ip.runtimeVersion), XR_VERSION_PATCH(ip.runtimeVersion), (int)r);
        x.xrDestroyInstance(x.instance), x.instance = XR_NULL_HANDLE;
        return false;
    }
    XrSystemProperties sp{XR_TYPE_SYSTEM_PROPERTIES};
    x.xrGetSystemProperties(x.instance, x.system, &sp);
    {
        std::string name = sp.systemName;
        for (char &ch : name) ch = (char)std::tolower((unsigned char)ch);
        x.psvr2 = name.find("playstation_vr2") != std::string::npos || name.find("psvr2") != std::string::npos;
    }
    XrGraphicsRequirementsVulkanKHR req{XR_TYPE_GRAPHICS_REQUIREMENTS_VULKAN_KHR};   // asked before a session, as the spec says
    x.xrGetVulkanGraphicsRequirementsKHR(x.instance, x.system, &req);
    for (int pass = 0; pass < 2; pass++) {
        auto get = pass ? x.xrGetVulkanDeviceExtensionsKHR : x.xrGetVulkanInstanceExtensionsKHR;
        std::string &s = pass ? x.device_exts : x.instance_exts;
        uint32_t len = 0;
        get(x.instance, x.system, 0, &len, nullptr);
        s.assign(len, '\0');
        if (len) get(x.instance, x.system, len, &len, s.data());
        while (!s.empty() && !s.back()) s.pop_back();
        split(s, pass ? x.device_list : x.instance_list);
    }
    rt_log("vr: %s %u.%u.%u, %s; Vulkan %u.%u to %u.%u; instance extensions \"%s\", device extensions \"%s\"",
           ip.runtimeName, XR_VERSION_MAJOR(ip.runtimeVersion), XR_VERSION_MINOR(ip.runtimeVersion),
           XR_VERSION_PATCH(ip.runtimeVersion), sp.systemName, XR_VERSION_MAJOR(req.minApiVersionSupported),
           XR_VERSION_MINOR(req.minApiVersionSupported), XR_VERSION_MAJOR(req.maxApiVersionSupported),
           XR_VERSION_MINOR(req.maxApiVersionSupported), x.instance_exts.c_str(), x.device_exts.c_str());
    x.ok = true;
    return true;
}

bool listed(const char *const *list, uint32_t n, const char *name) {
    for (uint32_t i = 0; i < n; i++)
        if (!std::strcmp(list[i], name)) return true;
    return false;
}

VkImageMemoryBarrier2 layout_change(VkImage image, VkImageLayout from, VkImageLayout to, VkImageAspectFlags aspect) {
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
    b.srcStageMask = b.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    b.srcAccessMask = VK_ACCESS_2_MEMORY_WRITE_BIT;
    b.dstAccessMask = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT;
    b.oldLayout = from, b.newLayout = to;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image;
    b.subresourceRange = {aspect, 0, 1, 0, 1};
    return b;
}

void barrier(VkCommandBuffer cb, VkImage image, VkImageLayout from, VkImageLayout to,
             VkImageAspectFlags aspect = VK_IMAGE_ASPECT_COLOR_BIT) {
    const VkImageMemoryBarrier2 b = layout_change(image, from, to, aspect);
    VkDependencyInfo d{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    d.imageMemoryBarrierCount = 1, d.pImageMemoryBarriers = &b;
    vkCmdPipelineBarrier2(cb, &d);
}

// For the session thread's own command buffer on VR's queue: straight to the driver, not through the replay's recorder.
void barrier_direct(VkCommandBuffer cb, VkImage image, VkImageLayout from, VkImageLayout to) {
    const VkImageMemoryBarrier2 b = layout_change(image, from, to, VK_IMAGE_ASPECT_COLOR_BIT);
    VkDependencyInfo d{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    d.imageMemoryBarrierCount = 1, d.pImageMemoryBarriers = &b;
    (vkCmdPipelineBarrier2)(cb, &d);
}

// v rotated by the unit quaternion q (x, y, z, w)
void rotate(const float q[4], const float v[3], float out[3]) {
    const float x = q[0], y = q[1], z = q[2], w = q[3];
    const float tx = 2 * (y * v[2] - z * v[1]), ty = 2 * (z * v[0] - x * v[2]), tz = 2 * (x * v[1] - y * v[0]);
    out[0] = v[0] + w * tx + (y * tz - z * ty);
    out[1] = v[1] + w * ty + (z * tx - x * tz);
    out[2] = v[2] + w * tz + (x * ty - y * tx);
}

// The frustum the game draws with for the eyes' lens on a picture of ratio `ratio`: centred (the game's projection is
// symmetric, and the projection layer is told this frustum, so the compositor puts each pixel where it belongs), the
// shorter side grown so nothing the eyes see is left out
Lens frustum(const Lens &eyes, float ratio) {
    const float side = std::fmax(-eyes.l, eyes.r), up = std::fmax(eyes.u, -eyes.d);
    const float v = std::fmax(up, side / ratio), h = v * ratio;
    Lens f;
    f.l = -h, f.r = h, f.u = v, f.d = -v;
    return f;
}

bool is_srgb(VkFormat f) {
    return f == VK_FORMAT_B8G8R8A8_SRGB || f == VK_FORMAT_R8G8B8A8_SRGB || f == VK_FORMAT_A8B8G8R8_SRGB_PACK32;
}

// The three boxes at the swapchain's size, in its channel order and the window's encoding: a blit between two sRGB or
// two UNORM formats keeps the bytes, so the copy into the sRGB swapchain shows them as the window does
bool make_boxes(VkFormat window) {
    Xr &x = xr();
    const bool srgb = is_srgb(window);
    const VkFormat format = x.rgba ? (srgb ? VK_FORMAT_R8G8B8A8_SRGB : VK_FORMAT_R8G8B8A8_UNORM)
                                   : (srgb ? VK_FORMAT_B8G8R8A8_SRGB : VK_FORMAT_B8G8R8A8_UNORM);
    VkFormatProperties fp{};
    vkGetPhysicalDeviceFormatProperties(x.phys, format, &fp);
    if (!(fp.optimalTilingFeatures & VK_FORMAT_FEATURE_BLIT_DST_BIT)) {
        rt_log("vr: no blit into format %d: the headset shows nothing", (int)format);
        return false;
    }
    VkPhysicalDeviceMemoryProperties mem;
    vkGetPhysicalDeviceMemoryProperties(x.phys, &mem);
    for (int k = 0; k < 9; k++) {   // the pictures' three, the HUD's, the right eye's
        VkImage &box = k < 3 ? x.boxes[k] : k < 6 ? x.hud_boxes[k - 3] : x.boxes_r[k - 6];
        VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
        ci.imageType = VK_IMAGE_TYPE_2D;
        ci.format = format;
        ci.extent = {x.width, x.height, 1};
        ci.mipLevels = ci.arrayLayers = 1;
        ci.samples = VK_SAMPLE_COUNT_1_BIT;
        ci.tiling = VK_IMAGE_TILING_OPTIMAL;
        ci.usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        if (vkCreateImage(x.device, &ci, nullptr, &box) != VK_SUCCESS) return false;
        VkMemoryRequirements mr;
        vkGetImageMemoryRequirements(x.device, box, &mr);
        uint32_t type = UINT32_MAX;
        for (uint32_t i = 0; i < mem.memoryTypeCount && type == UINT32_MAX; i++)
            if ((mr.memoryTypeBits & (1u << i)) && (mem.memoryTypes[i].propertyFlags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT))
                type = i;
        VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
        ai.allocationSize = mr.size, ai.memoryTypeIndex = type;
        VkDeviceMemory dm = VK_NULL_HANDLE;
        if (type == UINT32_MAX || vkAllocateMemory(x.device, &ai, nullptr, &dm) != VK_SUCCESS ||
            vkBindImageMemory(x.device, box, dm, 0) != VK_SUCCESS)
            return false;
    }
    rt_log("vr: VR's pictures: %ux%u, format %d (the window's %d)", x.width, x.height, (int)format, (int)window);
    return true;
}

// A device-local 2D image (one level, one layer) and a view of it; UNDEFINED until the caller's barrier
bool make_image(uint32_t w, uint32_t h, VkFormat format, VkImageUsageFlags usage, VkImage &image, VkImageView &view,
                VkImageAspectFlags aspect = VK_IMAGE_ASPECT_COLOR_BIT) {
    Xr &x = xr();
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.imageType = VK_IMAGE_TYPE_2D, ci.format = format, ci.extent = {w, h, 1};
    ci.mipLevels = ci.arrayLayers = 1, ci.samples = VK_SAMPLE_COUNT_1_BIT, ci.tiling = VK_IMAGE_TILING_OPTIMAL, ci.usage = usage;
    if (vkCreateImage(x.device, &ci, nullptr, &image) != VK_SUCCESS) return false;
    VkMemoryRequirements mr;
    vkGetImageMemoryRequirements(x.device, image, &mr);
    VkPhysicalDeviceMemoryProperties mem;
    vkGetPhysicalDeviceMemoryProperties(x.phys, &mem);
    uint32_t type = UINT32_MAX;
    for (uint32_t i = 0; i < mem.memoryTypeCount && type == UINT32_MAX; i++)
        if ((mr.memoryTypeBits & (1u << i)) && (mem.memoryTypes[i].propertyFlags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)) type = i;
    VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    ai.allocationSize = mr.size, ai.memoryTypeIndex = type;
    VkDeviceMemory dm = VK_NULL_HANDLE;
    VkResult ar = type == UINT32_MAX ? VK_ERROR_OUT_OF_DEVICE_MEMORY : vkAllocateMemory(x.device, &ai, nullptr, &dm);
    // the card's memory full (the game keeps it so): any other type the image may live in, the system's memory among them
    for (uint32_t i = 0; i < mem.memoryTypeCount && ar != VK_SUCCESS; i++)
        if ((mr.memoryTypeBits & (1u << i)) && i != type) ai.memoryTypeIndex = i, ar = vkAllocateMemory(x.device, &ai, nullptr, &dm);
    if (ar != VK_SUCCESS || vkBindImageMemory(x.device, image, dm, 0) != VK_SUCCESS) {
        rt_log("vr: an image %ux%u (format %d) found no memory (%d)", w, h, (int)format, (int)ar);
        return false;
    }
    VkImageViewCreateInfo vc{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    vc.image = image, vc.viewType = VK_IMAGE_VIEW_TYPE_2D, vc.format = format, vc.subresourceRange = {aspect, 0, 1, 0, 1};
    return vkCreateImageView(x.device, &vc, nullptr, &view) == VK_SUCCESS;
}

// A device-local buffer of n bytes
bool make_buffer(VkDeviceSize n, VkBufferUsageFlags usage, VkBuffer &buf) {
    Xr &x = xr();
    VkBufferCreateInfo bi{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bi.size = n, bi.usage = usage;
    if (vkCreateBuffer(x.device, &bi, nullptr, &buf) != VK_SUCCESS) return false;
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(x.device, buf, &mr);
    VkPhysicalDeviceMemoryProperties mem;
    vkGetPhysicalDeviceMemoryProperties(x.phys, &mem);
    uint32_t type = UINT32_MAX;
    for (uint32_t i = 0; i < mem.memoryTypeCount && type == UINT32_MAX; i++)
        if ((mr.memoryTypeBits & (1u << i)) && (mem.memoryTypes[i].propertyFlags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)) type = i;
    VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    ai.allocationSize = mr.size, ai.memoryTypeIndex = type;
    VkDeviceMemory dm = VK_NULL_HANDLE;
    VkResult ar = type == UINT32_MAX ? VK_ERROR_OUT_OF_DEVICE_MEMORY : vkAllocateMemory(x.device, &ai, nullptr, &dm);
    // the card's memory full: any other type the buffer may live in, as make_image
    for (uint32_t i = 0; i < mem.memoryTypeCount && ar != VK_SUCCESS; i++)
        if ((mr.memoryTypeBits & (1u << i)) && i != type) ai.memoryTypeIndex = i, ar = vkAllocateMemory(x.device, &ai, nullptr, &dm);
    if (ar != VK_SUCCESS) rt_log("vr: a buffer of %llu bytes found no memory (%d)", (unsigned long long)n, (int)ar);
    return ar == VK_SUCCESS && vkBindBufferMemory(x.device, buf, dm, 0) == VK_SUCCESS;
}

// A barrier on all memory: what came before is done and visible to what comes after
void memory_barrier(VkCommandBuffer cb) {
    VkMemoryBarrier2 m{VK_STRUCTURE_TYPE_MEMORY_BARRIER_2};
    m.srcStageMask = m.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    m.srcAccessMask = VK_ACCESS_2_MEMORY_WRITE_BIT;
    m.dstAccessMask = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT;
    VkDependencyInfo d{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    d.memoryBarrierCount = 1, d.pMemoryBarriers = &m;
    vkCmdPipelineBarrier2(cb, &d);
}

// The HUD panel's shader (shaders/xr_hud.comp): two sampled float images in, two RGBA8 storage images out, push descriptors
bool make_hud_pipeline() {
    Xr &x = xr();
    x.push_set = (PFN_vkCmdPushDescriptorSetKHR)vkGetDeviceProcAddr(x.device, "vkCmdPushDescriptorSetKHR");
    if (!x.push_set) return false;
    VkSamplerCreateInfo si{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
    si.magFilter = si.minFilter = VK_FILTER_NEAREST;
    si.addressModeU = si.addressModeV = si.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    if (vkCreateSampler(x.device, &si, nullptr, &x.nearest) != VK_SUCCESS) return false;
    const VkDescriptorSetLayoutBinding b[4] = {{0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {2, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {3, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}};
    VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    li.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR, li.bindingCount = 4, li.pBindings = b;
    if (vkCreateDescriptorSetLayout(x.device, &li, nullptr, &x.hud_set) != VK_SUCCESS) return false;
    const VkPushConstantRange pr{VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(int32_t) * 5};
    VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pi.setLayoutCount = 1, pi.pSetLayouts = &x.hud_set, pi.pushConstantRangeCount = 1, pi.pPushConstantRanges = &pr;
    if (vkCreatePipelineLayout(x.device, &pi, nullptr, &x.hud_layout) != VK_SUCCESS) return false;
    VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    mi.codeSize = sizeof XR_HUD_COMP_SPV, mi.pCode = XR_HUD_COMP_SPV;
    VkShaderModule m = VK_NULL_HANDLE;
    if (vkCreateShaderModule(x.device, &mi, nullptr, &m) != VK_SUCCESS) return false;
    VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    ci.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, nullptr, 0, VK_SHADER_STAGE_COMPUTE_BIT, m, "main", nullptr};
    ci.layout = x.hud_layout;
    const VkResult r = vkCreateComputePipelines(x.device, VK_NULL_HANDLE, 1, &ci, nullptr, &x.hud_pipe);
    vkDestroyShaderModule(x.device, m, nullptr);
    return r == VK_SUCCESS;
}

// ((Triforce VR) the sword's hand: the last two-grip draw's, else the Handedness row's)
// ((Triforce VR) research: while triforce-runs/gestures_in_immersive.txt exists, Immersive uses the gesture rules too (to see them
// from outside), a second's check
static bool gestures_in_immersive() {
    static bool on;
    static uint64_t looked;
    const uint64_t now = plat_now_ns();
    if (now - looked > 1000000000ull) {
        looked = now;
        const char *home = getenv("HOME");
        char path[512];
        snprintf(path, sizeof path, "%s/.app/pc_port/triforce-runs/gestures_in_immersive.txt", home ? home : "");
        FILE *f = fopen(path, "r");
        const bool v = f != nullptr;
        if (f) fclose(f);
        if (v != on) rt_log("vr: gestures in Immersive %s", v ? "on (research)" : "off");
        on = v;
    }
    return on;
}
// ((Triforce VR) the sword's gesture-chosen slashes: what a swing is, from its path in the head's frame (X toward the sword hand's
// side, U up, F ahead, metres) and what came before it (a pause, a raise). Codes: 0 none (ignored), 1-5 the combo's steps, 6 its
// finisher, 10/11 the steep slash from the sword hand's side / across the face, 12 the steep finisher, 20 the jump slash, 21 the
// stab, 31/32/33/36 the Biggoron's Sword's steps 1, 2, 3 and its finisher, 40 a slash in the air (the game's jump attack)
struct SlashIn {
    float X, U, F, pk, fwd0;    // (the swing so far; fwd0: how far ahead it went in its first 80 ms)
    float start_side, start_ahead, s0;   // (where it began: across the head (right +), ahead; s0 toward the sword hand's side)
    uint64_t quiet, last_fast, soft;     // (before it: the longest run under 0.3 m/s in 0.5 s, the time since over 1 m/s, under 0.5 in 1 s)
    bool raised, big, early;             // (a raise in the second before; the Biggoron's Sword; the live choice at 30 cm)
    bool zt = false, air = false;        // (Z held (the shield's raise, the head's tilt); Link in the air)
    float start_up = 0;                  // (how high it began, from the eyes)
};
int slash_classify(const SlashIn &in, const char **why) {
    const float X = in.X, U = in.U, F = in.F;
    const float flat = std::sqrt(X * X + F * F), st_deg = std::atan2(std::fabs(U), flat) * 57.2958f;
    const float side_up = std::sqrt(X * X + U * U);
    const bool strict = in.quiet >= 150000000ull || in.last_fast >= 300000000ull;
    const bool hesitant = in.early ? strict : in.soft >= 150000000ull || in.quiet >= 150000000ull || in.last_fast >= 350000000ull;
    const float fin = in.early ? 4.5f : 10.0f;   // (the finishers' speed)
    const bool deep = in.quiet >= 250000000ull || in.last_fast >= 350000000ull;
    const bool finisher = hesitant && in.pk > fin;
    const auto r = [&](int code, const char *w) { if (why) *why = w; return code; };
    // (in the air: any downward slash is the game's jump attack, nothing else looked for)
    if (in.air) return U < 0 && in.fwd0 > 0.0f ? r(40, "slash in the air (jump attack)") : r(0, "ignored (in the air, not downward)");
    if (in.fwd0 <= 0.0f) return r(0, "ignored (no forward start)");
    if (U > 0 && st_deg > 55.0f) return r(0, "ignored (wind-up: steep upward)");
    // (a stab: mostly forward, its forward part at least 0.8 of the rest)
    const bool thrust = F > 0.15f && F >= 0.8f * side_up;
    // ((Triforce VR) the Biggoron's Sword, both hands busy, needs no Z for its Z attacks (Z held for that press): its jump slash
    // first (begun at the middle, high or just after a raise, coming down)
    if (in.big && (in.raised || in.start_up > 0.0f) && std::fabs(in.start_side) < 0.10f && U < -0.10f) return r(20, "jump slash (Biggoron)");
    if (in.zt) {   // (the stab and the jump slash only with Z held: a swing begun high or just after a raise the jump slash, coming
                   // down or forward; a forward one begun lower without a raise the stab)
        if ((in.raised || in.start_up > 0.0f) && std::fabs(in.start_side) < 0.15f && (U < -0.10f || F > 0.15f)) return r(20, "jump slash");
        if (thrust) return r(21, "stab");
    }
    // (Z's finishers by the way the swing goes: away and down combo 1's (its third), else combo 2's)
    const auto z_finish = [&]() { return X < 0 && U < 0 ? r(13, "Z finisher 1 (away+down)") : r(12, "Z finisher 2 (toward+up)"); };
    // (the Biggoron's Sword: a forward thrust is its stab without Z too (Z held for that press), its hands on the hilt)
    // (without Z a truly straight jab: its forward part at least 1.5 times the rest, the Biggoron's swings carrying much forward)
    if (in.big && !in.zt && F > 0.15f && F >= 1.5f * side_up) return r(21, "stab (Biggoron)");
    // (a slash: at least 12 cm across or up and down; less is no slash)
    if (side_up < 0.12f) return r(0, "ignored (too small for a slash)");
    if (in.zt) {   // (Z held: Z's two slashes by the side of the face it starts on, its finishers; the Biggoron's the same)
        if (finisher) return z_finish();
        return in.s0 > 0 ? r(10, "Z slash: sword side (variant 1)") : r(11, "Z slash: far side (variant 2)");
    }
    if (in.big) {
        // (steep: up and down against side to side, its forward part left out (the Biggoron's swings carry much of it); strict on
        // the sword hand's side, lenient across the face)
        const float vert_deg = std::atan2(std::fabs(U), std::fabs(X)) * 57.2958f;
        if (U < 0 && vert_deg > (in.s0 > 0 ? 65.0f : 55.0f)) {
            if (deep && in.pk > 8.0f) return z_finish();
            return in.s0 > 0 ? r(10, "steep: sword side (Z variant 1)") : r(11, "steep: far side (Z variant 2)");
        }
        if (st_deg < 28.0f) return X < 0 ? r(31, "Biggoron 1 (horizontal away)") : r(32, "Biggoron 2 (horizontal toward)");
        if (X < 0 && U < 0) return finisher ? r(33, "Biggoron 3 (finisher, away+down)") : r(31, "Biggoron 1 (diagonal, no finisher)");
        if (X > 0 && U > 0) return finisher ? r(36, "Biggoron 6 (finisher, toward+up)") : r(32, "Biggoron 2 (diagonal, no finisher)");
        return r(0, "ignored (Biggoron backhand)");
    }
    // (the one-handed combos: four diagonals, 1 away and down (its finisher 3), 2 toward and up, 4 toward and down, 5 away and up;
    // combo 2's finisher F a level swing toward the sword hand's side)
    if (X > 0 && st_deg < 25.0f && finisher) return r(6, "finisher F (level, toward)");
    if (X < 0 && U < 0) return finisher ? r(3, "step 3 (finisher, away+down)") : r(1, "step 1 (away+down)");
    if (X < 0 && U >= 0) return r(5, "step 5 (away+up)");
    if (X >= 0 && U >= 0) return r(2, "step 2 (toward+up)");
    return r(4, "step 4 (toward+down)");
}
// (the combo counter that plays a code's step next (Link's component 107 +0x177c: n-1 plays CutSn, 5 its finisher); -1 none)
int slash_counter(int code) {
    switch (code) {
    case 1: case 2: case 3: case 4: case 5: return code - 1;
    case 6: return 5;
    case 31: return 0;
    case 32: return 1;
    case 33: return 2;
    case 36: return 5;
    case 10: return 0;
    case 11: return 1;
    case 12: return 5;
    case 13: return 2;
    default: return -1;
    }
}

int sword_hand_now() {
    const int live = g_live_sword.load();
    return live >= 0 ? live : strcmp(cfg_value("VR_HANDEDNESS"), "right") == 0 ? 1 : 0;
}

// VR_STEREO=balanced: each game frame drawn from one eye in turn (true geometry), the game's time held for the right
// eye's update so both eyes show one moment, rather than performant's depth stereo from the head
bool stereo_balanced() { return strcmp(cfg_value("VR_STEREO"), "balanced") == 0; }
// ((Triforce VR) the hand controllers' control scheme (VR Controls' Control Scheme): Full Gesture, or another (placeholder_play)
bool scheme_full_gesture() { return strcmp(cfg_value("VR_SCHEME"), "placeholder") != 0; }
bool stereo_turns() { return stereo_balanced(); }
// VR_STEREO=accurate: the game draws the left eye's picture and the renderer the same frame again for the right (true depth,
// both eyes the same moment, the game's full rate)
bool stereo_accurate() { return strcmp(cfg_value("VR_STEREO"), "accurate") == 0; }
std::atomic<double> update_step{-1};

// (vk_xr_capture, hud_mu held) the scene without the HUD and the HUD's panel, made from the HUD's own layer (without one: from
// the target as it is now and the scene kept from before the HUD), the panel clear within `cut` pixels of its middle (the game's
// reticle while Link aims); false when there is nothing new to make them from
bool make_panel(VkCommandBuffer cb, int cut, VkImageView tview = VK_NULL_HANDLE, VkImageView sview = VK_NULL_HANDLE, bool again = false) {
    Xr &x = xr();
    if (!x.scene || !x.hud_target) return x.panel_no_scene++, false;
    if (x.kept == x.used && !tview && !again) return x.panel_not_new++, false;
    if (!x.hud_tried) {
        x.hud_tried = true;
        if (!make_hud_pipeline()) {
            rt_log("vr: the HUD panel's shader could not be made: the HUD stays in the picture");
            x.hud_pipe = VK_NULL_HANDLE;
        }
    }
    if (!x.hud_pipe) return false;
    if (!x.scene8) {
        const VkImageUsageFlags u = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
        if (!make_image(x.hud_w, x.hud_h, VK_FORMAT_R8G8B8A8_UNORM, u | VK_IMAGE_USAGE_SAMPLED_BIT, x.scene8, x.scene8_view) ||
            !make_image(x.hud_w, x.hud_h, VK_FORMAT_R8G8B8A8_UNORM, u | VK_IMAGE_USAGE_SAMPLED_BIT, x.panel8, x.panel8_view)) {
            x.hud_pipe = VK_NULL_HANDLE;
            return false;
        }
        rt_log("vr: the HUD panel: the HUD's target %ux%u (format %d)", x.hud_w, x.hud_h, (int)x.hud_format);
    }
    if (x.target_viewed != x.hud_target) {   // a view of the game's target, made again when the target is another
        if (x.target_view) vkDestroyImageView(x.device, x.target_view, nullptr);
        VkImageViewCreateInfo vc{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        vc.image = x.hud_target, vc.viewType = VK_IMAGE_VIEW_TYPE_2D, vc.format = x.hud_format;
        vc.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        x.target_view = VK_NULL_HANDLE;
        if (vkCreateImageView(x.device, &vc, nullptr, &x.target_view) != VK_SUCCESS) return false;
        x.target_viewed = x.hud_target;
    }
    x.used = x.kept;
    if (x.layer) barrier(cb, x.layer, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
    barrier(cb, x.scene8, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
    barrier(cb, x.panel8, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.hud_pipe);
    const VkDescriptorImageInfo info[4] = {{x.nearest, x.layer ? x.layer_view : tview ? tview : x.target_view, VK_IMAGE_LAYOUT_GENERAL},
                                           {x.nearest, sview ? sview : x.scene_view, VK_IMAGE_LAYOUT_GENERAL},
                                           {VK_NULL_HANDLE, x.scene8_view, VK_IMAGE_LAYOUT_GENERAL},
                                           {VK_NULL_HANDLE, x.panel8_view, VK_IMAGE_LAYOUT_GENERAL}};
    VkWriteDescriptorSet w[4]{};
    for (uint32_t i = 0; i < 4; i++) {
        w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, w[i].dstBinding = i, w[i].descriptorCount = 1;
        w[i].descriptorType = i < 2 ? VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER : VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
        w[i].pImageInfo = &info[i];
    }
    vkCmdPushDescriptorSetKHR(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.hud_layout, 0, 4, w);
    // ((Triforce VR) 2: the layer with no full-picture fade looked for, the game paused (its menus' grey backdrop covers all)
    // ((Triforce VR) the Turn vignette, thousandths: Smooth turning and the eyes carried through the world (vk_xr_camera), eased
    // in quickly as either starts, out over a third of a second)
    int32_t vignette = 0;
    {
        static float v;
        static uint64_t at;
        const uint64_t now = plat_now_ns();
        const float dt = at ? std::fmin(0.2f, (float)(now - at) * 1e-9f) : 0.0f;
        at = now;
        const uint64_t said = g_turning_at.load();
        const float turn = said && now - said < 150000000ull ? std::fmin(1.0f, g_turning.load() * 1.5f) : 0.0f;
        const float want = !strcmp(cfg_value("VR_VIGNETTE"), "on") ? std::fmax(turn, g_moving.load()) : 0.0f;   // (a choice: its name)
        v += (want - v) * (1.0f - std::exp(-dt / (want > v ? 0.08f : 0.33f)));
        vignette = (int32_t)(v * 1000.0f);
    }
    const int32_t pc[5] = {(int32_t)x.hud_w, (int32_t)x.hud_h, x.layer ? (x.game_paused.load() ? 2 : 1) : 0, cut, vignette};
    vkCmdPushConstants(cb, x.hud_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, pc);
    vkCmdDispatch(cb, (x.hud_w + 7) / 8, (x.hud_h + 7) / 8, 1);
    barrier(cb, x.scene8, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
    x.panels++;
    return true;
}

// (vk_xr_capture, a picture from the head) the performance overlay (vk_menu.cpp menu_perf_rect), drawn on the window
// over the picture, copied from the window to the top middle of the HUD's panel, its size there as on the window; the
// HUD box made a clear panel first when the picture has none
// The window's rect r ({x, y, w, h}) clipped to it into [x0, y0, x1, y1); false when nothing is left
bool clip_rect(const int r[4], VkExtent2D extent, int out[4]) {
    out[0] = std::max(r[0], 0), out[1] = std::max(r[1], 0);
    out[2] = std::min(r[0] + r[2], (int)extent.width), out[3] = std::min(r[1] + r[3], (int)extent.height);
    return out[2] > out[0] && out[3] > out[1];
}

// The host's own overlay drawn into the window (vk_menu.cpp) onto the HUD's box: the performance overlay at the top middle.
// Without a HUD box this frame (d.hud and d.menu false) one is made clear first.
void overlay_onto_hud(VkCommandBuffer cb, int slot, VkImage window, VkExtent2D extent, Drawn &d) {
    Xr &x = xr();
    int r[4], perf[4] = {};
    const bool has_perf = menu_perf_rect(r) && clip_rect(r, extent, perf);
    if (!has_perf) return;
    const VkImage hb = x.hud_boxes[slot];
    const bool fresh = !d.hud && !d.menu;
    barrier(cb, hb, fresh ? VK_IMAGE_LAYOUT_UNDEFINED : VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    if (fresh) {
        const VkClearColorValue clear{};
        const VkImageSubresourceRange all{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        vkCmdClearColorImage(cb, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &clear, 1, &all);
        barrier(cb, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    }
    const float sx = (float)x.width / (float)extent.width, sy = (float)x.height / (float)extent.height;
    VkImageBlit b{};
    b.srcSubresource = b.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    if (has_perf) {
        const int x0 = perf[0], y0 = perf[1], x1 = perf[2], y1 = perf[3];
        const int w = std::max(1, (int)((x1 - x0) * sx)), h = std::max(1, (int)((y1 - y0) * sy));
        const int dx = ((int)x.width - w) / 2, dy = (int)(0.03f * (float)x.height);
        b.srcOffsets[0] = {x0, y0, 0}, b.srcOffsets[1] = {x1, y1, 1};
        b.dstOffsets[0] = {dx, dy, 0}, b.dstOffsets[1] = {std::min(dx + w, (int)x.width), std::min(dy + h, (int)x.height), 1};
        vkCmdBlitImage(cb, window, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                       VK_FILTER_LINEAR);
    }
    barrier(cb, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    if (fresh && !d.menu) d.hud = true;
}

// The depth stereo shader (shaders/xr_depth.comp): the scene and its depth sampled, the eye's RGBA8 image out
bool make_depth_pipeline() {
    Xr &x = xr();
    if (!x.push_set) return false;
    VkSamplerCreateInfo si{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
    si.magFilter = si.minFilter = VK_FILTER_LINEAR;
    si.addressModeU = si.addressModeV = si.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    if (vkCreateSampler(x.device, &si, nullptr, &x.linear) != VK_SUCCESS) return false;
    const VkDescriptorSetLayoutBinding b[4] = {{0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {2, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {3, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}};
    VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    li.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR, li.bindingCount = 4, li.pBindings = b;
    if (vkCreateDescriptorSetLayout(x.device, &li, nullptr, &x.depth_set) != VK_SUCCESS) return false;
    const VkPushConstantRange pr{VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(float) * 7};
    VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pi.setLayoutCount = 1, pi.pSetLayouts = &x.depth_set, pi.pushConstantRangeCount = 1, pi.pPushConstantRanges = &pr;
    if (vkCreatePipelineLayout(x.device, &pi, nullptr, &x.depth_layout) != VK_SUCCESS) return false;
    VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    mi.codeSize = sizeof XR_DEPTH_COMP_SPV, mi.pCode = XR_DEPTH_COMP_SPV;
    VkShaderModule m = VK_NULL_HANDLE;
    if (vkCreateShaderModule(x.device, &mi, nullptr, &m) != VK_SUCCESS) return false;
    VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    ci.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, nullptr, 0, VK_SHADER_STAGE_COMPUTE_BIT, m, "main", nullptr};
    ci.layout = x.depth_layout;
    const VkResult r = vkCreateComputePipelines(x.device, VK_NULL_HANDLE, 1, &ci, nullptr, &x.depth_pipe);
    vkDestroyShaderModule(x.device, m, nullptr);
    return r == VK_SUCCESS;
}

// The depth copy's shader (shaders/xr_depth_keep.comp), made on the thread that records the scene: the scene's depth
// sampled, an R32F storage image out
bool make_keep_pipeline() {
    Xr &x = xr();
    x.keep_push = (PFN_vkCmdPushDescriptorSetKHR)vkGetDeviceProcAddr(x.device, "vkCmdPushDescriptorSetKHR");
    if (!x.keep_push) return false;
    VkSamplerCreateInfo si{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
    si.magFilter = si.minFilter = VK_FILTER_NEAREST;
    si.addressModeU = si.addressModeV = si.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    if (vkCreateSampler(x.device, &si, nullptr, &x.keep_sampler) != VK_SUCCESS) return false;
    const VkDescriptorSetLayoutBinding b[3] = {{0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {1, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {2, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}};
    VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    li.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR, li.bindingCount = 3, li.pBindings = b;
    if (vkCreateDescriptorSetLayout(x.device, &li, nullptr, &x.keep_set) != VK_SUCCESS) return false;
    const VkPushConstantRange pr{VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(int32_t) * 2 + sizeof(float)};   // (size, nearer)
    VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pi.setLayoutCount = 1, pi.pSetLayouts = &x.keep_set, pi.pushConstantRangeCount = 1, pi.pPushConstantRanges = &pr;
    if (vkCreatePipelineLayout(x.device, &pi, nullptr, &x.keep_layout) != VK_SUCCESS) return false;
    VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    mi.codeSize = sizeof XR_DEPTH_KEEP_COMP_SPV, mi.pCode = XR_DEPTH_KEEP_COMP_SPV;
    VkShaderModule m = VK_NULL_HANDLE;
    if (vkCreateShaderModule(x.device, &mi, nullptr, &m) != VK_SUCCESS) return false;
    VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    ci.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, nullptr, 0, VK_SHADER_STAGE_COMPUTE_BIT, m, "main", nullptr};
    ci.layout = x.keep_layout;
    const VkResult r = vkCreateComputePipelines(x.device, VK_NULL_HANDLE, 1, &ci, nullptr, &x.keep_pipe);
    vkDestroyShaderModule(x.device, m, nullptr);
    return r == VK_SUCCESS;
}

// The aiming reticle's shader (shaders/xr_aim.comp): the scene's depth sampled, scene8 read and written
bool make_aim_pipeline() {
    Xr &x = xr();
    if (!x.push_set || !x.nearest) return false;
    const VkDescriptorSetLayoutBinding b[2] = {{0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                               {1, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}};
    VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    li.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR, li.bindingCount = 2, li.pBindings = b;
    if (vkCreateDescriptorSetLayout(x.device, &li, nullptr, &x.aim_set) != VK_SUCCESS) return false;
    const VkPushConstantRange pr{VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(float) * 12};
    VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pi.setLayoutCount = 1, pi.pSetLayouts = &x.aim_set, pi.pushConstantRangeCount = 1, pi.pPushConstantRanges = &pr;
    if (vkCreatePipelineLayout(x.device, &pi, nullptr, &x.aim_layout) != VK_SUCCESS) return false;
    VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    mi.codeSize = sizeof XR_AIM_COMP_SPV, mi.pCode = XR_AIM_COMP_SPV;
    VkShaderModule m = VK_NULL_HANDLE;
    if (vkCreateShaderModule(x.device, &mi, nullptr, &m) != VK_SUCCESS) return false;
    VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    ci.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, nullptr, 0, VK_SHADER_STAGE_COMPUTE_BIT, m, "main", nullptr};
    ci.layout = x.aim_layout;
    const VkResult r = vkCreateComputePipelines(x.device, VK_NULL_HANDLE, 1, &ci, nullptr, &x.aim_pipe);
    vkDestroyShaderModule(x.device, m, nullptr);
    return r == VK_SUCCESS;
}

// (vk_xr_capture, hud_mu held, after make_panel, before make_eyes) the reticle drawn into scene8 where the aim's ray
// first goes behind the scene's depth, while Link aims
void make_aim(VkCommandBuffer cb, const Drawn &d) {
    Xr &x = xr();
    float planes[2];
    if (!d.aim || !x.depth_kept || !vk_xr_planes(planes)) return;
    if (!x.aim_tried) {
        x.aim_tried = true;
        if (!make_aim_pipeline()) {
            rt_log("vr: the aiming reticle's shader could not be made");
            x.aim_pipe = VK_NULL_HANDLE;
        }
    }
    if (!x.aim_pipe) return;
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.aim_pipe);
    const VkDescriptorImageInfo info[2] = {{x.nearest, x.depth_view, VK_IMAGE_LAYOUT_GENERAL},
                                           {VK_NULL_HANDLE, x.scene8_view, VK_IMAGE_LAYOUT_GENERAL}};
    VkWriteDescriptorSet w[2]{};
    for (uint32_t i = 0; i < 2; i++) {
        w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, w[i].dstBinding = i, w[i].descriptorCount = 1;
        w[i].descriptorType = i ? VK_DESCRIPTOR_TYPE_STORAGE_IMAGE : VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        w[i].pImageInfo = &info[i];
    }
    vkCmdPushDescriptorSetKHR(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.aim_layout, 0, 2, w);
    const float pc[12] = {(float)x.hud_w, (float)x.hud_h, d.aim_o[0], d.aim_o[1], d.aim_o[2], d.aim_d[0], d.aim_d[1],
                          d.aim_d[2], d.lens.r * d.scale, d.lens.u * d.scale, planes[0], planes[1]};
    vkCmdPushConstants(cb, x.aim_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, pc);
    vkCmdDispatch(cb, 1, 1, 1);
    barrier(cb, x.scene8, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
}


// Stereo Balanced (vk_xr_capture, hud_mu held): this eye's picture (scene8, drawn from it) kept with
// its pose; once both eyes have one the picture is shown in stereo, each eye its latest at its own pose
void keep_eye(VkCommandBuffer cb, Drawn &d) {
    Xr &x = xr();
    if (!x.acc8[0] || x.acc_w != x.hud_w || x.acc_h != x.hud_h) {   // (another size's are left behind)
        const VkImageUsageFlags u = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        for (int e = 0; e < 3; e++)
            if (!make_image(x.hud_w, x.hud_h, VK_FORMAT_R8G8B8A8_UNORM, u, x.acc8[e], x.acc8_view[e])) {
                x.acc8[0] = x.acc8[1] = x.acc8[2] = VK_NULL_HANDLE;
                return;
            }
        x.acc_w = x.hud_w, x.acc_h = x.hud_h, x.acc_have[0] = x.acc_have[1] = x.acc_have[2] = false, x.pair_ok = false;
        for (int e = 0; e < 3; e++) barrier(cb, x.acc8[e], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
    }
    // the left eye's picture waits in [2] while the pair before stays shown, and goes to [0] with its right
    const bool paired = stereo_balanced();
    if (!paired) x.pair_ok = false;
    const int into = paired && d.eye == 0 ? 2 : d.eye;
    VkImageCopy c{};
    c.srcSubresource = c.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    c.extent = {x.hud_w, x.hud_h, 1};
    vkCmdCopyImage(cb, x.scene8, VK_IMAGE_LAYOUT_GENERAL, x.acc8[into], VK_IMAGE_LAYOUT_GENERAL, 1, &c);
    barrier(cb, x.acc8[into], VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
    x.acc_pose[into] = d.pose, x.acc_have[into] = true;
    std::memcpy(x.acc_base[into], d.base, sizeof d.base), x.acc_bx[into] = d.bx, x.acc_bz[into] = d.bz;
    if (paired) {
        if (d.eye == 0) {
            if (x.pair_ok) d.stereo = true, d.eye_pose[0] = x.pair_pose[0], d.eye_pose[1] = x.pair_pose[1];
            return;
        }
        if (!x.acc_have[2]) return;
        std::swap(x.acc8[0], x.acc8[2]), std::swap(x.acc8_view[0], x.acc8_view[2]);
        x.acc_pose[0] = x.acc_pose[2], std::memcpy(x.acc_base[0], x.acc_base[2], sizeof x.acc_base[0]);
        x.acc_bx[0] = x.acc_bx[2], x.acc_bz[0] = x.acc_bz[2], x.acc_have[0] = true, x.acc_have[2] = false;
    }
    if (x.acc_have[0] && x.acc_have[1]) {
        d.stereo = true;
        d.eye_pose[d.eye] = d.pose;
        // the other eye's picture, drawn a frame before with Link (and the game's camera) elsewhere in the world: its
        // pose put in this picture's LOCAL space, local = A_now^T (base_then - base_now + A_then local_then), turned by
        // the yaw between the two
        const int o = 1 - d.eye;
        const Pose &then = x.acc_pose[o];
        const double ob = x.acc_bx[o], oz = x.acc_bz[o];
        const double then_axes[3][3] = {{oz, 0, -ob}, {0, 1, 0}, {ob, 0, oz}}, now_axes[3][3] = {{d.bz, 0, -d.bx}, {0, 1, 0}, {d.bx, 0, d.bz}};
        double w[3];
        for (int c = 0; c < 3; c++)
            w[c] = x.acc_base[o][c] - d.base[c] + then_axes[0][c] * then.p[0] + then_axes[1][c] * then.p[1] + then_axes[2][c] * then.p[2];
        Pose moved = then;
        for (int k = 0; k < 3; k++) moved.p[k] = (float)(now_axes[k][0] * w[0] + now_axes[k][1] * w[1] + now_axes[k][2] * w[2]);
        // the yaw from then's axes to now's: then's right in now's axes (cos, and the back component as sin)
        const double c0 = now_axes[0][0] * then_axes[0][0] + now_axes[0][2] * then_axes[0][2];
        const double s0 = now_axes[2][0] * then_axes[0][0] + now_axes[2][2] * then_axes[0][2];
        const double half = 0.5 * std::atan2(-s0, c0);
        const float qy[4] = {0, (float)std::sin(half), 0, (float)std::cos(half)};   // about y, x y z w
        const float *a = qy, *b = then.q;   // moved.q = qy * then.q
        moved.q[0] = a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1];
        moved.q[1] = a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0];
        moved.q[2] = a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3];
        moved.q[3] = a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2];
        d.eye_pose[o] = moved;
        if (paired) x.pair_pose[0] = d.eye_pose[0], x.pair_pose[1] = d.eye_pose[1], x.pair_ok = true;
    }
}

// the image an eye's picture is in with stereo: Balanced's kept pictures, else depth stereo's
VkImage eye_image(const Drawn &d, int e) { return d.eye >= 0 ? xr().acc8[e] : xr().eye8[e]; }

VkImage eye_image(const Drawn &d, int e);
// ((Triforce VR) VR + a flat screen's 3D (red/cyan, side by side, crossed eyes, above and below, Cardboard): the desktop shows the
// headset's two eyes made into that picture by Flatscreen 3D's shader, the HUD at the screen; the window back in TRANSFER_SRC
// after. False when it could not (the caller then does as before)
bool window_vr_3d(VkCommandBuffer cb, VkImage window, VkExtent2D extent, const int rect[4], const Drawn &d) {
    Xr &x = xr();
    if (!x.hud_w || !x.hud_h || !x.panel8_view) return false;
    if (!x.flat_tried) {
        x.flat_tried = true;
        if (!make_flat_pipelines()) {
            rt_log("flat3d: the shaders could not be made: VR's desktop 3D off");
            x.flat_pipe = VK_NULL_HANDLE;
        } else rt_log("flat3d: VR's desktop 3D on");
    }
    if (!x.flat_pipe) return false;
    if (!x.screen) {
        if (!make_buffer(16, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT, x.screen)) {
            x.screen = VK_NULL_HANDLE;
            return false;
        }
        vkCmdFillBuffer(cb, x.screen, 0, 16, 0);
        memory_barrier(cb);
    }
    if (!x.flat8 || x.flat_w != x.hud_w || x.flat_h != x.hud_h) {
        if (!make_image(x.hud_w, x.hud_h, VK_FORMAT_R8G8B8A8_UNORM, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
                        x.flat8, x.flat8_view)) {
            x.flat8 = VK_NULL_HANDLE;
            return false;
        }
        x.flat_w = x.hud_w, x.flat_h = x.hud_h;
    }
    const VkImageView ev[2] = {d.eye >= 0 ? x.acc8_view[0] : x.eye8_view[0], d.eye >= 0 ? x.acc8_view[1] : x.eye8_view[1]};
    if (!ev[0] || !ev[1]) return false;
    const char *m = cfg_value("FLAT3D");
    const int32_t mode = !strcmp(m, "sbs") ? 1 : !strcmp(m, "crosseye") ? 2 : !strcmp(m, "tab") ? 3 : !strcmp(m, "cardboard") ? 4 : 0;
    barrier(cb, x.flat8, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.flat_pipe);
    const VkDescriptorImageInfo info[4] = {{x.linear, ev[0], VK_IMAGE_LAYOUT_GENERAL},
                                           {x.linear, ev[1], VK_IMAGE_LAYOUT_GENERAL},
                                           {x.linear, x.panel8_view, VK_IMAGE_LAYOUT_GENERAL},
                                           {VK_NULL_HANDLE, x.flat8_view, VK_IMAGE_LAYOUT_GENERAL}};
    const VkDescriptorBufferInfo scr{x.screen, 0, 16};
    VkWriteDescriptorSet w[5]{};
    for (uint32_t i = 0; i < 5; i++) {
        w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, w[i].dstBinding = i, w[i].descriptorCount = 1;
        w[i].descriptorType = i == 4 ? VK_DESCRIPTOR_TYPE_STORAGE_BUFFER
                              : i == 3 ? VK_DESCRIPTOR_TYPE_STORAGE_IMAGE : VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        if (i == 4) w[i].pBufferInfo = &scr;
        else w[i].pImageInfo = &info[i];
    }
    vkCmdPushDescriptorSetKHR(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.flat_layout, 0, 5, w);
    struct {
        int32_t w, h, mode, hud_on;
        float shift_l, shift_r;
    } fp{(int32_t)x.hud_w, (int32_t)x.hud_h, mode, 1, 0.0f, 0.0f};   // (the headset's eyes already apart: none moved)
    vkCmdPushConstants(cb, x.flat_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof fp, &fp);
    vkCmdDispatch(cb, (x.hud_w + 7) / 8, (x.hud_h + 7) / 8, 1);
    barrier(cb, x.flat8, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
    int to[4];
    gfx_fit_rect(rect[2], rect[3], (int)extent.width, (int)extent.height, to);
    if (to[2] <= 1 || to[3] <= 1) return false;
    barrier(cb, window, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    const VkClearColorValue black{};
    const VkImageSubresourceRange all{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdClearColorImage(cb, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &black, 1, &all);
    VkImageBlit b{};
    b.srcSubresource = b.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    b.srcOffsets[1] = {(int32_t)x.flat_w, (int32_t)x.flat_h, 1};
    b.dstOffsets[0] = {to[0], to[1], 0}, b.dstOffsets[1] = {to[0] + to[2], to[1] + to[3], 1};
    vkCmdBlitImage(cb, x.flat8, VK_IMAGE_LAYOUT_GENERAL, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
    barrier(cb, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    return true;
}
// (vk_xr_capture, last, hud_mu held) with Flatscreen 3D's Cardboard choice while VR runs in stereo: the desktop shows both of
// the headset's eyes, each its whole picture at half its size in its own half (the left eye's on the left), for a phone in a
// viewer or a stream in 3D; the window back in TRANSFER_SRC after
void window_both_eyes(VkCommandBuffer cb, VkImage window, VkExtent2D extent, const int rect[4], const Drawn &d) {
    Xr &x = xr();
    int to[4];
    gfx_fit_rect(rect[2], rect[3], (int)extent.width, (int)extent.height, to);
    if (to[2] <= 1 || to[3] <= 1 || !x.hud_w || !x.hud_h) return;
    barrier(cb, window, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    const VkClearColorValue black{};
    const VkImageSubresourceRange all{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdClearColorImage(cb, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &black, 1, &all);
    const int half = to[2] / 2, h = std::min(to[3], (int)((float)half * (float)x.hud_h / (float)x.hud_w));
    const int y0 = to[1] + (to[3] - h) / 2;
    for (int e = 0; e < 2; e++) {
        VkImageBlit b{};
        b.srcSubresource = b.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
        b.srcOffsets[1] = {(int32_t)x.hud_w, (int32_t)x.hud_h, 1};
        b.dstOffsets[0] = {to[0] + e * half, y0, 0}, b.dstOffsets[1] = {to[0] + e * half + half, y0 + h, 1};
        vkCmdBlitImage(cb, eye_image(d, e), VK_IMAGE_LAYOUT_GENERAL, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
    }
    barrier(cb, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
}

// Stereo Balanced (vk_xr_capture, last, hud_mu held): the desktop shows the left eye. Its presents' window picture
// (with the HUD and the hands) is kept, and put back over the window on the right eye's presents, so the window does
// not shift between the eyes every frame; the window back in TRANSFER_SRC after
void window_left_eye(VkCommandBuffer cb, VkImage window, VkExtent2D extent, VkFormat format, const int rect[4], int eye) {
    Xr &x = xr();
    int to[4];
    gfx_fit_rect(rect[2], rect[3], (int)extent.width, (int)extent.height, to);
    if (to[2] <= 0 || to[3] <= 0) return;
    if (!x.win_left || x.win_left_w != (uint32_t)to[2] || x.win_left_h != (uint32_t)to[3] || x.win_left_format != format) {
        x.win_left_have = false;
        VkImageView unused = VK_NULL_HANDLE;
        if (!make_image((uint32_t)to[2], (uint32_t)to[3], format, VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
                        x.win_left, unused)) {
            x.win_left = VK_NULL_HANDLE;
            return;
        }
        x.win_left_w = (uint32_t)to[2], x.win_left_h = (uint32_t)to[3], x.win_left_format = format;
        barrier(cb, x.win_left, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
    }
    VkImageCopy c{};
    c.srcSubresource = c.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    c.extent = {(uint32_t)to[2], (uint32_t)to[3], 1};
    if (eye == 0) {
        c.srcOffset = {to[0], to[1], 0};
        vkCmdCopyImage(cb, window, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, x.win_left, VK_IMAGE_LAYOUT_GENERAL, 1, &c);
        barrier(cb, x.win_left, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
        x.win_left_have = true;
    } else if (x.win_left_have) {
        c.dstOffset = {to[0], to[1], 0};
        barrier(cb, window, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        vkCmdCopyImage(cb, x.win_left, VK_IMAGE_LAYOUT_GENERAL, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &c);
        barrier(cb, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    }
}

// (vk_xr_capture, hud_mu held, after make_panel) each eye's picture from the scene make_panel left in scene8 and this
// present's scene depth: the eye half the eyes' distance (VR_DEPTH percent of it) to its side of the head's
// view; false without the depth (the head's view then shows the one picture to both eyes)
bool eyes_from(VkCommandBuffer cb, const float shift[2], const float planes[2]);

bool make_eyes(VkCommandBuffer cb, const Drawn &d) {
    Xr &x = xr();
    float planes[2];
    if (!vk_xr_planes(planes) || !x.depth_kept) {
        x.stereo_missed++;
        return false;
    }
    const float tan_x = d.lens.r * d.scale;   // the game's lens: x_ndc = view x / (z tan_x)
    const float strength = 0.01f * (float)cfg_int("VR_DEPTH");
    float shift[2];
    for (int e = 0; e < 2; e++) shift[e] = (e ? 0.5f : -0.5f) * d.ipd * strength / tan_x;   // the left eye to the left
    if (!eyes_from(cb, shift, planes)) return false;
    x.stereo_pictures++;
    return true;
}

// each eye's picture (eye8) from scene8 and the kept depth, the eye `shift` (view units times P00) to its side
bool eyes_from(VkCommandBuffer cb, const float shift[2], const float planes[2]) {
    Xr &x = xr();
    if (!x.depth_tried) {
        x.depth_tried = true;
        if (!make_depth_pipeline()) {
            rt_log("vr: the depth stereo shader could not be made: one picture to both eyes");
            x.depth_pipe = VK_NULL_HANDLE;
        }
    }
    if (!x.depth_pipe) return false;
    if (!x.eye8[0] || x.eye8_w != x.hud_w || x.eye8_h != x.hud_h) {   // (another size's are left behind, as the scene's)
        for (int e = 0; e < 2; e++)
            if (!make_image(x.hud_w, x.hud_h, VK_FORMAT_R8G8B8A8_UNORM,
                            VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                            x.eye8[e], x.eye8_view[e])) {
                rt_log("vr: the depth stereo eye images %ux%u could not be made: one picture to both eyes", x.hud_w, x.hud_h);
                x.depth_pipe = VK_NULL_HANDLE;
                return false;
            }
        x.eye8_w = x.hud_w, x.eye8_h = x.hud_h;
        rt_log("vr: depth stereo: eye pictures %ux%u", x.hud_w, x.hud_h);
    }
    const float near_inv = 1.0f / 0.01f;   // a guard alone: everything has its own depth down to a centimetre
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.depth_pipe);
    for (int e = 0; e < 2; e++) {
        barrier(cb, x.eye8[e], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
        const VkDescriptorImageInfo info[3] = {{x.linear, x.scene8_view, VK_IMAGE_LAYOUT_GENERAL},
                                               {x.nearest, x.depth_view, VK_IMAGE_LAYOUT_GENERAL},
                                               {VK_NULL_HANDLE, x.eye8_view[e], VK_IMAGE_LAYOUT_GENERAL}};
        const VkDescriptorBufferInfo rows{x.rows, 0, 8ull * x.depth_h};
        VkWriteDescriptorSet w[4]{};
        for (uint32_t i = 0; i < 4; i++) {
            w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, w[i].dstBinding = i, w[i].descriptorCount = 1;
            w[i].descriptorType = i == 3 ? VK_DESCRIPTOR_TYPE_STORAGE_BUFFER
                                  : i < 2 ? VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER : VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
            if (i == 3) w[i].pBufferInfo = &rows;
            else w[i].pImageInfo = &info[i];
        }
        vkCmdPushDescriptorSetKHR(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.depth_layout, 0, 4, w);
        // the largest move, at most a quarter of the picture: the shader scans no further
        const float most = std::min(0.25f, 0.5f * std::fabs(shift[e]) * near_inv + 0.002f);
        const float pc[7] = {(float)x.hud_w, (float)x.hud_h, shift[e], planes[0], planes[1], most, near_inv};
        vkCmdPushConstants(cb, x.depth_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, pc);
        vkCmdDispatch(cb, (x.hud_w + 7) / 8, (x.hud_h + 7) / 8, 1);
        barrier(cb, x.eye8[e], VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
    }
    return true;
}

// The hand controllers through OpenXR's actions, bound for the Touch controllers (Quest), read each headset frame onto
// the pad's buttons (input_map.h bits): A and B their own, X and Y A and B again; either stick's click alone X (jump); the left grip ZL (the Z lock), the right grip ZR; on the PSVR2 both sticks' clicks together (L3+R3, as its Options cannot reach OpenXR) or the Touch left Menu tapped Plus (the inventory), held a second
// Minus; the sword hand (VR_HANDEDNESS, the left by default) swung fast Y tapped, or held while the swing went
// outward and left the hand out to the side (the charge), until the hand comes back in. The shield hand's shield turned to face ahead before its own side's eye holds ZL (the Z lock), as Link
// holds his shield. Both arms shaken upward press the D-pad's down (the boots), both hands together before the face
// its left (the ocarina), both hands beside the head its right (Navi), a hand shaken sideways above the head its up
// (the mask). Both hands brought together behind the head draw the sword and shield (a tap of Y) or, while they are out,
// put them away (B). While Link plays the ocarina (vk_xr_ocarina) the notes swap places: the right stick's left, up, right and
// down play Y, X, A and R, the A button L; no sword or jump meanwhile. They go on the
// pad (vk_xr_pad); gamepad leaves the pad to the gamepad.
struct Controls {
    enum { A = 0, B, X, Y, STICK_L, STICK_R, L, R, ZL, ZR, PLUS, MINUS, LEFT, UP, RIGHT, DOWN };
    int dpad_bit = -1;
    uint64_t dpad_from = 0, dpad_until = 0;
    static constexpr uint64_t press_ns = 120000000ull, hold_ns = 1000000000ull;
    XrActionSet set = XR_NULL_HANDLE;
    XrAction stick = XR_NULL_HANDLE, click = XR_NULL_HANDLE, trigger = XR_NULL_HANDLE, squeeze = XR_NULL_HANDLE,
             grip = XR_NULL_HANDLE, a = XR_NULL_HANDLE, b = XR_NULL_HANDLE, xb = XR_NULL_HANDLE, yb = XR_NULL_HANDLE,
             menu = XR_NULL_HANDLE, aim = XR_NULL_HANDLE, haptic = XR_NULL_HANDLE;   // (haptic: the controllers' vibration, the game's rumble)
    bool buzzing[2] = {false, false};
    XrPath hand[2]{};
    XrSpace grip_space[2]{}, aim_space[2]{};
    bool ok = false;
    bool trigger_on[2]{}, squeeze_on[2]{};
    uint64_t menu_down = 0, plus_until = 0, minus_until = 0;   // plat_now_ns
    bool minus_sent = false;
    static constexpr uint64_t click_wait_ns = 80000000ull;
    bool combo_latch = false;   // both sticks clicked together, until both are let go
    uint64_t click_since = 0;   // one stick clicked alone since (plat_now_ns)
    // the swing: the sword hand's grip positions over the last frames (plat_now_ns). A swing starts once the speed is past
    // swing_on (VR_SWING_SPEED), at least refractory_ns after the last one started (a swing's follow-through is
    // not another), and ends under swing_off. Each is a tap of Y (tap_ns down, at least gap_ns up
    // before the next, one swing more kept for then), held on as the charge when it went outward and the hand is
    // out_on (VR_CHARGE_REACH) from the head's upright line at the tap's end, released once the hand is back
    // within out_off, 10 cm nearer
    static constexpr float swing_off = 1.0f;   // metres a second
    static constexpr uint64_t refractory_ns = 300000000ull;
    uint64_t swing_at = 0;
    static constexpr uint64_t tap_ns = 80000000ull, gap_ns = 80000000ull;
    float swing_p[4][3]{};
    uint64_t swing_t[4]{};
    int swing_n = 0, swing_hand = 1;
    bool swinging = false, outward = false, charging = false, queued = false;
    uint64_t y_down = 0, y_up = 0;   // the tap's press and release (0: none now)
    // the draw: both grips behind the head's eyes (behind_on), no lower than shoulder_drop under them and within
    // together_on of each other; once a draw, again only after the hands parted (apart_off) and refractory
    // ((Triforce VR) behind_on 12 cm: a hand only just behind the eyes is often still before the body)
    static constexpr float behind_on = 0.12f, shoulder_drop = 0.30f;
    // the D-pad's gestures (in play): both arms shaken upward the boots (down), both hands together before the face the
    // ocarina (left), both hands beside the head Navi (right), a hand shaken sideways above the head the mask (up); each
    // once, then not again for dpad_refractory_ns; the poses held dwell_ns first
    static constexpr uint64_t dpad_refractory_ns = 1000000000ull, dwell_ns = 250000000ull;
    float hand_p[2][4][3]{};
    uint64_t hand_t[2][4]{};
    int hand_n[2]{};
    uint64_t pose_since[2]{};   // the ocarina's and Navi's poses: held since (0 not held)
    uint64_t dpad_gesture_at = 0;
    // ((Triforce VR) the grips' draws: both squeezed behind the head or back (behind_on behind the eyes) with one hand at least
    // draw_gap higher arms the sword and shield, the higher hand the sword's; with both still squeezed, the sword's hand brought
    // ahead of the eyes (ahead_on) draws them (Y), and either let go after puts them away (B). One squeezed behind arms the
    // item; brought ahead still squeezed takes it out (ZR, a press), let go after puts it away (B). The bow, the hookshot,
    // the boomerang and the slingshot out: the other hand's grip held is the aim (ZR held), let go the shot. A grip let go
    // before its hand came ahead does nothing)
    static constexpr float ahead_on = 0.05f, draw_gap = 0.10f;
    bool draw_arm = false, drawn_by_grips = false;
    // (hook_hand: kept while the hookshot is out; pull_hand: the last item pull's, kept after its grip is let go)
    int draw_sword = -1, item_arm = -1, item_hand = -1, hook_hand = -1, pull_hand = -1;
    uint64_t empty_since = 0;   // ((Triforce VR) since when no item has read as held, or the last pull (0: one reads as held)
    bool boom_wait = false;     // ((Triforce VR) the boomerang aimed, its trigger let go without a throw: ZR kept until one
    uint64_t a_until = 0;       // ((Triforce VR) a bomb's or a Bombchu's drop or release (A), its grip let go
    static constexpr float throw_speed = 0.8f;   // ((Triforce VR) the boomerang's throw: its hand ahead this fast, m/s
    bool grip_seen[2] = {true, true};
    // ((Triforce VR) what is on his head as the gestures left it, the mask or the Lens of Truth (the game's equipped head item
    // names it still after it comes off): on when put on or newly worn, off after a shake or a pull; the shake and the pull
    // take it off only while on, never put it on)
    bool head_on = false;   // (the game's own worn flag, as vr_game.c tells it: head_worn's 4)
    uint64_t zr_until = 0, b_until = 0;
    // ((Triforce VR) something of the world's carried: in both his hands, each put on its own side of it by the game, so not mirrored
    // from then on (the next item, draw or shield sets it), or they cross; thrown by both hands together (carry_share of a
    // swing's speed each, much the same way: carry_same, the cosine between them)
    bool carry = false;
    bool shield_alone = false;   // ((Triforce VR) the shield raised with no sword out, and none drawn since (Y)
    static constexpr float carry_share = 0.6f, carry_same = 0.6f;
    // the bow's and the slingshot's draw: the other hand's grip squeezed within draw_reach of the holding hand arms it (about
    // where the string is: no need to touch the hands); drawn back bow_pull from where it was taken, still squeezed, ZR held (the aim, its direction
    // from the drawing hand to the holding hand); let go, or brought back within 4 cm of where it was taken, the shot
    static constexpr float draw_reach = 0.30f, bow_pull = 0.12f;   // (the bow: its reach, its draw from where it was taken)
    static constexpr float sling_up = 0.13f, sling_reach = 0.26f, sling_pull = 0.08f;   // (the slingshot's stone over its hand, the reach about it, its draw from where it was taken)
    bool bow_arm = false, bow_drawn = false;
    float sling_took = 0;   // (how far from the stone or the string the pulling hand took it)
    // a grip let go to put away what the game does not show out yet (it lags): put away once it is, within release_wait_ns
    // (and again every resend_ns while it still shows out and the grip stays let go: a press lost to a stutter is pressed again)
    static constexpr uint64_t release_wait_ns = 3000000000ull, resend_ns = 400000000ull;
    uint64_t sword_release_at = 0, item_release_at = 0, sword_sent_at = 0, item_sent_at = 0;
    char item_seen[96]{};   // the item the mirror was last set for
    uint64_t take_at = 0;   // ((Triforce VR) a pull the game has not shown yet: when it was pressed, and how often again
    int take_tries = 0;
    bool mask_pull[2]{};    // a grip squeezed before the face: drawn away (mask_away, any way), the mask comes off (D-Up)
    float mask_from[2][3]{};
    static constexpr float mask_away = 0.15f;
    // the head shaken "no" (the mask off, as Link shakes his when he takes one off): its turn's rate past shake_rate one way then
    // the other, twice within shake_ns
    static constexpr float shake_rate = 2.0f;   // radians a second
    static constexpr uint64_t shake_ns = 700000000ull;
    float head_yaw[4]{};
    uint64_t yaw_t[4]{}, shake_at = 0, shake_flip_at[3]{};
    int yaw_n = 0, shake_dir = 0, shake_flips = 0;
    uint64_t ocarina_off_since = 0;
    bool ocarina_left = false;
    // ((Triforce VR) the head's nods: up then down puts the Lens of Truth on, down then up takes it off; within nod_ns, at least
    // nod_speed metres a second each way, then not again for nod_refractory_ns; none within 0.6 s of a swing (the body's lean)
    static constexpr float nod_speed = 0.45f;
    static constexpr uint64_t nod_ns = 450000000ull, nod_refractory_ns = 1000000000ull;
    float head_y[4]{};
    uint64_t head_t[4]{}, nod_up_at = 0, nod_down_at = 0, nod_at = 0;
    int head_n = 0;
    int tap_bit = Y;     // what the swing's tap presses: Y (the sword) or ZR (the hammer, the stick, an empty bottle)
    static constexpr float shield_on = 0.79f, shield_off = 1.05f, shield_reach = 0.70f;   // radians, radians, metres
    bool shielding = false;
    uint64_t draw_at = 0, draw_until = 0;
    uint64_t weapon_seen_at = 0;   // ((Triforce VR) the last moment a weapon was out)
    int draw_bit = -1;

    XrPath path(const char *s) {
        XrPath p = XR_NULL_PATH;
        xr().xrStringToPath(xr().instance, s, &p);
        return p;
    }
    XrAction action(const char *name, XrActionType type, bool both) {
        XrActionCreateInfo ai{XR_TYPE_ACTION_CREATE_INFO};
        std::strcpy(ai.actionName, name);
        std::strcpy(ai.localizedActionName, name);
        ai.actionType = type;
        ai.countSubactionPaths = both ? 2 : 0;
        ai.subactionPaths = both ? hand : nullptr;
        XrAction out = XR_NULL_HANDLE;
        if (XR_FAILED(xr().xrCreateAction(set, &ai, &out))) rt_log("vr: xrCreateAction %s failed", name);
        return out;
    }
    void make(XrSession session) {
        Xr &x = xr();
        XrActionSetCreateInfo si{XR_TYPE_ACTION_SET_CREATE_INFO};
        std::strcpy(si.actionSetName, "gameplay");
        std::strcpy(si.localizedActionSetName, "Gameplay");
        XrResult r = x.xrCreateActionSet(x.instance, &si, &set);
        if (XR_FAILED(r)) {
            rt_log("vr: xrCreateActionSet failed (%d): no hand controllers", (int)r);
            return;
        }
        hand[0] = path("/user/hand/left"), hand[1] = path("/user/hand/right");
        stick = action("stick", XR_ACTION_TYPE_VECTOR2F_INPUT, true);
        click = action("stick_click", XR_ACTION_TYPE_BOOLEAN_INPUT, true);
        trigger = action("trigger", XR_ACTION_TYPE_FLOAT_INPUT, true);
        squeeze = action("squeeze", XR_ACTION_TYPE_FLOAT_INPUT, true);
        grip = action("grip", XR_ACTION_TYPE_POSE_INPUT, true);
        aim = action("aim", XR_ACTION_TYPE_POSE_INPUT, true);
        a = action("a", XR_ACTION_TYPE_BOOLEAN_INPUT, false);
        b = action("b", XR_ACTION_TYPE_BOOLEAN_INPUT, false);
        xb = action("x", XR_ACTION_TYPE_BOOLEAN_INPUT, false);
        yb = action("y", XR_ACTION_TYPE_BOOLEAN_INPUT, false);
        menu = action("menu", XR_ACTION_TYPE_BOOLEAN_INPUT, false);
        haptic = action("haptic", XR_ACTION_TYPE_VIBRATION_OUTPUT, true);
        const struct {
            XrAction act;
            const char *at;
        } binds[] = {
            {stick, "/user/hand/left/input/thumbstick"},         {stick, "/user/hand/right/input/thumbstick"},
            {click, "/user/hand/left/input/thumbstick/click"},   {click, "/user/hand/right/input/thumbstick/click"},
            {trigger, "/user/hand/left/input/trigger/value"},    {trigger, "/user/hand/right/input/trigger/value"},
            {squeeze, "/user/hand/left/input/squeeze/value"},    {squeeze, "/user/hand/right/input/squeeze/value"},
            {grip, "/user/hand/left/input/grip/pose"},           {grip, "/user/hand/right/input/grip/pose"},
            {aim, "/user/hand/left/input/aim/pose"},             {aim, "/user/hand/right/input/aim/pose"},
            {a, "/user/hand/right/input/a/click"},               {b, "/user/hand/right/input/b/click"},
            {xb, "/user/hand/left/input/x/click"},               {yb, "/user/hand/left/input/y/click"},
            {menu, "/user/hand/left/input/menu/click"},
            {haptic, "/user/hand/left/output/haptic"},           {haptic, "/user/hand/right/output/haptic"},
        };
        XrActionSuggestedBinding sb[sizeof binds / sizeof binds[0]];
        for (size_t i = 0; i < sizeof binds / sizeof binds[0]; i++) sb[i] = {binds[i].act, path(binds[i].at)};
        XrInteractionProfileSuggestedBinding pb{XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING};
        pb.interactionProfile = path("/interaction_profiles/oculus/touch_controller");
        pb.countSuggestedBindings = sizeof sb / sizeof sb[0];
        pb.suggestedBindings = sb;
        r = x.xrSuggestInteractionProfileBindings(x.instance, &pb);
        if (XR_FAILED(r)) {
            rt_log("vr: the Touch controllers' bindings were refused (%d): no hand controllers", (int)r);
            return;
        }
        // (SteamVR presents the PSVR2 Sense controllers as Touch ones, but its remapping of the Touch left Menu to the
        // Sense's right Options does not reach OpenXR, whose input is "menu", not "application_menu": hence L3+R3)
        XrSessionActionSetsAttachInfo at{XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO};
        at.countActionSets = 1, at.actionSets = &set;
        r = x.xrAttachSessionActionSets(session, &at);
        if (XR_FAILED(r)) {
            rt_log("vr: xrAttachSessionActionSets failed (%d): no hand controllers", (int)r);
            return;
        }
        for (int h = 0; h < 2; h++) {
            XrActionSpaceCreateInfo sci{XR_TYPE_ACTION_SPACE_CREATE_INFO};
            sci.action = grip, sci.subactionPath = hand[h];
            sci.poseInActionSpace.orientation.w = 1.0f;
            x.xrCreateActionSpace(session, &sci, &grip_space[h]);
            sci.action = aim;
            x.xrCreateActionSpace(session, &sci, &aim_space[h]);
        }
        ok = true;
        rt_log("vr: hand controllers bound (Touch)");
    }
    bool on(XrSession session, XrAction act, XrPath sub) {
        XrActionStateGetInfo gi{XR_TYPE_ACTION_STATE_GET_INFO};
        gi.action = act, gi.subactionPath = sub;
        XrActionStateBoolean st{XR_TYPE_ACTION_STATE_BOOLEAN};
        return XR_SUCCEEDED(xr().xrGetActionStateBoolean(session, &gi, &st)) && st.isActive && st.currentState;
    }
    float value(XrSession session, XrAction act, XrPath sub) {
        XrActionStateGetInfo gi{XR_TYPE_ACTION_STATE_GET_INFO};
        gi.action = act, gi.subactionPath = sub;
        XrActionStateFloat st{XR_TYPE_ACTION_STATE_FLOAT};
        return XR_SUCCEEDED(xr().xrGetActionStateFloat(session, &gi, &st)) && st.isActive ? st.currentState : 0.0f;
    }
    // this headset frame's buttons, sticks and grips (time: the frame's predicted display time) into the Xr's
    // ((Triforce VR) [PlaceHolder]: the play of a control scheme other than Full Gesture, while Link is in play (menus, pauses and
    // events keep the common buttons above). In: the pad's bits as the common buttons set them (A, B, X from the face buttons and
    // the stick clicks, L and R from the triggers, Plus and Minus from the Menu button) and the sticks (-1..1, x right, y up);
    // each grip's pose and whether it is tracked, its velocity in m/s, and the head's pose, all in the play space (OpenXR's x
    // right, y up, z back). Out: bits and sticks as the game is to read them (bits |= 1ull << ZR...). Nothing yet
    void placeholder_play(uint64_t &bits, float (&sticks)[2][2], const Pose (&poses)[2], const bool (&pose_ok)[2],
                          const float (&velocity)[2][3], const Pose &head_pose) {
        (void)bits, (void)sticks, (void)poses, (void)pose_ok, (void)velocity, (void)head_pose;
    }
    // ((Triforce VR) the game's rumble on the hand controllers (vk_xr_rumble: each side's strength, the left Joy-Con's on the left
    // hand, after the Controls tab's Rumble strength and Vibration curve): a short pulse renewed each frame while it lasts, stopped
    // when it ends
    void rumble(XrSession session, uint64_t now) {
        Xr &x = xr();
        if (!haptic || !x.xrApplyHapticFeedback) return;
        for (int h = 0; h < 2; h++) {
            const uint64_t at = g_rumble_at[h].load();
            const float amp = at && now - at < 150000000ull ? std::fmin(1.0f, g_rumble[h].load()) : 0.0f;
            XrHapticActionInfo hi{XR_TYPE_HAPTIC_ACTION_INFO};
            hi.action = haptic, hi.subactionPath = hand[h];
            if (amp > 0.02f) {
                XrHapticVibration v{XR_TYPE_HAPTIC_VIBRATION};
                v.duration = 60000000, v.frequency = XR_FREQUENCY_UNSPECIFIED, v.amplitude = amp;
                x.xrApplyHapticFeedback(session, &hi, reinterpret_cast<const XrHapticBaseHeader *>(&v));
                buzzing[h] = true;
            } else if (buzzing[h]) {
                x.xrStopHapticFeedback(session, &hi);
                buzzing[h] = false;
            }
        }
    }
    void read(XrSession session, XrSpace space, XrTime time, const Pose &head_pose) {
        const float *head = head_pose.p;
        if (!ok) return;
        Xr &x = xr();
        XrActiveActionSet active{set, XR_NULL_PATH};
        XrActionsSyncInfo sy{XR_TYPE_ACTIONS_SYNC_INFO};
        sy.countActiveActionSets = 1, sy.activeActionSets = &active;
        if (x.xrSyncActions(session, &sy) != XR_SUCCESS) return;   // (XR_SESSION_NOT_FOCUSED: nothing to read)
        const uint64_t now = plat_now_ns();
        rumble(session, now);
        uint64_t bits = 0;
        const auto set_bit = [&](int bit, bool down) { bits |= down ? 1ull << bit : 0; };
        // on the PSVR2 both sticks clicked together (L3+R3) are the Menu, below: one click alone is X (jump) once it has been held
        // click_wait_ns, so the first of two clicks pressed nearly together is not a jump; held both, no jump until both are up
        const bool click_l = on(session, click, hand[0]), click_r = on(session, click, hand[1]);
        bool click_x = click_l || click_r;
        if (x.psvr2) {   // (other headsets have their own Menu button: either click is X at once, as set above)
            const bool combo = click_l && click_r;
            if (combo) combo_latch = true;
            else if (!click_l && !click_r) combo_latch = false;
            if ((click_l != click_r) && !combo_latch) {
                if (!click_since) click_since = now;
            } else click_since = 0;
            click_x = click_since && now - click_since >= click_wait_ns;
        }
        bool squeezed_before[2] = {squeeze_on[0], squeeze_on[1]};
        for (int h = 0; h < 2; h++) {   // pressed past 0.6, released under 0.4
            const float t = value(session, trigger, hand[h]), s = value(session, squeeze, hand[h]);
            trigger_on[h] = trigger_on[h] ? t > 0.4f : t > 0.6f;
            squeeze_on[h] = squeeze_on[h] ? s > 0.4f : s > 0.6f;
        }
        const bool in_play = x.in_play.load() && !menu_is_open();   // (this menu over play: its buttons, no play roles)
        if (!in_play) {
            // menus, pauses and events (and this menu over play): a pad's buttons as labelled, the triggers L and R, the grips
            // ZL and ZR, each stick's click its own
            set_bit(A, on(session, a, XR_NULL_PATH)), set_bit(B, on(session, b, XR_NULL_PATH));
            set_bit(X, on(session, xb, XR_NULL_PATH)), set_bit(Y, on(session, yb, XR_NULL_PATH));
            set_bit(STICK_L, click_l && !combo_latch), set_bit(STICK_R, click_r && !combo_latch);   // (not the PSVR2's L3+R3 Menu)
            set_bit(L, trigger_on[0]), set_bit(R, trigger_on[1]);
            set_bit(ZL, squeeze_on[0]), set_bit(ZR, squeeze_on[1]);
        } else {
            // play: X and Y mirror A and B, and either stick's click jumps (X), so a controller with fewer buttons plays it all
            set_bit(A, on(session, a, XR_NULL_PATH) || on(session, xb, XR_NULL_PATH));
            set_bit(B, on(session, b, XR_NULL_PATH) || on(session, yb, XR_NULL_PATH));
            set_bit(X, click_x);
            // the triggers L and R: the game's item bars; ((Triforce VR) the Biggoron's Sword out: not the other hand's, which the
            // sword hand's controller presses by accident on the close two-handed grip)
            const int no_trig = x.weapon_out.load() && x.two_handed_sword.load() ? 1 - sword_hand_now() : -1;
            set_bit(L, trigger_on[0] && no_trig != 0), set_bit(R, trigger_on[1] && no_trig != 1);
        }
        // the Menu: a tap is Plus for a moment at its release, a second's hold Minus for a moment then
        if (combo_latch || on(session, menu, XR_NULL_PATH)) {
            if (!menu_down) menu_down = now, minus_sent = false;
            if (!minus_sent && now - menu_down >= hold_ns) minus_until = now + press_ns, minus_sent = true, rt_log("vr: Menu held: Minus");
        } else if (menu_down) {
            if (!minus_sent) plus_until = now + press_ns, rt_log("vr: Menu tapped: Plus");
            menu_down = 0;
        }
        set_bit(PLUS, now < plus_until), set_bit(MINUS, now < minus_until);
        float sticks[2][2]{};
        for (int h = 0; h < 2; h++) {
            XrActionStateGetInfo gi{XR_TYPE_ACTION_STATE_GET_INFO};
            gi.action = stick, gi.subactionPath = hand[h];
            XrActionStateVector2f st{XR_TYPE_ACTION_STATE_VECTOR2F};
            if (XR_SUCCEEDED(x.xrGetActionStateVector2f(session, &gi, &st)) && st.isActive)
                sticks[h][0] = st.currentState.x, sticks[h][1] = st.currentState.y;
        }
        const bool ocarina = x.ocarina.load();
        if (now >= dpad_from && now < dpad_until) set_bit(dpad_bit, true);
        Pose poses[2];
        bool pose_ok[2]{};
        for (int h = 0; h < 2; h++) {
            XrSpaceLocation loc{XR_TYPE_SPACE_LOCATION};
            const XrSpaceLocationFlags need = XR_SPACE_LOCATION_ORIENTATION_VALID_BIT | XR_SPACE_LOCATION_POSITION_VALID_BIT;
            if (grip_space[h] && XR_SUCCEEDED(x.xrLocateSpace(grip_space[h], space, time, &loc)) &&
                (loc.locationFlags & need) == need) {
                std::memcpy(poses[h].q, &loc.pose.orientation, sizeof poses[h].q);
                std::memcpy(poses[h].p, &loc.pose.position, sizeof poses[h].p);
                pose_ok[h] = true;
            }
        }
        // the head's level forward (fx, fz) and right (rx, rz), OpenXR's x right and z back, and where each hand is
        // behind the eyes along it (back_any), and so for the draw when no lower than the shoulders (behind)
        float fx = 0, fz = -1;
        {
            static const float ahead[3] = {0, 0, -1};
            float f[3];
            rotate(head_pose.q, ahead, f);
            const float n = std::sqrt(f[0] * f[0] + f[2] * f[2]);
            if (n > 1e-3f) fx = f[0] / n, fz = f[2] / n;
        }
        const float rx = -fz, rz = fx;
        float behind[2] = {-1.0f, -1.0f}, back_any[2] = {-1.0f, -1.0f}, side[2] = {};
        for (int h = 0; h < 2; h++)
            if (pose_ok[h]) {
                const float dx = poses[h].p[0] - head[0], dz = poses[h].p[2] - head[2];
                back_any[h] = -(dx * fx + dz * fz), side[h] = dx * rx + dz * rz;
                if (poses[h].p[1] > head[1] - shoulder_drop) behind[h] = back_any[h];
            }
        (void)behind;
        // the hands' velocities (over their last 4 frames) and places about the head: up, ahead (fwd) and to the right
        float hv[2][3]{}, hspeed[2]{}, up[2]{}, fwd[2]{};
        for (int h = 0; h < 2; h++) {
            if (!pose_ok[h]) {
                hand_n[h] = 0;
                continue;
            }
            const int i = hand_n[h]++ & 3;
            std::memcpy(hand_p[h][i], poses[h].p, sizeof hand_p[h][i]);
            hand_t[h][i] = now;
            up[h] = poses[h].p[1] - head[1], fwd[h] = -back_any[h];
            if (hand_n[h] < 4) continue;
            const int o = hand_n[h] & 3;
            const float dt = (float)(hand_t[h][i] - hand_t[h][o]) * 1e-9f;
            for (int c = 0; c < 3 && dt > 0; c++) hv[h][c] = (hand_p[h][i][c] - hand_p[h][o][c]) / dt;
            hspeed[h] = std::sqrt(hv[h][0] * hv[h][0] + hv[h][1] * hv[h][1] + hv[h][2] * hv[h][2]);
        }
        for (int h = 0; h < 2; h++)   // ((Triforce VR) a controller's tracking lost or found: said as it happens
            if (pose_ok[h] != grip_seen[h]) grip_seen[h] = pose_ok[h], rt_log("vr: the %s controller's tracking %s", h ? "right" : "left", pose_ok[h] ? "found again" : "lost");
        // ((Triforce VR) what every scheme hands on: the buttons and sticks, the grips' poses (for Link's arms), the aim's turns
        const auto publish = [&]() {
            std::lock_guard<std::mutex> lk(x.hands_mu);
            x.hand_buttons = bits, x.hand_menu = !in_play;
            std::memcpy(x.hand_sticks, sticks, sizeof sticks);
            for (int h = 0; h < 2; h++) {
                x.grip[h] = poses[h], x.grip_ok[h] = pose_ok[h];
                XrSpaceLocation loc{XR_TYPE_SPACE_LOCATION};
                const XrSpaceLocationFlags need = XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;
                x.aim_ok[h] = aim_space[h] && XR_SUCCEEDED(x.xrLocateSpace(aim_space[h], space, time, &loc)) &&
                              (loc.locationFlags & need) == need;
                if (x.aim_ok[h]) std::memcpy(x.aim_pose[h].q, &loc.pose.orientation, sizeof x.aim_pose[h].q);
            }
            x.hands_at = now;
        };
        if (!scheme_full_gesture()) {   // ((Triforce VR) another scheme's play: none of Full Gesture's below
            if (in_play) placeholder_play(bits, sticks, poses, pose_ok, hv, head_pose);
            publish();
            return;
        }
        if (in_play) {   // ((Triforce VR) the head's nods: the Lens of Truth on and off, while it is the head's item
            const int i = head_n++ & 3;
            head_y[i] = head[1], head_t[i] = now;
            if (head_n >= 4) {
                const int o = head_n & 3;
                const float dt = (float)(head_t[i] - head_t[o]) * 1e-9f, vy = dt > 0 ? (head_y[i] - head_y[o]) / dt : 0.0f;
                if (now - nod_at >= nod_refractory_ns && now - swing_at >= 600000000ull) {
                    if (vy > nod_speed) {
                        if (nod_down_at && now - nod_down_at < nod_ns) {
                            nod_at = now, nod_down_at = 0, rt_log("vr: head: down then up: the Lens of Truth off");
                            if ((x.head_worn.load() & 3) == 2 && head_on) x.head_request.store(3), head_on = false;
                        }
                        else if (!nod_up_at || now - nod_up_at > nod_ns) nod_up_at = now;
                    } else if (vy < -nod_speed) {
                        if (nod_up_at && now - nod_up_at < nod_ns) {
                            nod_at = now, nod_up_at = 0, rt_log("vr: head: up then down: the Lens of Truth on");
                            if (!((x.head_worn.load() & 3) == 2 && head_on)) x.head_request.store(2), head_on = true;   // (from a mask too)
                        }
                        else if (!nod_down_at || now - nod_down_at > nod_ns) nod_down_at = now;
                    }
                }
            }
        } else head_n = 0;
        head_on = (x.head_worn.load() & 4) != 0;
        if (in_play) {   // ((Triforce VR) the head shaken "no": the mask off, while one is worn)
            const int i = yaw_n++ & 3;
            head_yaw[i] = std::atan2(fx, -fz), yaw_t[i] = now;
            if (yaw_n >= 4) {
                const int o = yaw_n & 3;
                float dy = head_yaw[i] - head_yaw[o];
                if (dy > 3.14159265f) dy -= 6.2831853f;
                if (dy < -3.14159265f) dy += 6.2831853f;
                const float dt = (float)(yaw_t[i] - yaw_t[o]) * 1e-9f, rate = dt > 0 ? dy / dt : 0.0f;
                const int dir = rate > shake_rate ? 1 : rate < -shake_rate ? -1 : 0;
                if (dir && dir != shake_dir) {
                    shake_flip_at[shake_flips % 3] = now, shake_flips++, shake_dir = dir;
                    if (shake_flips >= 3 && now - shake_flip_at[(shake_flips - 3) % 3] < shake_ns && now - shake_at > 3000000000ull) {
                        shake_at = now, shake_flips = 0;
                        if ((x.head_worn.load() & 3) && head_on)
                            x.head_request.store(3), head_on = false,
                            rt_log("vr: head: shaken no: %s off", (x.head_worn.load() & 3) == 2 ? "the Lens of Truth" : "mask");
                    }
                }
            }
        } else yaw_n = 0, shake_flips = 0, shake_dir = 0;
        const float shake = 0.008f * (float)cfg_int("VR_SWING_SPEED");   // 80% of a swing's speed, m/s
        // both arms shaken upward together; a hand shaken (mostly sideways) above the head
        const bool both_up = hspeed[0] > shake && hspeed[1] > shake && hv[0][1] > 0.7f * hspeed[0] && hv[1][1] > 0.7f * hspeed[1];
        bool wave[2];
        for (int h = 0; h < 2; h++)
            wave[h] = pose_ok[h] && up[h] > 0.15f && hspeed[h] > shake &&
                      hv[h][0] * hv[h][0] + hv[h][2] * hv[h][2] > 0.49f * hspeed[h] * hspeed[h];
        // both hands together before the face (the ocarina held to the mouth); both beside the head (Navi called)
        bool at_face = false, beside = false;
        if (pose_ok[0] && pose_ok[1]) {
            float d2 = 0;
            for (int c = 0; c < 3; c++) d2 += (poses[0].p[c] - poses[1].p[c]) * (poses[0].p[c] - poses[1].p[c]);
            // ((Triforce VR) both within 15 cm of the mouth (14 cm ahead of the eyes, 17 below them): held at the mouth, not
            // up at the eyes, nor the Biggoron's Sword held up before the face)
            at_face = d2 < 0.16f * 0.16f;
            for (int h = 0; h < 2 && at_face; h++) {
                const float a = fwd[h] - 0.14f, u = up[h] + 0.17f;
                at_face = a * a + u * u + side[h] * side[h] < 0.15f * 0.15f;
            }
            beside = side[0] < -0.10f && side[0] > -0.35f && side[1] > 0.10f && side[1] < 0.35f && std::fabs(up[0]) < 0.15f &&
                     std::fabs(up[1]) < 0.15f && std::fabs(fwd[0]) < 0.15f && std::fabs(fwd[1]) < 0.15f;
        }
        {   // ((Triforce VR) the ocarina: both pointer rays sideways, the same way: left mirrored, right as made)
            float lat[2] = {0, 0};
            bool level = x.aim_ok[0] && x.aim_ok[1];   // ((Triforce VR) neither pointing up (past about 27 degrees))
            static const float ray[3] = {0, 0, -1};
            for (int h = 0; h < 2; h++)
                if (x.aim_ok[h]) {
                    float d[3];
                    rotate(x.aim_pose[h].q, ray, d);
                    if (d[1] > 0.45f) level = false;
                    // (its level part alone: how far it tips up or down, and its roll, do not count)
                    const float l = d[0] * rx + d[2] * rz, f = d[0] * fx + d[2] * fz, n = std::sqrt(l * l + f * f);
                    lat[h] = n > 0.2f ? l / n : 0.0f;
                }
            const bool sideways = x.aim_ok[0] && x.aim_ok[1] && std::fabs(lat[0]) > 0.6f && std::fabs(lat[1]) > 0.6f && lat[0] * lat[1] > 0;
            if (at_face && (!sideways || !level)) at_face = false;
            if (at_face) ocarina_left = lat[0] < 0;
            // (both hands within 30 cm of the mouth, about 12 cm ahead of the eyes and 8 below them)
            bool near_mouth = pose_ok[0] && pose_ok[1];
            for (int h = 0; h < 2 && near_mouth; h++) {
                const float mx = head[0] + 0.12f * fx, my = head[1] - 0.08f, mz = head[2] + 0.12f * fz;
                const float dx = poses[h].p[0] - mx, dy = poses[h].p[1] - my, dz = poses[h].p[2] - mz;
                near_mouth = dx * dx + dy * dy + dz * dz < 0.30f * 0.30f;
            }
            const bool still = sideways && lat[0] * (ocarina_left ? -1.0f : 1.0f) > 0.4f && near_mouth;
            if (x.ocarina.load()) {   // out of the pose a moment: B ends it (the game's ocarina is not "in play": no gate)
                if (still) ocarina_off_since = 0;
                else if (!ocarina_off_since) ocarina_off_since = now;
                else if (ocarina_off_since != 1 && now - ocarina_off_since > 300000000ull)
                    b_until = now + press_ns, ocarina_off_since = 1, rt_log("vr: ocarina: hands out of the pose: B");
            } else ocarina_off_since = 0;
        }
        pose_since[0] = at_face ? (pose_since[0] ? pose_since[0] : now) : 0;
        pose_since[1] = beside ? (pose_since[1] ? pose_since[1] : now) : 0;
        if (x.carrying.load()) pose_since[0] = pose_since[1] = 0;   // ((Triforce VR) his hands are full: none of these
        else if (in_play && !x.ocarina.load() && now - dpad_gesture_at >= dpad_refractory_ns) {
            int bit = -1;
            (void)wave;   // ((Triforce VR) the mask: the grips on and before the head now, below)
            // ((Triforce VR) the hands apart (30 cm or more): a two-handed grip's raise, such as the Biggoron's jump slash, is not it)
            float apart2 = 0;
            for (int c = 0; c < 3; c++) apart2 += (poses[0].p[c] - poses[1].p[c]) * (poses[0].p[c] - poses[1].p[c]);
            if (both_up && pose_ok[0] && pose_ok[1] && apart2 > 0.30f * 0.30f) bit = DOWN;
            else if (pose_since[0] && now - pose_since[0] >= dwell_ns) bit = LEFT, g_live_mirror.store(ocarina_left ? 1 : 0);
            else if (pose_since[1] && now - pose_since[1] >= dwell_ns) bit = RIGHT;
            if (bit >= 0) {
                dpad_bit = bit, dpad_from = now, dpad_until = now + press_ns, dpad_gesture_at = now;
                y_down = 0, charging = false, queued = false;   // the shake is not a swing
                pose_since[0] = pose_since[1] = 0;
            }
        }
        // in play the grips are the item button alone (no Z lock: the shield's raise holds it): pressed with that hand
        // behind the head it takes the item out, and held while the grip stays held (reach back, draw forward, let go);
        // with an item out either grip uses it. Which item is out: vr_game.c's (vk_xr_hand_item)
        char held_item[96];
        {
            std::lock_guard<std::mutex> lk(x.gear_mu);
            std::memcpy(held_item, x.held_item, sizeof held_item);
        }
        if (in_play && !x.ocarina.load()) {
            const bool sq[2] = {squeeze_on[0], squeeze_on[1]};
            const bool fresh[2] = {sq[0] && !squeezed_before[0], sq[1] && !squeezed_before[1]};
            const bool weapon = x.weapon_out.load();
            {   // ((Triforce VR) the last moment a weapon was out: the hands are chosen only when one is pulled out)
                static bool was_weapon;
                if (weapon) weapon_seen_at = now;
                if (weapon != was_weapon) rt_log("vr: weapon out: %s", weapon ? "yes" : "no"), was_weapon = weapon;
            }
            // both: the sword and shield
            if (!draw_arm && pose_ok[0] && pose_ok[1] && sq[0] && sq[1] && (fresh[0] || fresh[1]) && back_any[0] > behind_on &&
                back_any[1] > behind_on && std::fabs(poses[0].p[1] - poses[1].p[1]) > draw_gap) {
                draw_arm = true, draw_sword = poses[1].p[1] > poses[0].p[1] ? 1 : 0, item_arm = -1;
                rt_log("vr: grips: sword and shield armed, the sword in the %s hand", draw_sword ? "right" : "left");
            }
            // ((Triforce VR) the Biggoron's Sword equipped: both grips held, the sword hand alone behind the shoulder (Link draws it
            // with one hand and takes it in both on the way); the other hand anywhere)
            if (!draw_arm && x.two_handed_sword.load() && pose_ok[0] && pose_ok[1] && sq[0] && sq[1] && (fresh[0] || fresh[1]) &&
                (back_any[0] > behind_on || back_any[1] > behind_on)) {
                const bool both_back = back_any[0] > behind_on && back_any[1] > behind_on;
                draw_arm = true, item_arm = -1;
                draw_sword = both_back ? (poses[1].p[1] > poses[0].p[1] ? 1 : 0) : back_any[1] > behind_on ? 1 : 0;
                rt_log("vr: grips: the Biggoron's Sword armed, in the %s hand", draw_sword ? "right" : "left");
            }
            if (draw_arm && (!sq[0] || !sq[1])) draw_arm = false;
            if (draw_arm && pose_ok[draw_sword] && back_any[draw_sword] < -ahead_on) {
                draw_arm = false;
                if (!weapon) {
                    g_live_sword.store(draw_sword), g_live_mirror.store(draw_sword);   // (the sword: mirrored in the right hand)
                    draw_bit = Y, draw_at = now, draw_until = now + press_ns, drawn_by_grips = true;
                    y_down = 0, charging = false, queued = false;   // a swing on the way there is not one
                    rt_log("vr: grips: sword and shield drawn, the sword in the %s hand", draw_sword ? "right" : "left");
                }
            }
            if (drawn_by_grips && !draw_arm && (!sq[0] || !sq[1])) sword_release_at = now, drawn_by_grips = false;
            if (sword_release_at) {
                if (sq[0] && sq[1]) sword_release_at = 0;   // (gripped again: kept out)
                else if (weapon && now - sword_sent_at >= resend_ns)
                    draw_bit = B, draw_until = now + press_ns, sword_sent_at = now, rt_log("vr: grips: let go: sword and shield put away");
                if (now - sword_release_at > release_wait_ns || (!weapon && sword_sent_at)) sword_release_at = 0, sword_sent_at = 0;
            }
            // one: an item. ((Triforce VR) One at a time: the hand that pulled it out owns it until it is put away for good
            // (pull_hand); the other hand pulls nothing meanwhile)
            for (int h = 0; h < 2 && !draw_arm; h++)
                if (item_arm < 0 && item_hand < 0 && pull_hand < 0 && fresh[h] && !sq[1 - h] && pose_ok[h] && back_any[h] > behind_on)
                    item_arm = h;
            if (draw_arm) item_arm = -1;
            if (item_arm >= 0) {
                if (!sq[item_arm]) item_arm = -1;
                else if (pose_ok[item_arm] && back_any[item_arm] < -ahead_on) {
                    item_hand = pull_hand = item_arm, item_arm = -1, zr_until = now + press_ns;
                    empty_since = now;   // (the game shows it a few frames later: not put away meanwhile)
                    item_seen[0] = 0;    // ((Triforce VR) a new pull: its hand found again, the same item in the other hand too
                    take_at = now, take_tries = 0;
                    rt_log("vr: grips: item taken out by the %s hand", item_hand ? "right" : "left");
                }
            }
            // (an item read as none for a moment, around a shot, is still out: half a second before it counts as put away, or
            // the hookshot's trigger went back to being its item bar)
            if (held_item[0]) take_at = 0;   // ((Triforce VR) a pull the game ignored (a put-away still playing): pressed again,
            else if (take_at && pull_hand >= 0 && sq[pull_hand] && now - take_at > 700000000ull && take_tries < 2)   // twice at most
                zr_until = now + press_ns, take_at = now, take_tries++, empty_since = now,
                rt_log("vr: grips: the item not out yet: pulled again");
            if (held_item[0]) empty_since = 0;
            else if (!empty_since) empty_since = now;
            // ((Triforce VR) the hookshot or the boomerang: its hand's trigger stays its shot until that grip is let go; the game
            // shows neither for a while once it is shot or thrown, which is not put away)
            const bool hook_kept = hook_hand >= 0 && sq[hook_hand];
            const bool gone = !held_item[0] && now - empty_since > 1000000000ull && !hook_kept;
            const bool bomb = strstr(held_item, "Item_Bomb") != nullptr;   // (a bomb or a Bombchu)
            // (the hookshot and the boomerang: their own hand's trigger is the aim)
            if (strstr(held_item, "Hookshot") || strstr(held_item, "Boomerang")) {
                if (hook_hand < 0 && pull_hand >= 0) hook_hand = pull_hand;   // (the hand that pulled it, even let go already)
            } else if (!hook_kept && (held_item[0] || gone)) hook_hand = -1;
            if (item_hand >= 0 && !sq[item_hand]) item_release_at = now, item_hand = -1;   // (let go: put away; B a backup)
            if (item_release_at && pull_hand >= 0 && sq[pull_hand] && held_item[0])   // (its own hand gripped again: kept out)
                item_release_at = 0, item_sent_at = 0, item_hand = pull_hand;
            if (item_release_at) {   // (pressed again every resend_ns while it shows out: until it is gone, however long)
                if (bomb) {   // (a bomb or a Bombchu: dropped or let go once (A); the game shows it held still, after, so done)
                    a_until = now + press_ns, rt_log("vr: grips: let go: %s dropped (A)", held_item);
                    item_release_at = 0, item_sent_at = 0, pull_hand = -1;
                } else if (held_item[0] && now - item_sent_at >= resend_ns) {
                    b_until = now + press_ns, rt_log("vr: grips: let go: item put away");
                    item_sent_at = now;
                }
                if (gone) item_release_at = 0, item_sent_at = 0;   // (not a moment's none, as around a shot: really put away)
            }
            if (gone) pull_hand = -1;   // (put away for good: either hand may pull the next; a gamepad's item is aimed with the pad)
            // the item out: Link's hand for it, the hand that pulled it ((Triforce VR) even let go already: the game shows it a
            // few frames after the pull, often after the grip is let go)
            if (pull_hand >= 0 && held_item[0] && strcmp(held_item, item_seen)) {
                snprintf(item_seen, sizeof item_seen, "%s", held_item);
                g_live_mirror.store(item_mirrored_right(held_item) ? pull_hand : 1 - pull_hand);
                rt_log("vr: grips: %s in the %s hand: %s", held_item, pull_hand ? "right" : "left", g_live_mirror.load() ? "mirrored" : "as made");
            }
            // ((Triforce VR) an item put away for good: the hand it was in is kept (the next draw or pull chooses again))
            if (gone && item_seen[0]) item_seen[0] = 0;
            for (int h = 0; h < 2; h++) {   // masks: a grip on top of the head puts it on; squeezed before the face and drawn up, off
                if (!pose_ok[h] || !sq[h]) {
                    mask_pull[h] = false;
                    continue;
                }
                if (fresh[h] && up[h] > 0.08f && std::fabs(side[h]) < 0.15f && std::fabs(fwd[h]) < 0.15f) {
                    // ((Triforce VR) a mask only, not on already: the Lens of Truth is the nod's)
                    // (a mask in the member, or the Lens of Truth there with a mask worn before it: that mask back, +8)
                    const int hw = x.head_worn.load();
                    // ((Triforce VR) a mask in the member, or one known to him (+8) with the Lens of Truth or nothing there)
                    if (((hw & 3) == 1 || ((hw & 3) != 1 && (hw & 8))) && !((hw & 3) == 1 && head_on))
                        x.head_request.store(1), head_on = true, rt_log("vr: grips: mask on");
                    else rt_log("vr: grips: a grip on the head: no mask to put on (the head's item %d%s)", hw & 3,
                                head_on ? ", one on already" : "");
                } else if (fresh[h] && up[h] > 0.0f && std::fabs(side[h]) < 0.25f && std::fabs(fwd[h]) < 0.25f) {
                    rt_log("vr: grips: a grip near the head's top, not on it (up %.2f, side %.2f, ahead %.2f m)", up[h], side[h], fwd[h]);
                } else if (fresh[h] && fwd[h] > 0.04f && fwd[h] < 0.25f && up[h] > -0.20f && up[h] < 0.05f && std::fabs(side[h]) < 0.12f) {
                    mask_pull[h] = true, std::memcpy(mask_from[h], poses[h].p, sizeof mask_from[h]);
                } else if (mask_pull[h]) {
                    float d2 = 0;
                    for (int c = 0; c < 3; c++) d2 += (poses[h].p[c] - mask_from[h][c]) * (poses[h].p[c] - mask_from[h][c]);
                    if (d2 > mask_away * mask_away) {
                        mask_pull[h] = false;
                        if ((x.head_worn.load() & 3) && head_on)   // ((Triforce VR) the mask or the Lens of Truth, while on)
                            x.head_request.store(3), head_on = false,
                            rt_log("vr: grips: %s off", (x.head_worn.load() & 3) == 2 ? "the Lens of Truth" : "mask");
                    }
                }
            }
            bool drawing = false;
            if ((strstr(held_item, "Bow") || strstr(held_item, "SlingShot") || strstr(held_item, "Slingshot") ||
                 strstr(held_item, "Pachinko")) && pull_hand >= 0 &&
                pose_ok[0] && pose_ok[1]) {
                const int hold = pull_hand, pull = 1 - pull_hand;
                // ((Triforce VR) the slingshot: from its stone, on the string above the handle, not the hand on it)
                const bool sling = !strstr(held_item, "Bow");
                static const float out_of_fist[3] = {0, 0, -1};
                float d2 = 0, dv[3], up_handle[3];
                rotate(poses[hold].q, out_of_fist, up_handle);
                for (int c = 0; c < 3; c++)
                    dv[c] = poses[hold].p[c] + (sling ? sling_up * up_handle[c] : 0.0f) - poses[pull].p[c], d2 += dv[c] * dv[c];
                const float reach = sling ? sling_reach : draw_reach;
                if (!sq[pull]) bow_arm = bow_drawn = false;
                else if (fresh[pull]) {
                    if (d2 < reach * reach) bow_arm = true, sling_took = std::sqrt(d2);
                    else rt_log("vr: grips: a draw out of reach (%.0f cm of %.0f)", std::sqrt(d2) * 100.0f, reach * 100.0f);
                }
                const float pulled = sling_took + (sling ? sling_pull : bow_pull), returned = sling_took + 0.04f;
                if (bow_arm && !bow_drawn && d2 > pulled * pulled) bow_drawn = true, rt_log("vr: grips: drawn");
                if (bow_drawn && d2 < returned * returned) bow_drawn = bow_arm = false, rt_log("vr: grips: brought back: the shot");
                drawing = bow_drawn;
                if (drawing) {
                    const float n = std::sqrt(d2);
                    std::lock_guard<std::mutex> lk(x.hands_mu);
                    for (int c = 0; c < 3; c++) g_draw_dir[c] = dv[c] / n;
                }
            } else bow_arm = bow_drawn = false;
            g_draw_on.store(drawing);
            // ((Triforce VR) the hookshot and the boomerang: their own hand's trigger is the aim (ZR held), and that trigger is
            // not its item bar (L or R) while one is out. The hookshot: let go, the shot. The boomerang: let go with the hand
            // moving ahead (throw_speed), the throw; let go still, it stays aimed until such a move)
            bool hook_aim = false;
            const bool boomerang = strstr(held_item, "Boomerang") != nullptr;
            if (hook_hand >= 0) {
                static bool trig_was;
                const bool trig = trigger_on[hook_hand];
                if (trig && !trig_was) rt_log("vr: grips: %s aimed by the %s trigger", boomerang ? "boomerang" : "hookshot", hook_hand ? "right" : "left");
                trig_was = trig;
                const float ahead = hv[hook_hand][0] * fx + hv[hook_hand][2] * fz;
                // ((Triforce VR) a throw: the hand ahead fast after the trigger is let go, or in the 300 ms before (a throw lets go
                // as the arm ends its swing)
                static uint64_t ahead_at;
                if (ahead > throw_speed) ahead_at = now;
                if (trig) boom_wait = boomerang;
                else if (boom_wait && (ahead > throw_speed || now - ahead_at < 300000000ull))
                    boom_wait = false, rt_log("vr: grips: boomerang thrown");
                if (!boomerang) boom_wait = false;
                hook_aim = trig || boom_wait;
                bits &= ~(1ull << (hook_hand ? R : L));
            } else boom_wait = false;
            g_gaze_aim.store(boomerang && hook_hand >= 0);
            if (bomb && item_hand >= 0) {   // ((Triforce VR) a bomb or a Bombchu held by its grip: any face button puts it away (B); the grip let go drops it (A)
                const uint64_t face = (1ull << A) | (1ull << B);
                const bool any = bits & face;
                bits &= ~face;
                if (any) set_bit(B, true);
            }
            {   // ((Triforce VR) ZR let go: a shot (the bow's or slingshot's release, the hookshot's trigger, the boomerang's throw):
                // the aim held where it was just before, as the release's own motion would turn it (vk_xr_pointer)
                static bool zr_was;
                const bool zr = now < zr_until || hook_aim || drawing;
                if (zr_was && !zr) g_shot_at.store(now);
                zr_was = zr;
                set_bit(ZR, zr);
            }
            g_item_hand.store(held_item[0] ? (hook_hand >= 0 ? hook_hand : pull_hand) : -1);
            set_bit(B, now < b_until);
            set_bit(A, now < a_until);
        } else {
            draw_arm = false, item_arm = -1, item_hand = -1, sword_release_at = item_release_at = 0;
            if (held_item[0] && !strstr(held_item, "Hookshot") && !strstr(held_item, "Boomerang")) hook_hand = -1;
        }
        if (in_play || x.ocarina.load()) set_bit(B, now < b_until);   // (also the ocarina's end, made while the grips have no roles)
        // the shield: the other hand's shield (drawn on the back of the hand, its face out of the grip's -x on the left
        // hand and +x on the right) turned to face ahead (within shield_on of the head's level forward) and held before
        // its own side's eye (within 12 cm of it to either side, 19 to stay) holds ZL (the Z lock) until it turns away
        // past shield_off, moves off from before the eye or is held out past shield_reach
        {
            // the shield's raise for one hand: its face (drawn on the back of the hand, out of the grip's -x on the left hand, +x
            // on the right) within shield_on of ahead (shield_off to stay), before its own side's eye (12 cm, 19 to stay), in reach
            bool biggoron_guard = false;
            const auto raised = [&](int hd, bool staying) {
                if (!pose_ok[hd] || !x.aim_ok[hd]) return false;
                // ((Triforce VR) held as for the bottle and the ocarina: its pointer's level part pointing inward across the body
                // (the left hand's to the right, the right's to the left); its tilt and roll do not count)
                static const float ray[3] = {0, 0, -1};
                float d[3];
                rotate(x.aim_pose[hd].q, ray, d);
                const float l = d[0] * rx + d[2] * rz, fw = d[0] * fx + d[2] * fz, n = std::sqrt(l * l + fw * fw);
                const float ahead = n > 0.2f ? (hd ? -l : l) / n : 0.0f;   // (1 straight across, inward)
                const float outward = hd ? side[hd] : -side[hd];   // (toward its own side, from the head's middle)
                float off_eye = std::fabs(outward - 0.032f);   // (about 3 cm out from the head's middle)
                // ((Triforce VR) the Biggoron's Sword's guard, raised by the sword hand: from the body's middle over to the other
                // side, where the other hand on the hilt can follow it)
                if (biggoron_guard) off_eye = outward > 0.06f ? outward - 0.06f : outward < -0.30f ? -0.30f - outward : 0.0f;
                const float dx = poses[hd].p[0] - head[0], dz = poses[hd].p[2] - head[2];
                const bool in_reach = dx * dx + dz * dz < shield_reach * shield_reach;   // (not "near": windows.h defines it)
                // ((Triforce VR) away from the face: ahead of the eyes or below them (a mask's grab at the face is no shield)
                const bool off_face = staying ? fwd[hd] > 0.20f || up[hd] < -0.15f : fwd[hd] > 0.25f || up[hd] < -0.20f;
                return staying ? ahead > std::cos(shield_off) && off_eye < 0.19f && in_reach && off_face
                               : ahead > std::cos(shield_on) && off_eye < 0.12f && in_reach && !at_face && off_face;
            };
            // ((Triforce VR) the Biggoron's Sword out: both hands hold it, its guard raised by the sword hand)
            // (not the shield raised alone: with the Biggoron's Sword put away, its shield out is no Biggoron guard)
            const bool biggoron_out = !held_item[0] && x.weapon_out.load() && x.two_handed_sword.load() && !shield_alone;
            int shield = biggoron_out ? sword_hand_now() : 1 - sword_hand_now();
            biggoron_guard = biggoron_out;
            bool keep = false;
            // (the sword out: its other hand's shield; ((Triforce VR) the shield raised alone stays only while its grip is held)
            if (x.weapon_out.load()) keep = raised(shield, shielding) && (!shield_alone || squeeze_on[shield]);
            if (biggoron_guard && keep && !shielding) {   // ((Triforce VR) the guard begins only from a hand held fairly still, not
                                                          // within 0.4 s of a swing: a swing passes through the guard's pose)
                const float gs = std::sqrt(hv[shield][0] * hv[shield][0] + hv[shield][1] * hv[shield][1] + hv[shield][2] * hv[shield][2]);
                if (gs > 1.0f || now - swing_at < 400000000ull || swinging) keep = false;
            }
            else {
                // ((Triforce VR) no sword out: either hand's raise with its grip held is Link's lock with the shield alone, the shield
                // in that hand: the left mirrors him (the sword then the right's), the right does not; the last one kept while held)
                if (shielding && squeeze_on[shield] && raised(shield, true)) keep = true;
                // ((Triforce VR) not while the sword is being drawn, nor until 1.5 s after a weapon was last out: the hands of
                // a sword and shield already out never swap)
                const bool settled = !draw_arm && !drawn_by_grips && !sword_release_at && now - weapon_seen_at > 1500000000ULL &&
                                     now - draw_at > 1500000000ULL;
                for (int hd = 0; hd < 2 && !keep && settled; hd++)
                    // ((Triforce VR) not a hand that holds an item or owns its trigger: a boomerang aimed up before the face is
                    // no shield)
                    if (squeeze_on[hd] && raised(hd, false) && hd != pull_hand && hd != hook_hand) {
                        keep = shield_alone = true, shield = hd;
                        if (g_live_sword.load() != 1 - hd || g_live_mirror.load() != (hd == 0 ? 1 : 0)) {
                            g_live_sword.store(1 - hd), g_live_mirror.store(hd == 0 ? 1 : 0);
                            rt_log("vr: shield raised alone in the %s hand: %s", hd ? "right" : "left", hd == 0 ? "mirrored" : "as made");
                        }
                    }
            }
            shielding = keep && !x.ocarina.load() && in_play;   // (no shield, ZL, in the menus)
            if (shielding) set_bit(ZL, true);
            {   // ((Triforce VR) the shield's Z-target where no hand is free for the shield: tilted past 35 degrees to either side,
                // until back within 25. The bow, the slingshot or the hookshot: the hand holding it turned on its side; a bomb or a
                // Bombchu, the Biggoron's Sword out: the head
                static bool tilt_z;
                static const float right_of[3] = {1, 0, 0};
                const auto tilt_of = [](const float q[4]) {
                    float r[3];
                    rotate(q, right_of, r);
                    return std::fabs(std::asin(std::fmax(-1.0f, std::fmin(1.0f, r[1])))) * 57.2958f;
                };
                const bool ranged = strstr(held_item, "Bow") || strstr(held_item, "SlingShot") || strstr(held_item, "Slingshot") ||
                                    strstr(held_item, "Pachinko") || strstr(held_item, "Hookshot");
                const bool by_head = strstr(held_item, "Item_Bomb") || (!held_item[0] && x.weapon_out.load() && x.two_handed_sword.load());
                const int hand = ranged ? (hook_hand >= 0 ? hook_hand : pull_hand) : -1;
                const float tilt = hand >= 0 && pose_ok[hand] ? tilt_of(poses[hand].q) : by_head ? tilt_of(head_pose.q) : 0.0f;
                const bool was = tilt_z;
                tilt_z = (hand >= 0 || by_head) && in_play && !x.ocarina.load() && (tilt > 35.0f || (tilt_z && tilt > 25.0f));
                if (tilt_z != was) rt_log("vr: %s tilt: Z-target %s", hand >= 0 ? "hand" : "head", tilt_z ? "on" : "off");
                if (tilt_z) set_bit(ZL, true);
            }
        }
        const float swing_on = 0.01f * (float)cfg_int("VR_SWING_SPEED");   // metres a second
        const float out_on = 0.01f * (float)cfg_int("VR_CHARGE_REACH"), out_off = out_on - 0.1f;   // metres
        bool swung = false;
        float out = 0.0f;   // the hand's distance from the head's upright line
        // the swinging hand: the item's when one was taken out by a hand, else the sword's
        {
            const bool carries = x.carrying.load();
            if (carries && !carry) g_live_mirror.store(0), rt_log("vr: carry: lifted");
            carry = carries;
        }
        const int item_owner = held_item[0] && pull_hand >= 0 ? pull_hand : held_item[0] && item_hand >= 0 ? item_hand : -1;
        // ((Triforce VR) the hammer: its head end is Link's other hand, so that hand's swing is the hammer's; the gripping hand's
        // is none)
        const int sword = item_owner >= 0 ? (strstr(held_item, "Hammer") ? 1 - item_owner : item_owner) : sword_hand_now();
        if (sword != swing_hand) swing_hand = sword, swing_n = 0, swinging = false;
        if (pose_ok[sword]) {   // the velocity over the last 4 frames
            const float hx = poses[sword].p[0] - head[0], hz = poses[sword].p[2] - head[2];
            out = std::sqrt(hx * hx + hz * hz);
            const int i = swing_n++ & 3;
            std::memcpy(swing_p[i], poses[sword].p, sizeof swing_p[i]);
            swing_t[i] = now;
            if (swing_n >= 4) {
                const int o = swing_n & 3;   // the oldest
                const float dt = (float)(swing_t[i] - swing_t[o]) * 1e-9f;
                float v[3];
                for (int c = 0; c < 3; c++) v[c] = dt > 0 ? (swing_p[i][c] - swing_p[o][c]) / dt : 0.0f;
                const float speed = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
                // none starts with the hand out to the side of the head or behind it, or moving mostly back toward the
                // body: pulling the hands back (to draw, to rest) is not a swing
                // nor while both arms shake upward or the hand shakes above the head (the D-pad's gestures)
                const bool back = back_any[sword] > -0.03f || v[0] * fx + v[2] * fz < -0.5f * speed || both_up || wave[sword];
                // ((Triforce VR) the Deku Stick and the hammer: downward swings only; a bottle: inward only (the right hand's
                // right to left, the left's left to right); the sword any way)
                bool way = true;
                // ((Triforce VR) a thing held in both hands: the other hand at the holding controller's bottom (past its handle's
                // end along the controller's own down, within 18 cm, however it is tilted), and swinging with it)
                const int oh = 1 - sword;
                bool under = false;
                if (pose_ok[oh]) {
                    const float d[3] = {poses[oh].p[0] - poses[sword].p[0], poses[oh].p[1] - poses[sword].p[1], poses[oh].p[2] - poses[sword].p[2]};
                    const float inv[4] = {-poses[sword].q[0], -poses[sword].q[1], -poses[sword].q[2], poses[sword].q[3]};
                    float l[3];
                    rotate(inv, d, l);   // (in the holding controller's grip frame: its handle along z, -z out of the fist's top)
                    under = l[2] > 0.03f && l[0] * l[0] + l[1] * l[1] + l[2] * l[2] < 0.18f * 0.18f;
                }
                const float os = std::sqrt(hv[oh][0] * hv[oh][0] + hv[oh][1] * hv[oh][1] + hv[oh][2] * hv[oh][2]);
                if (strstr(held_item, "Hammer")) way = v[1] < -0.6f * speed;
                else if (strstr(held_item, "DekuStick"))   // (the Deku Stick: both swinging down)
                    way = v[1] < -0.6f * speed && under && os > 0.5f * speed && hv[oh][1] < -0.6f * os;
                else if (!held_item[0] && x.two_handed_sword.load())   // (the Biggoron's Sword: both swinging, any way)
                    way = under && os > 0.5f * speed;
                else if (!strcmp(held_item, "Item_Bottle")) {
                    const float lat = v[0] * rx + v[2] * rz;
                    way = sword ? lat < -0.5f * speed : lat > 0.5f * speed;
                    // ((Triforce VR) and held as at the face for the ocarina: its pointer's level part sideways, inward (the right
                    // hand's to the left, the left's to the right); its tilt and roll do not count)
                    float aim_lat = 0;
                    if (x.aim_ok[sword]) {
                        static const float ray[3] = {0, 0, -1};
                        float d[3];
                        rotate(x.aim_pose[sword].q, ray, d);
                        const float l = d[0] * rx + d[2] * rz, f = d[0] * fx + d[2] * fz, n = std::sqrt(l * l + f * f);
                        aim_lat = n > 0.2f ? l / n : 0.0f;
                    }
                    way = way && (sword ? aim_lat < -0.6f : aim_lat > 0.6f);
                }
                // ((Triforce VR) Immersive (third person): any solid swing, whichever way, for every item (no direction or two-hand rule)
                if (!strcmp(cfg_value("VR_VIEW"), "head") && !strcmp(cfg_value("VR_CAMERA"), "third") && !gestures_in_immersive()) way = true;
                if (!swinging && speed > swing_on && now - swing_at >= refractory_ns && !back && way) {
                    swinging = swung = true;
                    swing_at = now;
                    // outward: most of the motion away from the head's upright line
                    outward = out > 0.05f && (v[0] * hx + v[2] * hz) / out > 0.6f * speed;
                } else if (swinging && speed < swing_off) {
                    swinging = false;
                }
            }
        } else swing_n = 0, swinging = false;
        // ((Triforce VR) the sword's gesture-chosen slash: a sword swing waits for its choice (at 30 cm from its start, 250 ms at most)
        static bool slash_wait = false, slash_ready = false;
        static int slash_code = -1;
        static uint64_t slash_wait_at = 0, slash_extra_until = 0;
        static bool slash_zl = false, slash_fwd = false;   // (the press's Z held, the left stick forward with it)
        {   // ((Triforce VR) research, SWING-LOG: each swing's path in the head's frame (side to the right, up, ahead), its peak
            // speed and the half second before it (a pause, a slow start), logged when it ends, for the gesture-chosen slashes)
            struct Pt { uint64_t t; float s, u, f, v; };
            static Pt path[192];
            static int path_n, start_at = -1;
            static bool was_swinging;
            if (pose_ok[sword]) {
                const float dx = poses[sword].p[0] - head[0], dz = poses[sword].p[2] - head[2];
                Pt q{now, dx * rx + dz * rz, poses[sword].p[1] - head[1], dx * fx + dz * fz, 0};
                if (path_n) {
                    const Pt &o = path[(path_n - 1) % 192];
                    const float dt = (float)(now - o.t) * 1e-9f;
                    const float a = q.s - o.s, b = q.u - o.u, c = q.f - o.f;
                    q.v = dt > 0 ? std::sqrt(a * a + b * b + c * c) / dt : o.v;
                }
                path[path_n++ % 192] = q;
            }
            const auto at = [&](int i) -> const Pt & { return path[((i % 192) + 192) % 192]; };
            if (swung) start_at = path_n - 1;
            {   // ((Triforce VR) the live choice
                static int live_st = -1;
                static uint64_t l_quiet, l_fast, l_soft;
                static bool l_raised;
                // ((Triforce VR) not in Immersive (third person): there any solid swing is the sword's plain swing, as before)
                const bool immersive_view = !strcmp(cfg_value("VR_VIEW"), "head") && !strcmp(cfg_value("VR_CAMERA"), "third") &&
                                            !gestures_in_immersive();
                if (swung && in_play && !carry && !held_item[0] && x.weapon_out.load() && start_at >= 0 && !immersive_view) {
                    int st = start_at;
                    while (st > path_n - 190 && st > 0 && at(st - 1).v >= swing_off && now - at(st - 1).t < 1500000000ull) st--;
                    live_st = st, slash_wait = true, slash_ready = false, slash_wait_at = now;
                    const Pt &a0 = at(st);
                    uint64_t run = 0, soft_run = 0, prev_t = a0.t;
                    bool fast_seen = false;
                    float u_min = a0.u;
                    l_quiet = l_soft = 0, l_fast = 600000000ull;
                    for (int i = st - 1; i > st - 190 && i >= 0; i--) {
                        const Pt &p = at(i);
                        const uint64_t ago = a0.t - p.t;
                        if (ago > 1000000000ull) break;
                        u_min = std::fmin(u_min, p.u);
                        if (p.v < 0.5f) soft_run += prev_t - p.t, l_soft = std::max(l_soft, soft_run);
                        else soft_run = 0;
                        if (ago <= 500000000ull) {
                            if (p.v < 0.3f) run += prev_t - p.t, l_quiet = std::max(l_quiet, run);
                            else run = 0;
                            if (!fast_seen && p.v > 1.0f) l_fast = ago, fast_seen = true;
                        }
                        prev_t = p.t;
                    }
                    l_raised = a0.u - u_min > 0.35f;
                }
                if (slash_wait && !slash_ready && live_st >= 0 && path_n - live_st < 180) {
                    const Pt &a0 = at(live_st), &q = at(path_n - 1);
                    const float dx1 = q.s - a0.s, du1 = q.u - a0.u, df1 = q.f - a0.f;
                    if (dx1 * dx1 + du1 * du1 + df1 * df1 >= 0.30f * 0.30f || now - slash_wait_at >= 250000000ull || !swinging) {
                        float pk = 0, fwd0 = 0;
                        for (int i = live_st; i < path_n; i++) {
                            pk = std::fmax(pk, at(i).v);
                            if (at(i).t - a0.t <= 80000000ull) fwd0 = at(i).f - a0.f;
                        }
                        const float os = sword ? 1.0f : -1.0f;
                        SlashIn in{dx1 * os, du1, df1, pk, fwd0, a0.s, a0.f, a0.s * os, l_quiet, l_fast, l_soft, l_raised,
                                   x.two_handed_sword.load(), true};
                        in.zt = (bits & 1ull << ZL) != 0, in.air = x.airborne.load(), in.start_up = a0.u;
                        const char *why = "";
                        slash_code = slash_classify(in, &why), slash_ready = true;
                        rt_log("vr: slash: %s (counter %d, %.0f ms in)", why, slash_counter(slash_code), (double)(now - slash_wait_at) * 1e-6);
                    }
                }
            }
            if (was_swinging && !swinging && start_at >= 0 && path_n - start_at < 180) {
                // its start: back from the trigger to where the hand was last under swing_off (0.3 s at most)
                int st = start_at;
                while (st > path_n - 190 && st > 0 && at(st - 1).v >= swing_off && now - at(st - 1).t < 1500000000ull) st--;
                // its end: the point farthest from its start (a hand brought back after it is not part of it)
                int fe = st;
                float far2 = 0;
                for (int i = st; i < path_n; i++) {
                    const float a1 = at(i).s - at(st).s, b1 = at(i).u - at(st).u, c1 = at(i).f - at(st).f, d2 = a1 * a1 + b1 * b1 + c1 * c1;
                    if (d2 > far2) far2 = d2, fe = i;
                }
                const Pt &a = at(st), &b = at(fe);
                float peak = 0;
                for (int i = st; i <= fe; i++) peak = std::fmax(peak, at(i).v);
                // before it: the slowest and the fastest of the 0.6 s before, how long it was still (under 0.15 m/s) right
                // before, and its mean speed over the 0.25 s before
                float pre_min = 1e9f, pre_max = 0, mean25 = 0;
                int n25 = 0;
                uint64_t still_ns = 0;
                bool still_run = true;
                for (int i = st - 1; i > st - 180 && i >= 0 && a.t - at(i).t < 600000000ull; i--) {
                    const Pt &p = at(i);
                    pre_min = std::fmin(pre_min, p.v), pre_max = std::fmax(pre_max, p.v);
                    if (a.t - p.t < 250000000ull) mean25 += p.v, n25++;
                    if (still_run && p.v < 0.15f) still_ns = a.t - p.t;
                    else still_run = false;
                }
                // the speed over the 0.5 s before it, 50 ms a step (oldest first), and how far it went forward in its first 80 ms
                char prof[160];
                int po = 0;
                for (int k = 9; k >= 0; k--) {
                    float sum = 0;
                    int cnt = 0;
                    for (int i = st - 1; i > st - 180 && i >= 0; i--) {
                        const uint64_t ago = a.t - at(i).t;
                        if (ago >= (uint64_t)k * 50000000ull && ago < (uint64_t)(k + 1) * 50000000ull) sum += at(i).v, cnt++;
                        if (ago > 600000000ull) break;
                    }
                    po += snprintf(prof + po, sizeof prof - po, "%s%.2f", k == 9 ? "" : " ", cnt ? sum / (float)cnt : 0.0f);
                }
                float first_fwd = 0;
                for (int i = st; i <= fe; i++)
                    if (at(i).t - a.t <= 80000000ull) first_fwd = at(i).f - a.f;
                const float ds = b.s - a.s, du = b.u - a.u, df = b.f - a.f, flat = std::sqrt(ds * ds + df * df);
                const float steep = std::atan2(std::fabs(du), flat) * 57.2958f;
                const float out_s = sword ? 1.0f : -1.0f;   // (+ toward the sword hand's side)
                rt_log("vr: swing: %s hand, %.0f ms, peak %.2f m/s; from side %+.2f up %+.2f ahead %+.2f to side %+.2f up %+.2f ahead %+.2f "
                       "(toward sword side %+.2f, up %+.2f, ahead %+.2f; steep %.0f deg); before: still %.0f ms, slowest %.2f, fastest %.2f, "
                       "mean of 0.25 s %.2f; profile [%s]; first 80 ms ahead %+.3f; item \"%s\" biggoron %d weapon %d shield %d",
                       sword ? "right" : "left", (double)(b.t - a.t) * 1e-6, peak, a.s, a.u, a.f, b.s, b.u, b.f, ds * out_s, du, df, steep,
                       (double)still_ns * 1e-6, pre_min < 1e8f ? pre_min : 0.0f, pre_max, n25 ? mean25 / (float)n25 : 0.0f, prof, first_fwd, held_item,
                       (int)x.two_handed_sword.load(), (int)x.weapon_out.load(), (int)shielding);
                {   // ((Triforce VR) research, SWING-CLASS: the slash these rules would choose (log only), from the whole swing and
                    // from its first 100 ms (what a live choice would have)
                    // before it: the longest run under 0.3 m/s in the 0.5 s before, the time since the hand last moved over 1 m/s, and
                    // how far it rose in the second before (a jump slash's raise)
                    uint64_t quiet = 0, run = 0, soft = 0, soft_run = 0, last_fast = 600000000ull, prev_t = a.t;
                    bool fast_seen = false;
                    float u_min = a.u;
                    for (int i = st - 1; i > st - 190 && i >= 0; i--) {
                        const Pt &p = at(i);
                        const uint64_t ago = a.t - p.t;
                        if (ago > 1000000000ull) break;
                        u_min = std::fmin(u_min, p.u);
                        // (a softer pause for the finishers: under 0.5 m/s, anywhere in the second before)
                        if (p.v < 0.5f) soft_run += prev_t - p.t, soft = std::max(soft, soft_run);
                        else soft_run = 0;
                        if (ago <= 500000000ull) {
                            if (p.v < 0.3f) run += prev_t - p.t, quiet = std::max(quiet, run);
                            else run = 0;
                            if (!fast_seen && p.v > 1.0f) last_fast = ago, fast_seen = true;
                        }
                        prev_t = p.t;
                    }
                    const bool raised = a.u - u_min > 0.35f;
                    const float s0 = a.s * out_s;   // (its start toward the sword hand's side)
                    const bool big = !held_item[0] && x.two_handed_sword.load();
                    // (early: the live choice at 30 cm: a strict hesitation and the speed reached by then (4.5 m/s) mark a finisher)
                    const auto classify = [&](float X, float U, float F, float pk, float fwd0, bool early_rule = false) -> const char * {
                        const SlashIn in{X, U, F, pk, fwd0, a.s, a.f, s0, quiet, last_fast, soft, raised, big, early_rule};
                        const char *why = "";
                        slash_classify(in, &why);
                        return why;
                    };
                    int e = st;   // (100 ms in)
                    float pk_e = 0;
                    for (int i = st; i <= fe && at(i).t - a.t <= 100000000ull; i++) e = i, pk_e = std::fmax(pk_e, at(i).v);
                    const Pt &m = at(e);
                    const char *full = (b.t - a.t < 120000000ull || peak > 30.0f) ? "ignored (tracking glitch)"
                                     : classify(ds * out_s, du, df, peak, first_fwd);
                    const char *early = classify((m.s - a.s) * out_s, m.u - a.u, m.f - a.f, pk_e, first_fwd);
                    // (and once it has gone 20 cm and 30 cm from its start: the verdict and when)
                    char at_d[2][96];
                    for (int k = 0; k < 2; k++) {
                        const float dd = k ? 0.30f : 0.20f;
                        snprintf(at_d[k], sizeof at_d[k], "never");
                        float pk_d = 0;
                        for (int i = st; i <= fe; i++) {
                            const Pt &q = at(i);
                            pk_d = std::fmax(pk_d, q.v);
                            const float a1 = q.s - a.s, b1 = q.u - a.u, c1 = q.f - a.f;
                            if (a1 * a1 + b1 * b1 + c1 * c1 >= dd * dd) {
                                snprintf(at_d[k], sizeof at_d[k], "%s at %.0f ms, %.2f m/s", classify(a1 * out_s, b1, c1, pk_d, first_fwd, true),
                                         (double)(q.t - a.t) * 1e-6, pk_d);
                                break;
                            }
                        }
                    }
                    rt_log("vr: swing class: %s | early (100 ms): %s | 20 cm: %s | 30 cm: %s | quiet %.0f ms, last fast %.0f ms ago, raised %d, soft pause %.0f ms",
                           full, early, at_d[0], at_d[1], (double)quiet * 1e-6, (double)last_fast * 1e-6, (int)raised, (double)soft * 1e-6);
                }
                start_at = -1;
            }
            was_swinging = swinging;
        }
        if (carry) {   // (both hands together, neither back toward the body nor down, as it is put down; one alone throws nothing)
            swung = outward = charging = false;
            const float least = carry_share * swing_on;
            float vm[3], dot = 0;
            for (int c = 0; c < 3; c++) vm[c] = 0.5f * (hv[0][c] + hv[1][c]), dot += hv[0][c] * hv[1][c];
            const float m = std::sqrt(vm[0] * vm[0] + vm[1] * vm[1] + vm[2] * vm[2]);
            if (pose_ok[0] && pose_ok[1] && hspeed[0] > least && hspeed[1] > least && dot > carry_same * hspeed[0] * hspeed[1] &&
                vm[0] * fx + vm[2] * fz > -0.5f * m && vm[1] > -0.7f * m && now - swing_at >= refractory_ns)
                swung = true, swing_at = now, rt_log("vr: carry: thrown by both hands");
        }
        if (swung && !slash_wait) queued = true;
        if (slash_wait && slash_ready) {   // ((Triforce VR) the gesture-chosen slash: its step set, then the swing's press; none ignored
            slash_wait = false;
            if (slash_code != 0) {
                const int cv = slash_counter(slash_code);
                if (cv >= 0) x.combo_want.store(cv);
                // (the Biggoron's steep slashes: Z for that press; the stab: Z (held already) and forward; the jump slash: forward and A)
                slash_zl = x.two_handed_sword.load() && ((slash_code >= 10 && slash_code <= 13) || slash_code == 20 || slash_code == 21);
                slash_fwd = slash_code == 20 || slash_code == 21;
                slash_extra_until = now + 250000000ull;
                queued = true;
            }
        }
        if (charging) {
            queued = false;   // (the hand brought back in fast is the release, not a swing)
            if (out < out_off || !pose_ok[sword]) charging = false, y_down = 0, y_up = now;
        } else if (y_down) {
            if (now - y_down >= tap_ns) {
                if (outward && out > out_on) charging = true;
                else y_down = 0, y_up = now;
            }
        }
        if (!y_down && queued && now - y_up >= gap_ns) {
            // what the swing does in play: the sword out (no item) its swing, Y; the hammer, the Deku Stick or an empty
            // bottle out their use, ZR (the hammer's or stick's swing, the bottle's scoop); else nothing
            // ((Triforce VR) a bomb or a Bombchu: the swing throws it (ZR, the game's RT))
            const bool swinger = strstr(held_item, "Hammer") || strstr(held_item, "DekuStick") || !strcmp(held_item, "Item_Bottle") ||
                                 strstr(held_item, "Item_Bomb");
            // (something of the world's carried: the throw, Y, whatever item was out before)
            tap_bit = !in_play ? -1 : carry ? Y : swinger ? ZR : !held_item[0] && x.weapon_out.load() ? Y : -1;   // (no swing in menus)
            if (tap_bit == Y && slash_code == 20 && now < slash_extra_until) tap_bit = A;   // ((Triforce VR) the jump slash: A)
            queued = false;
            // (the charge: the sword's; ((Triforce VR) a gesture-chosen slash's press comes once it is chosen, often after the swing has
            // ended: its outward kept)
            if (tap_bit >= 0) y_down = now, outward = outward && (swinging || now < slash_extra_until) && tap_bit == Y && !carry;
            if (tap_bit == ZR && strstr(held_item, "Hammer")) g_hammer_swung.store(now);   // ((Triforce VR) his arms the swing's: vk_xr_arms_own
        }
        if (tap_bit >= 0) set_bit(tap_bit, y_down != 0);
        if (now < slash_extra_until && (y_down || queued)) {   // ((Triforce VR) the gesture-chosen slash's Z and stick
            if (slash_zl) set_bit(ZL, true);
            if (slash_fwd) sticks[0][0] = 0.0f, sticks[0][1] = 1.0f;
        }
        if (bits & 1ull << Y || (now < draw_until && draw_bit == Y)) shield_alone = false;
        {   // ((Triforce VR) (an item a gamepad took out: in the hand the mirror puts it)
            const bool hammer = strstr(held_item, "Hammer"), stick = strstr(held_item, "DekuStick");
            const int by_mirror = item_mirrored_right(held_item) ? g_live_mirror.load() == 1 : g_live_mirror.load() != 1;
            g_two_hands.store(hammer || stick ? (pull_hand >= 0 ? pull_hand : by_mirror) : shield_alone ? 2 : -1);
        }
        if (now < draw_until) set_bit(draw_bit, true);
        if (ocarina) {   // the notes: the right stick's left, up, right and down Y, X, A and R; the A button L
            const bool a_down = bits & (1ull << A);
            bits &= ~(1ull << A | 1ull << X | 1ull << Y | 1ull << L | 1ull << R);
            y_down = 0, charging = false, queued = false;   // no sword meanwhile
            set_bit(L, a_down);
            const float sx = sticks[1][0], sy = sticks[1][1];
            if (sx * sx + sy * sy > 0.25f)
                set_bit(std::fabs(sx) > std::fabs(sy) ? (sx < 0 ? Y : A) : (sy > 0 ? X : R), true);
        }
        publish();
    }
    void log_profile(XrSession session) {
        if (!ok) return;
        Xr &x = xr();
        for (int h = 0; h < 2; h++) {
            XrInteractionProfileState ps{XR_TYPE_INTERACTION_PROFILE_STATE};
            char name[XR_MAX_PATH_LENGTH] = "none";
            uint32_t n = 0;
            if (XR_SUCCEEDED(x.xrGetCurrentInteractionProfile(session, hand[h], &ps)) && ps.interactionProfile != XR_NULL_PATH)
                x.xrPathToString(x.instance, ps.interactionProfile, sizeof name, &n, name);
            rt_log("vr: the %s hand's controller: %s", h ? "right" : "left", name);
        }
    }
};

// The session's thread: its events, the headset's frames, and each newer box into the swapchain
void run(void *) {
    Xr &x = xr();
    XrGraphicsBindingVulkanKHR binding{XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR};
    binding.instance = x.vk_instance;
    binding.physicalDevice = x.phys;
    binding.device = x.device;
    binding.queueFamilyIndex = x.family;
    binding.queueIndex = x.queue_index;
    XrSessionCreateInfo sci{XR_TYPE_SESSION_CREATE_INFO};
    sci.next = &binding;
    sci.systemId = x.system;
    XrSession session = XR_NULL_HANDLE;
    XrResult r = x.xrCreateSession(x.instance, &sci, &session);
    if (XR_FAILED(r)) {
        rt_log("vr: xrCreateSession failed (%d): VR off", (int)r);
        return;
    }
    XrReferenceSpaceCreateInfo rs{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
    rs.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
    rs.poseInReferenceSpace.orientation.w = 1.0f;
    XrSpace space = XR_NULL_HANDLE, view_space = XR_NULL_HANDLE;
    x.xrCreateReferenceSpace(session, &rs, &space);
    rs.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW;
    x.xrCreateReferenceSpace(session, &rs, &view_space);

    uint32_t n = 0;
    x.xrEnumerateSwapchainFormats(session, 0, &n, nullptr);
    std::vector<int64_t> formats(n);
    x.xrEnumerateSwapchainFormats(session, n, &n, formats.data());
    int64_t format = 0;
    for (int64_t want : {(int64_t)VK_FORMAT_R8G8B8A8_SRGB, (int64_t)VK_FORMAT_B8G8R8A8_SRGB})
        for (int64_t f : formats)
            if (!format && f == want) format = f;
    if (!format) {
        rt_log("vr: the runtime offers no 8-bit sRGB swapchain format: VR off");
        return;
    }
    x.rgba.store(format == VK_FORMAT_R8G8B8A8_SRGB);

    XrSwapchain swapchain = XR_NULL_HANDLE, hud_swapchain = XR_NULL_HANDLE;   // (the HUD's panel's own)
    std::vector<XrSwapchainImageVulkanKHR> images, hud_images;
    bool hud_has = false;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkCommandBuffer cb = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    // the swapchain is the window's size, known at the first capture
    const auto make_swapchain = [&]() -> bool {
        uint32_t w = x.want_w.load(), h = x.want_h.load();
        if (!w || !h) return false;
        const uint32_t most = w > h ? w : h;
        if (most > 3840) w = w * 3840 / most, h = h * 3840 / most;
        x.width = w & ~1u, x.height = h & ~1u;
        XrSwapchainCreateInfo sw{XR_TYPE_SWAPCHAIN_CREATE_INFO};
        sw.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT;
        sw.format = format;
        sw.sampleCount = 1;
        sw.width = 2 * x.width, sw.height = x.height;   // the left eye's picture on the left, the right eye's beside it
        sw.faceCount = sw.arraySize = sw.mipCount = 1;
        r = x.xrCreateSwapchain(session, &sw, &swapchain);
        if (XR_FAILED(r)) {
            rt_log("vr: xrCreateSwapchain failed (%d): VR off", (int)r);
            return false;
        }
        x.xrEnumerateSwapchainImages(swapchain, 0, &n, nullptr);
        images.assign(n, {XR_TYPE_SWAPCHAIN_IMAGE_VULKAN_KHR});
        x.xrEnumerateSwapchainImages(swapchain, n, &n, (XrSwapchainImageBaseHeader *)images.data());
        sw.width = x.width;
        if (XR_SUCCEEDED(x.xrCreateSwapchain(session, &sw, &hud_swapchain))) {
            uint32_t hn = 0;
            x.xrEnumerateSwapchainImages(hud_swapchain, 0, &hn, nullptr);
            hud_images.assign(hn, {XR_TYPE_SWAPCHAIN_IMAGE_VULKAN_KHR});
            x.xrEnumerateSwapchainImages(hud_swapchain, hn, &hn, (XrSwapchainImageBaseHeader *)hud_images.data());
        } else {
            hud_swapchain = XR_NULL_HANDLE;
            rt_log("vr: no swapchain for the HUD's panel: the HUD stays in the picture");
        }
        VkCommandPoolCreateInfo pi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
        pi.queueFamilyIndex = x.family;
        vkCreateCommandPool(x.device, &pi, nullptr, &pool);
        VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
        ai.commandPool = pool, ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, ai.commandBufferCount = 1;
        vkAllocateCommandBuffers(x.device, &ai, &cb);
        VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
        vkCreateFence(x.device, &fi, nullptr, &fence);
        x.ready.store(true, std::memory_order_release);
        rt_log("vr: swapchain made: %ux%u, %u images, format %lld, queue %u of family %u; the screen %.2f m away",
               x.width, x.height, n, (long long)format, x.queue_index, x.family, x.screen_distance);
        return true;
    };
    rt_log("vr: session made");
    Controls controls;
    controls.make(session);

    bool running = false, have_image = false;
    uint64_t shown = 0, frames = 0, copies = 0, tracked_frames = 0;
    Drawn shown_drawn;   // what the picture in the swapchain was drawn from
    uint64_t last_log = plat_now_ns();
    for (;;) {
        XrEventDataBuffer ev{XR_TYPE_EVENT_DATA_BUFFER};
        bool quit = false;
        while (x.xrPollEvent(x.instance, &ev) == XR_SUCCESS) {
            if (ev.type == XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED) {
                const auto *s = (const XrEventDataSessionStateChanged *)&ev;
                rt_log("vr: session state %d", (int)s->state);
                if (s->state == XR_SESSION_STATE_READY) {
                    XrSessionBeginInfo bi{XR_TYPE_SESSION_BEGIN_INFO};
                    bi.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
                    r = x.xrBeginSession(session, &bi);
                    running = XR_SUCCEEDED(r);
                    if (!running) rt_log("vr: xrBeginSession failed (%d)", (int)r);
                } else if (s->state == XR_SESSION_STATE_STOPPING) {
                    x.xrEndSession(session);
                    running = false;
                } else if (s->state == XR_SESSION_STATE_EXITING || s->state == XR_SESSION_STATE_LOSS_PENDING) {
                    quit = true;
                }
            } else if (ev.type == XR_TYPE_EVENT_DATA_INTERACTION_PROFILE_CHANGED) {
                controls.log_profile(session);
            } else if (ev.type == XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING) {
                quit = true;
            }
            ev = XrEventDataBuffer{XR_TYPE_EVENT_DATA_BUFFER};
        }
        if (quit) {
            rt_log("vr: the session ended: VR off until the game starts again");
            x.ready.store(false), x.running.store(false);
            std::lock_guard<std::mutex> lk(x.head_mu);
            x.have_head = false;
            return;
        }
        x.running.store(running);
        if (!running) {
            plat_sleep_ms(50);
            continue;
        }
        if (!swapchain && !make_swapchain() && x.want_w.load()) return;   // known and failed: said above
        XrFrameWaitInfo wi{XR_TYPE_FRAME_WAIT_INFO};
        XrFrameState fs{XR_TYPE_FRAME_STATE};
        if (XR_FAILED(x.xrWaitFrame(session, &wi, &fs))) continue;
        XrFrameBeginInfo bfi{XR_TYPE_FRAME_BEGIN_INFO};
        x.xrBeginFrame(session, &bfi);
        frames++;

        {   // the head and the eyes' lenses at this frame's predicted time: what the game draws its next frame with
            XrViewLocateInfo li{XR_TYPE_VIEW_LOCATE_INFO};
            li.viewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
            li.displayTime = fs.predictedDisplayTime;
            li.space = space;
            XrViewState vs{XR_TYPE_VIEW_STATE};
            XrView views[2] = {{XR_TYPE_VIEW}, {XR_TYPE_VIEW}};
            uint32_t count = 0;
            XrSpaceLocation head{XR_TYPE_SPACE_LOCATION};
            const bool views_ok = XR_SUCCEEDED(x.xrLocateViews(session, &li, &vs, 2, &count, views)) && count == 2;
            const bool head_ok = XR_SUCCEEDED(x.xrLocateSpace(view_space, space, fs.predictedDisplayTime, &head)) &&
                                 (head.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);
            if (views_ok && head_ok) {
                Lens eyes;
                eyes.l = std::fmin(std::tan(views[0].fov.angleLeft), std::tan(views[1].fov.angleLeft));
                eyes.r = std::fmax(std::tan(views[0].fov.angleRight), std::tan(views[1].fov.angleRight));
                eyes.u = std::fmax(std::tan(views[0].fov.angleUp), std::tan(views[1].fov.angleUp));
                eyes.d = std::fmin(std::tan(views[0].fov.angleDown), std::tan(views[1].fov.angleDown));
                const float dx = views[1].pose.position.x - views[0].pose.position.x,
                            dy = views[1].pose.position.y - views[0].pose.position.y,
                            dz = views[1].pose.position.z - views[0].pose.position.z;
                const float ipd = std::sqrt(dx * dx + dy * dy + dz * dz);
                std::lock_guard<std::mutex> lk(x.head_mu);
                x.eyes = eyes;
                if (ipd > 0.04f && ipd < 0.09f) x.ipd = ipd;
                std::memcpy(x.head.q, &head.pose.orientation, sizeof x.head.q);
                std::memcpy(x.head.p, &head.pose.position, sizeof x.head.p);
                x.have_head = true;
            }
        }
        {
            Pose head_now;
            {
                std::lock_guard<std::mutex> lk(x.head_mu);
                head_now = x.head;
            }
            controls.read(session, space, fs.predictedDisplayTime, head_now);
        }

        int slot = -1;
        uint64_t value = 0;
        Drawn drawn;
        if (swapchain) {
            std::lock_guard<std::mutex> lk(x.mu);
            if (x.latest >= 0 && x.box_value[x.latest] > shown)
                slot = x.latest, value = x.box_value[slot], drawn = x.box_drawn[slot], x.reading = slot;
        }
        // a box into the next image of a swapchain on VR's queue, after the present that wrote it (its timeline value)
        const auto copy_into = [&](XrSwapchain target, std::vector<XrSwapchainImageVulkanKHR> &imgs, VkImage from) -> bool {
            uint32_t index = 0;
            XrSwapchainImageAcquireInfo acq{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
            XrSwapchainImageWaitInfo wait{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
            wait.timeout = XR_INFINITE_DURATION;
            if (XR_FAILED(x.xrAcquireSwapchainImage(target, &acq, &index)) || XR_FAILED(x.xrWaitSwapchainImage(target, &wait)))
                return false;
            const VkImage dst = imgs[index].image;
            (vkResetCommandPool)(x.device, pool, 0);
            VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
            bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
            (vkBeginCommandBuffer)(cb, &bi);
            barrier_direct(cb, dst, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
            VkImageCopy c{};
            c.srcSubresource = c.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
            c.extent = {x.width, x.height, 1};
            (vkCmdCopyImage)(cb, from, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, dst, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &c);
            barrier_direct(cb, dst, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
            (vkEndCommandBuffer)(cb);
            VkSemaphoreSubmitInfo w{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO};
            w.semaphore = x.timeline, w.value = value, w.stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
            VkCommandBufferSubmitInfo cbi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO};
            cbi.commandBuffer = cb;
            VkSubmitInfo2 si{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};
            si.waitSemaphoreInfoCount = 1, si.pWaitSemaphoreInfos = &w;
            si.commandBufferInfoCount = 1, si.pCommandBufferInfos = &cbi;
            (vkQueueSubmit2)(x.queue, 1, &si, fence);
            XrSwapchainImageReleaseInfo rel{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
            x.xrReleaseSwapchainImage(target, &rel);
            (vkWaitForFences)(x.device, 1, &fence, VK_TRUE, UINT64_MAX);
            (vkResetFences)(x.device, 1, &fence);
            return true;
        };
        if (slot >= 0 && (drawn.hud || drawn.menu) && hud_swapchain)
            hud_has = copy_into(hud_swapchain, hud_images, x.hud_boxes[slot]);
        if (slot >= 0) {
            uint32_t index = 0;
            XrSwapchainImageAcquireInfo acq{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
            XrSwapchainImageWaitInfo wait{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
            wait.timeout = XR_INFINITE_DURATION;
            if (XR_SUCCEEDED(x.xrAcquireSwapchainImage(swapchain, &acq, &index)) &&
                XR_SUCCEEDED(x.xrWaitSwapchainImage(swapchain, &wait))) {
                const VkImage dst = images[index].image;
                (vkResetCommandPool)(x.device, pool, 0);
                VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
                bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
                (vkBeginCommandBuffer)(cb, &bi);
                barrier_direct(cb, dst, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
                VkImageCopy c{};
                c.srcSubresource = c.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
                c.extent = {x.width, x.height, 1};
                (vkCmdCopyImage)(cb, x.boxes[slot], VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, dst,
                                 VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &c);
                if (drawn.stereo) {
                    c.dstOffset.x = (int32_t)x.width;
                    (vkCmdCopyImage)(cb, x.boxes_r[slot], VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, dst,
                                     VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &c);
                }
                barrier_direct(cb, dst, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
                (vkEndCommandBuffer)(cb);
                VkSemaphoreSubmitInfo w{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO};
                w.semaphore = x.timeline, w.value = value, w.stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
                VkCommandBufferSubmitInfo cbi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO};
                cbi.commandBuffer = cb;
                VkSubmitInfo2 si{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};
                si.waitSemaphoreInfoCount = 1, si.pWaitSemaphoreInfos = &w;
                si.commandBufferInfoCount = 1, si.pCommandBufferInfos = &cbi;
                (vkQueueSubmit2)(x.queue, 1, &si, fence);
                XrSwapchainImageReleaseInfo rel{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
                x.xrReleaseSwapchainImage(swapchain, &rel);
                (vkWaitForFences)(x.device, 1, &fence, VK_TRUE, UINT64_MAX);
                (vkResetFences)(x.device, 1, &fence);
                have_image = true;
                shown = value;
                shown_drawn = drawn;
                copies++;
            }
            std::lock_guard<std::mutex> lk(x.mu);
            x.reading = -1;
        }

        // the screen: VR_SCREEN_SIZE degrees of the view wide, screen_distance away, an arc of a cylinder around
        // the head or a flat quad
        const float wide = 3.14159265f / 180.0f * (float)cfg_int("VR_SCREEN_SIZE");
        const float ratio = x.height ? (float)x.width / (float)x.height : 16.0f / 9.0f;
        XrCompositionLayerQuad quad{XR_TYPE_COMPOSITION_LAYER_QUAD};
        quad.space = space;
        quad.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
        quad.subImage.swapchain = swapchain;
        quad.subImage.imageRect = {{0, 0}, {(int32_t)x.width, (int32_t)x.height}};
        quad.pose.orientation.w = 1.0f;
        quad.pose.position.z = -x.screen_distance;
        const float flat_w = 2.0f * x.screen_distance * std::tan(0.5f * std::fmin(wide, 2.6f));
        quad.size = {flat_w, flat_w / ratio};
        XrCompositionLayerCylinderKHR curve{XR_TYPE_COMPOSITION_LAYER_CYLINDER_KHR};
        curve.space = space;
        curve.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
        curve.subImage = quad.subImage;
        curve.pose.orientation.w = 1.0f;   // the head's start in the middle, the arc ahead (-z)
        curve.radius = x.screen_distance;
        curve.centralAngle = wide;
        curve.aspectRatio = ratio;   // the arc's length over its height
        const bool curved = x.cylinder && cfg_bool("VR_SCREEN_CURVE");
        // a picture drawn from the head's pose: a projection layer at that pose, the same picture to both eyes, or with
        // depth stereo each eye's own picture at its own place, half the eyes' distance to its side; the compositor turns
        // it with the head between the game's frames
        XrCompositionLayerProjectionView pv[2] = {{XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW},
                                                  {XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW}};
        for (int e = 0; e < 2; e++) {
            XrCompositionLayerProjectionView &v = pv[e];
            const Pose &own = shown_drawn.stereo && shown_drawn.eye >= 0 ? shown_drawn.eye_pose[e] : shown_drawn.pose;
            std::memcpy(&v.pose.orientation, own.q, sizeof own.q);
            float at[3] = {own.p[0], own.p[1], own.p[2]};
            if (shown_drawn.stereo && shown_drawn.eye < 0) {   // (Balanced's eyes are at their own poses already)
                const float side[3] = {(e ? 0.5f : -0.5f) * shown_drawn.ipd, 0, 0};
                float off[3];
                rotate(shown_drawn.pose.q, side, off);
                for (int c = 0; c < 3; c++) at[c] += off[c];
            }
            std::memcpy(&v.pose.position, at, sizeof at);
            v.fov.angleLeft = std::atan(shown_drawn.lens.l), v.fov.angleRight = std::atan(shown_drawn.lens.r);
            v.fov.angleUp = std::atan(shown_drawn.lens.u), v.fov.angleDown = std::atan(shown_drawn.lens.d);
            v.subImage.swapchain = swapchain;
            v.subImage.imageRect = {{shown_drawn.stereo && e ? (int32_t)x.width : 0, 0}, {(int32_t)x.width, (int32_t)x.height}};
        }
        XrCompositionLayerProjection proj{XR_TYPE_COMPOSITION_LAYER_PROJECTION};
        proj.space = space;
        proj.viewCount = 2;
        proj.views = pv;
        // the HUD's panel: held in front of the head (VR_HUD_SIZE centimetres wide, a metre away), over the view
        XrCompositionLayerQuad hud{XR_TYPE_COMPOSITION_LAYER_QUAD};
        hud.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
        hud.space = view_space;
        hud.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
        hud.subImage.swapchain = hud_swapchain;
        hud.subImage.imageRect = {{0, 0}, {(int32_t)x.width, (int32_t)x.height}};
        hud.pose.orientation.w = 1.0f;
        hud.pose.position.z = -1.0f;
        {
            const float wide = 0.01f * (float)cfg_int("VR_HUD_SIZE");
            hud.size = {wide, x.width ? wide * (float)x.height / (float)x.width : 0};
        }
        // the paused game's menus go on the HUD's panel, over the world as it was
        const bool show_menu = shown_drawn.tracked && shown_drawn.menu && hud_has && hud_swapchain;
        const bool show_hud = shown_drawn.tracked && shown_drawn.hud && hud_has && hud_swapchain && !x.hud_hidden.load();
        const XrCompositionLayerBaseHeader *screen = curved ? (const XrCompositionLayerBaseHeader *)&curve
                                                            : (const XrCompositionLayerBaseHeader *)&quad;
        const XrCompositionLayerBaseHeader *layers[] = {shown_drawn.tracked ? (const XrCompositionLayerBaseHeader *)&proj
                                                                            : screen,
                                                        (const XrCompositionLayerBaseHeader *)&hud};
        if (shown_drawn.tracked) tracked_frames++;
        XrFrameEndInfo ei{XR_TYPE_FRAME_END_INFO};
        ei.displayTime = fs.predictedDisplayTime;
        ei.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
        ei.layerCount = have_image && fs.shouldRender ? (show_hud || show_menu ? 2 : 1) : 0;
        ei.layers = layers;
        r = x.xrEndFrame(session, &ei);
        if (XR_FAILED(r)) rt_log("vr: xrEndFrame failed (%d)", (int)r);
        const uint64_t now = plat_now_ns();
        if (now - last_log > 10000000000ull) {
            rt_log("vr: %llu headset frames (%llu with the head's view), %llu pictures copied in the last 10 s (%u drawn "
                   "from the head, %u HUD panels made, %u in depth stereo, %u without the scene's depth, %u paused); the "
                   "game's camera %u, lens %u", (unsigned long long)frames, (unsigned long long)tracked_frames,
                   (unsigned long long)copies, x.tracked_pictures.exchange(0), x.panels.exchange(0), x.stereo_pictures.exchange(0),
                   x.stereo_missed.exchange(0), x.menu_pictures.exchange(0), x.camera_given.exchange(0), x.lens_given.exchange(0));
            rt_log("vr: the scene's feed (10 s): gameplay upscales %u (%u taken for VR), scenes kept %u, depths kept %u; panels "
                   "declined: %u without a scene or target, %u with no scene new since the last", x.upscales.exchange(0),
                   x.upscales_vr.exchange(0), x.scenes_kept.exchange(0), x.depths_kept.exchange(0), x.panel_no_scene.exchange(0),
                   x.panel_not_new.exchange(0));
            {
                std::lock_guard<std::mutex> lk(x.hands_mu);
                rt_log("vr: hands: buttons %#llx, sticks %.2f %.2f / %.2f %.2f, grips %s %s (left at %.2f %.2f %.2f)",
                       (unsigned long long)x.hand_buttons, x.hand_sticks[0][0], x.hand_sticks[0][1], x.hand_sticks[1][0],
                       x.hand_sticks[1][1], x.grip_ok[0] ? "tracked" : "lost", x.grip_ok[1] ? "tracked" : "lost",
                       x.grip[0].p[0], x.grip[0].p[1], x.grip[0].p[2]);
            }
            frames = copies = tracked_frames = 0, last_log = now;
        }
    }
}

} // namespace

extern "C" void vk_xr_instance_exts(const char **ext, uint32_t *n, uint32_t cap) {
    if (!init()) return;
    for (const char *name : xr().instance_list) {
        if (listed(ext, *n, name)) continue;
        if (*n >= cap) {
            rt_log("vr: no room for the instance extension %s: VR off", name);
            xr().ok = false;
            return;
        }
        ext[(*n)++] = name;
    }
}

extern "C" VkPhysicalDevice vk_xr_device(VkInstance instance) {
    Xr &x = xr();
    if (!x.ok) return VK_NULL_HANDLE;
    VkPhysicalDevice p = VK_NULL_HANDLE;
    const XrResult r = x.xrGetVulkanGraphicsDeviceKHR(x.instance, x.system, instance, &p);
    if (XR_FAILED(r) || !p) {
        rt_log("vr: xrGetVulkanGraphicsDeviceKHR failed (%d): VR off", (int)r);
        x.ok = false;
        return VK_NULL_HANDLE;
    }
    return x.phys = p;
}

extern "C" void vk_xr_device_picked(VkPhysicalDevice picked) {
    Xr &x = xr();
    if (!x.ok || picked == x.phys) return;
    VkPhysicalDeviceProperties a{}, b{};
    vkGetPhysicalDeviceProperties(picked, &a);
    if (x.phys) vkGetPhysicalDeviceProperties(x.phys, &b);
    rt_log("vr: the headset's runtime draws with %s, the game with %s (not usable there, or chosen by the GPU device row or RX_VK_DEVICE): "
           "VR off", x.phys ? b.deviceName : "no GPU", a.deviceName);
    x.ok = false;
}

extern "C" void vk_xr_device_exts(const VkExtensionProperties *have, uint32_t n_have, const char **ext, uint32_t *n,
                                  uint32_t cap) {
    Xr &x = xr();
    if (!x.ok) return;
    for (const char *name : x.device_list) {
        bool there = false;
        for (uint32_t i = 0; i < n_have && !there; i++) there = !std::strcmp(have[i].extensionName, name);
        if (!there) rt_log("vr: the device lacks %s, which the runtime asks for", name);
        else if (!listed(ext, *n, name)) {
            if (*n >= cap) {
                rt_log("vr: no room for the device extension %s: VR off", name);
                x.ok = false;
                return;
            }
            ext[(*n)++] = name;
        }
    }
}

extern "C" uint32_t vk_xr_queue(uint32_t family_queues, uint32_t first_free) {
    Xr &x = xr();
    if (!x.ok) return UINT32_MAX;
    if (first_free >= family_queues || first_free >= 4) {
        rt_log("vr: the graphics family has %u queues, none spare for VR: VR off", family_queues);
        x.ok = false;
        return UINT32_MAX;
    }
    return x.queue_index = first_free;
}

// Flatscreen 3D (FLAT3D other than off) with no headset: the device kept for it alone
bool flat_on() {
    Xr &x = xr();
    return !x.ok && x.device && strcmp(cfg_value("FLAT3D"), "off") != 0;
}
extern "C" int vk_xr_flat_wanted(void) { return flat_on(); }

extern "C" void vk_xr_device_ready(VkInstance instance, VkPhysicalDevice phys, VkDevice device, uint32_t family) {
    Xr &x = xr();
    if (!x.ok) {   // no headset: the device for flatscreen 3D alone (flat_on)
        x.vk_instance = instance, x.phys = phys, x.device = device, x.family = family;
        return;
    }
    if (x.queue_index == UINT32_MAX) return;
    x.vk_instance = instance, x.phys = phys, x.device = device, x.family = family;
    vkGetDeviceQueue(device, family, x.queue_index, &x.queue);
    VkSemaphoreTypeCreateInfo tc{VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO};
    tc.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
    VkSemaphoreCreateInfo sc{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    sc.pNext = &tc;
    if (vkCreateSemaphore(device, &sc, nullptr, &x.timeline) != VK_SUCCESS) {
        rt_log("vr: no timeline semaphore: VR off");
        x.ok = false;
        return;
    }
    if (!plat_thread_spawn(run, nullptr, "vr session", 0)) {
        rt_log("vr: the session's thread could not start: VR off");
        x.ok = false;
    }
}

extern "C" int vk_xr_head_wanted(void) { return xr().ok && strcmp(cfg_value("VR_VIEW"), "head") == 0; }

extern "C" int vk_xr_depth_wanted(void) {   // (Balanced keeps the depth too: the hands and the reticle are hidden by it)
    return flat_on() || (vk_xr_head_wanted() && (cfg_int("VR_DEPTH") > 0 || stereo_turns() || stereo_accurate()));
}

extern "C" void vk_xr_keep_depth(VkCommandBuffer cb, VkImageView depth, uint32_t w, uint32_t h) {
    if (xr().second_now) return;   // (Stereo Accurate's right eye: the left's depth is the one kept)
    Xr &x = xr();
    if (!((x.ok && x.head_view.load(std::memory_order_relaxed)) || flat_on()) || !depth || !w || !h) return;
    std::lock_guard<std::mutex> lk(x.hud_mu);
    if (!x.keep_tried) {
        x.keep_tried = true;
        if (!make_keep_pipeline()) {
            rt_log("vr: the depth stereo's depth copy could not be made: one picture to both eyes");
            x.keep_pipe = VK_NULL_HANDLE;
        }
    }
    if (!x.keep_pipe) return;
    bool fresh = false;
    if (!x.depth || x.depth_w != w || x.depth_h != h) {
        x.depth = VK_NULL_HANDLE, x.depth_kept = 0;   // (another size's is left behind, as the scene's)
        x.rows = VK_NULL_HANDLE;
        if (!make_image(w, h, VK_FORMAT_R32_SFLOAT, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, x.depth, x.depth_view) ||
            !make_buffer(8ull * h, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT, x.rows)) {
            rt_log("vr: the depth stereo's depth image %ux%u could not be made: one picture to both eyes", w, h);
            x.keep_pipe = VK_NULL_HANDLE;
            return;
        }
        x.depth_w = w, x.depth_h = h, fresh = true;
        rt_log("vr: depth stereo keeps the scene's depth: %ux%u", w, h);
    }
    barrier(cb, x.depth, fresh ? VK_IMAGE_LAYOUT_UNDEFINED : VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
    vkCmdFillBuffer(cb, x.rows, 0, 4ull * h, 0x7f800000u);   // each row's least: +inf
    vkCmdFillBuffer(cb, x.rows, 4ull * h, 4ull * h, 0);      // its greatest: 0
    memory_barrier(cb);
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.keep_pipe);
    const VkDescriptorImageInfo info[2] = {{x.keep_sampler, depth, VK_IMAGE_LAYOUT_GENERAL},
                                           {VK_NULL_HANDLE, x.depth_view, VK_IMAGE_LAYOUT_GENERAL}};
    const VkDescriptorBufferInfo rows{x.rows, 0, 8ull * h};
    VkWriteDescriptorSet wr[3]{};
    for (uint32_t i = 0; i < 3; i++) {
        wr[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, wr[i].dstBinding = i, wr[i].descriptorCount = 1;
        wr[i].descriptorType = i == 2 ? VK_DESCRIPTOR_TYPE_STORAGE_BUFFER
                               : i ? VK_DESCRIPTOR_TYPE_STORAGE_IMAGE : VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        if (i == 2) wr[i].pBufferInfo = &rows;
        else wr[i].pImageInfo = &info[i];
    }
    vkCmdPushDescriptorSetKHR(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.keep_layout, 0, 3, wr);
    // (which way is nearer in the stored depth, from the scene's projection: d = a + b / distance, so nearer is greater
    // when b > 0; not known yet: the shader keeps the depth as it is)
    float planes[2];
    const float nearer = vk_xr_planes(planes) && planes[1] != 0 ? (planes[1] > 0 ? 1.0f : -1.0f) : 0.0f;
    struct { int32_t w, h; float nearer; } pc = {(int32_t)w, (int32_t)h, nearer};
    vkCmdPushConstants(cb, x.keep_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
    vkCmdDispatch(cb, (w + 7) / 8, (h + 7) / 8, 1);
    memory_barrier(cb);
    x.depth_kept++;
    x.depths_kept++;
}

extern "C" int vk_xr_head_active(void) {
    Xr &x = xr();
    return x.ok && x.head_view.load(std::memory_order_relaxed) && x.running.load(std::memory_order_relaxed);
}

extern "C" int vk_xr_pad(uint64_t *buttons, int32_t left[2], int32_t right[2]) {
    Xr &x = xr();
    if (!x.ok || !x.running.load()) return 0;
    uint64_t bits;
    float sticks[2][2];
    {
        std::lock_guard<std::mutex> lk(x.hands_mu);
        if (!x.hands_at || plat_now_ns() - x.hands_at > 250000000ull) return 0;   // not read for a while: not focused
        bits = x.hand_buttons;
        std::memcpy(sticks, x.hand_sticks, sizeof sticks);
    }
    if (x.ocarina.load()) sticks[1][0] = sticks[1][1] = 0, right[0] = right[1] = 0;   // the right stick plays the notes
    int used = bits != 0;
    int32_t *out[2] = {left, right};
    for (int h = 0; h < 2; h++) {   // a small dead zone, then the stick farther out of the two (the gamepad's or this)
        const float m = std::sqrt(sticks[h][0] * sticks[h][0] + sticks[h][1] * sticks[h][1]);
        if (m < 0.12f) continue;
        const float k = std::fmin(1.0f, (m - 0.12f) / 0.88f) / m;
        const int32_t sx = (int32_t)(sticks[h][0] * k * 32767.0f), sy = (int32_t)(sticks[h][1] * k * 32767.0f);
        if ((int64_t)sx * sx + (int64_t)sy * sy > (int64_t)out[h][0] * out[h][0] + (int64_t)out[h][1] * out[h][1])
            out[h][0] = sx, out[h][1] = sy;
        used = 1;
    }
    *buttons |= bits;
    return used;
}


extern "C" void vk_xr_ocarina(int on) { xr().ocarina.store(on != 0); }

extern "C" void vk_xr_weapon_out(int out) { xr().weapon_out.store(out != 0); }
extern "C" void vk_xr_two_handed_sword(int on) { xr().two_handed_sword.store(on != 0); }
extern "C" void vk_xr_game_paused(int on) { xr().game_paused.store(on != 0); }
extern "C" void vk_xr_turning(float strength) { g_turning.store(strength), g_turning_at.store(plat_now_ns()); }
extern "C" void vk_xr_rumble(int side, float strength) { g_rumble[side & 1].store(strength), g_rumble_at[side & 1].store(plat_now_ns()); }
// ((Triforce VR) vr_body.c: Link's arms as the game's animation has them now, not on the controllers: the bow or the slingshot
// drawn (its ZR), the hammer's swing
extern "C" int vk_xr_arms_own(void) {
    const uint64_t swung = g_hammer_swung.load();
    return g_draw_on.load() || (swung && plat_now_ns() - swung < kHammerSwingNs);
}
extern "C" void vk_xr_child(int child) { xr().child.store(child != 0); }

extern "C" void vk_xr_in_play(int on) { xr().in_play.store(on != 0); }

extern "C" void vk_xr_scene_camera(const float r[12]) {
    Xr &x = xr();
    double at[3];   // the camera's place: -R^T t
    for (int c = 0; c < 3; c++) at[c] = -(r[c] * r[3] + r[4 + c] * r[7] + r[8 + c] * r[11]);
    if (!std::isfinite(at[0]) || !std::isfinite(at[1]) || !std::isfinite(at[2])) return;
    std::lock_guard<std::mutex> lk(x.frame_mu);
    std::memcpy(x.scene_at, at, sizeof at), x.scene_new = true;
}

extern "C" void vk_xr_aim_freeze(int on) {
    Xr &x = xr();
    std::lock_guard<std::mutex> lk(x.frame_mu);
    x.aim_freeze = on != 0;
}

extern "C" int vk_xr_pointer(double dir[3]) {
    Xr &x = xr();
    Pose g;
    {
        std::lock_guard<std::mutex> lk(x.hands_mu);
        const int held = g_item_hand.load(), sword = held >= 0 ? held : sword_hand_now();   // (the hand that pulled the item out)
        // (an item the gamepad took out: aimed with the pad, not steered by a hand controller lying anywhere)
        if (held < 0 && !g_draw_on.load()) return 0;
        if (!x.hands_at || plat_now_ns() - x.hands_at > 250000000ull) return 0;
        if (x.aim_ok[sword]) g = x.aim_pose[sword];   // its own pointing ray; else the grip's
        else if (x.grip_ok[sword]) g = x.grip[sword];
        else return 0;
    }
    // where the controller points, in the LOCAL space (x right, y up, z back): its aim pose's -z tilted down by
    // VR_AIM_TILT degrees (35 by default, found right for the Quest's Touch controllers)
    const float tilt = (float)cfg_int("VR_AIM_TILT") * 3.14159265f / 180.0f;
    const float ahead[3] = {0, -std::sin(tilt), -std::cos(tilt)};
    float v[3];
    rotate(g.q, ahead, v);
    if (g_draw_on.load()) {   // ((Triforce VR) the bow's or slingshot's draw: from the drawing hand to the holding hand)
        std::lock_guard<std::mutex> lk(x.hands_mu);
        std::memcpy(v, g_draw_dir, sizeof v);
    }
    if (g_gaze_aim.load()) {   // ((Triforce VR) the boomerang: where the head looks, the middle of the view
        std::lock_guard<std::mutex> lk(x.head_mu);
        if (!x.have_head) return 0;
        static const float ahead_of_head[3] = {0, 0, -1};
        rotate(x.head.q, ahead_of_head, v);
    }
    {   // ((Triforce VR) a shot just now: the way from just before it (g_shot_at)
        static std::mutex mu;
        static struct { uint64_t at; float v[3]; } past[64];
        static int head;
        std::lock_guard<std::mutex> lk(mu);
        const uint64_t now = plat_now_ns(), shot = g_shot_at.load();
        if (shot && now - shot < kShotHoldNs) {
            const uint64_t want = shot - kShotBeforeNs;
            int best = -1;
            for (int i = 0; i < 64; i++)
                if (past[i].at && past[i].at <= want && (best < 0 || past[i].at > past[best].at)) best = i;
            if (best >= 0) std::memcpy(v, past[best].v, sizeof v);
        } else {
            head = (head + 1) % 64;
            past[head].at = now, std::memcpy(past[head].v, v, sizeof v);
        }
    }
    double bx, bz;
    {
        std::lock_guard<std::mutex> lk(x.frame_mu);
        bx = x.cur_bx, bz = x.cur_bz;
    }
    dir[0] = bz * v[0] + bx * v[2], dir[1] = v[1], dir[2] = -bx * v[0] + bz * v[2];
    return 1;
}

extern "C" int vk_xr_hands(double pos[6], double point[6], double palm[6]) {
    Xr &x = xr();
    if (!x.ok || !x.running.load(std::memory_order_relaxed)) return 0;
    Pose g[2];
    bool ok[2];
    {
        std::lock_guard<std::mutex> lk(x.hands_mu);
        if (!x.hands_at || plat_now_ns() - x.hands_at > 250000000ull) return 0;
        for (int h = 0; h < 2; h++) g[h] = x.grip[h], ok[h] = x.grip_ok[h];
    }
    double base[3], bx, bz;
    {   // the mapping vk_xr_camera put the head on: the camera's place before the head's offset, its level yaw
        std::lock_guard<std::mutex> lk(x.frame_mu);
        if (!x.frame_on || !x.drawn.tracked) return 0;
        std::memcpy(base, x.drawn.base, sizeof base), bx = x.drawn.bx, bz = x.drawn.bz;
    }
    const double axes[3][3] = {{bz, 0, -bx}, {0, 1, 0}, {bx, 0, bz}};   // right, up, back in the world
    const auto world = [&](const float v[3], double *out) {
        for (int c = 0; c < 3; c++) out[c] = axes[0][c] * v[0] + axes[1][c] * v[1] + axes[2][c] * v[2];
    };
    int any = 0;
    for (int h = 0; h < 2; h++) {
        if (!ok[h]) {
            for (int c = 0; c < 3; c++) pos[h * 3 + c] = point[h * 3 + c] = palm[h * 3 + c] = 0;
            continue;
        }
        static const float ahead[3] = {0, 0, -1};
        const float out_of_palm[3] = {h ? -1.0f : 1.0f, 0, 0};
        float pt[3], pa[3];
        rotate(g[h].q, ahead, pt), rotate(g[h].q, out_of_palm, pa);
        world(g[h].p, pos + h * 3);
        for (int c = 0; c < 3; c++) pos[h * 3 + c] += base[c];
        world(pt, point + h * 3), world(pa, palm + h * 3);
        any = 1;
    }
    return any;
}

extern "C" void vk_xr_hand_item(const char *model) {
    Xr &x = xr();
    std::lock_guard<std::mutex> lk(x.gear_mu);
    std::snprintf(x.held_item, sizeof x.held_item, "%s", model);
}


extern "C" void vk_xr_aim(int on, const double origin[3], const double dir[3]) {
    Xr &x = xr();
    std::lock_guard<std::mutex> lk(x.frame_mu);
    x.aim_on = on != 0;
    if (on) std::memcpy(x.aim_o, origin, sizeof x.aim_o), std::memcpy(x.aim_d, dir, sizeof x.aim_d);
}


extern "C" int vk_xr_holds_time(void) {
    Xr &x = xr();
    return stereo_balanced() && x.ok && x.head_view.load(std::memory_order_relaxed) &&
           x.running.load(std::memory_order_relaxed);
}

extern "C" void vk_xr_update_step(double seconds) { update_step.store(seconds, std::memory_order_relaxed); }

extern "C" int vk_xr_camera(double pos[3], double at[3], float up[3], int in_place) {
    Xr &x = xr();
    {   // ((Triforce VR) the Turn vignette's motion: the eyes' speed through the world in first person (in_place), over the last
        // update: none below 0.3 m/s, all from 3 m/s (a run), more than that saturating; a jump of over a metre (a load, a
        // teleport) is no motion
        static double was[3];
        static uint64_t was_at;
        const uint64_t now = plat_now_ns();
        float m = 0.0f;
        if (in_place && was_at && now > was_at) {
            const double dt = (now - was_at) * 1e-9;
            const double d = std::sqrt((pos[0] - was[0]) * (pos[0] - was[0]) + (pos[1] - was[1]) * (pos[1] - was[1]) +
                                       (pos[2] - was[2]) * (pos[2] - was[2]));
            if (dt > 0.001 && dt < 0.5 && d < 1.0) m = (float)std::fmin(1.0, std::fmax(0.0, (d / dt - 0.3) / 2.7));
        }
        std::memcpy(was, pos, sizeof was), was_at = in_place ? now : 0;
        g_moving.store(m);
    }
    if (!x.ok || !x.head_view.load(std::memory_order_relaxed) || !x.running.load(std::memory_order_relaxed)) {
        vk_xr_untracked();
        return 0;
    }
    Pose head;
    Lens eyes;
    float ipd;
    {
        std::lock_guard<std::mutex> lk(x.head_mu);
        if (!x.have_head) return 0;
        head = x.head, eyes = x.eyes;
        ipd = x.ipd;
    }
    // the camera's facing made level (its yaw alone, so the horizon stays level whatever the game's camera does): the
    // head's axes are put on it, x right, y up, z back as OpenXR's
    double f[3] = {at[0] - pos[0], at[1] - pos[1], at[2] - pos[2]};
    const double reach = std::sqrt(f[0] * f[0] + f[1] * f[1] + f[2] * f[2]);
    const double flat = std::sqrt(f[0] * f[0] + f[2] * f[2]);
    if (!(reach > 1e-6) || !(flat > 1e-6)) return 0;
    double bx = -f[0] / flat, bz = -f[2] / flat;
    {
        std::lock_guard<std::mutex> lk(x.frame_mu);
        if (x.aim_freeze) {
            if (!x.frozen_ok) x.frozen_bx = bx, x.frozen_bz = bz, x.frozen_ok = true;
            bx = x.frozen_bx, bz = x.frozen_bz;
        } else x.frozen_ok = false;
        x.cur_bx = bx, x.cur_bz = bz;
    }
    const double axes[3][3] = {{bz, 0, -bx}, {0, 1, 0}, {bx, 0, bz}};   // right, up, back in the world
    const auto world = [&](const float v[3], double out[3]) {
        for (int c = 0; c < 3; c++) out[c] = axes[0][c] * v[0] + axes[1][c] * v[1] + axes[2][c] * v[2];
    };
    static const float ahead[3] = {0, 0, -1}, upward[3] = {0, 1, 0}, rightward[3] = {1, 0, 0};
    float hf[3], hu[3], hr[3];
    rotate(head.q, ahead, hf), rotate(head.q, upward, hu), rotate(head.q, rightward, hr);
    if (in_place) {   // ((Triforce VR) Link's eyes: the view stays on them wherever the headset is, turned by it alone; the base
                      // moved back by the headset's place, so the hands (vk_xr_hands) keep theirs about the head)
        double place[3];
        world(head.p, place);
        for (int c = 0; c < 3; c++) pos[c] -= place[c];
    }
    // Stereo Balanced: this picture from one eye, the other the next (eyes in turn): the head moved half the eyes'
    // distance (VR_DEPTH percent of it, as depth stereo's) to that eye's side, the game's camera with it
    int eye = -1;
    if (stereo_accurate()) {   // the left eye's place; the renderer's second pass moves the camera on to the right's
        const float shift = ipd * 0.01f * (float)cfg_int("VR_DEPTH");
        for (int c = 0; c < 3; c++) head.p[c] -= 0.5f * shift * hr[c];
        x.acc_shift.store(shift, std::memory_order_relaxed);
        eye = 0;
    } else if (stereo_turns()) {
        {
            std::lock_guard<std::mutex> lk(x.frame_mu);
            const double step = update_step.load(std::memory_order_relaxed);
            if (step > 0) x.turn = step < 0.006 ? 1 : 0;   // the held update draws the right eye
            eye = x.turn, x.turn ^= 1;
        }
        const float strength = 0.01f * (float)cfg_int("VR_DEPTH");
        for (int c = 0; c < 3; c++) head.p[c] += (eye ? 0.5f : -0.5f) * ipd * strength * hr[c];
    }
    double wf[3], wu[3], wp[3], wr[3];
    world(hf, wf), world(hu, wu), world(head.p, wp), world(hr, wr);
    double base[3] = {pos[0], pos[1], pos[2]};
    for (int c = 0; c < 3; c++) {
        pos[c] += wp[c];
        at[c] = pos[c] + wf[c] * reach;
        up[c] = (float)wu[c];
    }
    std::lock_guard<std::mutex> lk(x.frame_mu);
    x.frame_on = true;
    x.drawn.tracked = true, x.drawn.pose = head, x.drawn.lens = frustum(eyes, x.picture_ratio.load());
    x.drawn.eye = eye;
    std::memcpy(x.drawn.base, base, sizeof base), x.drawn.bx = bx, x.drawn.bz = bz;
    x.drawn.aim = x.aim_on;
    if (x.aim_on) {   // the aim's ray in the view: right, up and back (-forward)
        double o[3];
        for (int c = 0; c < 3; c++) o[c] = x.aim_o[c] - pos[c];
        const double *axis[3] = {wr, wu, wf};
        for (int k = 0; k < 3; k++) {
            const double sign = k == 2 ? -1.0 : 1.0;
            x.drawn.aim_o[k] = (float)(sign * (o[0] * axis[k][0] + o[1] * axis[k][1] + o[2] * axis[k][2]));
            x.drawn.aim_d[k] = (float)(sign * (x.aim_d[0] * axis[k][0] + x.aim_d[1] * axis[k][1] + x.aim_d[2] * axis[k][2]));
        }
    }
    // the game draws a lens this many times the one the headset is told (VR_VIEW_SCALE, 100 % by default: the
    // headset's own): more of the world in the same view, everything smaller above 100 %
    x.render_scale = std::fmax(0.5f, std::fmin(2.0f, (float)cfg_int("VR_VIEW_SCALE") / 100.0f));
    x.drawn.scale = x.render_scale, x.drawn.ipd = ipd;
    x.camera_given++;
    Xr::Given &g = x.given[x.given_next++ % 6];
    g.d = x.drawn, g.used = true;
    for (int c = 0; c < 3; c++) g.at[c] = pos[c];
    x.updates++;
    return 1;
}

extern "C" int vk_xr_lens(float *angle) {
    Xr &x = xr();
    std::lock_guard<std::mutex> lk(x.frame_mu);
    if (!x.frame_on) return 0;
    *angle = 2.0f * std::atan(x.drawn.lens.u * x.render_scale);
    x.lens_given++;
    return 1;
}

extern "C" void vk_xr_untracked(void) {
    Xr &x = xr();
    std::lock_guard<std::mutex> lk(x.frame_mu);
    x.frame_on = false;
    x.drawn.tracked = false;
}

extern "C" VkImage vk_xr_scene_image(VkImage target, uint32_t w, uint32_t h, VkFormat format, int *init) {
    Xr &x = xr();
    *init = 0;
    const bool vr = x.ok && x.head_view.load(std::memory_order_relaxed);
    if (!(vr || flat_on()) || !target || !w || !h) return VK_NULL_HANDLE;
    // other pictures pass through the upscaler too (a 2560x1440 sRGB one): only the one of the presented picture's size
    // is the scene the HUD is drawn over
    if (w != x.pic_w.load(std::memory_order_relaxed) || h != x.pic_h.load(std::memory_order_relaxed)) return VK_NULL_HANDLE;
    std::lock_guard<std::mutex> lk(x.hud_mu);
    if (x.hud_tried && !x.hud_pipe) return VK_NULL_HANDLE;   // the panel could not be made: the HUD stays in the picture
    if (!x.scene || x.hud_w != w || x.hud_h != h || x.hud_format != format) {
        // (images of another size are left behind: the picture's size changes rarely, at a setting)
        x.scene = x.scene8 = x.panel8 = x.layer = VK_NULL_HANDLE, x.used = x.kept;
        if (!make_image(w, h, format, VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, x.scene, x.scene_view)) {
            static int told_fail;
            if (told_fail++ < 4) rt_log("vr: the HUD panel's scene image %ux%u format %d could not be made", w, h, (int)format);
            x.scene = VK_NULL_HANDLE;
            return VK_NULL_HANDLE;
        }
        rt_log("vr: the HUD panel keeps the scene: %ux%u format %d", w, h, (int)format);
        x.hud_w = w, x.hud_h = h, x.hud_format = format;
        *init = 1;
    }
    if (x.second_now) {   // (Stereo Accurate: the right eye's pass, its scene apart)
        if (!x.scene_r && !make_image(w, h, format, VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, x.scene_r, x.scene_r_view))
            return VK_NULL_HANDLE;
        if (!x.scene_r) return VK_NULL_HANDLE;
        static bool told;
        if (!told) told = true, *init = 1;
        return x.scene_r;
    }
    x.hud_target = target;
    x.kept++;
    x.scenes_kept++;
    return x.scene;
}

extern "C" VkImageView vk_xr_hud_layer(VkImage *image, int *init) {
    Xr &x = xr();
    std::lock_guard<std::mutex> lk(x.hud_mu);
    *init = 0;
    static const bool on = !(getenv("RX_VK_XR_HUD_LAYER") && atoi(getenv("RX_VK_XR_HUD_LAYER")) == 0);
    static bool failed;
    if (!on || failed || !x.scene || !x.hud_w) return VK_NULL_HANDLE;
    if (!x.layer) {
        if (!make_image(x.hud_w * 2, x.hud_h, x.hud_format, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, x.layer, x.layer_view)) {
            x.layer = VK_NULL_HANDLE, failed = true;
            rt_log("vr: the HUD's own layer could not be made: the panel is what the HUD changed, as before");
            return VK_NULL_HANDLE;
        }
        rt_log("vr: the HUD's own layer: %ux%u format %d", x.hud_w * 2, x.hud_h, (int)x.hud_format);
        *init = 1;
    }
    *image = x.layer;
    return x.layer_view;
}

extern "C" int vk_xr_item_bar_open(void) { return xr().item_bar.load(std::memory_order_relaxed); }
extern "C" void vk_xr_item_bar(int open) { xr().item_bar.store(open != 0); }
extern "C" int vk_xr_item_bar_layer(VkImage target, uint32_t w, uint32_t h) {
    Xr &x = xr();
    std::lock_guard<std::mutex> lk(x.hud_mu);
    if (!x.layer || x.hud_target != target || x.hud_w != w || x.hud_h != h) return 0;
    x.bar_drawn.store(true);
    return 1;
}

// Stereo Accurate: the right eye's pass begins (phase 1: the left eye's target, picture and HUD, copied apart first) or ends (0)
extern "C" void vk_xr_second_eye(VkCommandBuffer cb, int phase) {
    Xr &x = xr();
    std::lock_guard<std::mutex> lk(x.hud_mu);
    if (!phase) {
        x.acc_ready = x.second_now && x.target_l && x.scene_r;
        x.second_now = false;
        return;
    }
    x.second_now = false, x.acc_ready = false;
    if (!x.hud_target || !x.scene || !x.hud_w) return;
    if (!x.target_l && !make_image(x.hud_w, x.hud_h, x.hud_format, VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                                   x.target_l, x.target_l_view))
        return;
    VkMemoryBarrier2 mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER_2};
    mb.srcStageMask = mb.dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    mb.srcAccessMask = mb.dstAccessMask = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT;
    VkDependencyInfo dep{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    dep.memoryBarrierCount = 1, dep.pMemoryBarriers = &mb;
    static bool laid;
    if (!laid) {
        laid = true;
        barrier(cb, x.target_l, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
    }
    vkCmdPipelineBarrier2(cb, &dep);
    VkImageCopy c{};
    c.srcSubresource = c.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    c.extent = {x.hud_w, x.hud_h, 1};
    vkCmdCopyImage(cb, x.hud_target, VK_IMAGE_LAYOUT_GENERAL, x.target_l, VK_IMAGE_LAYOUT_GENERAL, 1, &c);
    vkCmdPipelineBarrier2(cb, &dep);
    x.second_now = true;
}

// Stereo Balanced: the eyes drawn in turn, so the frame before's camera (which the game's temporal passes reproject from) is the
// other eye's: how far to move it onto this picture's eye, metres along its right (+ for the right eye's picture), 0 not now
extern "C" float vk_xr_balanced_prev_shift(void) {
    Xr &x = xr();
    if (!stereo_balanced() || !x.ok || !x.head_view.load(std::memory_order_relaxed) || !x.running.load(std::memory_order_relaxed))
        return 0.0f;
    std::lock_guard<std::mutex> lk(x.frame_mu);
    if (x.drawn.eye < 0) return 0.0f;
    const float shift = x.drawn.ipd * 0.01f * (float)cfg_int("VR_DEPTH");
    return x.drawn.eye == 1 ? shift : -shift;
}

// Stereo Accurate: how far right of the left eye the right eye's camera is, metres (0: not now)
extern "C" float vk_xr_accurate_shift(void) {
    Xr &x = xr();
    return stereo_accurate() && x.ok && x.head_view.load(std::memory_order_relaxed) && x.running.load(std::memory_order_relaxed)
               ? x.acc_shift.load(std::memory_order_relaxed) : 0.0f;
}

extern "C" int vk_xr_menu_buttons(uint64_t *buttons, float sticks[2][2]) {
    Xr &x = xr();
    if (!x.ok || !x.running.load()) return 0;
    std::lock_guard<std::mutex> lk(x.hands_mu);
    if (!x.hand_menu) return 0;
    *buttons = x.hand_buttons;
    std::memcpy(sticks, x.hand_sticks, sizeof x.hand_sticks);
    return 1;
}

extern "C" void vk_xr_note_upscale(int taken) { xr().upscales++; if (taken) xr().upscales_vr++; }

extern "C" int vk_xr_wants_capture(int hdr) {
    Xr &x = xr();
    if (!x.ok || !x.timeline) return 0;
    const bool head = vk_xr_head_wanted();
    // (this menu over the game's own Options screen stays in the head's view, the game's paused picture on the HUD panel;
    // (Triforce VR) a movie on the floating screen)
    x.head_view.store(head && (!menu_is_open() || menu_embedded()) && !mkwvk::pace::movie_playing(), std::memory_order_relaxed);
    if (hdr) {
        static bool told;
        if (!told) told = true, rt_log("vr: the headset needs HDR off");
        return 0;
    }
    if (!x.ready.load(std::memory_order_acquire)) return 1;   // the window's size is still to be learned (vk_xr_capture)
    if (x.boxes_failed) return 0;
    std::lock_guard<std::mutex> lk(x.mu);
    for (int i = 0; i < 3; i++)
        if (i != x.reading && i != x.latest) return 1;
    return 0;
}

void desat_right(VkCommandBuffer cb);

extern "C" void vk_xr_capture(VkCommandBuffer cb, VkImage window, VkExtent2D extent, VkFormat format, VkImage picture,
                              VkImageLayout picture_layout, const int rect[4], VkSemaphoreSubmitInfo *signal) {
    Xr &x = xr();
    *signal = VkSemaphoreSubmitInfo{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO};
    if (!extent.width || !extent.height) return;
    const bool have_picture = picture && rect[2] > 0 && rect[3] > 0;
    if (have_picture) {
        x.picture_ratio.store((float)rect[2] / (float)rect[3], std::memory_order_relaxed);
        x.pic_w.store((uint32_t)rect[2], std::memory_order_relaxed), x.pic_h.store((uint32_t)rect[3], std::memory_order_relaxed);
    }
    // the swapchain at the game's picture's size (the head's view shows it over the eyes' whole view, every pixel
    // counts); the boot screen before it, which has none, is not shown
    if (!x.want_w.load() && have_picture) x.want_h.store((uint32_t)rect[3]), x.want_w.store((uint32_t)rect[2]);
    if (!x.ready.load(std::memory_order_acquire)) return;
    if (!x.boxes_made) {
        x.boxes_made = make_boxes(format);
        x.boxes_failed = !x.boxes_made;
        if (!x.boxes_made) return;
    }
    int slot = -1;
    {
        std::lock_guard<std::mutex> lk(x.mu);
        for (int i = 0; i < 3 && slot < 0; i++) {
            const int c = (x.next_slot + i) % 3;
            if (c != x.reading && c != x.latest) slot = c;
        }
        if (slot < 0) return;
        x.next_slot = (slot + 1) % 3;
    }
    // the head's view: the game's picture (without the window's menu, which the screen shows) with the pose the last
    // gameplay camera update put on it; else the window for the screen
    Drawn d;
    x.stale = x.updates.exchange(0) ? 0 : x.stale + 1;
    x.moving = x.stale ? 0 : x.moving + 1;
    if (x.moving > 60) x.item_bar.store(false);   // (play goes on: the bar is closed, however it went)
    const bool head = x.head_view.load(std::memory_order_relaxed) && have_picture;
    if (head && x.stale < 3) {
        std::lock_guard<std::mutex> lk(x.frame_mu);
        d = x.drawn;
        if (x.scene_new) {   // the camera update this picture was drawn from: the one whose place the scene's camera had
            double best = 1e30;
            for (const auto &g : x.given) {
                if (!g.used) continue;
                double e2 = 0;
                for (int c = 0; c < 3; c++) e2 += (g.at[c] - x.scene_at[c]) * (g.at[c] - x.scene_at[c]);
                if (e2 < best) best = e2, d = g.d;
            }
            x.scene_new = false;
        }
    }
    if (!head) x.frozen.tracked = false;
    if (head && x.stale >= 3 && x.frozen.tracked) {   // paused: the frozen world, and the game's picture on the HUD's panel
        d = x.frozen;
        d.hud = false, d.menu = true;
        x.box_drawn[slot] = d;
        x.menu_pictures++;
        VkImageBlit b{};
        b.srcSubresource = b.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
        b.dstOffsets[1] = {(int32_t)x.width, (int32_t)x.height, 1};
        {
            std::lock_guard<std::mutex> lk(x.hud_mu);
            b.srcOffsets[1] = {(int32_t)x.hud_w, (int32_t)x.hud_h, 1};
            for (int e = 0; e < (d.stereo ? 2 : 1); e++) {
                const VkImage bx = e ? x.boxes_r[slot] : x.boxes[slot];
                barrier(cb, bx, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
                vkCmdBlitImage(cb, d.stereo ? eye_image(d, e) : x.scene8, VK_IMAGE_LAYOUT_GENERAL, bx,
                               VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
                barrier(cb, bx, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
            }
        }
        const VkImage hb = x.hud_boxes[slot];
        barrier(cb, hb, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        // this menu open over the game's Options screen, or that screen on its own tab with ours drawn over its header: the
        // window's picture, with them ((Triforce VR) at once, not only after L or R opens one of ours)
        bool bar = x.bar_drawn.exchange(false) && x.item_bar.load() && !menu_embedded();
        if (bar) {   // the item bar, apart from its background
            std::lock_guard<std::mutex> lk(x.hud_mu);
            bar = x.layer && make_panel(cb, 0, VK_NULL_HANDLE, VK_NULL_HANDLE, true);
            b.srcOffsets[0] = {0, 0, 0};
            b.srcOffsets[1] = {(int32_t)x.hud_w, (int32_t)x.hud_h, 1};
            if (bar) vkCmdBlitImage(cb, x.panel8, VK_IMAGE_LAYOUT_GENERAL, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
        }
        if (bar) {
        } else if (menu_embedded() || mkwvk::menu_game_options()) {
            int wr[4];
            gfx_fit_rect(rect[2], rect[3], (int)extent.width, (int)extent.height, wr);
            b.srcOffsets[0] = {wr[0], wr[1], 0};
            b.srcOffsets[1] = {wr[0] + wr[2], wr[1] + wr[3], 1};
            vkCmdBlitImage(cb, window, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                           VK_FILTER_LINEAR);
        } else {
            b.srcOffsets[0] = {rect[0], rect[1], 0};
            b.srcOffsets[1] = {rect[0] + rect[2], rect[1] + rect[3], 1};
            vkCmdBlitImage(cb, picture, picture_layout, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
        }
        barrier(cb, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        overlay_onto_hud(cb, slot, window, extent, d);
        x.pending = slot;
        signal->semaphore = x.timeline;
        signal->value = ++x.next_value;
        signal->stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
        return;
    }
    // the HUD apart and depth stereo (VR_DEPTH) start from the scene kept before the HUD:
    // the head's view without the HUD (with it where it stays in the picture), the HUD on its panel, each eye's picture
    const bool depth = d.tracked && vk_xr_depth_wanted();
    bool made = false;
    uint32_t hw = 0, hh = 0;
    if (d.tracked) {
        std::lock_guard<std::mutex> lk(x.hud_mu);
        const bool pair = d.eye == 0 && stereo_accurate() && x.acc_ready;   // (Accurate: the left eye's target as its pass left it)
        made = make_panel(cb, d.aim ? (int)(0.06f * (float)x.hud_h) : 0, pair ? x.target_l_view : VK_NULL_HANDLE);
        hw = x.hud_w, hh = x.hud_h;
        if (made) make_aim(cb, d);
        if (made && depth && d.eye < 0) d.stereo = make_eyes(cb, d);
        if (made && d.eye >= 0) keep_eye(cb, d);   // Balanced: this eye's picture kept, both shown once both are
        // Accurate: the left eye's panel was made from the scene and the target as the left eye's pass left it (target_l);
        // the right eye's now, from its pass's scene and the target as it is, kept as eye 1: the pair shown at once
        if (made && d.eye == 0 && stereo_accurate() && x.acc_ready) {
            Drawn r = d;
            r.eye = 1;
            static const float right[3] = {1, 0, 0};
            float hr2[3];
            rotate(d.pose.q, right, hr2);
            const float shift = x.acc_shift.load(std::memory_order_relaxed);
            for (int c = 0; c < 3; c++) r.pose.p[c] += shift * hr2[c];
            if (make_panel(cb, d.aim ? (int)(0.06f * (float)x.hud_h) : 0, x.target_view, x.scene_r_view)) {
                desat_right(cb);   // (its colours down to the left eye's)
                keep_eye(cb, r);
                d = r;
            }
            x.acc_ready = false;
        }
    }
    d.hud = made;
    if (d.tracked && made) x.frozen = d;   // its world stays in scene8 and eye8 until the next one made
    x.box_drawn[slot] = d;
    if (d.tracked) x.tracked_pictures++;
    const VkImage box = x.boxes[slot];
    barrier(cb, box, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkImageBlit b{};
    b.srcSubresource = b.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    b.dstOffsets[1] = {(int32_t)x.width, (int32_t)x.height, 1};
    if (made) {
        b.srcOffsets[1] = {(int32_t)hw, (int32_t)hh, 1};
        vkCmdBlitImage(cb, d.stereo ? eye_image(d, 0) : x.scene8, VK_IMAGE_LAYOUT_GENERAL, box,
                       VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
        if (d.stereo) {
            const VkImage rb = x.boxes_r[slot];
            barrier(cb, rb, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
            vkCmdBlitImage(cb, eye_image(d, 1), VK_IMAGE_LAYOUT_GENERAL, rb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                           VK_FILTER_LINEAR);
            barrier(cb, rb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        }
        if (d.hud) {
            const VkImage hb = x.hud_boxes[slot];
            barrier(cb, hb, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
            vkCmdBlitImage(cb, x.panel8, VK_IMAGE_LAYOUT_GENERAL, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
            barrier(cb, hb, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        }
    } else if (d.tracked) {
        b.srcOffsets[0] = {rect[0], rect[1], 0};
        b.srcOffsets[1] = {rect[0] + rect[2], rect[1] + rect[3], 1};
        vkCmdBlitImage(cb, picture, picture_layout, box, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
    } else {
        b.srcOffsets[1] = {(int32_t)extent.width, (int32_t)extent.height, 1};
        vkCmdBlitImage(cb, window, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, box, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                       VK_FILTER_LINEAR);
    }
    barrier(cb, box, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    if (d.tracked) {
        overlay_onto_hud(cb, slot, window, extent, d);
        x.box_drawn[slot] = d;
        if (have_picture) {   // last: the headset's copies are made
            std::lock_guard<std::mutex> lk(x.hud_mu);
            if (d.stereo && strcmp(cfg_value("FLAT3D"), "off") && window_vr_3d(cb, window, extent, rect, d)) {}
            else if (d.stereo && !strcmp(cfg_value("FLAT3D"), "cardboard")) window_both_eyes(cb, window, extent, rect, d);
            else if (d.eye >= 0 && !stereo_accurate()) window_left_eye(cb, window, extent, format, rect, d.eye);
            else x.win_left_have = false;   // (Accurate shows both eyes at once: nothing to hold between presents)
        }
    }
    x.pending = slot;
    signal->semaphore = x.timeline;
    signal->value = ++x.next_value;
    signal->stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
}

extern "C" void vk_xr_captured(const VkSemaphoreSubmitInfo *signal) {
    Xr &x = xr();
    if (!signal->semaphore || x.pending < 0) return;
    std::lock_guard<std::mutex> lk(x.mu);
    x.box_value[x.pending] = signal->value;
    x.latest = x.pending;
    x.pending = -1;
}

// ---- the scene's depth planes, from its projection (vk_temporal.cpp temporal_note_scene_draw): the distances the stored 0
// and 1 stand for, whichever is the near plane (reversed depth), and d = a + b / distance through them. A projection whose near plane is not in front of the camera keeps the last planes.
namespace {
std::atomic<uint64_t> planes_bits{0};   // (planes[0], planes[1] as two floats' bits; 0 none yet)
std::atomic<uint64_t> planes_at{0};     // (plat_now_ns of the last projection)
std::atomic<float> lens_p00{0.0f};       // (its P00: Flatscreen 3D's eyes' moves)

double plane_dist(const float P[16], double k) {
    const double den = P[10] - k * P[14];
    if (std::fabs(den) <= 1e-9 * (std::fabs(P[10]) + std::fabs(P[14]))) return INFINITY;
    return -(k * P[15] - P[11]) / den;
}
}   // namespace

extern "C" void vk_xr_note_projection(const float P[16], int minus_w) {
    const double at0 = plane_dist(P, minus_w ? -1.0 : 0.0), at1 = plane_dist(P, 1.0);
    const bool inverted = !(at0 < at1);
    const double n = inverted ? at1 : at0, f = inverted ? at0 : at1;
    if (!(n > 0) || !std::isfinite(n)) return;
    float planes[2];
    if (!std::isfinite(f) || f > 1e8) planes[0] = inverted ? 0.0f : 1.0f, planes[1] = (float)(inverted ? n : -n);
    else if (inverted) planes[0] = (float)(-n / (f - n)), planes[1] = (float)(n * f / (f - n));
    else planes[0] = (float)(f / (f - n)), planes[1] = (float)(-n * f / (f - n));
    uint64_t bits;
    std::memcpy(&bits, planes, 8);
    planes_bits.store(bits, std::memory_order_relaxed);
    lens_p00.store(P[0], std::memory_order_relaxed);
    planes_at.store(plat_now_ns(), std::memory_order_relaxed);
    static int lines;
    static float logged[2];
    if (lines < 20 && (std::fabs(planes[0] - logged[0]) > 1e-4f * std::fabs(logged[0]) + 1e-9f ||
                       std::fabs(planes[1] - logged[1]) > 1e-4f * std::fabs(logged[1]) + 1e-9f)) {
        lines++, logged[0] = planes[0], logged[1] = planes[1];
        rt_log("vr: the scene's projection: near %.6g, far %.6g, depth %s, clip depth %s", n, f,
               inverted ? "inverted (1 near)" : "0 near, 1 far", minus_w ? "-w..w" : "0..w");
    }
}

extern "C" int vk_xr_planes(float planes[2]) {
    const uint64_t bits = planes_bits.load(std::memory_order_relaxed);
    if (!bits || plat_now_ns() - planes_at.load(std::memory_order_relaxed) > 1000000000ull) return 0;   // (none for a second)
    std::memcpy(planes, &bits, 8);
    return 1;
}

extern "C" int vk_xr_active(void) { return xr().ok && xr().timeline; }
extern "C" void vk_xr_head_worn(int what) { xr().head_worn.store(what); }
extern "C" void vk_xr_carrying(int on) { xr().carrying.store(on != 0); }
extern "C" int vk_xr_head_request(void) { return xr().head_request.exchange(0); }
extern "C" int vk_xr_combo_want(void) { return xr().combo_want.exchange(-1); }
extern "C" void vk_xr_airborne(int on) { xr().airborne.store(on != 0); }
extern "C" void vk_xr_hud_hidden(int hidden) { xr().hud_hidden.store(hidden != 0); }

extern "C" const MkwVkXr *vk_xr_table(void) {
    static const MkwVkXr t = {
        vk_xr_cfg, vk_xr_head_active, vk_xr_camera, vk_xr_lens, vk_xr_holds_time, vk_xr_update_step, vk_xr_pad,
        vk_xr_ocarina, vk_xr_weapon_out, vk_xr_child,
        vk_xr_hand_item, vk_xr_in_play, vk_xr_item_bar, vk_xr_aim_freeze, vk_xr_pointer, vk_xr_aim, vk_xr_untracked, vk_xr_hands,
        vk_xr_active, vk_xr_head_worn, vk_xr_hud_hidden, vk_xr_carrying, vk_xr_head_request, vk_xr_two_handed_sword, vk_xr_arms_own, vk_xr_game_paused, vk_xr_rumble, vk_xr_turning, vk_xr_combo_want, vk_xr_airborne};
    return &t;
}

// Flatscreen 3D's shaders (shaders/xr_flat3d.comp, xr_flat3d_conv.comp): push descriptors, as the others
bool flat_pipeline(const VkDescriptorSetLayoutBinding *b, uint32_t n, uint32_t push, const uint32_t *code, size_t size,
                   VkDescriptorSetLayout &set, VkPipelineLayout &layout, VkPipeline &pipe) {
    Xr &x = xr();
    VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    li.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR, li.bindingCount = n, li.pBindings = b;
    if (vkCreateDescriptorSetLayout(x.device, &li, nullptr, &set) != VK_SUCCESS) return false;
    const VkPushConstantRange pr{VK_SHADER_STAGE_COMPUTE_BIT, 0, push};
    VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    pi.setLayoutCount = 1, pi.pSetLayouts = &set, pi.pushConstantRangeCount = 1, pi.pPushConstantRanges = &pr;
    if (vkCreatePipelineLayout(x.device, &pi, nullptr, &layout) != VK_SUCCESS) return false;
    VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    mi.codeSize = size, mi.pCode = code;
    VkShaderModule m = VK_NULL_HANDLE;
    if (vkCreateShaderModule(x.device, &mi, nullptr, &m) != VK_SUCCESS) return false;
    VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    ci.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, nullptr, 0, VK_SHADER_STAGE_COMPUTE_BIT, m, "main", nullptr};
    ci.layout = layout;
    const VkResult res = vkCreateComputePipelines(x.device, VK_NULL_HANDLE, 1, &ci, nullptr, &pipe);
    vkDestroyShaderModule(x.device, m, nullptr);
    return res == VK_SUCCESS;
}

bool make_flat_pipelines() {
    Xr &x = xr();
    const VkDescriptorSetLayoutBinding fb[5] = {{0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                                {1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                                {2, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                                {3, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                                {4, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}};
    const VkDescriptorSetLayoutBinding cbd[2] = {{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
                                                 {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}};
    return flat_pipeline(fb, 5, 24, XR_FLAT3D_COMP_SPV, sizeof XR_FLAT3D_COMP_SPV, x.flat_set, x.flat_layout, x.flat_pipe) &&
           flat_pipeline(cbd, 2, 28, XR_FLAT3D_CONV_COMP_SPV, sizeof XR_FLAT3D_CONV_COMP_SPV, x.conv_set, x.conv_layout, x.conv_pipe);
}

// (vk_xr_flat3d, hud_mu held, the eyes made) the screen's distance eased, then the window's picture made from the eyes
bool flat_compose(VkCommandBuffer cb, const float shift[2], const float planes[2]) {
    Xr &x = xr();
    if (!x.screen) {
        if (!make_buffer(16, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT, x.screen)) {
            x.screen = VK_NULL_HANDLE;
            return false;
        }
        vkCmdFillBuffer(cb, x.screen, 0, 16, 0);
        memory_barrier(cb);
    }
    if (!x.flat8 || x.flat_w != x.hud_w || x.flat_h != x.hud_h) {   // (another size's is left behind, as the scene's)
        if (!make_image(x.hud_w, x.hud_h, VK_FORMAT_R8G8B8A8_UNORM, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
                        x.flat8, x.flat8_view)) {
            x.flat8 = VK_NULL_HANDLE;
            return false;
        }
        x.flat_w = x.hud_w, x.flat_h = x.hud_h;
        rt_log("flat3d: pictures %ux%u", x.hud_w, x.hud_h);
    }
    // the screen: the nearest thing in the middle rows (the 3DS's way, 0) or FLAT3D_SCREEN cm
    const int cm = cfg_int("FLAT3D_SCREEN");
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.conv_pipe);
    const VkDescriptorBufferInfo rows{x.rows, 0, 8ull * x.depth_h}, scr{x.screen, 0, 16};
    VkWriteDescriptorSet cw[2]{};
    for (uint32_t i = 0; i < 2; i++) {
        cw[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, cw[i].dstBinding = i, cw[i].descriptorCount = 1;
        cw[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, cw[i].pBufferInfo = i ? &scr : &rows;
    }
    vkCmdPushDescriptorSetKHR(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.conv_layout, 0, 2, cw);
    struct {
        int32_t h;
        float a, b, near_inv, far_inv, fixed_inv, rate;
    } cp{(int32_t)x.depth_h, planes[0], planes[1], 1.0f / 1.5f, 1.0f / 30.0f, cm > 0 ? 100.0f / (float)cm : 0.0f, 0.08f};
    vkCmdPushConstants(cb, x.conv_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof cp, &cp);
    vkCmdDispatch(cb, 1, 1, 1);
    memory_barrier(cb);
    const char *m = cfg_value("FLAT3D");
    const int32_t mode = !strcmp(m, "sbs") ? 1 : !strcmp(m, "crosseye") ? 2 : !strcmp(m, "tab") ? 3 : !strcmp(m, "cardboard") ? 4 : 0;
    barrier(cb, x.flat8, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.flat_pipe);
    const VkDescriptorImageInfo info[4] = {{x.linear, x.eye8_view[0], VK_IMAGE_LAYOUT_GENERAL},
                                           {x.linear, x.eye8_view[1], VK_IMAGE_LAYOUT_GENERAL},
                                           {x.linear, x.panel8_view, VK_IMAGE_LAYOUT_GENERAL},
                                           {VK_NULL_HANDLE, x.flat8_view, VK_IMAGE_LAYOUT_GENERAL}};
    VkWriteDescriptorSet w[5]{};
    for (uint32_t i = 0; i < 5; i++) {
        w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, w[i].dstBinding = i, w[i].descriptorCount = 1;
        w[i].descriptorType = i == 4 ? VK_DESCRIPTOR_TYPE_STORAGE_BUFFER
                              : i == 3 ? VK_DESCRIPTOR_TYPE_STORAGE_IMAGE : VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        if (i == 4) w[i].pBufferInfo = &scr;
        else w[i].pImageInfo = &info[i];
    }
    vkCmdPushDescriptorSetKHR(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.flat_layout, 0, 5, w);
    struct {
        int32_t w, h, mode, hud_on;
        float shift_l, shift_r;
    } fp{(int32_t)x.hud_w, (int32_t)x.hud_h, mode, 1, shift[0], shift[1]};
    vkCmdPushConstants(cb, x.flat_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof fp, &fp);
    vkCmdDispatch(cb, (x.hud_w + 7) / 8, (x.hud_h + 7) / 8, 1);
    barrier(cb, x.flat8, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
    return true;
}

// Flatscreen 3D: the window's picture (window in TRANSFER_DST_OPTIMAL; to: the game's picture's place in it, rect: the
// picture's own size) made from this frame's scene before the HUD and its depth, each eye 3.2 cm (FLAT3D_DEPTH percent of
// it) to its side of the game's camera, the HUD at the screen. Before the menu is drawn over the window
extern "C" void vk_xr_flat3d(VkCommandBuffer cb, VkImage window, int hdr, const int rect[4], const int to[4]) {
    Xr &x = xr();
    if (!flat_on() || hdr || rect[2] <= 0 || rect[3] <= 0 || to[2] <= 0 || to[3] <= 0) {
        x.flat_age = 1000;
        return;
    }
    // the game's picture's size: the scene kept before the HUD is the one of this size (vk_xr_scene_image)
    x.pic_w.store((uint32_t)rect[2], std::memory_order_relaxed), x.pic_h.store((uint32_t)rect[3], std::memory_order_relaxed);
    std::lock_guard<std::mutex> lk(x.hud_mu);
    float planes[2];
    const float p00 = lens_p00.load(std::memory_order_relaxed);
    const bool cam = vk_xr_planes(planes) && p00 > 0.0f && x.depth_kept;
    bool made = false;
    if (cam && make_panel(cb, 0)) {
        if (!x.flat_tried) {
            x.flat_tried = true;
            if (!make_flat_pipelines()) {
                rt_log("flat3d: the shaders could not be made: flatscreen 3D off");
                x.flat_pipe = VK_NULL_HANDLE;
            } else rt_log("flat3d: on, the game's lens P00 %.3f", p00);
        }
        const float half = 0.5f * 0.064f * 0.01f * (float)cfg_int("FLAT3D_DEPTH");
        const float shift[2] = {-half * p00, half * p00};
        made = x.flat_pipe && eyes_from(cb, shift, planes) && flat_compose(cb, shift, planes);
    }
    // a present with no new scene (the same frame shown again) shows the last picture; a few without one (a menu, the
    // title, a paused game drawing no world) the game's own
    x.flat_age = made ? 0 : std::min(x.flat_age + 1, 1000);
    if (x.flat_age > 2 || !x.flat8) return;
    memory_barrier(cb);
    VkImageBlit b{};
    b.srcSubresource = b.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    b.srcOffsets[1] = {(int32_t)x.flat_w, (int32_t)x.flat_h, 1};
    b.dstOffsets[0] = {to[0], to[1], 0}, b.dstOffsets[1] = {to[0] + to[2], to[1] + to[3], 1};
    vkCmdBlitImage(cb, x.flat8, VK_IMAGE_LAYOUT_GENERAL, window, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b, VK_FILTER_LINEAR);
    memory_barrier(cb);
}

// Stereo Accurate (vk_xr_capture, hud_mu held, the right eye's panel just made in scene8): its picture a little less saturated
// and darker, so its colours meet the left eye's (its second drawing comes out more saturated and brighter: the game's lighting
// carries a little of the left eye's drawing into it). Matched by eye in a Quest 3: 90% of its saturation, 78% of its brightness
bool flat_pipeline(const VkDescriptorSetLayoutBinding *b, uint32_t n, uint32_t push, const uint32_t *code, size_t size,
                   VkDescriptorSetLayout &set, VkPipelineLayout &layout, VkPipeline &pipe);
void desat_right(VkCommandBuffer cb) {
    Xr &x = xr();
    constexpr float keep = 0.90f, light = 0.78f;
    if (!x.scene8) return;
    if (!x.desat_tried) {
        x.desat_tried = true;
        const VkDescriptorSetLayoutBinding b{0, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr};
        if (!flat_pipeline(&b, 1, 16, XR_DESAT_COMP_SPV, sizeof XR_DESAT_COMP_SPV, x.desat_set, x.desat_layout, x.desat_pipe)) {
            rt_log("vr: the right eye's colour shader could not be made: its colours as drawn");
            x.desat_pipe = VK_NULL_HANDLE;
        }
    }
    if (!x.desat_pipe) return;
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.desat_pipe);
    const VkDescriptorImageInfo info{VK_NULL_HANDLE, x.scene8_view, VK_IMAGE_LAYOUT_GENERAL};
    VkWriteDescriptorSet w{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
    w.dstBinding = 0, w.descriptorCount = 1, w.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, w.pImageInfo = &info;
    vkCmdPushDescriptorSetKHR(cb, VK_PIPELINE_BIND_POINT_COMPUTE, x.desat_layout, 0, 1, &w);
    struct { int32_t w, h; float keep, light; } pc{(int32_t)x.hud_w, (int32_t)x.hud_h, keep, light};
    vkCmdPushConstants(cb, x.desat_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
    vkCmdDispatch(cb, (x.hud_w + 7) / 8, (x.hud_h + 7) / 8, 1);
    barrier(cb, x.scene8, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL);
}
