#pragma once

#include "frame_config.h"

// SD card lifecycle. Unlike ../panorama_photo_frame_w_counter -- which mounted
// the card for sub-second windows around each deep-sleep wake and tore the bus
// down in between -- this build keeps the card mounted for the lifetime of the
// process. Uploads arrive at arbitrary times and span multiple callbacks, so
// per-request mounting would mean bringing the bus up inside
// UPLOAD_FILE_START and down inside the abort path, which is more failure
// surface, not less. The battery argument for unmounting is also gone.
//
// The user-visible consequence is that the card can no longer be pulled
// casually: see POST /sd/eject in web.cpp and the README's "Swapping the SD
// card" section.
bool mountSd();
void unmountSd();
bool sdIsMounted();

// True once mountSd() has succeeded at least once this boot. Used to decide
// whether a failure should draw an error screen over a photo that's already up.
bool sdEverMounted();

// Tiny XML helpers. These files are produced by prepare_image.py, not
// arbitrary XML, so the parsing is deliberately naive.
String readTag(const String &xml, const char *tag);
String xmlUnescape(String s);
String xmlEscape(const String &s);
uint16_t parseGrayColor(const String &value, uint16_t fallback);

// Photo enumeration and loading.
std::vector<String> listPictures();
uint8_t *loadImageBuffer(const String &binName); // caller free()s; nullptr on failure
PhotoMeta loadPhotoMeta(const String &binName);

// /frame_config.xml
FrameConfig readConfig();
// Rewrites one tag's value in place, preserving everything else in the file
// (comments, other tags, formatting). Generalized from the sibling project's
// writeConfigCounter(), which was this same substring swap hardcoded to
// <counter>.
bool writeConfigTag(const char *tag, const String &value);
bool writeConfigCounter(int32_t value);

void appendCounterTrack(int delta, int32_t newValue, bool clockValid);

// Reads up to `maxBytes` from the END of /counter_track.txt into `out`, so the
// history page shows recent entries without ever loading an unbounded file into
// a heap shared with lwIP. Any partial first line produced by the seek is
// dropped. `truncated` reports whether older entries were skipped and
// `totalSize` the full file size, so the page can say so. Returns false if the
// file doesn't exist or the card isn't mounted.
bool readCounterTrackTail(String &out, size_t maxBytes, bool *truncated, size_t *totalSize);

// Free space, for the upload precheck and the status page.
uint64_t sdFreeBytes();
