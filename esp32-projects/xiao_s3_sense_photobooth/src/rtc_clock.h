#pragma once

#include "booth_config.h"

// Call once at boot, after setupScreen() (which starts Wire).
void setupClock();
bool clockValid();         // system time is set and sane (> CLOCK_SANE_EPOCH)
String timestampForName(); // local "YYYY-MM-DD_HH-MM-SS", or "" if !clockValid()
String formatLocalTime();  // local "YYYY-MM-DD HH:MM:SS TZ", or "not set"
