#include "pull.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <mbedtls/sha256.h>

#include "secrets.h" // SERVER_URL / DEVICE_TOKEN -- gitignored, see README.md

namespace
{

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

bool validName(const String &name)
{
    if (name.length() == 0 || name.length() >= NAME_MAX_LEN)
        return false;
    for (size_t i = 0; i < name.length(); i++)
    {
        char c = name[i];
        if (!isalnum((unsigned char)c) && c != '-' && c != '_' && c != '.')
            return false;
    }
    return true;
}

// Downloads image_url into buf, checking length and SHA-256.
// Returns "" on success, else why not.
String download(const String &url, size_t expectedBytes, const String &expectedSha, uint8_t *buf)
{
    if (expectedBytes != IMAGE_BYTES)
        return "server sent " + String(expectedBytes) + " bytes, panel needs " + String(IMAGE_BYTES);
    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.setConnectTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(url))
        return "bad image url";
    int code = http.GET();
    if (code != HTTP_CODE_OK)
    {
        http.end();
        return "image HTTP " + String(code);
    }
    if (http.getSize() != (int)IMAGE_BYTES)
    {
        int len = http.getSize();
        http.end();
        return "image Content-Length " + String(len);
    }
    WiFiClient *stream = http.getStreamPtr();
    size_t total = 0;
    uint32_t lastData = millis();
    while (total < IMAGE_BYTES && (http.connected() || stream->available()))
    {
        size_t avail = stream->available();
        if (avail == 0)
        {
            if ((uint32_t)(millis() - lastData) > HTTP_TIMEOUT_MS)
                break;
            delay(1);
            continue;
        }
        int n = stream->readBytes(buf + total, min(avail, IMAGE_BYTES - total));
        if (n > 0)
        {
            total += n;
            lastData = millis();
        }
    }
    http.end();
    if (total != IMAGE_BYTES)
        return "short download (" + String(total) + " bytes)";

    uint8_t digest[32];
    mbedtls_sha256(buf, IMAGE_BYTES, digest, 0);
    char hex[65];
    for (int i = 0; i < 32; i++)
        sprintf(hex + 2 * i, "%02x", digest[i]);
    if (!expectedSha.equalsIgnoreCase(hex))
        return "sha256 mismatch";
    return "";
}

void sendSignal(const String &pullId, bool success)
{
    if (pullId.length() == 0)
        return;
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

// Copies the verified buffer into the sprite and runs a full refresh
// (~3-4 s). update() leaves the panel controller in deep sleep.
void draw(const uint8_t *buf)
{
    epaper.begin();
    memcpy(epaper.getPointer(), buf, IMAGE_BYTES);
    uint32_t t0 = millis();
    epaper.update();
    Serial.printf("Panel refresh took %lums\n", (unsigned long)(millis() - t0));
}

} // namespace

String deviceId()
{
    String mac = WiFi.macAddress();
    mac.replace(":", "");
    return mac;
}

PullResult runPull(const char *reason, const Battery &battery)
{
    PullResult r{PullOutcome::Failed, 0, 0, ""};

    String url = String(SERVER_URL) + "/esp32/v1/pull?device_id=" + deviceId() + "&reason=" + reason +
                 "&battery=" + battery.pct + "&battery_mv=" + battery.mv;
    if (rtc.scheduledFor[0])
        url += "&scheduled_for=" + urlEncode(rtc.scheduledFor);
    // Empty after a cold boot (see power.h), so the server answers "show".
    if (rtc.current[0])
        url += "&current=" + urlEncode(rtc.current);

    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.setConnectTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(url))
    {
        r.detail = "bad SERVER_URL";
        return r;
    }
    http.addHeader("X-Access-Token", DEVICE_TOKEN);
    int code = http.GET();
    if (code != HTTP_CODE_OK)
    {
        http.end();
        r.detail = code < 0 ? HTTPClient::errorToString(code) : "HTTP " + String(code);
        return r;
    }
    String body = http.getString();
    http.end();
    r.answeredMs = millis();

    JsonDocument doc;
    if (deserializeJson(doc, body))
    {
        r.detail = "unparseable response";
        return r;
    }
    String st = doc["status"] | "";
    r.nextCheckS = doc["next_check_s"] | 0;
    strlcpy(rtc.scheduledFor, doc["next_check_at"] | "", sizeof rtc.scheduledFor);

    if (st == "keep" || st == "none")
    {
        r.outcome = PullOutcome::Kept;
        r.detail = st;
        return r;
    }
    if (st != "show")
    {
        r.outcome = PullOutcome::Declined;
        r.detail = "server: " + String((const char *)(doc["message"] | "error"));
        return r;
    }

    String name = doc["name"] | "";
    String pullId = doc["pull_id"] | "";
    if (!validName(name))
    {
        r.detail = "server sent a bad image name";
        return r;
    }
    uint8_t *buf = (uint8_t *)ps_malloc(IMAGE_BYTES);
    if (!buf)
        buf = (uint8_t *)malloc(IMAGE_BYTES);
    if (!buf)
    {
        r.detail = "out of memory";
        return r;
    }
    String err = download(doc["image_url"] | "", doc["image_bytes"] | 0, doc["sha256"] | "", buf);
    if (err.length())
    {
        free(buf);
        sendSignal(pullId, false);
        r.detail = "download: " + err;
        return r;
    }
    draw(buf);
    free(buf);
    strlcpy(rtc.current, name.c_str(), sizeof rtc.current);
    sendSignal(pullId, true);
    r.outcome = PullOutcome::Shown;
    r.detail = "show " + name;
    return r;
}
