#include "frame_config.h" // MUST be first -- see the include-order note there

#include "app.h"
#include "storage.h"
#include "web.h"

#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <time.h>
#include <sys/time.h>

#include "secrets.h" // WIFI_SSID / WIFI_PASSWORD -- gitignored, see README.md

#ifdef EPAPER_ENABLE
EPaper epaper;
#endif

// Battery placeholder text. Still not drawn -- but note this build targets the
// XIAO ESP32-S3 Plus board id, whose variant header defines BAT_VOLT_PIN
// (ADC_BAT = GPIO10). That's the missing piece if real battery sensing ever
// gets wired up; the top-right corner now shows network status instead.
const char *BATTERY_PLACEHOLDER = "BAT --%";

namespace
{

Preferences preferences;

// NVS namespace/key. This build stores exactly one thing. The sibling project
// also kept nextRefEpoch and rtcValid, both of which existed only to survive
// the deep-sleep reboot -- see the notes on the scheduler and the clock below.
constexpr const char *NVS_NAMESPACE = "frame";
constexpr const char *NVS_KEY_IMG = "imgName";

// --- Refresh scheduling -------------------------------------------------
//
// The deadline is tracked in millis(), NOT as an absolute epoch, and that is
// not a stylistic choice. The ESP32 boots at epoch 0 and NTP steps the clock by
// decades within seconds of connecting. An epoch deadline computed before that
// sync would be instantly overdue afterwards (refresh storm); a backward
// correction would push it years away. millis() is monotonic and completely
// immune to settimeofday().
//
// The unsigned subtraction below is correct across the ~49.7-day millis()
// rollover for any interval < 2^31 ms; refreshHours is clamped to 168 (7 days)
// in readConfig() to stay an order of magnitude clear of that boundary.
uint32_t lastRefreshMs = 0;
uint32_t refreshMs = DEFAULT_REFRESH_HOURS * 3600UL * 1000UL;

bool refreshDue()
{
    return (uint32_t)(millis() - lastRefreshMs) >= refreshMs;
}

// --- Display state machine ----------------------------------------------
enum DisplayState : uint8_t
{
    DISP_IDLE,
    DISP_SETTLING,
};

PendingAction pendingAction = PENDING_NONE;
String pendingJumpName;
DisplayState displayState = DISP_IDLE;
uint32_t settleUntilMs = 0;

// --- Photo state --------------------------------------------------------
String currentPhoto;              // basename of the .bin currently displayed
std::vector<String> cachedPhotos; // /pictures listing, refreshed on demand
bool picturesDirty = true;

FrameConfig config;

// --- Network state ------------------------------------------------------
bool wifiWasUp = false;
uint32_t lastWifiTryMs = 0;

// --- Button state -------------------------------------------------------
struct ButtonState
{
    int pin;
    bool lastLevelLow;
    unsigned long lastChangeMs;
};

ButtonState buttons[] = {
    {BUTTON_REFRESH, false, 0},
    {BUTTON_COUNTER_UP, false, 0},
    {BUTTON_COUNTER_DOWN, false, 0},
};

} // namespace

// =============================================================================
// NVS
// =============================================================================

// The current photo is persisted by NAME, not by index. listPictures() sorts by
// filename, so uploading a photo that sorts early shifts every index by one --
// an index-based scheme would silently resume on the wrong photo after any
// upload. A name survives that; if the file is gone we fall back to the first.
String loadPhotoName()
{
    preferences.begin(NVS_NAMESPACE, true /* read-only */);
    String name = preferences.getString(NVS_KEY_IMG, "");
    preferences.end();
    return name;
}

void persistPhotoName(const String &name)
{
    preferences.begin(NVS_NAMESPACE, false);
    preferences.putString(NVS_KEY_IMG, name);
    preferences.end();
}

// =============================================================================
// Clock
// =============================================================================

// No persisted "the clock was set" flag in this build. With deep sleep gone, a
// reset is always a genuine power loss, so a stored flag would report "valid"
// for a clock that had just reset to 1970. Sanity-check the epoch instead.
bool clockValid()
{
    return time(nullptr) > CLOCK_SANE_EPOCH;
}

