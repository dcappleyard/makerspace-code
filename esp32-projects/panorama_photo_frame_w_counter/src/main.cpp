#include <Arduino.h>

// Must be included before TFT_eSPI.h -- Seeed_GFX's ESP32-S3 processor header
// (Processors/TFT_eSPI_ESP32_S3.h) does `#define FS_NO_GLOBALS` before pulling
// in FS.h, which suppresses `using fs::File;`/`using fs::FS;` and breaks
// unqualified `File`/`FS` use elsewhere -- including SD.open()'s return type.
// Same fix as ../eink_sd_test/src/main.cpp.
#include <FS.h>

#include <TFT_eSPI.h>
#include <SPI.h>
#include <SD.h>
#include <Preferences.h>
#include <esp_sleep.h>
#include <time.h>
#include <sys/time.h>
#include <vector>
#include <algorithm>

#ifdef EPAPER_ENABLE
EPaper epaper;
#endif

Preferences preferences;

// Same physical buttons as ../ee03-text-test and ../eink_sd_test (GPIO 2/3/5,
// the kit's built-in buttons). GPIO2 forces an immediate image refresh/cycle;
// GPIO3/5 adjust a persistent, display-only counter that never touches the
// panel on its own (deferred redraw -- see the counter branch in setup()).
constexpr int BUTTON_REFRESH = 2;
constexpr int BUTTON_COUNTER_UP = 3;
constexpr int BUTTON_COUNTER_DOWN = 5;
constexpr uint64_t BUTTON_BITMASK =
    (1ULL << BUTTON_REFRESH) | (1ULL << BUTTON_COUNTER_UP) | (1ULL << BUTTON_COUNTER_DOWN);

// SD card on its own SPI host (SPIClass(FSPI) -> SPI2_HOST), completely
// separate from the EE03 panel's bus (HSPI/SPI3_HOST), so the two never
// contend -- same wiring proven in ../eink_sd_test. Pins/freq ported from
// there verbatim.
constexpr int SD_SPI_SCLK = 11;
constexpr int SD_SPI_MISO = 12;
constexpr int SD_SPI_MOSI = 13;
constexpr int SD_CS = 39;
constexpr uint32_t SD_FREQUENCY_HZ = 4000000;
SPIClass sdSPI(FSPI);

// Fixed EE03 panel resolution.
constexpr int IMAGE_WIDTH = 1872;
constexpr int IMAGE_HEIGHT = 1404;
constexpr size_t IMAGE_BYTES = (size_t)IMAGE_WIDTH * IMAGE_HEIGHT / 2;

// The photo strip: a fixed 6:17 region on the panel's long edge, vertically
// centered on the canvas. MUST stay in sync (by hand) with REGION_HEIGHT/
// REGION_TOP in python-projects/grayscale_image_conversion/prepare_image.py --
// the .bin files are baked with white everywhere outside rows
// REGION_TOP..REGION_TOP+REGION_HEIGHT, and the caption line is drawn just
// below that strip.
constexpr int REGION_HEIGHT = 661; // round(1872 * 6/17)
constexpr int REGION_TOP = (IMAGE_HEIGHT - REGION_HEIGHT) / 2; // 371
constexpr int REGION_BOTTOM = REGION_TOP + REGION_HEIGHT;      // 1032
// Text lines bracket the photo. The header (above the strip) is font 2. The
// caption (below the strip) mixes font 2 on the left and font 4 on the right;
// the two are bottom-aligned on a shared edge (CAPTION_BOTTOM_Y) so their ends
// line up despite the height difference. CAPTION_GAP is the base gap between the
// strip and the nearest text edge; EDGE_NUDGE pushes each line a bit further
// toward its panel edge (header up, caption down).
constexpr int FONT2_HEIGHT = 16; // TFT_eSPI built-in font 2
constexpr int FONT4_HEIGHT = 26; // TFT_eSPI built-in font 4
constexpr int CAPTION_GAP = 8;
constexpr int EDGE_NUDGE = 16;
constexpr int TITLE_Y = REGION_TOP - CAPTION_GAP - EDGE_NUDGE - FONT2_HEIGHT;             // 331, header top (font 2, top datum)
constexpr int CAPTION_BOTTOM_Y = REGION_BOTTOM + CAPTION_GAP + EDGE_NUDGE + FONT4_HEIGHT; // 1082, caption shared bottom (bottom datum)

