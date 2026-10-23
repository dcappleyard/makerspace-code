#include "cam_config.h"

#include "battery.h"
#include "screen.h"
#include "web.h"

#include <HWCDC.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <freertos/semphr.h>
#include <time.h>
#include <algorithm>

namespace
{

constexpr const char *LOG_DIR = "/battery";
constexpr const char *NVS_NAMESPACE = "batt";
constexpr const char *CSV_HEADER =
    "elapsed_s,uptime_s,local_time,a0_mv,battery_mv_est,percent_est,usb_host,screen_on,stream_clients,event\n";
constexpr int CAL_POINTS = 11; // 100%, 90%, ... 0%

SemaphoreHandle_t lock = nullptr;
struct Guard
{
    Guard() { xSemaphoreTake(lock, portMAX_DELAY); }
    ~Guard() { xSemaphoreGive(lock); }
};

bool fsOk = false;
BatteryReading latest = {false, 0, 0, -1, false};
uint32_t lastReadMs = 0;

int cal[CAL_POINTS];
String calSource;

// Logger
bool logging = false;
String runName;
uint32_t intervalS = 30;
uint32_t samples = 0;
uint32_t elapsedBaseS = 0;   // carried over a reboot mid-run
uint32_t segmentStartMs = 0; // millis() when this boot's part of the run began
uint32_t lastSampleMs = 0;
String lastEvent;

void defaultCalibration()
{
    // Linear between BATTERY_EMPTY_A0_MV and BATTERY_FULL_A0_MV, as Seeed's example.
    for (int i = 0; i < CAL_POINTS; i++)
        cal[i] = BATTERY_FULL_A0_MV - (BATTERY_FULL_A0_MV - BATTERY_EMPTY_A0_MV) * i / (CAL_POINTS - 1);
    calSource = "";
}

int percentFor(int a0Mv)
{
    if (a0Mv >= cal[0])
        return 100;
    if (a0Mv <= cal[CAL_POINTS - 1])
        return 0;
    for (int i = 1; i < CAL_POINTS; i++)
    {
        if (a0Mv >= cal[i])
        {
            int hi = cal[i - 1], lo = cal[i];
            int pHi = 100 - (i - 1) * 10;
            return hi == lo ? pHi : pHi - 10 * (hi - a0Mv) / (hi - lo);
        }
    }
    return 0;
}

BatteryReading measure()
{
    uint32_t sum = 0;
    for (int i = 0; i < BATTERY_ADC_SAMPLES; i++)
        sum += analogReadMilliVolts(BATTERY_ADC_PIN);
    BatteryReading r;
    r.a0Mv = sum / BATTERY_ADC_SAMPLES;
    r.valid = r.a0Mv >= BATTERY_MIN_VALID_A0_MV;
    r.batteryMv = (int)(r.a0Mv * BATTERY_DIVIDER);
    r.percent = r.valid ? percentFor(r.a0Mv) : -1;
    r.usbHost = HWCDC::isPlugged();
    return r;
}

String runPath(const String &name) { return String(LOG_DIR) + "/" + name; }

uint32_t elapsedS() { return elapsedBaseS + (millis() - segmentStartMs) / 1000; }

String localTime()
{
    time_t now = time(nullptr);
    if (now <= CLOCK_SANE_EPOCH)
        return "";
    struct tm tm;
    localtime_r(&now, &tm);
    char buf[24];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm);
    return buf;
}

// One CSV row (a sample, or an event row with the same columns).
bool appendRow(const BatteryReading &r, const char *event)
{
    File f = LittleFS.open(runPath(runName), FILE_APPEND);
    if (!f)
        return false;
    char line[160];
    snprintf(line, sizeof(line), "%lu,%lu,%s,%d,%d,%d,%d,%d,%d,%s\n", (unsigned long)elapsedS(),
             (unsigned long)(millis() / 1000), localTime().c_str(), r.a0Mv, r.batteryMv, r.percent, r.usbHost ? 1 : 0,
             screenOn() ? 1 : 0, streamClientCount(), event);
    bool ok = f.print(line) == strlen(line);
    f.close();
    return ok;
}

void persistLogState()
{
    Preferences p;
    p.begin(NVS_NAMESPACE, false);
    p.putBool("logOn", logging);
    p.putString("logRun", runName);
    p.putULong("logIntv", intervalS);
    p.putULong("logElap", logging ? elapsedS() : 0);
    p.putULong("logN", samples);
    p.end();
}

