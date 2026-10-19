#include "frame_config.h" // MUST be first -- see the include-order note there

#include "web.h"
#include "app.h"
#include "pull.h"
#include "storage.h"

#include <WiFi.h>
#include <WebServer.h>

#include "secrets.h"

namespace
{

WebServer server(80);

// Same opt-in Basic Auth seam as ../panorama_photo_frame_web: uncomment
// WEB_AUTH_USER/WEB_AUTH_PASS in secrets.h and every route is protected.
bool requireAuth()
{
#ifdef WEB_AUTH_USER
    if (!server.authenticate(WEB_AUTH_USER, WEB_AUTH_PASS))
    {
        server.requestAuthentication();
        return false;
    }
#endif
    return true;
}

String esc(const String &s)
{
    String out = s;
    out.replace("&", "&amp;");
    out.replace("<", "&lt;");
    out.replace(">", "&gt;");
    out.replace("\"", "&quot;");
    return out;
}

String jsonStr(const String &s)
{
    String out = "\"";
    for (size_t i = 0; i < s.length(); i++)
    {
        char c = s[i];
        if (c == '"' || c == '\\')
            out += '\\';
        if ((unsigned char)c >= 0x20)
            out += c;
    }
    return out + "\"";
}

String duration(uint32_t ms)
{
    uint32_t s = ms / 1000;
    char buf[32];
    if (s >= 3600)
        snprintf(buf, sizeof(buf), "%luh %02lum", (unsigned long)(s / 3600), (unsigned long)(s % 3600 / 60));
    else
        snprintf(buf, sizeof(buf), "%lum %02lus", (unsigned long)(s / 60), (unsigned long)(s % 60));
    return buf;
}

const char PAGE_HEAD[] PROGMEM =
    "<!DOCTYPE html><html><head><title>EE03 Frame</title>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<style>body{font-family:system-ui,sans-serif;margin:0;padding:1rem;max-width:44rem}"
    "h1{font-size:1.3rem}table{border-collapse:collapse;width:100%}"
    "td{border-bottom:1px solid #ddd;padding:.4rem;font-size:.95rem}td.k{color:#666;width:11rem}"
    ".off{color:#b4400c;font-weight:600}button{padding:.4rem .8rem}</style></head><body>";

void row(String &html, const char *k, const String &v)
{
    html += "<tr><td class='k'>";
    html += k;
    html += "</td><td>" + v + "</td></tr>";
}

void handleRoot()
{
    if (!requireAuth())
        return;
    const PullStatus &st = pullStatus();
    String html = FPSTR(PAGE_HEAD);
    html += "<h1>EE03 pull frame</h1>";
    if (st.offline)
        html += "<p class='off'>Server unreachable -- cycling cached photos until it's back.</p>";
    html += "<table>";
    row(html, "Showing", esc(currentImageName().length() ? currentImageName() : String("--")) +
                             (displayBusy() ? " <i>(refreshing)</i>" : ""));
    row(html, "Server", esc(SERVER_URL));
    row(html, "Last pull", esc(st.lastAttempt.length() ? st.lastAttempt : String("--")) + " &rarr; " +
                               esc(st.lastResult.length() ? st.lastResult : String("--")));
    row(html, "Next check", "in " + duration(msUntilNextPull()) +
                                (st.nextCheckAt.length() ? " (" + esc(st.nextCheckAt) + ")" : ""));
    row(html, "Failures in a row", String(st.failures));
    row(html, "Since boot", String(st.pulls) + " pulls, " + String(st.downloads) + " downloads");
    row(html, "SD cache", sdIsMounted() ? String(cacheCount()) + " images, " +
                                               String((unsigned long)(sdFreeBytes() / (1024 * 1024))) + " MB free"
                                         : String("<span class='off'>no card</span>"));
    row(html, "Clock", esc(formatLocalTime()));
    row(html, "WiFi", esc(wifiStatusText()) + " (" + String(WiFi.RSSI()) + " dBm)");
    row(html, "Device id", esc(deviceId()));
    row(html, "Uptime", duration(millis()));
    row(html, "Free heap", String(ESP.getFreeHeap() / 1024) + " KB (min " + String(ESP.getMinFreeHeap() / 1024) + " KB)");
    html += "</table><p><form method='post' action='/pull-now'><button>Pull now</button></form> "
            "Ask the server what to show right away instead of waiting for the next check.</p>"
            "<p><a href='/status.json'>status.json</a></p></body></html>";
    server.send(200, "text/html", html);
}

void handleStatusJson()
{
    if (!requireAuth())
        return;
    const PullStatus &st = pullStatus();
    String j = "{";
    j += "\"showing\":" + jsonStr(currentImageName());
    j += ",\"server\":" + jsonStr(SERVER_URL);
    j += ",\"last_attempt\":" + jsonStr(st.lastAttempt);
    j += ",\"last_result\":" + jsonStr(st.lastResult);
    j += ",\"next_check_ms\":" + String(msUntilNextPull());
    j += ",\"next_check_at\":" + jsonStr(st.nextCheckAt);
    j += ",\"failures\":" + String(st.failures);
    j += ",\"offline\":" + String(st.offline ? "true" : "false");
    j += ",\"pulls\":" + String(st.pulls) + ",\"downloads\":" + String(st.downloads);
    j += ",\"cache_images\":" + String(sdIsMounted() ? cacheCount() : 0);
    j += ",\"sd_free_mb\":" + String((unsigned long)(sdFreeBytes() / (1024 * 1024)));
    j += ",\"clock\":" + jsonStr(formatLocalTime());
    j += ",\"ip\":" + jsonStr(wifiStatusText()) + ",\"rssi\":" + String(WiFi.RSSI());
    j += ",\"device_id\":" + jsonStr(deviceId());
    j += ",\"uptime_ms\":" + String(millis()) + ",\"min_free_heap\":" + String(ESP.getMinFreeHeap());
    j += "}";
    server.send(200, "application/json", j);
}

// POST-only, like every state-changing route in ../panorama_photo_frame_web:
// link previewers and LAN scanners issue GETs and shouldn't trigger pulls.
void handlePullNow()
{
    if (!requireAuth())
        return;
    requestPullNow();
    server.sendHeader("Location", "/");
    server.send(303);
}

} // namespace

void setupWebServer()
{
    server.on("/", HTTP_GET, handleRoot);
    server.on("/status.json", HTTP_GET, handleStatusJson);
    server.on("/pull-now", HTTP_POST, handlePullNow);
    server.onNotFound([] { server.send(404, "text/plain", "not found"); });
    server.begin();
}

void handleWebClient() { server.handleClient(); }
