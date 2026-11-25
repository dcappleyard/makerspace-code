#pragma once

#include <Arduino.h>
#include <TFT_eSPI.h>

// -----------------------------------------------------------------------------
// Panel: 4.26" 800x480 B/W. The server's ee04_bw1 pipeline sends exactly the
// Seeed_GFX 1-bit sprite buffer (row-major, 100 bytes/row, MSB = left pixel,
// 1 = white), so it's copied straight into the sprite.
// -----------------------------------------------------------------------------
constexpr int IMAGE_WIDTH = 800;
constexpr int IMAGE_HEIGHT = 480;
constexpr size_t IMAGE_BYTES = (size_t)IMAGE_WIDTH * IMAGE_HEIGHT / 8; // 48000

// -----------------------------------------------------------------------------
// EE04 board pins that Seeed_GFX doesn't own (see ../hardware_info.md).
// -----------------------------------------------------------------------------
constexpr int PIN_BAT_ADC = 1;    // A0, through a divider
constexpr int PIN_BAT_ADC_EN = 6; // A5, HIGH connects the divider (LOW in sleep)

// -----------------------------------------------------------------------------
// Battery. Seeed's EE04 sample scaling: V = raw / 4096 * 7.16. If a multimeter
// disagrees, adjust BATTERY_CAL (measured / reported).
// -----------------------------------------------------------------------------
constexpr float BATTERY_SCALE = 7.16f / 4096.0f;
constexpr float BATTERY_CAL = 1.0f;
// Below this, skip WiFi entirely and sleep long, to protect the cell. Not
// applied while a USB host is attached (bench work with no battery).
constexpr uint16_t BATTERY_CUTOFF_MV = 3300;
constexpr uint32_t BATTERY_CUTOFF_SLEEP_S = 12UL * 3600;

// -----------------------------------------------------------------------------
// Scheduling. The server says when to check next (next_check_s). Deep sleep
// clears millis(), so the countdown is the ESP32's RTC sleep timer instead --
// same idea, but its internal RC oscillator drifts (expect ~1%); the server's
// per-frame wake offset and early-wake handling absorb that.
// -----------------------------------------------------------------------------
constexpr uint32_t MIN_CHECK_S = 60;
constexpr uint32_t MAX_CHECK_S = 7UL * 24 * 3600;
// After a failed pull (no WiFi, server down): back off, keep the last image.
constexpr uint32_t RETRY_BACKOFF_S[] = {300, 900, 1800, 3600};
constexpr uint32_t HTTP_TIMEOUT_MS = 10000;

// -----------------------------------------------------------------------------
// Staying awake for development. Deep sleep drops the USB port, so after a
// cold boot (reset button, power-on, reflash) the frame stays awake this long,
// and stays awake for as long as a USB *host* is attached (a charger alone
// doesn't count). While awake it runs the same cycle on a millis() countdown.
// -----------------------------------------------------------------------------
constexpr uint32_t BOOT_STAY_AWAKE_MS = 120000;
constexpr bool STAY_AWAKE_ON_USB_HOST = true;

// -----------------------------------------------------------------------------
// WiFi
// -----------------------------------------------------------------------------
constexpr const char *HOSTNAME = "ee04-frame";
// First try the AP/channel remembered from the last wake (skips the scan),
// then a normal connect.
constexpr uint32_t WIFI_FAST_TIMEOUT_MS = 5000;
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 15000;

constexpr size_t NAME_MAX_LEN = 64;

extern EPaper epaper;
