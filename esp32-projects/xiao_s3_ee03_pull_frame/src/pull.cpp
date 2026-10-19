#include "frame_config.h" // MUST be first -- see the include-order note there

#include "pull.h"
#include "app.h"
#include "storage.h"

#include <WiFi.h>
#include <HTTPClient.h>
#include <SD.h>
#include <ArduinoJson.h>
#include <mbedtls/sha256.h>

#include "secrets.h" // SERVER_URL / DEVICE_TOKEN -- gitignored, see README.md

namespace
{

PullStatus status;

// Next pull: a millis() deadline, never wall time (see frame_config.h).
uint32_t lastArmMs = 0;
uint32_t waitMs = 0;
bool pullRequested = true; // pull once at boot
String requestReason = "boot";
// The server's next_check_at, echoed back as scheduled_for so it can log drift
// and treat a slightly early check as the slot it was meant for.
String scheduledFor;

uint32_t lastOfflineCycleMs = 0;

void arm(uint32_t seconds)
{
    seconds = constrain(seconds, MIN_CHECK_S, MAX_CHECK_S);
    lastArmMs = millis();
    waitMs = seconds * 1000UL;
}

bool pullDue() { return (uint32_t)(millis() - lastArmMs) >= waitMs; }

String urlEncode(const String &s)
{
    String out;
    const char *hex = "0123456789ABCDEF";
    for (size_t i = 0; i < s.length(); i++)
    {
        unsigned char c = s[i];
        if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~')
        {
            out += (char)c;
        }
        else
        {
            out += '%';
            out += hex[c >> 4];
            out += hex[c & 15];
        }
    }
    return out;
}

void fail(const String &why)
{
    status.failures++;
    status.lastResult = "error: " + why;
    if (status.failures >= OFFLINE_AFTER_FAILURES && !status.offline)
    {
        status.offline = true;
        lastOfflineCycleMs = millis();
        Serial.println("Server unreachable -- cycling the SD cache until it's back");
    }
    Serial.printf("Pull failed (%u in a row): %s\n", status.failures, why.c_str());
    arm(RETRY_S);
}

// Streams image_url to the SD temp file, checking length and SHA-256 as it
// goes, then renames it into the cache. Returns "" on success, else why not.
String download(const String &url, const String &name, size_t expectedBytes, const String &expectedSha)
{
    if (expectedBytes != IMAGE_BYTES)
    {
        return "server sent " + String(expectedBytes) + " bytes, panel needs " + String(IMAGE_BYTES);
    }
    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.setConnectTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(url))
    {
        return "bad image url";
    }
    int code = http.GET();
    if (code != HTTP_CODE_OK)
    {
        http.end();
        return "image HTTP " + String(code);
    }
    int len = http.getSize();
    if (len != (int)IMAGE_BYTES)
    {
        http.end();
        return "image Content-Length " + String(len);
    }

    File f = SD.open(DOWNLOAD_TMP, FILE_WRITE);
    if (!f)
    {
        http.end();
        return "can't write to SD";
    }
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    mbedtls_sha256_starts(&sha, 0);

    static uint8_t buf[4096];
    WiFiClient *stream = http.getStreamPtr();
    size_t total = 0;
    uint32_t lastData = millis();
    bool writeOk = true;
    while (total < IMAGE_BYTES && (http.connected() || stream->available()))
    {
        size_t avail = stream->available();
        if (avail == 0)
        {
            if ((uint32_t)(millis() - lastData) > HTTP_TIMEOUT_MS)
            {
                break;
            }
            delay(1);
            continue;
        }
        size_t want = min(min(avail, sizeof(buf)), IMAGE_BYTES - total);
        int n = stream->readBytes(buf, want);
        if (n <= 0)
        {
            continue;
        }
        if (f.write(buf, n) != (size_t)n)
        {
            writeOk = false;
            break;
        }
        mbedtls_sha256_update(&sha, buf, n);
        total += n;
        lastData = millis();
    }
    f.close();
    http.end();

    uint8_t digest[32];
    mbedtls_sha256_finish(&sha, digest);
    mbedtls_sha256_free(&sha);
    char hex[65];
    for (int i = 0; i < 32; i++)
    {
        sprintf(hex + 2 * i, "%02x", digest[i]);
    }

    String err;
    if (!writeOk)
        err = "SD write failed";
    else if (total != IMAGE_BYTES)
        err = "short download (" + String(total) + " bytes)";
    else if (!expectedSha.equalsIgnoreCase(hex))
        err = "sha256 mismatch";
    if (err.length())
    {
        SD.remove(DOWNLOAD_TMP);
        return err;
    }

    // All-or-nothing, as uploads were in ../panorama_photo_frame_web: the cache
    // only ever holds complete, verified images.
    String path = cachePath(name);
    if (SD.exists(path))
    {
        SD.remove(path);
    }
    if (!SD.rename(DOWNLOAD_TMP, path))
    {
        SD.remove(DOWNLOAD_TMP);
        return "rename into cache failed";
    }
    pruneCache(name);
    status.downloads++;
    return "";
}

