#include "app.h"
#include "camera.h"
#include "screen.h"
#include "storage.h"
#include "web.h"

#include <WiFi.h>
#include <ESPmDNS.h>
#include <time.h>

#include "secrets.h" // WIFI_SSID / WIFI_PASSWORD -- gitignored

// Everything request-driven runs in the two esp_http_server tasks (web.cpp);
// loop() keeps WiFi up and runs the round display (screen.cpp).

namespace
{

bool wifiWasUp = false;
uint32_t lastWifiTryMs = 0;

bool connectWiFi(uint32_t timeoutMs)
{
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(HOSTNAME);
    WiFi.setAutoReconnect(true);
    WiFi.setSleep(false); // modem sleep stutters the stream badly
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("Connecting to WiFi (up to %us)...\n", (unsigned)(timeoutMs / 1000));
    return WiFi.waitForConnectResult(timeoutMs) == WL_CONNECTED;
}

void startMdns()
{
    MDNS.end();
    if (MDNS.begin(HOSTNAME))
        MDNS.addService("http", "tcp", HTTP_PORT);
}

void applyTimeConfig() { configTzTime(TZ_DEFAULT, NTP_SERVER_1, NTP_SERVER_2); }

void announce()
{
    Serial.printf("WiFi up: http://%s/  (http://%s.local/), stream on port %u\n",
                  WiFi.localIP().toString().c_str(), HOSTNAME, STREAM_PORT);
}

// Never blocks; autoreconnect handles most drops, this covers the rest.
void serviceWiFi()
{
    if (wifiConnected())
    {
        if (!wifiWasUp)
        {
            wifiWasUp = true;
            announce();
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

    if (!psramFound())
        Serial.println("No PSRAM found -- check board_build.arduino.memory_type (qio_opi)");
    cameraInit(); // the page still comes up without it, and says so
    setupScreen(); // before mountSd(): the card rides on the display's SPI bus
    mountSd();

    wifiWasUp = connectWiFi(WIFI_CONNECT_TIMEOUT_MS);
    if (wifiWasUp)
    {
        announce();
        startMdns();
    }
    else
    {
        Serial.println("WiFi failed -- will keep retrying");
    }
    applyTimeConfig();
    startWebServers();
    Serial.println("Setup complete.");
}

void loop()
{
    serviceWiFi();
    serviceScreen();
    if (!screenOn())
        delay(5); // idle; while the preview runs, decoding paces the loop
}