// NVS is written every sample; at 30 s that's ~120 writes an hour, well within
// what NVS's wear levelling is for.
void takeSample(const char *event)
{
    if (appendRow(latest, event))
    {
        if (!*event)
            samples++;
        lastEvent = event;
    }
    persistLogState();
}

void stopLocked(const char *event)
{
    if (!logging)
        return;
    takeSample(event);
    logging = false;
    persistLogState();
    Serial.printf("Battery log %s stopped (%s)\n", runName.c_str(), event);
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

} // namespace

void setupBattery()
{
    lock = xSemaphoreCreateMutex();
    analogReadResolution(12);
    analogSetPinAttenuation(BATTERY_ADC_PIN, ADC_11db);

    defaultCalibration();
    Preferences p;
    if (p.begin(NVS_NAMESPACE, true))
    {
        int16_t stored[CAL_POINTS];
        if (p.getBytes("cal", stored, sizeof(stored)) == sizeof(stored))
        {
            for (int i = 0; i < CAL_POINTS; i++)
                cal[i] = stored[i];
            calSource = p.getString("calSrc", "calibrated");
        }
        logging = p.getBool("logOn", false);
        runName = p.getString("logRun", "");
        intervalS = p.getULong("logIntv", 30);
        elapsedBaseS = p.getULong("logElap", 0);
        samples = p.getULong("logN", 0);
        p.end();
    }

    // Formats the partition on first use (takes a few seconds, once).
    fsOk = LittleFS.begin(true);
    if (fsOk && !LittleFS.exists(LOG_DIR))
        LittleFS.mkdir(LOG_DIR);
    if (!fsOk)
        Serial.println("LittleFS mount failed -- battery logging unavailable");

    latest = measure();
    lastReadMs = millis();
    Serial.printf("Battery: A0 %d mV (~%d mV battery, %d%%), USB host %s\n", latest.a0Mv, latest.batteryMv,
                  latest.percent, latest.usbHost ? "yes" : "no");

    // A reset mid-run (brownout, watchdog, or someone pressing RST) carries on
    // the same run; the gap shows as a "boot" row.
    if (logging && fsOk && validRunName(runName) && LittleFS.exists(runPath(runName)))
    {
        segmentStartMs = millis();
        lastSampleMs = millis();
        takeSample("boot");
        Serial.printf("Battery log %s resumed after reboot\n", runName.c_str());
    }
    else if (logging)
    {
        logging = false;
        persistLogState();
    }
}

void serviceBattery()
{
    Guard g;
    uint32_t now = millis();
    if ((uint32_t)(now - lastReadMs) >= BATTERY_READ_INTERVAL_MS)
    {
        latest = measure();
        lastReadMs = now;
    }
    if (logging && (uint32_t)(now - lastSampleMs) >= intervalS * 1000UL)
    {
        lastSampleMs = now;
        latest = measure(); // fresh for the log, not up to 5 s old
        lastReadMs = now;
        if (LittleFS.totalBytes() - LittleFS.usedBytes() < BATTERY_LOG_MIN_FREE_BYTES)
            stopLocked("flash full");
        else
            takeSample("");
    }
}

BatteryReading batteryNow()
{
    Guard g;
    return latest;
}

bool validRunName(const String &name)
{
    // run-001.csv
    if (name.length() != 11 || !name.startsWith("run-") || !name.endsWith(".csv"))
        return false;
    for (int i = 4; i < 7; i++)
        if (!isdigit((unsigned char)name[i]))
            return false;
    return true;
}

bool startBatteryLog(uint32_t interval, String &name)
{
    Guard g;
    if (!fsOk)
        return false;
    if (logging)
        stopLocked("stop");

    Preferences p;
    p.begin(NVS_NAMESPACE, false);
    uint32_t seq = p.getULong("runSeq", 0);
    p.end();
    // Next free number (skips any that still exist).
    char buf[16];
    do
    {
        seq = seq % 999 + 1;
        snprintf(buf, sizeof(buf), "run-%03lu.csv", (unsigned long)seq);
    } while (LittleFS.exists(runPath(buf)));
    p.begin(NVS_NAMESPACE, false);
    p.putULong("runSeq", seq);
    p.end();

    File f = LittleFS.open(runPath(buf), FILE_WRITE);
    if (!f)
        return false;
    f.print(CSV_HEADER);
    f.close();

    runName = buf;
    intervalS = interval;
    samples = 0;
    elapsedBaseS = 0;
    segmentStartMs = millis();
    lastSampleMs = millis();
    logging = true;
    latest = measure();
    lastReadMs = millis();
    takeSample("start");
    takeSample(""); // a first data point at t=0
    name = runName;
    Serial.printf("Battery log %s started, every %lus\n", buf, (unsigned long)interval);
    return true;
}

