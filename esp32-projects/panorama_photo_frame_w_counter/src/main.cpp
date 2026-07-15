#include <Arduino.h>

// Must be included before TFT_eSPI.h -- Seeed_GFX's ESP32-S3 processor header
// (Processors/TFT_eSPI_ESP32_S3.h) does `#define FS_NO_GLOBALS` before pulling
// in FS.h, which suppresses `using fs::File;`/`using fs::FS;` and breaks
// unqualified `File`/`FS` use elsewhere -- including LittleFS.open()'s return
// type. Same fix as ../wifi_counter_eink/src/main.cpp.
#include <FS.h>

#include <TFT_eSPI.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <esp_sleep.h>
#include <time.h>
#include <sys/time.h>
#include <vector>

#ifdef EPAPER_ENABLE
EPaper epaper;
#endif

Preferences preferences;

// Same physical buttons as ../ee03-text-test and ../test_bw_image_eink
// (GPIO 2/3/5, the kit's built-in buttons). GPIO2 forces an immediate
// image refresh/cycle; GPIO3/5 adjust a persistent, display-only counter
// that never touches the panel on its own.
constexpr int BUTTON_REFRESH = 2;
constexpr int BUTTON_COUNTER_UP = 3;
constexpr int BUTTON_COUNTER_DOWN = 5;
constexpr uint64_t BUTTON_BITMASK =
    (1ULL << BUTTON_REFRESH) | (1ULL << BUTTON_COUNTER_UP) | (1ULL << BUTTON_COUNTER_DOWN);

// Fixed EE03 panel resolution -- matches prepare_image.py's defaults.
constexpr int IMAGE_WIDTH = 1872;
constexpr int IMAGE_HEIGHT = 1404;
constexpr size_t IMAGE_BYTES = (size_t)IMAGE_WIDTH * IMAGE_HEIGHT / 2;

// Keep these two in sync by hand -- SEC drives the actual sleep timer, LABEL
// is just what gets drawn in the overlay.
constexpr uint64_t REFRESH_INTERVAL_SEC = 2ULL * 60 * 60;
constexpr const char *REFRESH_INTERVAL_LABEL = "Every 2h";

constexpr uint64_t MIN_SLEEP_SEC = 5;
// Generous during bring-up: `pio run -t uploadfs`/`upload` have their own
// startup overhead (dependency scanning, building the FS image) between
// pressing reset and esptool actually opening the port, which easily eats
// a 20s window before the device even gets attempted. Safe to shorten once
// the device isn't being iterated on over serial anymore.
constexpr unsigned long TIME_SET_WINDOW_MS = 120000;
constexpr const char *NVS_NAMESPACE = "frame";

struct FrameState
{
    uint8_t imgIndex;
    int32_t counter;
    int64_t nextRefEpoch;
    bool clockValid;
};

struct ImageEntry
{
    String binName;
    String sourceName;
};

FrameState loadState()
{
    FrameState state;
    preferences.begin(NVS_NAMESPACE, true /* read-only */);
    state.imgIndex = preferences.getUChar("imgIndex", 0);
    state.counter = preferences.getInt("counter", 0);
    state.nextRefEpoch = preferences.getLong64("nextRefEpoch", 0);
    state.clockValid = preferences.getBool("rtcValid", false);
    preferences.end();
    return state;
}

// Opened/closed per write rather than held open, so each change is flushed
// immediately instead of risking loss if power is cut before some later
// end() call -- same pattern as ../wifi_counter_eink's loadCounter()/
// persistCounter().
void persistImageState(uint8_t imgIndex, int64_t nextRefEpoch)
{
    preferences.begin(NVS_NAMESPACE, false);
    preferences.putUChar("imgIndex", imgIndex);
    preferences.putLong64("nextRefEpoch", nextRefEpoch);
    preferences.end();
}

void persistCounter(int32_t counter)
{
    preferences.begin(NVS_NAMESPACE, false);
    preferences.putInt("counter", counter);
    preferences.end();
}

void persistClockValid(bool valid)
{
    preferences.begin(NVS_NAMESPACE, false);
    preferences.putBool("rtcValid", valid);
    preferences.end();
}

// Reads data/images/manifest.txt (uploaded via `pio run -t uploadfs`):
// one "<bin filename>\t<original source filename>" line per image, in
// display order.
std::vector<ImageEntry> loadManifest()
{
    std::vector<ImageEntry> entries;

    File f = LittleFS.open("/images/manifest.txt", "r");
    if (!f)
    {
        Serial.println("manifest.txt not found -- did you run pio run -t uploadfs?");
        return entries;
    }

    while (f.available())
    {
        String line = f.readStringUntil('\n');
        line.trim();
        if (line.length() == 0)
        {
            continue;
        }

        int tabIndex = line.indexOf('\t');
        if (tabIndex < 0)
        {
            continue;
        }

        ImageEntry entry;
        entry.binName = line.substring(0, tabIndex);
        entry.sourceName = line.substring(tabIndex + 1);
        entries.push_back(entry);
    }

    f.close();
    return entries;
}

