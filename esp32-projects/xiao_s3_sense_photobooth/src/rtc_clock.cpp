#include "booth_config.h" // first, see screen.cpp

#include "rtc_clock.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_sntp.h>
#include <sys/time.h>
#include <time.h>

#if __has_include("secrets.h")
#include "secrets.h"
#endif

namespace
{
// PCF8563 registers 0x02-0x08, all BCD, holding UTC:
//   0x02 seconds (bit7 = VL, clock integrity lost)   0x03 minutes
//   0x04 hours                                       0x05 days
//   0x06 weekday 0-6                                 0x07 months (bit7 = century)
//   0x08 years 00-99
// Years are read as 2000+yy and the century bit is ignored.
constexpr uint8_t REG_SECONDS = 0x02;
constexpr size_t REG_COUNT = 7;

volatile bool sntpSynced = false;

uint8_t fromBcd(uint8_t v) { return (v >> 4) * 10 + (v & 0x0F); }
uint8_t toBcd(uint8_t v) { return ((v / 10) << 4) | (v % 10); }

// Days since 1970-01-01 for a proleptic Gregorian date (Hinnant's algorithm);
// avoids mktime(), which would apply the local TZ.
int64_t daysFromCivil(int y, int m, int d)
{
    y -= m <= 2;
    const int era = (y >= 0 ? y : y - 399) / 400;
    const int yoe = y - era * 400;
    const int doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    const int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return (int64_t)era * 146097 + doe - 719468;
}

// Returns the RTC's UTC epoch, or 0 if it didn't answer or isn't trustworthy.
time_t readRtc()
{
    Wire.beginTransmission(RTC_I2C_ADDR);
    Wire.write(REG_SECONDS);
    if (Wire.endTransmission() != 0)
    {
        Serial.println("RTC: no ACK from PCF8563");
        return 0;
    }
    if (Wire.requestFrom((int)RTC_I2C_ADDR, (int)REG_COUNT) != (int)REG_COUNT)
    {
        Serial.println("RTC: short read");
        return 0;
    }
    uint8_t r[REG_COUNT];
    for (size_t i = 0; i < REG_COUNT; i++)
    {
        r[i] = Wire.read();
    }
    if (r[0] & 0x80)
    {
        Serial.println("RTC: VL set, time not trusted");
        return 0;
    }
    const int sec = fromBcd(r[0] & 0x7F);
    const int min = fromBcd(r[1] & 0x7F);
    const int hour = fromBcd(r[2] & 0x3F);
    const int day = fromBcd(r[3] & 0x3F);
    const int mon = fromBcd(r[5] & 0x1F);
    const int year = 2000 + fromBcd(r[6]);
    if (sec > 59 || min > 59 || hour > 23 || day < 1 || day > 31 || mon < 1 || mon > 12)
    {
        Serial.println("RTC: invalid fields");
        return 0;
    }
    return (time_t)(daysFromCivil(year, mon, day) * 86400 + hour * 3600 + min * 60 + sec);
}

// Writing seconds with bit 7 clear also clears VL.
void writeRtc(time_t utc)
{
    struct tm t;
    gmtime_r(&utc, &t);
    Wire.beginTransmission(RTC_I2C_ADDR);
    Wire.write(REG_SECONDS);
    Wire.write(toBcd(t.tm_sec));
    Wire.write(toBcd(t.tm_min));
    Wire.write(toBcd(t.tm_hour));
    Wire.write(toBcd(t.tm_mday));
    Wire.write(t.tm_wday);
    Wire.write(toBcd(t.tm_mon + 1));
    Wire.write(toBcd(t.tm_year % 100));
    if (Wire.endTransmission() != 0)
    {
        Serial.println("RTC: write failed");
    }
}

void onSntpSync(struct timeval *) { sntpSynced = true; }

} // namespace

#ifdef WIFI_SSID
bool wifiUp()
{
    if (WiFi.status() == WL_CONNECTED)
        return true;
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(HOSTNAME);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS)
    {
        delay(100);
    }
    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println("WiFi: connect timed out");
        wifiDown();
        return false;
    }
    return true;
}

void wifiDown()
{
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
}

