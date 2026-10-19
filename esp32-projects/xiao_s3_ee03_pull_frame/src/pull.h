#pragma once

#include "frame_config.h"

// Talks to the eink_photo_server's esp32_pull protocol (see
// python-projects/eink_photo_server/server/protocols/esp32_pull.py):
//   GET /esp32/v1/pull   -> {"status": show|keep|none|error, "next_check_s", ...}
//   GET {image_url}      -> the packed 1,314,144-byte panel buffer, streamed to SD
//   GET /esp32/v1/signal -> after the panel shows it
// The server decides what to show and when to check again; this side just
// follows, and falls back to cycling its SD cache when the server is gone.

struct PullStatus
{
    String lastAttempt;     // local time of the last pull attempt
    String lastResult;      // "show 12-ab…_G.bin", "keep", "none", "error: …"
    String nextCheckAt;     // ISO UTC time the server asked us to check
    uint8_t failures = 0;   // consecutive failed pulls
    bool offline = false;   // cycling the SD cache locally
    uint32_t pulls = 0;     // successful pulls since boot
    uint32_t downloads = 0; // images downloaded since boot
};

void setupPull();
// Call every loop pass: runs a due pull, and the offline cache cycle.
void servicePull();
// Pull at the next pass regardless of the schedule (web "Pull now").
void requestPullNow();
// Milliseconds until the next scheduled pull.
uint32_t msUntilNextPull();
const PullStatus &pullStatus();
// Report a display result for a pull (called by main.cpp after the refresh).
void sendSignal(const String &pullId, bool success);
// Stable id for this board (WiFi MAC, no colons), sent as device_id.
String deviceId();