// Fallback refresh cadence if /frame_config.xml is missing/unparseable. The
// live value is read from the SD card's <refresh_hours> on each full refresh.
constexpr uint32_t DEFAULT_REFRESH_HOURS = 2;

constexpr uint64_t MIN_SLEEP_SEC = 5;

// Seeed_GFX's 16-gray update() is fire-and-forget: unlike its B/W path (which
// ends in tconWaitForDisplayReady()), the gray path issues the panel refresh
// and immediately tconSleep()s without waiting for the waveform to finish. If
// we deep-sleep (or a rapid refresh-button press triggers a new cycle) before
// it completes, the refresh is truncated and the prior image ghosts through.
// Hold awake this long after update() to let the waveform develop first. A full
// 16-gray refresh on this 10.3" panel is ~1-2s; this is deliberately generous
// and can be trimmed once verified on hardware (it's pure awake-time cost, once
// per refresh, against a multi-hour sleep -- negligible for battery).
constexpr unsigned long GRAY_REFRESH_SETTLE_MS = 3000;
// Generous during bring-up: `pio run -t upload` has its own startup overhead
// (dependency scanning) between pressing reset and esptool actually opening
// the port, which easily eats a short window before the device is attempted.
// Safe to shorten once the device isn't being reflashed frequently.
constexpr unsigned long TIME_SET_WINDOW_MS = 120000;
constexpr const char *NVS_NAMESPACE = "frame";

const char *PICTURES_DIR = "/pictures";
const char *CONFIG_PATH = "/frame_config.xml";
const char *COUNTER_TRACK_PATH = "/counter_track.txt";

// Battery placeholder text. Currently NOT drawn -- the top-right battery label
// was removed pending real battery sensing; kept here for when it's wired up.
const char *BATTERY_PLACEHOLDER = "BAT --%";

// Counter lives in /frame_config.xml now (not NVS) -- see readConfig()/
// writeConfigCounter() -- so it's not part of FrameState.
struct FrameState
{
    uint8_t imgIndex;
    int64_t nextRefEpoch;
    bool clockValid;
};

// Parsed from a photo's .xml sidecar. `location` is captured but not drawn on
// its own line; `title` is the field the Python tool prompts for as "Title".
struct PhotoMeta
{
    String artist;
    String date;
    String location;
    String title;
    String film;
};

// Parsed from /frame_config.xml. `counter` is the persistent, editable counter
// value -- its boot value and where GPIO counter changes are written back.
struct FrameConfig
{
    uint32_t refreshHours;
    int32_t counter;
};

FrameState loadState()
{
    FrameState state;
    preferences.begin(NVS_NAMESPACE, true /* read-only */);
    state.imgIndex = preferences.getUChar("imgIndex", 0);
    state.nextRefEpoch = preferences.getLong64("nextRefEpoch", 0);
    state.clockValid = preferences.getBool("rtcValid", false);
    preferences.end();
    return state;
}

// Opened/closed per write rather than held open, so each change is flushed
// immediately instead of risking loss if power is cut before some later
// end() call.
void persistImageState(uint8_t imgIndex, int64_t nextRefEpoch)
{
    preferences.begin(NVS_NAMESPACE, false);
    preferences.putUChar("imgIndex", imgIndex);
    preferences.putLong64("nextRefEpoch", nextRefEpoch);
    preferences.end();
}

void persistClockValid(bool valid)
{
    preferences.begin(NVS_NAMESPACE, false);
    preferences.putBool("rtcValid", valid);
    preferences.end();
}