String formatLocalTime()
{
    if (!clockValid())
    {
        return "not set";
    }
    time_t now = time(nullptr);
    struct tm timeinfo;
    localtime_r(&now, &timeinfo);
    char buf[48];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S %Z", &timeinfo);
    return String(buf);
}

// configTzTime() is non-blocking: it stops any running SNTP, sets the servers,
// starts SNTP in poll mode, then setenv("TZ")/tzset(). Safe to call before WiFi
// is up (SNTP just retries) and safe to call repeatedly, which is what makes
// the reconnect re-kick and the timezone-change path trivial.
void applyTimeConfig()
{
    configTzTime(config.timezone.c_str(), NTP_SERVER_1, NTP_SERVER_2);
}

bool setClockFromEpoch(time_t epoch)
{
    if (epoch <= CLOCK_SANE_EPOCH)
    {
        return false;
    }
    struct timeval tv = {.tv_sec = epoch, .tv_usec = 0};
    settimeofday(&tv, nullptr);
    Serial.printf("Clock set manually: %s\n", formatLocalTime().c_str());
    return true;
}

bool setTimezone(const String &tz)
{
    if (tz.length() == 0 || tz.length() > 64)
    {
        return false;
    }
    config.timezone = tz;
    writeConfigTag("timezone", tz);
    applyTimeConfig();
    return true;
}

// =============================================================================
// WiFi
// =============================================================================

bool wifiConnected()
{
    return WiFi.status() == WL_CONNECTED;
}

String wifiStatusText()
{
    if (wifiConnected())
    {
        return WiFi.localIP().toString();
    }
    return "no wifi";
}

// Bounded, unlike ../wifi_counter_eink's `while (WiFi.status() != WL_CONNECTED)
// delay(500);` -- that spins forever if the AP is unreachable. This is a photo
// frame first: if WiFi never comes up, the frame must still boot, mount the
// card, draw a photo, and honour its buttons.
bool connectWiFi(uint32_t timeoutMs)
{
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(HOSTNAME); // must precede begin()
    WiFi.setAutoReconnect(true);
    WiFi.setSleep(false); // steadier server latency; free, since we're on mains
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.printf("Connecting to WiFi (up to %us)...\n", (unsigned)(timeoutMs / 1000));
    bool ok = WiFi.waitForConnectResult(timeoutMs) == WL_CONNECTED;
    if (ok)
    {
        Serial.printf("WiFi up: %s\n", WiFi.localIP().toString().c_str());
    }
    else
    {
        Serial.println("WiFi failed -- continuing without it (frame still works)");
    }
    return ok;
}

void startMdns()
{
    MDNS.end(); // re-announce cleanly after a reconnect
    if (MDNS.begin(HOSTNAME))
    {
        MDNS.addService("http", "tcp", 80);
        Serial.printf("mDNS: http://%s.local/\n", HOSTNAME);
    }
    else
    {
        Serial.println("mDNS setup failed -- use the IP address instead.");
    }
}

// Never blocks. setAutoReconnect() handles most transient drops on its own;
// this covers the cases it doesn't (AP rebooted, DHCP failure).
void serviceWiFi()
{
    if (wifiConnected())
    {
        if (!wifiWasUp)
        {
            wifiWasUp = true;
            Serial.printf("WiFi up: %s\n", WiFi.localIP().toString().c_str());
            startMdns();
            applyTimeConfig(); // re-kick SNTP now that there's a route out
            // The panel's top-right corner shows the IP, so it's worth a redraw
            // once we actually have one to show.
            queueAction(PENDING_REDRAW);
        }
        return;
    }

    wifiWasUp = false;
    if ((uint32_t)(millis() - lastWifiTryMs) < WIFI_RETRY_INTERVAL_MS)
    {
        return;
    }
    lastWifiTryMs = millis();
    Serial.println("WiFi down -- retrying");
    WiFi.disconnect(false, false);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD); // non-blocking; checked next pass
}

// =============================================================================
// Display -- copied verbatim from ../panorama_photo_frame_w_counter apart from
// the top-right network line. The display side of this project is deliberately
// unchanged.
// =============================================================================

