#include "booth_config.h" // first, see screen.cpp

#include "upload.h"
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

    ntpSyncNow(); // WiFi's up anyway: keep the RTC from drifting between reboots
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