void doPull(const String &reason)
{
    status.lastAttempt = formatLocalTime();
    if (!wifiConnected())
    {
        fail("no WiFi");
        return;
    }
    if (!sdIsMounted() && !mountSd())
    {
        fail("no SD card");
        return;
    }

    String url = String(SERVER_URL) + "/esp32/v1/pull?device_id=" + deviceId() + "&reason=" + reason;
    if (scheduledFor.length())
    {
        url += "&scheduled_for=" + urlEncode(scheduledFor);
    }
    // At boot the panel may still hold something from before (e-paper keeps its
    // image unpowered, and after a reflash it isn't necessarily ours), so don't
    // claim a current image: the server answers "show" and we redraw -- straight
    // from the cache, if we already have it.
    String current = currentImageName();
    if (current.length() && reason != "boot")
    {
        url += "&current=" + urlEncode(current);
    }

    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.setConnectTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(url))
    {
        fail("bad SERVER_URL");
        return;
    }
    http.addHeader("X-Access-Token", DEVICE_TOKEN);
    int code = http.GET();
    if (code != HTTP_CODE_OK)
    {
        http.end();
        fail(code < 0 ? HTTPClient::errorToString(code) : "HTTP " + String(code));
        return;
    }
    String body = http.getString();
    http.end();

    JsonDocument doc;
    if (deserializeJson(doc, body))
    {
        fail("unparseable response");
        return;
    }
    String st = doc["status"] | "";
    uint32_t next = doc["next_check_s"] | RETRY_S;
    scheduledFor = String((const char *)(doc["next_check_at"] | ""));

    if (st == "show")
    {
        String name = doc["name"] | "";
        String pullId = doc["pull_id"] | "";
        if (!validCacheName(name))
        {
            fail("server sent a bad image name");
            return;
        }
        if (!cacheHas(name))
        {
            String err = download(doc["image_url"] | "", name, doc["image_bytes"] | 0, doc["sha256"] | "");
            if (err.length())
            {
                sendSignal(pullId, false);
                fail("download: " + err);
                return;
            }
        }
        queueDisplay(name, pullId);
        status.lastResult = "show " + name;
    }
    else if (st == "keep" || st == "none")
    {
        status.lastResult = st;
    }
    else
    {
        // The server answered but declined (bad token, prep failure): reachable,
        // so not an offline failure -- just wait as long as it says.
        status.lastResult = "server: " + String((const char *)(doc["message"] | "error"));
        Serial.printf("Server declined pull: %s\n", status.lastResult.c_str());
        arm(next);
        return;
    }

    status.failures = 0;
    if (status.offline)
    {
        Serial.println("Server back -- leaving offline mode");
    }
    status.offline = false;
    status.pulls++;
    status.nextCheckAt = scheduledFor;
    arm(next);
    Serial.printf("Pull (%s): %s, next check in %lus\n", reason.c_str(), status.lastResult.c_str(),
                  (unsigned long)(waitMs / 1000));
}

void serviceOffline()
{
    if (!status.offline || (uint32_t)(millis() - lastOfflineCycleMs) < OFFLINE_CYCLE_S * 1000UL)
    {
        return;
    }
    lastOfflineCycleMs = millis();
    std::vector<String> names = listCache();
    if (names.empty())
    {
        return;
    }
    String current = currentImageName();
    size_t i = 0;
    while (i < names.size() && names[i] != current)
    {
        i++;
    }
    String next = names[(i + 1) % names.size()]; // i == size() (not found) -> first
    Serial.printf("Offline: showing cached %s\n", next.c_str());
    queueDisplay(next, "");
}

} // namespace

String deviceId()
{
    String mac = WiFi.macAddress();
    mac.replace(":", "");
    return mac;
}

void setupPull()
{
    arm(MIN_CHECK_S);
    pullRequested = true;
    requestReason = "boot";
}

void servicePull()
{
    if (pullRequested)
    {
        pullRequested = false;
        doPull(requestReason);
    }
    else if (pullDue())
    {
        doPull(status.failures ? "retry" : "timer");
    }
    serviceOffline();
}

void requestPullNow()
{
    pullRequested = true;
    requestReason = "manual";
}

uint32_t msUntilNextPull()
{
    uint32_t elapsed = (uint32_t)(millis() - lastArmMs);
    return elapsed >= waitMs ? 0 : waitMs - elapsed;
}

const PullStatus &pullStatus() { return status; }

void sendSignal(const String &pullId, bool success)
{
    if (pullId.length() == 0 || !wifiConnected())
    {
        return;
    }
    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    String url = String(SERVER_URL) + "/esp32/v1/signal?pull_id=" + urlEncode(pullId) +
                 "&success=" + (success ? "1" : "0");
    if (http.begin(url))
    {
        http.addHeader("X-Access-Token", DEVICE_TOKEN);
        http.GET();
        http.end();
    }
}