// Brings up the SD card on its dedicated SPI host. Returns false (and leaves
// the bus torn down) if the card can't be mounted, so callers can fail soft.
bool mountSd()
{
    pinMode(SD_CS, OUTPUT);
    digitalWrite(SD_CS, HIGH);
    sdSPI.begin(SD_SPI_SCLK, SD_SPI_MISO, SD_SPI_MOSI, SD_CS);

    if (!SD.begin(SD_CS, sdSPI, SD_FREQUENCY_HZ))
    {
        Serial.println("SD.begin() failed -- check card/wiring");
        sdSPI.end();
        return false;
    }
    if (SD.cardType() == CARD_NONE)
    {
        Serial.println("No SD card detected (cardType == CARD_NONE)");
        SD.end();
        sdSPI.end();
        return false;
    }
    return true;
}

void unmountSd()
{
    SD.end();
    sdSPI.end();
}

// Returns the inner text of <tag>...</tag> from a small XML document, or "" if
// the tag isn't present. Deliberately tiny -- these sidecar/config files are
// produced by prepare_image.py, not arbitrary XML.
String readTag(const String &xml, const char *tag)
{
    String open = String("<") + tag + ">";
    String close = String("</") + tag + ">";
    int start = xml.indexOf(open);
    if (start < 0)
    {
        return "";
    }
    start += open.length();
    int end = xml.indexOf(close, start);
    if (end < 0)
    {
        return "";
    }
    String value = xml.substring(start, end);
    value.trim();
    return value;
}

// Undo the &amp;/&lt;/&gt; escaping prepare_image.py applies (plus quot/apos
// for good measure). &amp; must be last so "&amp;lt;" doesn't over-decode.
String xmlUnescape(String s)
{
    s.replace("&lt;", "<");
    s.replace("&gt;", ">");
    s.replace("&quot;", "\"");
    s.replace("&apos;", "'");
    s.replace("&amp;", "&");
    return s;
}

// Scans /pictures for *.bin files (skipping macOS ._ shadow files), returning
// their basenames sorted by filename == display order.
std::vector<String> listPictures()
{
    std::vector<String> bins;

    File dir = SD.open(PICTURES_DIR);
    if (!dir || !dir.isDirectory())
    {
        Serial.printf("%s missing or not a directory\n", PICTURES_DIR);
        return bins;
    }

    for (File entry = dir.openNextFile(); entry; entry = dir.openNextFile())
    {
        if (!entry.isDirectory())
        {
            String name = entry.name();
            int slash = name.lastIndexOf('/');
            if (slash >= 0)
            {
                name = name.substring(slash + 1);
            }
            if (!name.startsWith("._") && name.endsWith(".bin"))
            {
                bins.push_back(name);
            }
        }
        entry.close();
    }
    dir.close();

    std::sort(bins.begin(), bins.end());
    return bins;
}

