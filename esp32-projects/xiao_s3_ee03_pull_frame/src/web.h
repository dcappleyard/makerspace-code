#pragma once

#include "frame_config.h"

// A small read-only status page (plus one "Pull now" button). Photos, schedules
// and captions are all managed on the eink_photo_server now.
void setupWebServer();
// Serviced from loop(), first each pass -- see the single-task note in app.h.
void handleWebClient();
