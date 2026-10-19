#pragma once

// -----------------------------------------------------------------------------
// Shared constants and -- critically -- the one place the fragile include order
// is enforced. Every .cpp in this project MUST include this header FIRST.
//
// Carried over from ../panorama_photo_frame_web: Seeed_GFX's ESP32-S3 processor
// header (Processors/TFT_eSPI_ESP32_S3.h) does `#define FS_NO_GLOBALS` before
// pulling in FS.h, which suppresses `using fs::File;`/`using fs::FS;` and breaks
// both SD.open()'s return type and WebServer.h's unqualified use of `FS`.
// Including FS.h here first lets its `using` declarations fire while global;
// FS.h's include guard then makes TFT_eSPI.h's later include a no-op.
// -----------------------------------------------------------------------------

#include <Arduino.h>
#include <FS.h>
#include <TFT_eSPI.h>

#include <vector>

// -----------------------------------------------------------------------------
// SD card on its own SPI host (SPIClass(FSPI) -> SPI2_HOST), separate from the
// EE03 panel's bus (SPI3_HOST) -- wiring proven in ../eink_sd_test. 20MHz as in
// ../panorama_photo_frame_web; if the card misbehaves, step DOWN 20 -> 16 -> 10
// -> 4 MHz (the breakout is jumper-wired, so signal integrity is the suspect).
// -----------------------------------------------------------------------------
constexpr int SD_SPI_SCLK = 11;
constexpr int SD_SPI_MISO = 12;
constexpr int SD_SPI_MOSI = 13;
constexpr int SD_CS = 39;
constexpr uint32_t SD_FREQUENCY_HZ = 20000000;

// -----------------------------------------------------------------------------
// Panel: the full-canvas packed buffer the server's ee03_gray16 pipeline
// produces (caption and all) -- 4bpp, two pixels per byte, high nibble first.
// -----------------------------------------------------------------------------
constexpr int IMAGE_WIDTH = 1872;
constexpr int IMAGE_HEIGHT = 1404;
constexpr size_t IMAGE_BYTES = (size_t)IMAGE_WIDTH * IMAGE_HEIGHT / 2; // 1314144

// Seeed_GFX's 16-gray update() is fire-and-forget: the panel needs ~3s
// undisturbed for the waveform to finish. A millis() gate, not a delay(), so the
// web server stays responsive (see serviceDisplay() in main.cpp).
constexpr unsigned long GRAY_REFRESH_SETTLE_MS = 3000;

// -----------------------------------------------------------------------------
// Pull scheduling. The server says when to check next (next_check_s); these
// bound it and cover the failure paths. All deadlines are millis()-based --
// never wall-clock -- for the reason ../panorama_photo_frame_web documents (NTP
// steps the clock by decades just after boot).
// -----------------------------------------------------------------------------
constexpr uint32_t MIN_CHECK_S = 60;
constexpr uint32_t MAX_CHECK_S = 7UL * 24 * 3600; // well clear of the 49.7-day millis() rollover
constexpr uint32_t RETRY_S = 300;                 // after a failed pull
constexpr uint8_t OFFLINE_AFTER_FAILURES = 3;     // then cycle the SD cache locally...
constexpr uint32_t OFFLINE_CYCLE_S = 2UL * 3600;  // ...this often, still retrying every RETRY_S
constexpr uint32_t HTTP_TIMEOUT_MS = 15000;

// -----------------------------------------------------------------------------
// SD cache of downloaded images (the offline fallback).
// -----------------------------------------------------------------------------
extern const char *CACHE_DIR;     // "/cache"
extern const char *DOWNLOAD_TMP;  // "/cache/.download.tmp"
constexpr size_t CACHE_MAX_FILES = 60; // ~80 MB of 1.3 MB images
constexpr size_t NAME_MAX_LEN = 64;

// -----------------------------------------------------------------------------
// Clock (display only -- nothing is scheduled on wall time)
// -----------------------------------------------------------------------------
constexpr time_t CLOCK_SANE_EPOCH = 1735689600; // 2025-01-01T00:00:00Z
constexpr const char *TZ_DEFAULT = "CST6CDT,M3.2.0,M11.1.0"; // US Central, US DST rules
constexpr const char *NTP_SERVER_1 = "pool.ntp.org";
constexpr const char *NTP_SERVER_2 = "time.nist.gov";

// -----------------------------------------------------------------------------
// Network
// -----------------------------------------------------------------------------
constexpr const char *HOSTNAME = "ee03-frame";
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 60000;

#ifdef EPAPER_ENABLE
extern EPaper epaper;
#endif
