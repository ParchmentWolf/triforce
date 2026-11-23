"""(Triforce, 11-23) The next swapchain image acquired ahead on the present thread (RX_VK_ACQUIRE_AHEAD, gpu/vk/vk_replay.cpp
acquire_ahead; no game, no GPU).

On AMD's Windows driver an acquired image comes back with the compositor's next refresh, and present_image waited for it
(the acquire's fence, RX_VK_ACQUIRE_FENCE) on the thread that replays the frame: 2.4 to 4.2 ms of every frame on an RX 6700
XT, 16% of that thread in a profile. The present thread now acquires the next image right after its present and waits for it
there, while the frame is replayed; present_image finds it held and free.

Read from the source, as the rest of the present's rules are (tests/test_present_thread.py):
- when: only on the present thread, after present_out and before it says it is done; with the acquire's fence, without DLSS
  frame generation, on AMD's Windows driver unless RX_VK_ACQUIRE_AHEAD says otherwise; and the present thread is wanted for it;
- what: nothing while an image is held, with no swapchain, or while a resize or a lost surface waits for present_image; the
  acquire signals the fence and no semaphore; the image waited for at most 250 ms; held, marked free when it was;
- no present_image_mu: present_image holds it while it settles this thread's work, and would wait for itself;
- present_image takes a held image marked free without waiting, and every other held image as before.

    python -I -B tests/test_acquire_ahead.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def before(text, *parts):
    at = -1
    for p in parts:
        i = text.find(p, at + 1)
        if i < 0:
            return False
        at = i
    return True


def main():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    fails = []

    def check(ok, why):
        if not ok:
            fails.append(why)

    wanted = block(replay, "bool acquire_ahead_wanted() {")
    check("#ifdef _WIN32" in wanted and 'getenv("RX_VK_ACQUIRE_AHEAD")' in wanted, "the switch is not read, or not on Windows alone")
    check("if (asked == 0 || !acquire_fence_on() || dlssg::active()) return false;" in wanted,
          "it runs without the acquire's fence, with DLSS frame generation, or with the switch at 0")
    check("return asked > 0 || dev.props.vendorID == 0x1002;" in wanted, "it is not AMD's by default, or =1 does not turn it on")

    ahead = block(replay, "void acquire_ahead() {")
    check("present_image_mu" not in ahead.split("//")[0] and "std::lock_guard lk(present_image_mu)" not in ahead,
          "it takes present_image_mu, which present_image holds while it waits for this thread")
    check(before(ahead, "if (held_image.on || !dev.swapchain || dev.swap_resize.load(std::memory_order_acquire) ||",
                 "surface_lost_noted.load(std::memory_order_acquire)", "return;", "vkAcquireNextImageKHR("),
          "it acquires while an image is held, with no swapchain, or before present_image made the swapchain again")
    check("vkAcquireNextImageKHR(dev.device, dev.swapchain, UINT64_MAX, VK_NULL_HANDLE, fence, &index);" in ahead,
          "the acquire does not signal the fence alone")
    check(before(ahead, "if (res != VK_SUCCESS && res != VK_SUBOPTIMAL_KHR) {", "return;", "image_free(250000000ull)",
                 "held_image = {true, index, dev.swap_generation, 0, false, ready == VK_SUCCESS};"),
          "the image is not waited for at most 250 ms and held, marked free when it was")

    main_ = block(replay, "void present_thread_main() {")
    check(before(main_, "present_out(o, qk, true);", "}", "acquire_ahead();", "present_hand.done();"),
          "it does not run on the present thread after its present, with the queue's lock let go, before the thread is done")
    ptw = block(replay, "bool present_thread_wanted() {")
    check("acquire_ahead_wanted()" in ptw, "the present thread is not wanted for it")

    pi = block(replay, "void present_image(VkImage src, uint32_t sw, uint32_t sh, const int crop[4], VkImageView view) {")
    check(before(pi, "present_thread_settle();", "held_image.on && held_image.free ? VK_SUCCESS : image_free("),
          "present_image does not settle the present thread first, or waits again for an image waited free")
    held = block(replay, "struct HeldImage {")
    check("bool free = false;" in held, "a held image has no mark for having been waited free")

    if fails:
        for f in fails:
            print("FAIL: " + f)
        raise SystemExit(1)
    print("acquire ahead: ok")


if __name__ == "__main__":
    main()