// Reads a packed nibble image straight from LittleFS into a PSRAM buffer.
// Caller owns the returned buffer and must free() it. Returns nullptr on
// any failure (missing file, alloc failure, short read).
uint8_t *loadImageBuffer(const String &binName)
{
    String path = "/images/" + binName;

    File f = LittleFS.open(path, "r");
    if (!f)
    {
        Serial.printf("Failed to open %s\n", path.c_str());
        return nullptr;
    }

    uint8_t *buffer = (uint8_t *)ps_malloc(IMAGE_BYTES);
    if (buffer == nullptr)
    {
        Serial.println("ps_malloc failed for image buffer");
        f.close();
        return nullptr;
    }

    size_t bytesRead = f.read(buffer, IMAGE_BYTES);
    f.close();

    if (bytesRead != IMAGE_BYTES)
    {
        Serial.printf("Short read for %s: %u/%u bytes\n", path.c_str(),
                       (unsigned)bytesRead, (unsigned)IMAGE_BYTES);
        free(buffer);
        return nullptr;
    }

    return buffer;
}

// Only called on a true cold boot (not a deep-sleep timer/button wake --
// the RTC domain stays powered through deep sleep, so there's nothing to
// re-set there). Waits up to TIME_SET_WINDOW_MS for a pasted Unix epoch
// integer (e.g. from running `date +%s` on the user's computer); pressing
// Enter with no input skips and leaves the previous clock state untouched.
void maybeSetClockFromSerial()
{
    Serial.println();
    Serial.println("Cold boot -- to set the clock, run `date +%s` on your computer,");
    Serial.println("paste the number below, and press Enter within 20s. Press Enter");
    Serial.println("with no input to skip and keep the previous clock state.");

    unsigned long start = millis();
    String line;

    while (millis() - start < TIME_SET_WINDOW_MS)
    {
        if (Serial.available())
        {
            char c = (char)Serial.read();
            if (c == '\n' || c == '\r')
            {
                line.trim();
                if (line.length() > 0)
                {
                    time_t epoch = (time_t)line.toInt();
                    if (epoch > 0)
                    {
                        struct timeval tv = {.tv_sec = epoch, .tv_usec = 0};
                        settimeofday(&tv, nullptr);
                        persistClockValid(true);
                        Serial.println("Clock set.");
                    }
                }
                return;
            }
            line += c;
        }
        delay(10);
    }

    Serial.println("No input -- skipping clock set.");
}

void drawErrorScreen(const char *message)
{
#ifdef EPAPER_ENABLE
    epaper.begin();
    epaper.fillScreen(TFT_WHITE);
    epaper.setTextColor(TFT_BLACK, TFT_WHITE);
    epaper.setTextSize(2);
    epaper.setTextDatum(TL_DATUM);
    epaper.drawString(message, 40, 40);
    epaper.update();
#endif
    Serial.println(message);
}

// Draws into the panel's lower-right white margin (confirmed empirically:
// prepare_image.py's default letterboxing leaves rows ~1020-1404 solid
// white across the full 1872px width). Pixel placement is a starting
// point, not a finalized layout -- expect to tune it visually on hardware.
void drawTextOverlay(const String &filename, int32_t counter, bool clockValid, time_t lastRefresh)
{
#ifdef EPAPER_ENABLE
    constexpr int margin = 24;
    constexpr int lineHeight = 40;
    const int rightX = epaper.width() - margin;
    int y = epaper.height() - margin - (lineHeight * 4);

    epaper.setTextDatum(TR_DATUM);
    epaper.setTextSize(2);
    epaper.setTextColor(TFT_BLACK, TFT_WHITE);

    char line[64];

    if (clockValid)
    {
        struct tm timeinfo;
        localtime_r(&lastRefresh, &timeinfo);
        strftime(line, sizeof(line), "%Y-%m-%d %H:%M", &timeinfo);
    }
    else
    {
        snprintf(line, sizeof(line), "Time not set");
    }
    epaper.drawString(line, rightX, y);
    y += lineHeight;

    snprintf(line, sizeof(line), "Counter: %ld", (long)counter);
    epaper.drawString(line, rightX, y);
    y += lineHeight;

    epaper.drawString(REFRESH_INTERVAL_LABEL, rightX, y);
    y += lineHeight;

    epaper.drawString(filename.c_str(), rightX, y);
#endif
}

void waitForButtonRelease(int pin)
{
    while (digitalRead(pin) == LOW)
    {
        delay(10);
    }
}

