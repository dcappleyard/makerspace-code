#pragma once

// Two esp_http_server instances, each with its own task: the page + API on
// HTTP_PORT, the MJPEG stream on STREAM_PORT. A stream holds its server's task
// for as long as it's open, so keeping it separate is what lets snapshots and
// setting changes work while someone is watching. (The sibling projects'
// synchronous WebServer.h, serviced from loop(), can't do that.)
void startWebServers();

// Open MJPEG streams right now (for status and the battery log).
int streamClientCount();
