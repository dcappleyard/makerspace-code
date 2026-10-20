#pragma once

#include "cam_config.h"

// The surface main.cpp offers to web.cpp.
bool wifiConnected();
String wifiStatusText(); // IP, or "no wifi"
bool clockValid();
String formatLocalTime(); // "2026-10-19 21:08:44 CDT", or "not set"
