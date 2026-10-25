#pragma once

#include "booth_config.h"

// -----------------------------------------------------------------------------
// Sends new photos to the eink_photo_server's photobooth source
// (python-projects/eink_photo_server, POST /sources/<id>/upload), so they show
// up there -- and on any frame scheduled to show the booth's photos.
//
// Runs when the booth goes to sleep (camera already off, screen still on to
// show progress): brings WiFi up, posts every pending photo oldest first --
// streamed from the card, or from PSRAM for shots taken without one -- then
// switches WiFi off again. Uploaded card photos move to /photos/uploaded/;
// anything not sent (server down, time budget used up) is retried next time.
// A no-op unless include/secrets.h defines WIFI_SSID, SERVER_URL and UPLOAD_TOKEN.
// -----------------------------------------------------------------------------

// Number of photos waiting to be uploaded (card + RAM).
size_t pendingUploads();
// Uploads what it can within UPLOAD_BUDGET_MS; returns how many were sent.
size_t uploadPending();
