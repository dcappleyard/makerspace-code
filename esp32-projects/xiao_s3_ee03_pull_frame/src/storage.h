#pragma once

#include "frame_config.h"

// SD card lifecycle -- mounted for the life of the process, as in
// ../panorama_photo_frame_web (downloads arrive at arbitrary times).
bool mountSd();
bool sdIsMounted();
uint64_t sdFreeBytes();

// The image cache: /cache/<name>.bin, one file per image the server has sent.
// Names come from the server and are validated before touching the card.
bool validCacheName(const String &name);
String cachePath(const String &name);
bool cacheHas(const String &name);
std::vector<String> listCache();          // sorted by name
size_t cacheCount();
// Deletes the oldest files (by last-write time) beyond CACHE_MAX_FILES, never
// the one named `keep`.
void pruneCache(const String &keep);

// Reads a packed image into a PSRAM buffer the caller free()s; nullptr on any
// failure (missing file, alloc failure, short read).
uint8_t *loadImageBuffer(const String &name);