void drawErrorScreen(const char *message)
{
#ifdef EPAPER_ENABLE
    epaper.fillScreen(TFT_WHITE);
    epaper.setTextColor(TFT_BLACK, TFT_WHITE);
    epaper.setTextSize(2);
    epaper.setTextDatum(TL_DATUM);
    epaper.drawString(message, 40, 40);
    // Where to reach the device, so a cardless boot isn't a dead end.
    String where = String(HOSTNAME) + ".local  /  " + wifiStatusText();
    epaper.drawString(where, 40, 100);
    epaper.update();
#endif
    Serial.println(message);
}

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
    epaper.fillRect(cx - stemW / 2, top, stemW, glyphH, color);                            // stem
    epaper.fillRect(cx - barW / 2, top + glyphH / 4 - barH / 2, barW, barH, color);        // upper crossbar
    epaper.fillRect(cx - barW / 2, top + (3 * glyphH) / 4 - barH / 2, barW, barH, color);  // lower crossbar
#endif
}

// Draws non-empty segments joined by a hand-drawn separator on one line,
// bottom-aligned at bottomY. Uses transparent text (single-arg setTextColor) so
// the background shows through.
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

// Header (above the strip, font 2): counter top-left, network status top-right.
// Caption (below the strip, bottom-aligned on CAPTION_BOTTOM_Y):
//   left  (font 2): Title . Location . Film   (centered-dot separators)
//   right (font 4): Artist (double dagger) Date
// Empty fields are dropped with no dangling separators.
void drawTextOverlay(const PhotoMeta &meta, int32_t counter)
{
#ifdef EPAPER_ENABLE
    const int rightX = epaper.width() - TEXT_MARGIN;

    epaper.setTextFont(2);
    epaper.setTextSize(1);

    // --- Header left: counter ---
    epaper.setTextDatum(TL_DATUM);
    epaper.setTextColor(meta.colorTopLeft); // per-corner color, transparent bg
    epaper.drawString(String((long)counter), TEXT_MARGIN, TITLE_Y);

    // --- Header right: network status ---
    // This corner was previously empty (the battery placeholder was removed),
    // but prepare_image.py has been computing text_color_top_right for it all
    // along -- so showing the IP here costs no new geometry and no new metadata.
    // It updates at refresh time, not instantly; see README.
    epaper.setTextDatum(TR_DATUM);
    epaper.setTextColor(meta.colorTopRight);
    epaper.drawString(wifiStatusText(), rightX, TITLE_Y);

    // --- Caption line (bottom-aligned; left font 2, right font 4) ---
    std::vector<String> leftSegs;
    if (meta.title.length())
        leftSegs.push_back(meta.title);
    if (meta.location.length())
        leftSegs.push_back(meta.location);
    if (meta.film.length())
        leftSegs.push_back(meta.film);
    drawSeparatedLine(leftSegs, true, TEXT_MARGIN, CAPTION_BOTTOM_Y,
                      2, FONT2_HEIGHT, meta.colorBottomLeft, DOT_SEP_W, drawDotSep);

    std::vector<String> rightSegs;
    if (meta.artist.length())
        rightSegs.push_back(meta.artist);
    if (meta.date.length())
        rightSegs.push_back(meta.date);
    drawSeparatedLine(rightSegs, false, rightX, CAPTION_BOTTOM_Y,
                      4, FONT4_HEIGHT, meta.colorBottomRight, DAGGER_SEP_W, drawDaggerSep);
#endif
}

// =============================================================================
// Refresh
// =============================================================================

void refreshPhotoList()
{
    cachedPhotos = listPictures();
    picturesDirty = false;
}

// Picks the .bin to display for `action`. Returns "" if there's nothing to show.
String chooseTarget(PendingAction action)
{
    if (cachedPhotos.empty())
    {
        return "";
    }

    // Where the current photo sits in the (possibly changed) listing.
    int idx = -1;
    for (size_t i = 0; i < cachedPhotos.size(); i++)
    {
        if (cachedPhotos[i] == currentPhoto)
        {
            idx = (int)i;
            break;
        }
    }

    switch (action)
    {
    case PENDING_JUMP:
        for (const String &name : cachedPhotos)
        {
            if (name == pendingJumpName)
            {
                return name;
            }
        }
        // Target vanished (deleted off the card between request and service).
        // Fall through to redraw behavior rather than failing the refresh.
        break;

    case PENDING_ADVANCE:
        if (idx < 0)
        {
            return cachedPhotos[0];
        }
        return cachedPhotos[(idx + 1) % cachedPhotos.size()];

    case PENDING_RESCAN:
    case PENDING_REDRAW:
    default:
        break;
    }

    return (idx >= 0) ? cachedPhotos[idx] : cachedPhotos[0];
}

