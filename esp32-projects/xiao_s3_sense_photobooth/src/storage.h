#pragma once

#include "booth_config.h"

#include <functional>
#include <vector>

// -----------------------------------------------------------------------------
// Photo storage: /photos/<name>.jpg on the SD card when one is mounted,
// otherwise a small PSRAM list (see RAM_PHOTOS_MAX*) that's moved onto the card
// by the next successful mountSd() -- the booth tries one at every wake. All
// called from the loop() task.
// -----------------------------------------------------------------------------

// (Re)mounts the card, in whichever slot it's in (Sense board or round
// display): unmounts first if it was mounted, so this doubles as the "card
// swapped / inserted" check. Logs every attempt. `thorough` (boot) also retries
// at a faster clock; the quick pass (wake) keeps a missing card from delaying
// the live view much. On success, moves any RAM photos onto it and returns how
// many in `moved`.
bool mountSd(size_t *moved = nullptr, bool thorough = true);
bool sdIsMounted();
uint64_t sdFreeBytes();

// The shared base for one capture sequence ("2026-10-23_14-03-22"), taken at
// "Yes"; each shot appends _A, _B, _C.
String sequenceName(bool &dated);

struct SaveResult
{
    bool ok;
    String name;
    bool onSd;
};

// Saves as <base>.jpg (or <base>-2.jpg if taken).
SaveResult savePhoto(const uint8_t *data, size_t len, const String &base);

size_t ramPhotoCount();
size_t ramPhotoBytes();

// --- Upload bookkeeping (see upload.cpp) ---------------------------------------
// A photo on the card is "pending" until it has been uploaded, then it moves to
// /photos/uploaded/ (kept, just out of the way). RAM photos are dropped once
// uploaded -- the server has them.
extern const char *UPLOADED_DIR; // "/photos/uploaded"
std::vector<String> pendingSdPhotos(); // names in /photos, oldest (name order) first
bool markSdUploaded(const String &name);
struct RamPhotoRef
{
    String name;
    const uint8_t *data;
    size_t len;
};
std::vector<RamPhotoRef> ramPhotos();  // oldest first; valid until the next storage call
void dropRamPhoto(const String &name);
