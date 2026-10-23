#pragma once

#include "cam_config.h"

#include <functional>

// -----------------------------------------------------------------------------
// Snapshot storage: /photos/<name>.jpg on the SD card when one is mounted,
// otherwise a small PSRAM list (see RAM_PHOTOS_MAX*) that's moved onto the card
// by the next successful mountSd().
//
// Only the HTTP_PORT server task calls into this (one request at a time), so
// none of it is locked. Keep the stream task out of here.
// -----------------------------------------------------------------------------

// (Re)mounts the card, in whichever slot it's in (Sense board or round
// display): unmounts first if it was mounted, so this doubles as the "card
// swapped / inserted" check. Logs every attempt. On success, moves any RAM photos onto it
// and returns how many in `moved`.
bool mountSd(size_t *moved = nullptr);
bool sdIsMounted();
uint64_t sdFreeBytes();

struct PhotoInfo
{
    String name;
    size_t size;
    bool onSd;
};

struct SaveResult
{
    bool ok;
    String name;
    bool onSd;
    bool dated; // false if the clock wasn't set (name is nodate_<uptime>)
};

SaveResult savePhoto(const uint8_t *data, size_t len);
std::vector<PhotoInfo> listPhotos(); // newest first
bool validPhotoName(const String &name);
bool findPhoto(const String &name, PhotoInfo &out);
// Streams the photo to `sink` in chunks; stops early (returning false) if the
// sink returns false.
bool readPhoto(const String &name, const std::function<bool(const uint8_t *, size_t)> &sink);
bool deletePhoto(const String &name);

size_t ramPhotoCount();
size_t ramPhotoBytes();