// Blocking, ~1.5-2s. Returns true if the panel was actually touched (so the
// caller knows to start the settle gate).
bool performRefresh(PendingAction action, bool userRequested)
{
    if (!sdIsMounted())
    {
        // A SCHEDULED refresh with no card must fail silently and try again next
        // interval -- drawing an error screen here would wipe the photo the user
        // is looking at, which is strictly worse than showing a stale one. Only
        // an explicit request (or a boot with nothing on screen yet) earns an
        // error screen. The sibling project drew one unconditionally.
        if (userRequested || !sdEverMounted())
        {
            drawErrorScreen("SD mount failed -- check card is inserted/formatted FAT32");
            return true;
        }
        Serial.println("Scheduled refresh skipped -- no SD card");
        return false;
    }

    if (picturesDirty)
    {
        refreshPhotoList();
    }

    if (cachedPhotos.empty())
    {
        if (userRequested || currentPhoto.length() == 0)
        {
            drawErrorScreen("No .bin images in /pictures -- run prepare_image.py");
            return true;
        }
        return false;
    }

    String target = chooseTarget(action);
    if (target.length() == 0)
    {
        return false;
    }

    // Re-read the config every refresh so a counter change made since the last
    // one (via button or web) shows up now -- that IS the deferred-redraw
    // contract. Also picks up an edited refresh_hours without a reboot.
    config = readConfig();
    refreshMs = config.refreshHours * 3600UL * 1000UL;

    uint8_t *buffer = loadImageBuffer(target);
    PhotoMeta meta = loadPhotoMeta(target);

    if (buffer == nullptr)
    {
        drawErrorScreen("Failed to read image from SD card");
        return true;
    }

#ifdef EPAPER_ENABLE
    epaper.pushImage(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT, (uint16_t *)buffer);
    drawTextOverlay(meta, config.counter);
    epaper.update();
#endif
    free(buffer);

    if (target != currentPhoto)
    {
        currentPhoto = target;
        persistPhotoName(currentPhoto);
    }
    Serial.printf("Displayed %s (counter %ld)\n", target.c_str(), (long)config.counter);
    return true;
}

void serviceRefresh()
{
    // The settle is a millis() gate, NOT a delay(). Seeed_GFX's gray update() is
    // fire-and-forget, so the panel needs ~3s undisturbed for the waveform to
    // develop -- but nothing except performRefresh() ever touches the panel, so
    // "undisturbed" costs us nothing: server.handleClient() keeps running right
    // through it. That drops the unresponsive window from ~5s to ~1.5-2s.
    if (displayState == DISP_SETTLING)
    {
        if ((int32_t)(millis() - settleUntilMs) < 0)
        {
            return;
        }
        displayState = DISP_IDLE;
    }

    bool userRequested = (pendingAction != PENDING_NONE);

    if (pendingAction == PENDING_NONE && refreshDue())
    {
        queueAction(PENDING_ADVANCE);
    }
    if (pendingAction == PENDING_NONE)
    {
        return;
    }

    PendingAction action = pendingAction;
    pendingAction = PENDING_NONE;

    bool touched = performRefresh(action, userRequested);

    // The interval restarts from the END of a completed refresh, so a forced
    // refresh gives you a fresh full interval -- matching the GPIO2 behavior
    // documented for the sibling project.
    lastRefreshMs = millis();

    if (touched)
    {
        settleUntilMs = millis() + GRAY_REFRESH_SETTLE_MS;
        displayState = DISP_SETTLING;
    }
}

// =============================================================================
// app.h implementations
// =============================================================================

void queueAction(PendingAction action)
{
    if (action > pendingAction)
    {
        pendingAction = action;
    }
}