// Re-arms both wake sources (GPIO config doesn't survive deep sleep, so
// pinMode must be repeated every boot) and never returns.
void armWakeSourcesAndSleep(uint64_t sleepSec)
{
    pinMode(BUTTON_REFRESH, INPUT_PULLUP);
    pinMode(BUTTON_COUNTER_UP, INPUT_PULLUP);
    pinMode(BUTTON_COUNTER_DOWN, INPUT_PULLUP);

    esp_sleep_enable_timer_wakeup(sleepSec * 1000000ULL);
    esp_sleep_enable_ext1_wakeup(BUTTON_BITMASK, ESP_EXT1_WAKEUP_ANY_LOW);

#ifdef EPAPER_ENABLE
    epaper.sleep();
#endif

    Serial.printf("Sleeping for %llus\n", (unsigned long long)sleepSec);
    Serial.flush();
    esp_deep_sleep_start();
}

void setup()
{
    Serial.begin(115200);
    delay(1000);

    pinMode(BUTTON_REFRESH, INPUT_PULLUP);
    pinMode(BUTTON_COUNTER_UP, INPUT_PULLUP);
    pinMode(BUTTON_COUNTER_DOWN, INPUT_PULLUP);

    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    uint64_t ext1Status = esp_sleep_get_ext1_wakeup_status();

    bool refreshPressed = ext1Status & (1ULL << BUTTON_REFRESH);
    bool counterUpPressed = ext1Status & (1ULL << BUTTON_COUNTER_UP);
    bool counterDownPressed = ext1Status & (1ULL << BUTTON_COUNTER_DOWN);

    // A true cold boot/reset is anything that isn't a deep-sleep timer or
    // ext1 (button) wake.
    bool isColdBoot = (cause != ESP_SLEEP_WAKEUP_TIMER && cause != ESP_SLEEP_WAKEUP_EXT1);

    if (isColdBoot)
    {
        maybeSetClockFromSerial();
    }

    FrameState state = loadState();

    if (!LittleFS.begin(false /* do not auto-format */))
    {
        drawErrorScreen("LittleFS mount failed -- run: pio run -t uploadfs");
        armWakeSourcesAndSleep(REFRESH_INTERVAL_SEC);
    }

    std::vector<ImageEntry> images = loadManifest();
    if (images.empty())
    {
        drawErrorScreen("No images in manifest -- run tools/pack_images.py + uploadfs");
        armWakeSourcesAndSleep(REFRESH_INTERVAL_SEC);
    }

    bool doFullRefresh = isColdBoot || cause == ESP_SLEEP_WAKEUP_TIMER || refreshPressed;

    if (doFullRefresh)
    {
        waitForButtonRelease(BUTTON_REFRESH);

        // Cold boot resumes on the same image that was showing; a timer or
        // forced-refresh wake advances to the next one.
        uint8_t nextIndex = isColdBoot
                                 ? (uint8_t)(state.imgIndex % images.size())
                                 : (uint8_t)((state.imgIndex + 1) % images.size());

        const ImageEntry &entry = images[nextIndex];
        uint8_t *buffer = loadImageBuffer(entry.binName);
        time_t now = time(nullptr);

        if (buffer == nullptr)
        {
            drawErrorScreen("Failed to read image from LittleFS");
        }
        else
        {
#ifdef EPAPER_ENABLE
            epaper.begin();
            epaper.initGrayMode(GRAY_LEVEL16);
            epaper.pushImage(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT, (uint16_t *)buffer);
            drawTextOverlay(entry.sourceName, state.counter, state.clockValid, now);
            epaper.update();
#endif
            free(buffer);
        }

        state.imgIndex = nextIndex;
        state.nextRefEpoch = (int64_t)now + REFRESH_INTERVAL_SEC;
        persistImageState(state.imgIndex, state.nextRefEpoch);
    }
    else if (counterUpPressed || counterDownPressed)
    {
        // Deferred redraw: the counter persists immediately but the panel
        // is never touched here -- the new value only becomes visible at
        // the next full refresh.
        int pin = counterUpPressed ? BUTTON_COUNTER_UP : BUTTON_COUNTER_DOWN;
        waitForButtonRelease(pin);

        state.counter += counterUpPressed ? 1 : -1;
        persistCounter(state.counter);
        Serial.printf("Counter now %ld (display updates at next refresh)\n", (long)state.counter);
    }

    time_t now = time(nullptr);
    int64_t remaining = state.nextRefEpoch - (int64_t)now;
    uint64_t sleepSec = remaining > (int64_t)MIN_SLEEP_SEC ? (uint64_t)remaining : MIN_SLEEP_SEC;

    armWakeSourcesAndSleep(sleepSec);
}

void loop()
{
    // Unreachable: setup() always ends in esp_deep_sleep_start(), and a
    // deep-sleep wake re-enters setup() via a full reset, never loop().
}
