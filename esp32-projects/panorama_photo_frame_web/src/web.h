#pragma once

#include "frame_config.h"

// Registers every route and starts the server. Called once from setup().
// Safe to call before WiFi is up: the server binds INADDR_ANY:80 and simply
// starts serving once an address exists.
void setupWebServer();

// Serviced from loop(). Must be called first each pass so the server stays
// responsive; see the single-task note in app.h.
void handleWebClient();