void queueJump(const String &binName)
{
    pendingJumpName = binName;
    queueAction(PENDING_JUMP);
}

bool displayBusy() { return displayState == DISP_SETTLING || pendingAction != PENDING_NONE; }
const FrameConfig &appConfig() { return config; }
String currentPhotoName() { return currentPhoto; }
void markPicturesDirty() { picturesDirty = true; }
uint32_t refreshIntervalMs() { return refreshMs; }

uint32_t msUntilNextRefresh()
{
    uint32_t elapsed = (uint32_t)(millis() - lastRefreshMs);
    return (elapsed >= refreshMs) ? 0 : (refreshMs - elapsed);
}

bool applyCounterDelta(int delta, int32_t *newValueOut)
{
    if (!sdIsMounted())
    {
        Serial.println("SD unavailable -- counter change not applied");
        return false;
    }

    int32_t newCounter = readConfig().counter + delta;
    if (!writeConfigCounter(newCounter))
    {
        return false;
    }
    appendCounterTrack(delta, newCounter, clockValid());
    config.counter = newCounter;
    if (newValueOut)
    {
        *newValueOut = newCounter;
    }
    Serial.printf("Counter now %ld (display updates at next refresh)\n", (long)newCounter);
    return true;
}

// =============================================================================
// Buttons -- polled, not deep-sleep wake sources. This build never sleeps.
// =============================================================================

void pollButtons()
{
    unsigned long now = millis();
    for (ButtonState &b : buttons)
    {
        bool low = (digitalRead(b.pin) == LOW);
        if (low == b.lastLevelLow)
        {
            continue;
        }
        if (now - b.lastChangeMs < BUTTON_DEBOUNCE_MS)
        {
            continue;
        }
        b.lastChangeMs = now;
        b.lastLevelLow = low;

        if (!low)
        {
            continue; // act on press, ignore release
        }

        if (b.pin == BUTTON_REFRESH)
        {
            Serial.println("Button: advance");
            queueAction(PENDING_ADVANCE);
        }
        else
        {
            int delta = (b.pin == BUTTON_COUNTER_UP) ? 1 : -1;
            Serial.printf("Button: counter %+d\n", delta);
            applyCounterDelta(delta, nullptr);
        }
    }
}

// =============================================================================
// setup / loop
// =============================================================================

void setup()
{
    Serial.begin(115200);
    delay(1000);

    pinMode(BUTTON_REFRESH, INPUT_PULLUP);
    pinMode(BUTTON_COUNTER_UP, INPUT_PULLUP);
    pinMode(BUTTON_COUNTER_DOWN, INPUT_PULLUP);

    if (mountSd())
    {
        config = readConfig();
        refreshMs = config.refreshHours * 3600UL * 1000UL;
        refreshPhotoList();
        Serial.printf("SD mounted: %u photos, %u h interval, counter %ld\n",
                      (unsigned)cachedPhotos.size(), (unsigned)config.refreshHours,
                      (long)config.counter);
    }

    currentPhoto = loadPhotoName();

#ifdef EPAPER_ENABLE
    // Initialized ONCE here rather than per refresh. The sibling project called
    // begin() on every refresh only because every refresh WAS a fresh boot out
    // of deep sleep. If the first refresh renders correctly but later ones come
    // out blank or ghosted, try moving begin(1) (the initFromSleep path) into
    // performRefresh().
    epaper.begin();
    epaper.initGrayMode(GRAY_LEVEL16);
#else
    Serial.println("EPAPER_ENABLE is not defined.");
#endif

    connectWiFi(WIFI_CONNECT_TIMEOUT_MS);
    wifiWasUp = wifiConnected();
    if (wifiWasUp)
    {
        startMdns();
    }
    applyTimeConfig();

    setupWebServer();

    // Queue the first draw rather than doing it here, so exactly one code path
    // ever touches the panel. Cold boot resumes the photo that was showing.
    lastRefreshMs = millis();
    queueAction(PENDING_REDRAW);

    Serial.println("Setup complete -- serving.");
}

void loop()
{
    handleWebClient(); // always first, every pass
    pollButtons();
    serviceWiFi();
    serviceRefresh();
}
