#pragma once

#include "booth_config.h"

// -----------------------------------------------------------------------------
// The photo booth itself (see README.md for the full sequence):
//   asleep --tap--> live view --tap--> "Capture?" Yes / No
//     Yes: three shots (_A, _B, _C), each a 3..2..1 countdown over the live
//          view, a white flash at capture, then the photo for REVIEW_MS
//     No, or CONFIRM_TIMEOUT_MS: back to live view
//   live view with no touch for LIVE_IDLE_SLEEP_MS --> asleep
// -----------------------------------------------------------------------------

void setupBooth();   // starts asleep (camera off, panel off)
void serviceBooth(); // call every loop(); sleeps inside when asleep
