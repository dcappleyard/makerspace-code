#include "booth_config.h" // first, see screen.cpp

#include "upload.h"
#include "battery.h"
#include "rtc_clock.h"
#include "screen.h"
#include "storage.h"

#include <HTTPClient.h>
#include <SD.h>
#include <WiFi.h>

#if __has_include("secrets.h")
#include "secrets.h"
#endif

#if defined(WIFI_SSID) && defined(SERVER_URL) && defined(UPLOAD_TOKEN)
#define UPLOAD_ENABLED 1
#else
#define UPLOAD_ENABLED 0
#endif

size_t pendingUploads()
{
#if UPLOAD_ENABLED
    return pendingSdPhotos().size() + ramPhotoCount();
#else
    return 0;
#endif
}

#if UPLOAD_ENABLED
namespace
{

String endpoint() { return String(SERVER_URL) + "/sources/" + UPLOAD_SOURCE + "/upload"; }

// One POST. `stream` for a card file, else `data` from PSRAM. True when the
// server has the photo (stored, or already had it: a duplicate).
bool post(const String &name, Stream *stream, const uint8_t *data, size_t len)
{
    HTTPClient http;
    http.setTimeout(UPLOAD_HTTP_TIMEOUT_MS);
    http.setConnectTimeout(UPLOAD_HTTP_TIMEOUT_MS);
    if (!http.begin(endpoint()))
        return false;
    http.addHeader("X-Access-Token", UPLOAD_TOKEN);
    http.addHeader("X-Filename", name);
    http.addHeader("Content-Type", "image/jpeg");
    int code = stream ? http.sendRequest("POST", stream, len) : http.POST((uint8_t *)data, len);
    String body = code > 0 ? http.getString() : HTTPClient::errorToString(code);
    http.end();
    bool ok = code == 200;
    Serial.printf("Upload %s (%u bytes): %d %s\n", name.c_str(), (unsigned)len, code, body.c_str());
    return ok;
}

} // namespace
#endif

size_t uploadPending()
{
#if UPLOAD_ENABLED
    std::vector<String> sd = pendingSdPhotos();
    std::vector<RamPhotoRef> ram = ramPhotos();
    size_t total = sd.size() + ram.size();
    if (total == 0)
        return 0;

    drawMessage("Uploading...", (String(total) + (total == 1 ? " photo" : " photos")).c_str());
    uint32_t start = millis();
    if (!wifiUp())
    {
        drawMessage("Upload later", "no WiFi");
        delay(1500);
        return 0;
    }
    // Before anything else: sets the clock if it was never set, so the next
    // sequences get real names (photos already taken keep their nodate_ name).
    syncClockOnline();
    size_t sent = 0, n = 0;
    auto outOfTime = [&] { return (uint32_t)(millis() - start) > UPLOAD_BUDGET_MS; };
    char line[32];

    for (const String &name : sd)
    {
        if (outOfTime())
            break;
        snprintf(line, sizeof(line), "%u of %u", (unsigned)++n, (unsigned)total);
        drawMessage("Uploading...", line);
        File f = SD.open(String(PHOTO_DIR) + "/" + name, FILE_READ);
        if (!f)
            continue;
        size_t len = f.size();
        bool ok = post(name, &f, nullptr, len);
        f.close();
        if (!ok)
            break; // server down or refusing: stop and retry next time
        if (markSdUploaded(name))
            sent++;
    }
    for (const RamPhotoRef &p : ram)
    {
        if (outOfTime())
            break;
        snprintf(line, sizeof(line), "%u of %u", (unsigned)++n, (unsigned)total);
        drawMessage("Uploading...", line);
        if (!post(p.name, nullptr, p.data, p.len))
            break;
        dropRamPhoto(p.name);
        sent++;
    }

    pushBatteryLog(); // while WiFi is up anyway
    wifiDown();
    snprintf(line, sizeof(line), "%u of %u sent", (unsigned)sent, (unsigned)total);
    drawMessage(sent == total ? "Uploaded" : "Upload incomplete", line);
    Serial.printf("Upload: %u of %u sent in %lu ms\n", (unsigned)sent, (unsigned)total,
                  (unsigned long)(millis() - start));
    delay(1200);
    return sent;
#else
    return 0;
#endif
}

#if UPLOAD_ENABLED
namespace
{

// The `"length": N` in the server's battery responses; -1 if absent.
long parseLength(const String &body)
{
    int i = body.indexOf("\"length\"");
    if (i < 0)
        return -1;
    i = body.indexOf(':', i);
    return i < 0 ? -1 : body.substring(i + 1).toInt();
}

} // namespace
#endif

bool pushBatteryLog()
{
#if UPLOAD_ENABLED
    logBattery("upload");
    String id = batteryLogId();
    uint8_t *buf = id.isEmpty() ? nullptr : (uint8_t *)ps_malloc(BATTERY_UPLOAD_CHUNK);
    bool done = false;
    // The server appends idempotently by offset (X-Offset): a retried chunk's
    // overlap is skipped, and a 409 says where it actually is.
    for (int i = 0; buf && i < 32; i++)
    {
        size_t sent = batteryLogSent(), size = batteryLogSize();
        if (sent >= size)
        {
            done = true;
            break;
        }
        size_t n = readBatteryLog(sent, buf, std::min(BATTERY_UPLOAD_CHUNK, size - sent));
        if (n == 0)
            break;
        HTTPClient http;
        http.setTimeout(UPLOAD_HTTP_TIMEOUT_MS);
        http.setConnectTimeout(UPLOAD_HTTP_TIMEOUT_MS);
        if (!http.begin(String(SERVER_URL) + "/sources/" + UPLOAD_SOURCE + "/battery"))
            break;
        http.addHeader("X-Access-Token", UPLOAD_TOKEN);
        http.addHeader("X-Log-Id", id);
        http.addHeader("X-Offset", String((unsigned long)sent));
        http.addHeader("Content-Type", "text/csv");
        int code = http.POST(buf, n);
        String body = code > 0 ? http.getString() : HTTPClient::errorToString(code);
        http.end();
        long length = parseLength(body);
        Serial.printf("Battery log %s: %u bytes at %u -> %d %s\n", id.c_str(), (unsigned)n, (unsigned)sent, code,
                      body.c_str());
        if ((code == 200 || code == 409) && length >= 0)
            setBatteryLogSent((size_t)length);
        else
            break; // server down or refusing: try again next push
    }
    free(buf);
    return done;
#else
    return false;
#endif
}
