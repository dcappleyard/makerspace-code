#pragma once

// -----------------------------------------------------------------------------
// Shared constants for the XIAO ESP32-S3 Sense photo booth. See
// ../hardware_info.md for the board, and README.md for what the firmware does.
// Every timing the booth uses is here, so it can be tuned in one place.
// -----------------------------------------------------------------------------

#include <Arduino.h>
#include <FS.h>
#include <esp_camera.h> // framesize_t, for the camera-mode constants

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
constexpr uint32_t SD_SLOW_FREQUENCY_HZ = 4000000; // fallback, and the only speed tried at wake

extern const char *PHOTO_DIR; // "/photos"
constexpr size_t PHOTO_NAME_MAX_LEN = 48;

// Photos taken with no card are held in PSRAM until a card turns up (checked
// at every wake) or the board reboots. Oldest dropped first past either limit;
// full-size JPEGs are ~0.3-0.8 MB, so this is roughly the last two sequences.
constexpr size_t RAM_PHOTOS_MAX = 6;
constexpr size_t RAM_PHOTOS_MAX_BYTES = 4UL * 1024 * 1024;

// -----------------------------------------------------------------------------
// 1.28" Round Touch Display (GC9A01 240x240 + CHSC6X touch), driven by
// Seeed_GFX -- see screen.cpp. Its LCD pins (CS=GPIO2, DC=GPIO4, BL=GPIO43,
// SCK/MISO/MOSI = 7/8/9, shared with the SD slot above) come from Seeed_GFX's
// Setup501; only what this project uses directly is repeated here.
// -----------------------------------------------------------------------------
constexpr int TOUCH_INT_PIN = 44;      // D7, active LOW while touched
constexpr uint8_t TOUCH_I2C_ADDR = 0x2E;
constexpr int BACKLIGHT_PIN = 43;      // D6 (Seeed_GFX's TFT_BL) -- held LOW through sleep
constexpr int ROUND_SD_CS = 3;          // D2: the display's own SD slot -- tried after the Sense slot; held HIGH when unused
constexpr uint8_t DISPLAY_ROTATION = 1; // 0-3, in 90-degree steps; 1 = rotated 90 deg clockwise from the panel default
// RGB565 byte order of jpg2rgb565's output vs. what the panel expects; true was
// confirmed on hardware in ../xiao_s3_sense_webcam (false gives rainbow banding).
constexpr bool PREVIEW_SWAP_BYTES = true;
// A touch only counts as a new tap after this long with no touch reports, so a
// held finger (the controller keeps pulsing INT) fires once.
constexpr uint32_t TOUCH_REARM_MS = 300;
// After every screen change, touch reports are ignored for this long: the
// controller can report again as the finger lifts, which would otherwise
// re-open the prompt.
constexpr uint32_t TOUCH_LOCKOUT_MS = 1000;

// -----------------------------------------------------------------------------
// Booth timings (see README.md for the sequence)
// -----------------------------------------------------------------------------
constexpr uint32_t LIVE_IDLE_SLEEP_MS = 30000;   // live view with no touch -> sleep
constexpr uint32_t CONFIRM_TIMEOUT_MS = 3000;    // unanswered "Capture?" -> back to live view
constexpr uint8_t SHOTS_PER_SEQUENCE = 3;        // named _A, _B, _C
constexpr uint8_t COUNTDOWN_FROM = 3;            // 3..2..1
constexpr uint32_t COUNTDOWN_STEP_MS = 1000;     // per number
constexpr uint32_t FLASH_MS = 250;               // full-white flash at capture (minimum: it also covers one full-size frame)
constexpr uint32_t REVIEW_MS = 3000;             // each captured photo is shown this long

// -----------------------------------------------------------------------------
// Camera modes. Live view runs small so decoding keeps up; each capture
// switches to the sensor's largest size (UXGA on an OV2640, QXGA on an OV3660)
// and back. CAPTURE_QUALITY is JPEG quality, lower = better: 4-6 can overflow
// the frame buffers at full size, so stay around 8-10.
// -----------------------------------------------------------------------------
constexpr framesize_t LIVE_FRAMESIZE = FRAMESIZE_VGA; // 640x480 -> decoded at 1/2
constexpr int LIVE_QUALITY = 12;
constexpr int CAPTURE_QUALITY = 8;
// Frames dropped after switching to full size, so the capture isn't a
// half-switched frame and auto-exposure has a moment at the new size. This
// happens on the frozen "1" of the countdown, before the flash.
constexpr int CAPTURE_DISCARD_FRAMES = 2;
// Frames dropped after the flash starts, so the saved frame was exposed with
// the screen white rather than queued just before it.
constexpr int FLASH_DISCARD_FRAMES = 1;
constexpr int WAKE_DISCARD_FRAMES = 3; // after re-initing the camera on wake

// -----------------------------------------------------------------------------
// Sleep. While a USB *host* (a computer) is attached, "sleep" is screen and
// camera off with the CPU still awake: light sleep drops the USB serial/JTAG
// port, which makes uploads and the serial monitor miserable. On battery or a
// power-only charger the board really light-sleeps, woken by touch INT.
// -----------------------------------------------------------------------------
constexpr bool STAY_AWAKE_ON_USB_HOST = true;

// -----------------------------------------------------------------------------
// Clock (see rtc_clock.cpp): the round display's PCF8563 keeps time; if WiFi
// credentials are in include/secrets.h, it's set from NTP once at boot and
// WiFi is switched off again. Photo names come from it.
// -----------------------------------------------------------------------------
constexpr uint8_t RTC_I2C_ADDR = 0x51; // PCF8563
constexpr time_t CLOCK_SANE_EPOCH = 1735689600; // 2025-01-01T00:00:00Z
constexpr const char *TZ_DEFAULT = "CST6CDT,M3.2.0,M11.1.0"; // US Central, US DST rules
constexpr const char *NTP_SERVER_1 = "pool.ntp.org";
constexpr const char *NTP_SERVER_2 = "time.nist.gov";
constexpr const char *HOSTNAME = "xiao-booth";
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 15000;
constexpr uint32_t NTP_SYNC_TIMEOUT_MS = 10000;

// -----------------------------------------------------------------------------
// Upload to the eink_photo_server (see upload.cpp). Runs as the booth goes to
// sleep, if include/secrets.h sets SERVER_URL and UPLOAD_TOKEN. The source id
// must match the server's devices.yaml `sources:` entry.
// -----------------------------------------------------------------------------
constexpr const char *UPLOAD_SOURCE = "photobooth";
constexpr uint32_t UPLOAD_HTTP_TIMEOUT_MS = 20000; // per photo
constexpr uint32_t UPLOAD_BUDGET_MS = 60000;       // per session; the rest go next time
