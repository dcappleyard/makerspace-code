#pragma once

#include "frame_config.h"

// State that survives deep sleep (RTC slow memory). Reset on power-on/reset,
// which is deliberate: after a cold boot the frame doesn't claim to know
// what's on the panel, so the server answers "show" and it redraws.
struct RtcState
{
    uint32_t magic;
    uint32_t wakes;              // timer wakes since the last cold boot
    uint8_t failures;            // consecutive failed pulls
    char current[NAME_MAX_LEN];  // image on the panel ("" = unknown)
    char scheduledFor[40];       // server's next_check_at, echoed back
    bool apValid;                // remembered AP for a fast reconnect
    uint8_t bssid[6];
    int32_t channel;
};
extern RtcState rtc;

// Initialises rtc on a cold boot; returns true if this was a timer wake.
bool beginPower();

struct Battery
{
    uint16_t mv;
    uint8_t pct;
    uint16_t raw;
};
Battery readBattery();

// True while the frame should stay awake rather than deep sleep.
bool stayAwake(bool timerWake);

// Panel power off, pins held, timer armed, deep sleep. Doesn't return.
[[noreturn]] void deepSleep(uint32_t seconds);
