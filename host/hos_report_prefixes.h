/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
/* Renderer log protocol consumed by the host's crash records (host/hos_crash_record.c, through host/hos_thread.c hos_log).
   Keep these in step with checkpoints_report (gpu/vk/vk_draw.cpp) and replay_fatal (gpu/vk/vk_replay.cpp).
   Only a prefix at the start of a line counts, never a quoted mention. */
#define HOS_REPORT_DEVICE_LOST_PREFIX "vk: device lost:"
#define HOS_REPORT_FATAL_PREFIX "vk: FATAL:"