// Reads a packed nibble image straight from the SD card into a PSRAM buffer.
// Caller owns the returned buffer and must free() it. Returns nullptr on any
// failure (missing file, alloc failure, short read).
uint8_t *loadImageBuffer(const String &binName)
{
    String path = String(PICTURES_DIR) + "/" + binName;

    File f = SD.open(path, FILE_READ);
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

// Reads <binBase>.xml alongside the image. A missing/partial sidecar just
// yields blank fields (the caption renders them as empty).
PhotoMeta loadPhotoMeta(const String &binName)
{
    PhotoMeta meta;

    // Swap the .bin extension for .xml.
    String xmlName = binName.substring(0, binName.length() - 4) + ".xml";
    String path = String(PICTURES_DIR) + "/" + xmlName;

    File f = SD.open(path, FILE_READ);
    if (!f)
    {
        Serial.printf("No sidecar %s -- caption fields blank\n", path.c_str());
        return meta;
    }

    String xml = f.readString();
    f.close();

    meta.artist = xmlUnescape(readTag(xml, "artist"));
    meta.date = xmlUnescape(readTag(xml, "date"));
    meta.location = xmlUnescape(readTag(xml, "location"));
    meta.title = xmlUnescape(readTag(xml, "title"));
    meta.film = xmlUnescape(readTag(xml, "film"));
    return meta;
}

// Reads /frame_config.xml. <refresh_hours> falls back to the default if the
// file is missing or the value doesn't parse to a positive integer; <counter>
// falls back to 0 if missing/blank.
FrameConfig readConfig()
{
    FrameConfig cfg;
    cfg.refreshHours = DEFAULT_REFRESH_HOURS;
    cfg.counter = 0;

    File f = SD.open(CONFIG_PATH, FILE_READ);
    if (!f)
    {
        Serial.printf("%s missing -- default %u h, counter 0\n", CONFIG_PATH,
                      (unsigned)DEFAULT_REFRESH_HOURS);
        return cfg;
    }
    String xml = f.readString();
    f.close();

    long hours = readTag(xml, "refresh_hours").toInt();
    if (hours >= 1)
    {
        cfg.refreshHours = (uint32_t)hours;
    }
    else
    {
        Serial.printf("Bad/blank refresh_hours -- using default %u h\n",
                      (unsigned)DEFAULT_REFRESH_HOURS);
    }

    // toInt() yields 0 for a missing/blank <counter>, which is the intended
    // default; a real "0" is indistinguishable but harmless.
    cfg.counter = (int32_t)readTag(xml, "counter").toInt();
    return cfg;
}

// Rewrites /frame_config.xml with <counter> set to `value`, preserving the rest
// of the file (comments, refresh_hours, formatting) via an in-place substring
// swap. If <counter> is absent it's inserted before </config>; if the file is
// missing/empty a minimal config is written. SD must already be mounted.
void writeConfigCounter(int32_t value)
{
    String xml;
    File rf = SD.open(CONFIG_PATH, FILE_READ);
    if (rf)
    {
        xml = rf.readString();
        rf.close();
    }

    String valueStr = String((long)value);
    const String openTag = "<counter>";
    const String closeTag = "</counter>";

    int open = xml.indexOf(openTag);
    int close = (open >= 0) ? xml.indexOf(closeTag, open + openTag.length()) : -1;

    if (open >= 0 && close >= 0)
    {
        xml = xml.substring(0, open + openTag.length()) + valueStr + xml.substring(close);
    }
    else
    {
        String tagLine = "  " + openTag + valueStr + closeTag + "\n";
        int cfgEnd = xml.indexOf("</config>");
        if (cfgEnd >= 0)
        {
            xml = xml.substring(0, cfgEnd) + tagLine + xml.substring(cfgEnd);
        }
        else
        {
            xml = "<config>\n" + tagLine + "</config>\n";
        }
    }

    File wf = SD.open(CONFIG_PATH, FILE_WRITE); // "w" -> truncates and rewrites
    if (!wf)
    {
        Serial.printf("Could not open %s to update counter\n", CONFIG_PATH);
        return;
    }
    wf.print(xml);
    wf.close();
}

// Appends one timestamped line per counter change to /counter_track.txt. SD
// must already be mounted (the counter-press path also reads/writes the config
// on the same mount). Uses TIME_NOT_SET when the RTC has never been set.
void appendCounterTrack(int delta, int32_t newValue, bool clockValid)
{
    File f = SD.open(COUNTER_TRACK_PATH, FILE_APPEND);
    if (!f)
    {
        Serial.printf("Could not open %s for append\n", COUNTER_TRACK_PATH);
        return;
    }

    char ts[32];
    if (clockValid)
    {
        time_t now = time(nullptr);
        struct tm timeinfo;
        localtime_r(&now, &timeinfo);
        strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", &timeinfo);
    }
    else
    {
        snprintf(ts, sizeof(ts), "TIME_NOT_SET");
    }

    f.printf("%s\t%+d\t%ld\n", ts, delta, (long)newValue);
    f.close();
}

// Only called on a true cold boot (not a deep-sleep timer/button wake -- the
// RTC domain stays powered through deep sleep). Waits up to TIME_SET_WINDOW_MS
// for a pasted Unix epoch integer (e.g. from `date +%s`); pressing Enter with
// no input skips and leaves the previous clock state untouched.
void maybeSetClockFromSerial()
{
    Serial.println();
    Serial.println("Cold boot -- to set the clock, run `date +%s` on your computer,");
    Serial.println("paste the number below, and press Enter within the window. Press");
    Serial.println("Enter with no input to skip and keep the previous clock state.");

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

// Hand-drawn separators between caption segments: the built-in fonts only cover
// ASCII 32-127, so there's no centered interpunct or double-dagger glyph to set
// as text. Each separator occupies a fixed horizontal advance; the mark is
// centered within that width and vertically on the text cell (whose bottom is
// bottomY and height is fontHeight). Signature matches SepDrawer so the segment
// renderer can call either through a function pointer.
constexpr int DOT_SEP_W = 12;    // centered-dot separator advance (font 2)
constexpr int DAGGER_SEP_W = 20; // double-dagger separator advance (font 4)

typedef void (*SepDrawer)(int x, int bottomY, int fontHeight, uint16_t color);

// A small filled interpunct (centered dot), sitting on the text's visual middle
// rather than the cell center so it reads between the letters.
void drawDotSep(int x, int bottomY, int fontHeight, uint16_t color)
{
#ifdef EPAPER_ENABLE
    int cx = x + DOT_SEP_W / 2;
    int cy = bottomY - (fontHeight * 2) / 5;
    epaper.fillCircle(cx, cy, 2, color);
#endif
}

// A stylized double dagger (double-obelisk): a vertical stem with two
// horizontal crossbars, centered vertically in the font-4 cell.
void drawDaggerSep(int x, int bottomY, int fontHeight, uint16_t color)
{
#ifdef EPAPER_ENABLE
    constexpr int glyphH = 18;
    constexpr int stemW = 2;
    constexpr int barW = 10;
    constexpr int barH = 2;
    int cx = x + DAGGER_SEP_W / 2;
    int top = bottomY - fontHeight + (fontHeight - glyphH) / 2;
    epaper.fillRect(cx - stemW / 2, top, stemW, glyphH, color);                        // stem
    epaper.fillRect(cx - barW / 2, top + glyphH / 4 - barH / 2, barW, barH, color);    // upper crossbar
    epaper.fillRect(cx - barW / 2, top + (3 * glyphH) / 4 - barH / 2, barW, barH, color); // lower crossbar
#endif
}

// Draws non-empty segments joined by a hand-drawn separator on one line,
// bottom-aligned at bottomY. leftAlign anchors the run's left edge at anchorX
// and grows right; otherwise the run is right-aligned (its right edge at
// anchorX). Font/size/color/datum are set here. Uses transparent text (single-
// arg setTextColor, fg == bg) so the background shows through.
void drawSeparatedLine(const std::vector<String> &segs, bool leftAlign,
                       int anchorX, int bottomY, uint8_t font, int fontHeight,
                       uint16_t color, int sepWidth, SepDrawer drawSep)
{
#ifdef EPAPER_ENABLE
    if (segs.empty())
    {
        return;
    }

    epaper.setTextFont(font);
    epaper.setTextSize(1);
    epaper.setTextColor(color);
    epaper.setTextDatum(BL_DATUM);

    int total = 0;
    for (size_t i = 0; i < segs.size(); i++)
    {
        if (i > 0)
        {
            total += sepWidth;
        }
        total += epaper.textWidth(segs[i]);
    }

    int x = leftAlign ? anchorX : (anchorX - total);
    for (size_t i = 0; i < segs.size(); i++)
    {
        if (i > 0)
        {
            drawSep(x, bottomY, fontHeight, color);
            x += sepWidth;
        }
        epaper.drawString(segs[i], x, bottomY);
        x += epaper.textWidth(segs[i]);
    }
#endif
}

// Header (above the strip, font 2): counter top-left (grey), battery top-right.
// Caption (below the strip, bottom-aligned on CAPTION_BOTTOM_Y, all grey):
//   left  (font 2): Title . Location . Film   (centered-dot separators)
//   right (font 4): Artist (double dagger) Date
// Empty fields are dropped with no dangling separators.
void drawTextOverlay(const PhotoMeta &meta, int32_t counter)
{
#ifdef EPAPER_ENABLE
    constexpr int margin = 24;
    const int rightX = epaper.width() - margin;

    // --- Header line (font 2, top datum): counter only ---
    // (The top-right battery label is removed for now; see BATTERY_PLACEHOLDER.)
    epaper.setTextFont(2);
    epaper.setTextSize(1);
    epaper.setTextDatum(TL_DATUM);
    epaper.setTextColor(TFT_GRAY_8); // grey, transparent background
    epaper.drawString(String((long)counter), margin, TITLE_Y);

    // --- Caption line (bottom-aligned; left font 2, right font 4) ---
    std::vector<String> leftSegs;
    if (meta.title.length())
        leftSegs.push_back(meta.title);
    if (meta.location.length())
        leftSegs.push_back(meta.location);
    if (meta.film.length())
        leftSegs.push_back(meta.film);
    drawSeparatedLine(leftSegs, true, margin, CAPTION_BOTTOM_Y,
                      2, FONT2_HEIGHT, TFT_GRAY_8, DOT_SEP_W, drawDotSep);

    std::vector<String> rightSegs;
    if (meta.artist.length())
        rightSegs.push_back(meta.artist);
    if (meta.date.length())
        rightSegs.push_back(meta.date);
    drawSeparatedLine(rightSegs, false, rightX, CAPTION_BOTTOM_Y,
                      4, FONT4_HEIGHT, TFT_GRAY_8, DAGGER_SEP_W, drawDaggerSep);
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

    bool doFullRefresh = isColdBoot || cause == ESP_SLEEP_WAKEUP_TIMER || refreshPressed;

    if (doFullRefresh)
    {
        waitForButtonRelease(BUTTON_REFRESH);

        if (!mountSd())
        {
            drawErrorScreen("SD mount failed -- check card is inserted/formatted FAT32");
            armWakeSourcesAndSleep(DEFAULT_REFRESH_HOURS * 3600ULL);
        }

        FrameConfig cfg = readConfig();
        uint64_t refreshSec = (uint64_t)cfg.refreshHours * 3600ULL;

        std::vector<String> bins = listPictures();
        if (bins.empty())
        {
            unmountSd();
            drawErrorScreen("No .bin images in /pictures -- run prepare_image.py");
            armWakeSourcesAndSleep(refreshSec);
        }

        // Cold boot resumes on the same image that was showing; a timer or
        // forced-refresh wake advances to the next one.
        uint8_t nextIndex = isColdBoot
                                ? (uint8_t)(state.imgIndex % bins.size())
                                : (uint8_t)((state.imgIndex + 1) % bins.size());

        const String &binName = bins[nextIndex];
        uint8_t *buffer = loadImageBuffer(binName);
        PhotoMeta meta = loadPhotoMeta(binName);
        unmountSd();

        time_t now = time(nullptr);

        if (buffer == nullptr)
        {
            drawErrorScreen("Failed to read image from SD card");
        }
        else
        {
#ifdef EPAPER_ENABLE
            epaper.begin();
            epaper.initGrayMode(GRAY_LEVEL16);
            epaper.pushImage(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT, (uint16_t *)buffer);
            drawTextOverlay(meta, cfg.counter);
            epaper.update();
            // Let the fire-and-forget 16-gray refresh finish before we sleep or
            // allow another refresh (see GRAY_REFRESH_SETTLE_MS) -- prevents the
            // prior image ghosting through on rapid refreshes.
            delay(GRAY_REFRESH_SETTLE_MS);
#endif
            free(buffer);
        }

        state.imgIndex = nextIndex;
        state.nextRefEpoch = (int64_t)now + refreshSec;
        persistImageState(state.imgIndex, state.nextRefEpoch);
    }
    else if (counterUpPressed || counterDownPressed)
    {
        // Deferred redraw: the counter is read from /frame_config.xml, adjusted,
        // written back, and logged to /counter_track.txt -- but the panel is
        // never touched here, so the new value only becomes visible at the next
        // full refresh.
        int pin = counterUpPressed ? BUTTON_COUNTER_UP : BUTTON_COUNTER_DOWN;
        waitForButtonRelease(pin);

        int delta = counterUpPressed ? 1 : -1;

        if (mountSd())
        {
            int32_t newCounter = readConfig().counter + delta;
            writeConfigCounter(newCounter);
            appendCounterTrack(delta, newCounter, state.clockValid);
            unmountSd();
            Serial.printf("Counter now %ld (display updates at next refresh)\n", (long)newCounter);
        }
        else
        {
            Serial.println("SD unavailable -- counter change not applied");
        }
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
