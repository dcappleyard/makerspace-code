#pragma once

// -----------------------------------------------------------------------------
// Shared constants for the XIAO ESP32-S3 Sense web cam. See ../hardware_info.md
// for the board, and README.md for what the firmware does.
// -----------------------------------------------------------------------------

#include <Arduino.h>
#include <FS.h>

#include <vector>

// -----------------------------------------------------------------------------
// Camera: the Sense expansion board's DVP connector. Pin map copied from the
// Arduino-ESP32 core's Camera example (camera_pins.h, CAMERA_MODEL_XIAO_ESP32S3).
// No PWDN/RESET lines are wired on this board.
// -----------------------------------------------------------------------------
constexpr int CAM_PIN_PWDN = -1;
constexpr int CAM_PIN_RESET = -1;
constexpr int CAM_PIN_XCLK = 10;
constexpr int CAM_PIN_SIOD = 40;
constexpr int CAM_PIN_SIOC = 39;
constexpr int CAM_PIN_D7 = 48; // Y9
constexpr int CAM_PIN_D6 = 11; // Y8
constexpr int CAM_PIN_D5 = 12; // Y7
constexpr int CAM_PIN_D4 = 14; // Y6
constexpr int CAM_PIN_D3 = 16; // Y5
constexpr int CAM_PIN_D2 = 18; // Y4
constexpr int CAM_PIN_D1 = 17; // Y3
constexpr int CAM_PIN_D0 = 15; // Y2
constexpr int CAM_PIN_VSYNC = 38;
constexpr int CAM_PIN_HREF = 47;
constexpr int CAM_PIN_PCLK = 13;
constexpr int CAM_XCLK_HZ = 20000000;

// -----------------------------------------------------------------------------
// microSD slot on the same expansion board: SPI on the XIAO's default SPI pins
// (SCK=7, MISO=8, MOSI=9), shared with the round display and driven through its
// SPI instance -- see screenSpi(). CS is GPIO21, which is also the user LED --
// the LED flickers on card access.
// -----------------------------------------------------------------------------
constexpr int SD_CS = 21;
constexpr uint32_t SD_FREQUENCY_HZ = 20000000;

extern const char *PHOTO_DIR; // "/photos"
constexpr size_t PHOTO_NAME_MAX_LEN = 48;

// Snapshots taken with no card are held in PSRAM until one is mounted (or the
// board reboots). Oldest dropped first past either limit.
constexpr size_t RAM_PHOTOS_MAX = 20;
constexpr size_t RAM_PHOTOS_MAX_BYTES = 4UL * 1024 * 1024;

// -----------------------------------------------------------------------------
// 1.28" Round Touch Display (GC9A01 240x240 + CHSC6X touch), driven by
// Seeed_GFX -- see screen.cpp. Its LCD pins (CS=GPIO2, DC=GPIO4, BL=GPIO43,
// SCK/MISO/MOSI = 7/8/9, shared with the SD slot above) come from Seeed_GFX's
// Setup501; only what this project uses directly is repeated here.
// -----------------------------------------------------------------------------
constexpr int TOUCH_INT_PIN = 44;      // D7, active LOW while touched
constexpr uint8_t TOUCH_I2C_ADDR = 0x2E;
constexpr int ROUND_SD_CS = 3;          // the display's own SD slot (unused) -- held HIGH
constexpr uint8_t DISPLAY_ROTATION = 0; // 0-3; change if the preview comes out rotated
// jpg2rgb565 writes big-endian RGB565, which the panel wants as-is. Flip this
// if the preview shows blue/orange swapped.
constexpr bool PREVIEW_SWAP_BYTES = false;
constexpr uint32_t SCREEN_IDLE_OFF_MS = 2UL * 60 * 1000; // no touch for this long -> off
constexpr uint32_t CONFIRM_TIMEOUT_MS = 10000;           // unanswered Yes/No -> back to preview
// A touch only counts as a new tap after this long with no touch reports, so a
// held finger (the controller keeps pulsing INT) fires once.
constexpr uint32_t TOUCH_REARM_MS = 300;

// -----------------------------------------------------------------------------
// Clock: only used to name snapshots.
// -----------------------------------------------------------------------------
constexpr time_t CLOCK_SANE_EPOCH = 1735689600; // 2025-01-01T00:00:00Z
constexpr const char *TZ_DEFAULT = "CST6CDT,M3.2.0,M11.1.0"; // US Central, US DST rules
constexpr const char *NTP_SERVER_1 = "pool.ntp.org";
constexpr const char *NTP_SERVER_2 = "time.nist.gov";

// -----------------------------------------------------------------------------
// Network
// -----------------------------------------------------------------------------
constexpr const char *HOSTNAME = "xiao-cam";
constexpr uint16_t HTTP_PORT = 80;
constexpr uint16_t STREAM_PORT = 81;
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 60000;
