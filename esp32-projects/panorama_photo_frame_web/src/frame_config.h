#pragma once

// -----------------------------------------------------------------------------
// Shared constants, types, and -- critically -- the one place the fragile
// include order is enforced. Every .cpp in this project MUST include this
// header FIRST, before anything else.
// -----------------------------------------------------------------------------

#include <Arduino.h>

// Must be included before TFT_eSPI.h -- Seeed_GFX's ESP32-S3 processor header
// (Processors/TFT_eSPI_ESP32_S3.h) does `#define FS_NO_GLOBALS` before pulling
// in FS.h, which suppresses `using fs::File;`/`using fs::FS;` and breaks
// unqualified `File`/`FS` use elsewhere. This project trips that twice over:
// SD.open()'s return type (as in ../panorama_photo_frame_w_counter) AND
// WebServer.h's own unqualified use of `FS` (as in ../wifi_counter_eink).
// Including FS.h here first lets its `using` declarations fire while global;
// FS.h's include guard then makes TFT_eSPI.h's later include a no-op.
//
// Keeping this in a header that every translation unit includes first is
// deliberate: it makes the rule structural rather than a comment somebody can
// accidentally regress by reordering includes in a new file.
#include <FS.h>

#include <TFT_eSPI.h>

#include <vector>

// -----------------------------------------------------------------------------
// Buttons -- same physical pins as the sibling EE03 projects (the kit's
// built-in buttons, active LOW with internal pullups). Unlike
// ../panorama_photo_frame_w_counter these are polled in loop(), not used as
// deep-sleep ext1 wake sources: this build never sleeps.
// -----------------------------------------------------------------------------
constexpr int BUTTON_REFRESH = 2;      // advance to the next photo
constexpr int BUTTON_COUNTER_UP = 3;   // counter +1
constexpr int BUTTON_COUNTER_DOWN = 5; // counter -1
constexpr unsigned long BUTTON_DEBOUNCE_MS = 50;

// -----------------------------------------------------------------------------
// SD card on its own SPI host (SPIClass(FSPI) -> SPI2_HOST), completely
// separate from the EE03 panel's bus (HSPI/SPI3_HOST), so the two never
// contend -- wiring proven in ../eink_sd_test.
// -----------------------------------------------------------------------------
constexpr int SD_SPI_SCLK = 11;
constexpr int SD_SPI_MISO = 12;
constexpr int SD_SPI_MOSI = 13;
constexpr int SD_CS = 39;

// Raised from the 4MHz the sibling project used. SD-over-SPI is specified to
// 25MHz and 20MHz is a clean divisor of the 80MHz APB clock (N=4), so there's
// no rounding; the panel is on a different SPI peripheral entirely, so there's
// nothing to contend with. This is the highest-leverage constant here: it cuts
// the 1.3MB image read on every refresh from ~5s to ~1.3s AND speeds uploads.
// If the card starts failing to mount, reading short, or corrupting writes,
// step DOWN this ladder: 20 -> 16 -> 10 -> 4 MHz. The breakout is jumper-wired,
// so signal integrity is the plausible failure, not the card.
constexpr uint32_t SD_FREQUENCY_HZ = 20000000;

// -----------------------------------------------------------------------------
// Panel geometry -- IDENTICAL to ../panorama_photo_frame_w_counter. The display
// side of this project is deliberately unchanged.
// -----------------------------------------------------------------------------
constexpr int IMAGE_WIDTH = 1872;
constexpr int IMAGE_HEIGHT = 1404;
constexpr size_t IMAGE_BYTES = (size_t)IMAGE_WIDTH * IMAGE_HEIGHT / 2; // 1314144

// The photo strip: a fixed 6:17 region on the panel's long edge, vertically
// centered. MUST stay in sync (by hand) with REGION_HEIGHT/REGION_TOP in
// python-projects/grayscale_image_conversion/prepare_image.py -- the .bin files
// are baked with white everywhere outside these rows.
constexpr int REGION_HEIGHT = 661;                             // round(1872 * 6/17)
constexpr int REGION_TOP = (IMAGE_HEIGHT - REGION_HEIGHT) / 2; // 371
constexpr int REGION_BOTTOM = REGION_TOP + REGION_HEIGHT;      // 1032

