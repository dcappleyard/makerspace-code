#include "frame_config.h" // MUST be first -- see the include-order note there

#include "app.h"
#include "pull.h"
#include "storage.h"
#include "web.h"

#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <time.h>

#include "secrets.h" // WIFI_SSID / WIFI_PASSWORD / SERVER_URL / DEVICE_TOKEN -- gitignored

#ifdef EPAPER_ENABLE
EPaper epaper;
#endif

namespace
{

Preferences preferences;
constexpr const char *NVS_NAMESPACE = "frame";
constexpr const char *NVS_KEY_IMG = "imgName";

// --- Display state machine (same shape as ../panorama_photo_frame_web) ------
String currentName;      // cache file on the panel
String pendingName;      // queued by pull.cpp; drawn at the next idle pass
String pendingSignalId;  // pull to confirm after the draw
bool settling = false;
uint32_t settleUntilMs = 0;

// --- Network ------------------------------------------------------------------
bool wifiWasUp = false;
uint32_t lastWifiTryMs = 0;

// The panel keeps its image unpowered, so the name is persisted to know what's
// up there after a reboot (used only to show it in status; the first pull
// redraws anyway -- see doPull()).
String loadImageName()
{
    preferences.begin(NVS_NAMESPACE, true);
    String name = preferences.getString(NVS_KEY_IMG, "");
    preferences.end();
    return name;
}

void persistImageName(const String &name)
{
    preferences.begin(NVS_NAMESPACE, false);
    preferences.putString(NVS_KEY_IMG, name);
    preferences.end();
}

void drawMessage(const char *message)
{
#ifdef EPAPER_ENABLE
    epaper.fillScreen(TFT_WHITE);
    epaper.setTextColor(TFT_BLACK, TFT_WHITE);
    epaper.setTextSize(2);
    epaper.setTextDatum(TL_DATUM);
    epaper.drawString(message, 40, 40);
    String where = String("http://") + HOSTNAME + ".local  /  " + wifiStatusText();
    epaper.drawString(where, 40, 100);
    epaper.drawString(String("server: ") + SERVER_URL, 40, 160);
    epaper.update();
#endif
    Serial.println(message);
}

// Blocking, ~1.5-2 s. The server already rendered everything -- photo, caption
// -- into the buffer, so this just pushes pixels.
bool performRefresh(const String &name)
{
    uint8_t *buffer = loadImageBuffer(name);
    if (!buffer)
    {
        Serial.printf("Can't load %s from the SD cache\n", name.c_str());
        return false;
    }
#ifdef EPAPER_ENABLE
    epaper.pushImage(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT, (uint16_t *)buffer);
    epaper.update();
#endif
    free(buffer);
    if (name != currentName)
    {
        currentName = name;
        persistImageName(name);
    }
    Serial.printf("Displayed %s\n", name.c_str());
    return true;
}

void serviceDisplay()
{
    // Settle is a millis() gate, not a delay(): the 16-gray update() is
    // fire-and-forget and needs ~3 s undisturbed, but nothing else touches the
    // panel, so the web server and pulls keep running meanwhile.
    if (settling)
    {
        if ((int32_t)(millis() - settleUntilMs) < 0)
            return;
        settling = false;
    }
    if (pendingName.length() == 0)
        return;
    String name = pendingName, signalId = pendingSignalId;
    pendingName = "";
    pendingSignalId = "";
    bool ok = performRefresh(name);
    if (ok)
    {
        settling = true;
        settleUntilMs = millis() + GRAY_REFRESH_SETTLE_MS;
    }
    sendSignal(signalId, ok);
}

bool connectWiFi(uint32_t timeoutMs)
{
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(HOSTNAME);
    WiFi.setAutoReconnect(true);
    WiFi.setSleep(false); // mains powered; steadier latency
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("Connecting to WiFi (up to %us)...\n", (unsigned)(timeoutMs / 1000));
    return WiFi.waitForConnectResult(timeoutMs) == WL_CONNECTED;
}

void startMdns()
{
    MDNS.end();
    if (MDNS.begin(HOSTNAME))
        MDNS.addService("http", "tcp", 80);
}

void applyTimeConfig() { configTzTime(TZ_DEFAULT, NTP_SERVER_1, NTP_SERVER_2); }

// Never blocks; autoreconnect handles most drops, this covers the rest.
void serviceWiFi()
{
    if (wifiConnected())
    {
        if (!wifiWasUp)
        {
            wifiWasUp = true;
            Serial.printf("WiFi up: %s\n", WiFi.localIP().toString().c_str());
            startMdns();
            applyTimeConfig();
        }
        return;
    }
    wifiWasUp = false;
    if ((uint32_t)(millis() - lastWifiTryMs) < WIFI_RETRY_INTERVAL_MS)
        return;
    lastWifiTryMs = millis();
    Serial.println("WiFi down -- retrying");
    WiFi.disconnect(false, false);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

} // namespace

// =============================================================================
// app.h
// =============================================================================

void queueDisplay(const String &name, const String &signalPullId)
{
    if (pendingSignalId.length() && pendingSignalId != signalPullId)
    {
        sendSignal(pendingSignalId, false); // superseded before it was drawn
    }
    pendingName = name;
    pendingSignalId = signalPullId;
}

String currentImageName() { return currentName; }
bool displayBusy() { return settling || pendingName.length() > 0; }
bool wifiConnected() { return WiFi.status() == WL_CONNECTED; }
String wifiStatusText() { return wifiConnected() ? WiFi.localIP().toString() : String("no wifi"); }
bool clockValid() { return time(nullptr) > CLOCK_SANE_EPOCH; }

String formatLocalTime()
{
    if (!clockValid())
        return "not set";
    time_t now = time(nullptr);
    struct tm tm;
    localtime_r(&now, &tm);
    char buf[48];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S %Z", &tm);
    return buf;
}

// =============================================================================
// setup / loop
// =============================================================================

void setup()
{
    Serial.begin(115200);
    delay(1000);

    bool sdOk = mountSd();
    currentName = loadImageName();

#ifdef EPAPER_ENABLE
    // Once at boot, as in ../panorama_photo_frame_web (see its README if later
    // refreshes come out blank or ghosted).
    epaper.begin();
    epaper.initGrayMode(GRAY_LEVEL16);
#endif

    wifiWasUp = connectWiFi(WIFI_CONNECT_TIMEOUT_MS);
    if (wifiWasUp)
    {
        Serial.printf("WiFi up: %s\n", WiFi.localIP().toString().c_str());
        startMdns();
    }
    else
    {
        Serial.println("WiFi failed -- will keep retrying; showing the cache meanwhile");
    }
    applyTimeConfig();
    setupWebServer();
    setupPull();

    if (!sdOk)
    {
        drawMessage("SD card missing -- needed for the image cache");
    }
    else if (!wifiWasUp && cacheHas(currentName))
    {
        queueDisplay(currentName, ""); // the boot pull will fail; show what we have
    }
    Serial.println("Setup complete.");
}

void loop()
{
    handleWebClient(); // first, every pass
    serviceWiFi();
    servicePull();
    serviceDisplay();
}
