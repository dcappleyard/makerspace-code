#pragma once

#include "frame_config.h"

// -----------------------------------------------------------------------------
// The surface main.cpp offers to pull.cpp and web.cpp.
//
// As in ../panorama_photo_frame_web, EVERYTHING runs in one Arduino task:
// web requests, pulls (including the image download) and the panel refresh all
// execute from loop(), so they can never interleave and nothing needs a lock.
// A pull blocks the web page for the few seconds a 1.3 MB download takes; that
// is the accepted cost of keeping it single-task.
// -----------------------------------------------------------------------------

// Show cache file `name` at the next loop pass. If signalPullId is non-empty,
// the result is reported to the server (GET /esp32/v1/signal) after the panel
// update. A later call before it's serviced replaces the earlier one.
void queueDisplay(const String &name, const String &signalPullId);

// The cache file on the panel now ("" before the first draw).
String currentImageName();
// True while a refresh is queued or the panel is still settling.
bool displayBusy();

bool wifiConnected();
String wifiStatusText();
bool clockValid();
String formatLocalTime(); // "2026-10-19 21:08:44 CDT", or "not set"