constexpr int FONT2_HEIGHT = 16; // TFT_eSPI built-in font 2
constexpr int FONT4_HEIGHT = 26; // TFT_eSPI built-in font 4
constexpr int CAPTION_GAP = 8;
constexpr int EDGE_NUDGE = 16;
constexpr int TITLE_Y = REGION_TOP - CAPTION_GAP - EDGE_NUDGE - FONT2_HEIGHT;             // 331
constexpr int CAPTION_BOTTOM_Y = REGION_BOTTOM + CAPTION_GAP + EDGE_NUDGE + FONT4_HEIGHT; // 1082

constexpr int TEXT_MARGIN = 24;

// Largest single counter step offered by the web UI's -5..+5 button row (0 is
// omitted -- it would be a no-op that still costs an SD write and a history
// line). The GPIO buttons remain +/-1. appendCounterTrack()'s "%+d" format
// already handles any step size, so nothing downstream is limited by this.
constexpr int COUNTER_STEP_MAX = 5;

// Seeed_GFX's 16-gray update() is fire-and-forget: unlike its B/W path (which
// ends in tconWaitForDisplayReady()), the gray path issues the panel refresh
// and immediately tconSleep()s without waiting for the waveform to finish.
// Touching the panel again before it completes truncates the refresh and ghosts
// the prior image. Unlike the sibling project this is NOT a delay() -- it's a
// millis() gate (see serviceRefresh() in main.cpp), so the web server stays
// responsive throughout.
constexpr unsigned long GRAY_REFRESH_SETTLE_MS = 3000;

// -----------------------------------------------------------------------------
// Refresh cadence
// -----------------------------------------------------------------------------
constexpr uint32_t DEFAULT_REFRESH_HOURS = 2;
// Clamped so refreshIntervalMs stays an order of magnitude clear of the
// millis() rollover at 2^32 ms (~49.7 days). 168h = 7 days.
constexpr uint32_t MIN_REFRESH_HOURS = 1;
constexpr uint32_t MAX_REFRESH_HOURS = 168;

// -----------------------------------------------------------------------------
// Clock. There is no persisted "clock was set" flag in this build: with no deep
// sleep, a reset is always a genuine power loss, so a stored flag would lie.
// Validity is derived live by sanity-checking the epoch instead.
// -----------------------------------------------------------------------------
constexpr time_t CLOCK_SANE_EPOCH = 1735689600; // 2025-01-01T00:00:00Z
// Madison, WI -- US Central with US DST rules (2nd Sun Mar -> 1st Sun Nov).
constexpr const char *TZ_DEFAULT = "CST6CDT,M3.2.0,M11.1.0";
constexpr const char *NTP_SERVER_1 = "pool.ntp.org";
constexpr const char *NTP_SERVER_2 = "time.nist.gov";

// -----------------------------------------------------------------------------
// Network
// -----------------------------------------------------------------------------
constexpr const char *HOSTNAME = "photo-frame";
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 60000;

// -----------------------------------------------------------------------------
// SD card paths
// -----------------------------------------------------------------------------
extern const char *PICTURES_DIR;
extern const char *CONFIG_PATH;
extern const char *COUNTER_TRACK_PATH;
extern const char *UPLOAD_TMP_BIN;
extern const char *UPLOAD_TMP_XML;

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

// Parsed from a photo's .xml sidecar. `location` is captured but not drawn on
// its own line; `title` is the field the Python tool prompts for as "Title".
// The color* members are per-corner text colors (gray levels 0-15) that
// prepare_image.py picks for contrast against the image; they default to the
// house grey so an older sidecar without them still renders.
struct PhotoMeta
{
    String artist;
    String date;
    String location;
    String title;
    String film;
    uint16_t colorTopLeft = TFT_GRAY_8;
    uint16_t colorTopRight = TFT_GRAY_8;
    uint16_t colorBottomLeft = TFT_GRAY_8;
    uint16_t colorBottomRight = TFT_GRAY_8;
};

// Parsed from /frame_config.xml.
struct FrameConfig
{
    uint32_t refreshHours = DEFAULT_REFRESH_HOURS;
    int32_t counter = 0;
    String timezone = TZ_DEFAULT;
};

#ifdef EPAPER_ENABLE
extern EPaper epaper;
#endif
