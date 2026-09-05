#pragma once

#include "frame_config.h"

// -----------------------------------------------------------------------------
// The app-level surface that web.cpp calls into. Implemented in main.cpp.
//
// The single most important invariant behind all of this: EVERYTHING runs in
// one Arduino task. server.handleClient() and the panel refresh both execute
// from loop(), so they can never interleave. There is no concurrency to guard
// against here -- only latency to manage. That is why none of this needs locks,
// and why a web handler can safely mutate state a refresh will later read.
// -----------------------------------------------------------------------------

// Ordered by priority: when a second request arrives before the first has been
// serviced, the higher value wins and they collapse into one refresh. Three
// rapid counter posts plus a /next therefore cost exactly one panel refresh.
enum PendingAction : uint8_t
{
    PENDING_NONE = 0,
    PENDING_REDRAW = 1,  // same photo, re-render (counter or IP changed)
    PENDING_RESCAN = 2,  // /pictures changed; relist, keep current photo by name
    PENDING_ADVANCE = 3, // next photo in filename order
    PENDING_JUMP = 4,    // go to the queued jump target
};

void queueAction(PendingAction action);
void queueJump(const String &binName);

// True while a refresh is in flight or the panel is still settling. Purely
// informational for the status page -- callers never need to wait on it.
bool displayBusy();

// Live config (counter, refresh interval, timezone), re-read from the card
// whenever it changes.
const FrameConfig &appConfig();

// Adjusts the counter by +/-1: reads the card, writes the new value back into
// <counter>, and appends to /counter_track.txt. Deliberately does NOT touch the
// panel -- the on-screen value updates at the next refresh (see README).
// Returns false if the card is unavailable.
bool applyCounterDelta(int delta, int32_t *newValueOut);

// Photo state.
String currentPhotoName();
// Re-reads /pictures (e.g. after an upload) and refreshes the cached listing.
void markPicturesDirty();

// Clock.
bool clockValid();
String formatLocalTime();      // "2026-09-03 21:08:44 CDT", or "not set"
bool setClockFromEpoch(time_t epoch);
bool setTimezone(const String &tz);

// Scheduling. Both in milliseconds; msUntilNextRefresh() is derived from the
// monotonic millis() clock, never from wall time (see the note in main.cpp).
uint32_t refreshIntervalMs();
uint32_t msUntilNextRefresh();

// Network status, also used for the top-right corner of the panel overlay.
String wifiStatusText();
bool wifiConnected();
