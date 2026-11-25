// xiao_s3_ee04_pullframe -- battery-powered pull client of the eink_photo_server.
//
// Every wake: read the battery, connect WiFi, ask the server what to show,
// download + verify + draw if it's new, then deep sleep until the server's
// next check. If the server can't be reached the panel keeps its last image
// (e-paper needs no power to hold it) and the frame retries with a backoff.
// See README.md and DESIGN.md.
#include "frame_config.h"
#include "power.h"
#include "pull.h"

#include <WiFi.h>

#include "secrets.h" // WIFI_SSID / WIFI_PASSWORD -- gitignored

EPaper epaper;

namespace
{

bool timerWake = false;
uint32_t nextCycleMs = 0; // stay-awake mode only

bool waitConnected(uint32_t timeoutMs)
{
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeoutMs)
        delay(20);
    return WiFi.status() == WL_CONNECTED;
}

bool connectWiFi()
{
    if (WiFi.status() == WL_CONNECTED)
        return true;
    uint32_t t0 = millis();
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(HOSTNAME);
    bool ok = false;
    if (rtc.apValid)
    {
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD, rtc.channel, rtc.bssid);
        ok = waitConnected(WIFI_FAST_TIMEOUT_MS);
        if (!ok)
        {
            Serial.println("Remembered AP didn't answer -- full connect");
            rtc.apValid = false;
            WiFi.disconnect(false, false);
        }
    }
    if (!ok)
    {
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        ok = waitConnected(WIFI_CONNECT_TIMEOUT_MS);
    }
    if (ok)
    {
        memcpy(rtc.bssid, WiFi.BSSID(), 6);
        rtc.channel = WiFi.channel();
        rtc.apValid = true;
        Serial.printf("WiFi up in %lums: %s, RSSI %d\n", (unsigned long)(millis() - t0),
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
    }
    else
    {
        Serial.printf("WiFi failed (status %d)\n", WiFi.status());
    }
    return ok;
}

uint32_t backoffS()
{
    constexpr size_t n = sizeof(RETRY_BACKOFF_S) / sizeof(RETRY_BACKOFF_S[0]);
    uint8_t i = rtc.failures == 0 ? 0 : rtc.failures - 1;
    return RETRY_BACKOFF_S[i < n ? i : n - 1];
}

// One wake's work. Returns how long to sleep.
uint32_t runCycle(const char *reason)
{
    Battery bat = readBattery();
    Serial.printf("Battery %u mV (%u%%, raw %u)\n", bat.mv, bat.pct, bat.raw);

    if (bat.mv < BATTERY_CUTOFF_MV && !(STAY_AWAKE_ON_USB_HOST && HWCDC::isPlugged()))
    {
        Serial.println("Battery below cutoff -- not pulling");
        return BATTERY_CUTOFF_SLEEP_S;
    }

    PullResult r;
    if (connectWiFi())
    {
        r = runPull(rtc.failures ? "retry" : reason, bat);
    }
    else
    {
        r = {PullOutcome::Failed, 0, 0, "no WiFi"};
    }

    uint32_t sleepS;
    if (r.outcome == PullOutcome::Failed)
    {
        if (rtc.failures < 255)
            rtc.failures++;
        sleepS = backoffS();
        Serial.printf("Pull failed (%u in a row): %s -- keeping the last image\n", rtc.failures, r.detail.c_str());
    }
    else
    {
        rtc.failures = 0;
        // next_check_s counts from the server's answer; take off the time
        // spent since (download, refresh, signal).
        uint32_t spentS = (millis() - r.answeredMs) / 1000;
        sleepS = r.nextCheckS > spentS ? r.nextCheckS - spentS : 0;
        Serial.printf("Pull (%s): %s, next check in %lus\n", reason, r.detail.c_str(), (unsigned long)sleepS);
    }
    return constrain(sleepS, MIN_CHECK_S, MAX_CHECK_S);
}

void sleepOrWait(uint32_t seconds)
{
    if (stayAwake(timerWake))
    {
        Serial.printf("Staying awake (USB host or boot window); next cycle in %lus\n", (unsigned long)seconds);
        nextCycleMs = millis() + seconds * 1000UL;
        return;
    }
    deepSleep(seconds);
}

} // namespace

void setup()
{
    timerWake = beginPower();
    Serial.begin(115200);
    if (!timerWake)
    {
        // Cold boot: give the serial monitor a moment to attach.
        for (int i = 0; i < 20 && !Serial; i++)
            delay(100);
    }
    Serial.printf("\nxiao_s3_ee04_pullframe [%s, MAC %s]: %s (wake #%lu), current \"%s\"\n", HOSTNAME,
                  WiFi.macAddress().c_str(), timerWake ? "timer wake" : "cold boot", (unsigned long)rtc.wakes,
                  rtc.current);

    sleepOrWait(runCycle(timerWake ? "timer" : "boot"));
}

void loop()
{
    // Only reached in stay-awake mode.
    if (!stayAwake(timerWake))
    {
        int32_t leftMs = (int32_t)(nextCycleMs - millis());
        deepSleep(leftMs > 0 ? max<uint32_t>(leftMs / 1000, 1) : 1);
    }
    if ((int32_t)(millis() - nextCycleMs) >= 0)
        sleepOrWait(runCycle("timer"));
    delay(100);
}