void stopBatteryLog()
{
    Guard g;
    stopLocked("stop");
}

String batteryJson()
{
    Guard g;
    String j = "{";
    j += "\"valid\":" + String(latest.valid ? "true" : "false");
    j += ",\"a0_mv\":" + String(latest.a0Mv);
    j += ",\"battery_mv\":" + String(latest.batteryMv);
    j += ",\"percent\":" + String(latest.percent);
    j += ",\"usb_host\":" + String(latest.usbHost ? "true" : "false");
    j += ",\"divider\":" + String(BATTERY_DIVIDER, 2);
    j += ",\"cal_source\":" + jsonStr(calSource);
    j += ",\"cal\":[";
    for (int i = 0; i < CAL_POINTS; i++)
        j += (i ? "," : "") + String(cal[i]);
    j += "],\"fs\":" + String(fsOk ? "true" : "false");
    if (fsOk)
    {
        j += ",\"fs_free\":" + String((unsigned long)(LittleFS.totalBytes() - LittleFS.usedBytes()));
    }
    j += ",\"log\":{\"active\":" + String(logging ? "true" : "false");
    j += ",\"run\":" + jsonStr(logging ? runName : String(""));
    j += ",\"interval_s\":" + String(intervalS);
    j += ",\"samples\":" + String(logging ? samples : 0);
    j += ",\"elapsed_s\":" + String(logging ? elapsedS() : 0);
    j += "},\"runs\":[";
    if (fsOk)
    {
        std::vector<std::pair<String, size_t>> runs;
        File dir = LittleFS.open(LOG_DIR);
        if (dir && dir.isDirectory())
        {
            for (File f = dir.openNextFile(); f; f = dir.openNextFile())
            {
                String n = f.name();
                int slash = n.lastIndexOf('/');
                if (slash >= 0)
                    n = n.substring(slash + 1);
                if (validRunName(n))
                    runs.push_back({n, (size_t)f.size()});
                f.close();
            }
        }
        dir.close();
        std::sort(runs.begin(), runs.end(), [](const auto &a, const auto &b) { return a.first > b.first; });
        bool first = true;
        for (const auto &r : runs)
        {
            j += String(first ? "" : ",") + "{\"name\":" + jsonStr(r.first) + ",\"size\":" + String(r.second) +
                 ",\"active\":" + ((logging && r.first == runName) ? "true" : "false") + "}";
            first = false;
        }
    }
    return j + "]}";
}

bool readRun(const String &name, const std::function<bool(const uint8_t *, size_t)> &sink)
{
    if (!validRunName(name))
        return false;
    // Lock per chunk, not for the whole download, so a slow client doesn't
    // stall loop() (the screen and the logger).
    size_t offset = 0;
    static uint8_t buf[2048]; // only the API server task calls this
    while (true)
    {
        size_t n;
        {
            Guard g;
            if (!fsOk)
                return false;
            File f = LittleFS.open(runPath(name), FILE_READ);
            if (!f)
                return offset > 0;
            f.seek(offset);
            n = f.read(buf, sizeof(buf));
            f.close();
        }
        if (n == 0)
            return true;
        if (!sink(buf, n))
            return false;
        offset += n;
    }
}

bool deleteRun(const String &name)
{
    Guard g;
    if (!fsOk || !validRunName(name) || (logging && name == runName))
        return false;
    return LittleFS.remove(runPath(name));
}

bool setCalibration(const int *mv, const String &source)
{
    for (int i = 0; i < CAL_POINTS; i++)
    {
        if (mv[i] < 0 || mv[i] > 3300 || (i && mv[i] > mv[i - 1]))
            return false;
    }
    if (mv[0] == mv[CAL_POINTS - 1])
        return false;
    Guard g;
    int16_t stored[CAL_POINTS];
    for (int i = 0; i < CAL_POINTS; i++)
        cal[i] = stored[i] = mv[i];
    calSource = source.length() ? source : String("calibrated");
    Preferences p;
    p.begin(NVS_NAMESPACE, false);
    p.putBytes("cal", stored, sizeof(stored));
    p.putString("calSrc", calSource);
    p.end();
    latest.percent = latest.valid ? percentFor(latest.a0Mv) : -1;
    return true;
}

void resetCalibration()
{
    Guard g;
    defaultCalibration();
    Preferences p;
    p.begin(NVS_NAMESPACE, false);
    p.remove("cal");
    p.remove("calSrc");
    p.end();
    latest.percent = latest.valid ? percentFor(latest.a0Mv) : -1;
}
