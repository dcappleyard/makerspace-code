#pragma once

#include "frame_config.h"
#include "power.h"

// One exchange with the eink_photo_server's esp32_pull protocol (see
// python-projects/eink_photo_server/server/protocols/esp32_pull.py):
//   GET /esp32/v1/pull   -> {"status": show|keep|none|error, "next_check_s", ...}
//   GET {image_url}      -> the 48,000-byte packed panel buffer
//   GET /esp32/v1/signal -> after the panel shows it
// The server decides what to show and when to check again.

enum class PullOutcome
{
    Shown,    // new image drawn (and signalled)
    Kept,     // keep / none: panel untouched
    Declined, // server answered "error" (bad token, prep failure)
    Failed,   // couldn't reach the server, or the download was bad
};

struct PullResult
{
    PullOutcome outcome;
    uint32_t nextCheckS; // from the server; 0 if it never answered
    uint32_t answeredMs; // millis() when the server answered
    String detail;
};

PullResult runPull(const char *reason, const Battery &battery);
String deviceId();
