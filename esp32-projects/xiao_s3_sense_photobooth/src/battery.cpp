#include "booth_config.h"

#include "battery.h"

#include <LittleFS.h>
#include <Preferences.h>
#include <esp_random.h>
#include <time.h>

namespace
{

constexpr const char *NVS_NAMESPACE = "battlog";
constexpr const char *LOG_DIR = "/battery";
constexpr const char *CSV_HEADER = "epoch,local_time,boot,uptime_s,event,a0_mv,battery_mv\n";

bool fsOk = false;
String logId;
String logPath;
uint32_t bootCount = 0;
size_t sentBytes = 0;
uint32_t lastSampleMs = 0;
uint32_t lastPushMs = 0;

void deleteDir(const char *dir)
{
    File d = LittleFS.open(dir);
    if (!d || !d.isDirectory())
        return;
    std::vector<String> names;
    for (File f = d.openNextFile(); f; f = d.openNextFile())
    {
        names.push_back(String(dir) + "/" + f.name());
        f.close();
    }
    d.close();
    for (const String &n : names)
        LittleFS.remove(n);
}

void startFreshLog(Preferences &p)
{
    // Also clears anything left in this flash by ../xiao_s3_sense_webcam's
    // battery logger, which used the same partition and folder.
    deleteDir(LOG_DIR);
    char id[17];
    snprintf(id, sizeof(id), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
    logId = id;
    sentBytes = 0;
    p.putString("id", logId);
    p.putULong("sent", 0);
    p.putUChar("gen", BATTERY_LOG_GENERATION);
    File f = LittleFS.open(String(LOG_DIR) + "/" + logId + ".csv", FILE_WRITE);
    if (f)
    {
        f.print(CSV_HEADER);
        f.close();
    }
    Serial.printf("Battery log: started fresh log %s\n", id);
}

} // namespace

void setupBattery()
{
    analogReadResolution(12);
    analogSetPinAttenuation(BATTERY_ADC_PIN, ADC_11db);
    // Formats the partition on first use (a few seconds, once).
    fsOk = LittleFS.begin(true);
    if (!fsOk)
    {
        Serial.println("Battery log: LittleFS mount failed -- no log");
        return;
    }
    if (!LittleFS.exists(LOG_DIR))
        LittleFS.mkdir(LOG_DIR);

    Preferences p;
    p.begin(NVS_NAMESPACE, false);
    bootCount = p.getULong("boots", 0) + 1;
    p.putULong("boots", bootCount);
    logId = p.getString("id", "");
    sentBytes = p.getULong("sent", 0);
    logPath = String(LOG_DIR) + "/" + logId + ".csv";
    if (p.getUChar("gen", 0) != BATTERY_LOG_GENERATION || logId.isEmpty() || !LittleFS.exists(logPath))
        startFreshLog(p);
    p.end();
    logPath = String(LOG_DIR) + "/" + logId + ".csv";

    lastSampleMs = millis();
    lastPushMs = millis();
    logBattery("boot");
}

void logBattery(const char *event)
{
    if (!fsOk)
        return;
    if (LittleFS.totalBytes() - LittleFS.usedBytes() < BATTERY_LOG_MIN_FREE_BYTES)
        return; // full; the server has everything up to the last push
    uint32_t sum = 0;
    for (int i = 0; i < BATTERY_ADC_SAMPLES; i++)
        sum += analogReadMilliVolts(BATTERY_ADC_PIN);
    int a0 = sum / BATTERY_ADC_SAMPLES;

    time_t now = time(nullptr);
    char local[24] = "";
    if (now > CLOCK_SANE_EPOCH)
    {
        struct tm tm;
        localtime_r(&now, &tm);
        strftime(local, sizeof(local), "%Y-%m-%d %H:%M:%S", &tm);
    }
    else
    {
        now = 0; // no clock: the server charts rows by epoch and skips these
    }
    char line[128];
    snprintf(line, sizeof(line), "%ld,%s,%lu,%lu,%s,%d,%d\n", (long)now, local, (unsigned long)bootCount,
             (unsigned long)(millis() / 1000), event, a0, (int)(a0 * BATTERY_DIVIDER));
    File f = LittleFS.open(logPath, FILE_APPEND);
    if (f)
    {
        f.print(line);
        f.close();
    }
    lastSampleMs = millis();
}

uint32_t msUntilBatterySample()
{
    uint32_t elapsed = millis() - lastSampleMs;
    uint32_t interval = BATTERY_LOG_INTERVAL_S * 1000UL;
    return elapsed >= interval ? 0 : interval - elapsed;
}

bool serviceBatteryTimer()
{
    if (!fsOk)
        return false;
    if (msUntilBatterySample() == 0)
        logBattery("timer");
    return (uint32_t)(millis() - lastPushMs) >= BATTERY_UPLOAD_INTERVAL_S * 1000UL && batteryLogSize() > sentBytes;
}

String batteryLogId() { return logId; }

size_t batteryLogSize()
{
    if (!fsOk)
        return 0;
    File f = LittleFS.open(logPath, FILE_READ);
    size_t n = f ? f.size() : 0;
    if (f)
        f.close();
    return n;
}

size_t batteryLogSent() { return sentBytes; }

void setBatteryLogSent(size_t bytes)
{
    sentBytes = bytes;
    Preferences p;
    p.begin(NVS_NAMESPACE, false);
    p.putULong("sent", bytes);
    p.end();
}

size_t readBatteryLog(size_t offset, uint8_t *buf, size_t max)
{
    File f = LittleFS.open(logPath, FILE_READ);
    if (!f)
        return 0;
    f.seek(offset);
    size_t n = f.read(buf, max);
    f.close();
    return n;
}

void markBatteryLogPushed() { lastPushMs = millis(); }
