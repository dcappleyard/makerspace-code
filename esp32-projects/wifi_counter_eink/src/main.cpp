#include <Arduino.h>

// Must be included before TFT_eSPI.h: Seeed_GFX's ESP32-S3 processor header
// (Processors/TFT_eSPI_ESP32_S3.h) does `#define FS_NO_GLOBALS` before
// pulling in FS.h, which suppresses FS.h's `using fs::FS;` and breaks
// WebServer.h's unqualified use of `FS`. Including FS.h here first lets
// that `using` declaration fire while global; FS.h's own include guard
// then makes TFT_eSPI.h's later include of it a no-op, so the `using`
// stays in effect for the rest of this file.
#include <FS.h>

#include <TFT_eSPI.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <ESPmDNS.h>

#include "secrets.h" // WIFI_SSID / WIFI_PASSWORD -- gitignored, see README.md

#ifdef EPAPER_ENABLE
EPaper epaper;
#endif

WebServer server(80);
Preferences preferences;

// Fixed region the counter digits are redrawn into. x and w are kept
// 8px-aligned since EPaper::updataPartial() (Seeed_GFX Extensions/EPaper.cpp)
// 8px-aligns internally and would otherwise silently redraw a slightly
// wider strip than requested.
constexpr int COUNTER_X = 80;
constexpr int COUNTER_Y = 200;
constexpr int COUNTER_W = 400;
constexpr int COUNTER_H = 200;

int counter = 0;

void loadCounter()
{
    preferences.begin("counter", true /* read-only */);
    counter = preferences.getInt("value", 0);
    preferences.end();
}

void persistCounter()
{
    // Opened/closed per write rather than held open for the process
    // lifetime, so each change is flushed immediately instead of
    // risking loss if power is cut before some later end() call.
    preferences.begin("counter", false);
    preferences.putInt("value", counter);
    preferences.end();
}

// Draws the counter digits into the sprite buffer only -- does not touch
// the physical panel. Used both for the initial (pre-first-update) draw
// and as the first half of drawCounter() below.
void renderCounterPixels()
{
#ifdef EPAPER_ENABLE
    epaper.fillRect(COUNTER_X, COUNTER_Y, COUNTER_W, COUNTER_H, TFT_WHITE);
    epaper.setTextSize(6);
    epaper.drawString(String(counter).c_str(), COUNTER_X + 20, COUNTER_Y + 40);
#endif
}

// Redraws the counter and pushes just that region to the panel. Only
// valid to call after the initial full epaper.update() in setup() has
// established a baseline image -- see Seeed_GFX's
// examples/ePaper/Partial/HelloWorld/HelloWorld.ino for the pattern this
// follows (full update() once, updataPartial() for changes after that).
void drawCounter()
{
#ifdef EPAPER_ENABLE
    renderCounterPixels();
    epaper.updataPartial(COUNTER_X, COUNTER_Y, COUNTER_W, COUNTER_H);
#endif
}

void connectWiFi()
{
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }
    Serial.println();

    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());

    if (MDNS.begin("wifi-counter"))
    {
        MDNS.addService("http", "tcp", 80);
        Serial.println("mDNS: http://wifi-counter.local/");
    }
    else
    {
        Serial.println("mDNS setup failed -- use the IP address above instead.");
    }
}

void handleRoot()
{
    String html =
        "<!DOCTYPE html><html><head><title>WiFi Counter</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "</head><body>"
        "<h1>Counter: " +
        String(counter) +
        "</h1>"
        "<form method='POST' action='/increment' style='display:inline'>"
        "<button type='submit'>+1</button></form> "
        "<form method='POST' action='/decrement' style='display:inline'>"
        "<button type='submit'>-1</button></form>"
        "</body></html>";

    server.send(200, "text/html", html);
}

void handleIncrement()
{
    if (server.method() != HTTP_POST)
    {
        server.send(405, "text/plain", "Method Not Allowed");
        return;
    }

    counter++;
    persistCounter();
    drawCounter();

    server.sendHeader("Location", "/");
    server.send(303, "text/plain", "");
}

void handleDecrement()
{
    if (server.method() != HTTP_POST)
    {
        server.send(405, "text/plain", "Method Not Allowed");
        return;
    }

    counter--;
    persistCounter();
    drawCounter();

    server.sendHeader("Location", "/");
    server.send(303, "text/plain", "");
}

void handleStatus()
{
    server.send(200, "application/json", "{\"counter\":" + String(counter) + "}");
}

void handleNotFound()
{
    server.send(404, "text/plain", "Not found");
}

void setup()
{
    Serial.begin(115200);
    delay(1000);

    loadCounter();

#ifdef EPAPER_ENABLE
    Serial.println("Initializing EE03 display...");
    epaper.begin();
    epaper.fillScreen(TFT_WHITE);
    epaper.setTextColor(TFT_BLACK, TFT_WHITE);

    epaper.setTextSize(2);
    epaper.drawString("WiFi Counter", 40, 40);
    renderCounterPixels();

    epaper.update(); // one full refresh at boot -- baseline for partial updates
#else
    Serial.println("EPAPER_ENABLE is not defined.");
#endif

    connectWiFi();

    server.on("/", HTTP_GET, handleRoot);
    server.on("/increment", HTTP_POST, handleIncrement);
    server.on("/decrement", HTTP_POST, handleDecrement);
    server.on("/status", HTTP_GET, handleStatus);
    server.onNotFound(handleNotFound);
    server.begin();

    Serial.println("Web server started.");
}

void loop()
{
    server.handleClient();
}