bool ntpSyncNow()
{
    if (WiFi.status() != WL_CONNECTED)
        return false;
    sntpSynced = false;
    sntp_set_time_sync_notification_cb(onSntpSync);
    configTzTime(TZ_DEFAULT, NTP_SERVER_1, NTP_SERVER_2);
    uint32_t start = millis();
    while (!sntpSynced && millis() - start < NTP_SYNC_TIMEOUT_MS)
    {
        delay(100);
    }
    bool synced = sntpSynced && clockValid();
    if (synced)
    {
        writeRtc(time(nullptr));
    }
    return synced;
}
#else
bool wifiUp() { return false; }
void wifiDown() {}
bool ntpSyncNow() { return false; }
#endif

namespace
{
// Days since 1970-01-01 for a civil date (Howard Hinnant's days_from_civil).
long daysFromCivil(int y, unsigned m, unsigned d)
{
    y -= m <= 2;
    long era = (y >= 0 ? y : y - 399) / 400;
    unsigned yoe = (unsigned)(y - era * 400);
    unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + (long)doe - 719468;
}

// "Sun, 25 Oct 2026 14:03:22 GMT" (RFC 7231 IMF-fixdate) -> epoch, or 0.
time_t parseHttpDate(const String &s)
{
    int d, y, hh, mm, ss;
    char mon[4] = {0};
    if (sscanf(s.c_str(), "%*3s, %d %3s %d %d:%d:%d", &d, mon, &y, &hh, &mm, &ss) != 6)
        return 0;
    const char *months = "JanFebMarAprMayJunJulAugSepOctNovDec";
    const char *at = strstr(months, mon);
    if (!at || (at - months) % 3)
        return 0;
    unsigned m = (unsigned)((at - months) / 3 + 1);
    return (time_t)daysFromCivil(y, m, (unsigned)d) * 86400 + hh * 3600 + mm * 60 + ss;
}
} // namespace

bool serverTimeSync()
{
#if defined(WIFI_SSID) && defined(SERVER_URL)
    if (WiFi.status() != WL_CONNECTED)
        return false;
    HTTPClient http;
    http.setTimeout(5000);
    http.setConnectTimeout(5000);
    if (!http.begin(String(SERVER_URL) + "/health"))
        return false;
    const char *keys[] = {"Date"};
    http.collectHeaders(keys, 1);
    int code = http.GET();
    String date = http.header("Date");
    http.end();
    time_t t = code > 0 ? parseHttpDate(date) : 0;
    if (t <= CLOCK_SANE_EPOCH)
    {
        Serial.printf("Clock: no usable Date from the server (%d, \"%s\")\n", code, date.c_str());
        return false;
    }
    struct timeval tv = {t, 0};
    settimeofday(&tv, nullptr);
    writeRtc(t);
    return true;
#else
    return false;
#endif
}

bool syncClockOnline()
{
    // The photo server first: it's on the LAN, answers in milliseconds and is
    // good to a second -- plenty for photo names. NTP only if that fails (it
    // needs outside access, and waits NTP_SYNC_TIMEOUT_MS when there's none).
    if (serverTimeSync())
    {
        Serial.printf("Clock: set from the photo server: %s\n", formatLocalTime().c_str());
        return true;
    }
    return ntpSyncNow();
}

bool clockValid()
{
    return time(nullptr) > CLOCK_SANE_EPOCH;
}

String timestampForName()
{
    if (!clockValid())
    {
        return "";
    }
    time_t now = time(nullptr);
    struct tm t;
    localtime_r(&now, &t);
    char buf[24];
    strftime(buf, sizeof(buf), "%Y-%m-%d_%H-%M-%S", &t);
    return String(buf);
}

String formatLocalTime()
{
    if (!clockValid())
    {
        return "not set";
    }
    time_t now = time(nullptr);
    struct tm t;
    localtime_r(&now, &t);
    char buf[40];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S %Z", &t);
    return String(buf);
}

void setupClock()
{
    setenv("TZ", TZ_DEFAULT, 1);
    tzset();

    const char *source = "none";
    time_t rtc = readRtc();
    if (rtc > CLOCK_SANE_EPOCH)
    {
        struct timeval tv = {rtc, 0};
        settimeofday(&tv, nullptr);
        source = "rtc";
    }

#ifdef WIFI_SSID
    // Connect, sync, and always power WiFi down again (the uploader brings it
    // back briefly when there are photos to send -- see upload.cpp).
    if (wifiUp() && syncClockOnline())
    {
        source = "online";
    }
    wifiDown();
#else
    Serial.println("Clock: no secrets.h WiFi credentials, using RTC only");
#endif

    Serial.printf("Clock: source=%s time=%s\n", source, formatLocalTime().c_str());
}
