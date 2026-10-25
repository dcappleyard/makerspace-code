#include "storage.h"
#include "screen.h"

#include <Preferences.h>
#include <SD.h>
#include <SPI.h>
#include <time.h>
#include <algorithm>

const char *PHOTO_DIR = "/photos";
const char *UPLOADED_DIR = "/photos/uploaded";

namespace
{

constexpr const char *NVS_NAMESPACE = "booth";

bool mounted = false;

struct RamPhoto
{
    String name;
    uint8_t *data; // ps_malloc'd
    size_t len;
};
std::vector<RamPhoto> ramStore; // oldest first
size_t ramBytes = 0;

String sdPath(const String &name) { return String(PHOTO_DIR) + "/" + name; }

RamPhoto *findRam(const String &name)
{
    for (RamPhoto &p : ramStore)
    {
        if (p.name == name)
            return &p;
    }
    return nullptr;
}

bool nameTaken(const String &name)
{
    return findRam(name) || (mounted && SD.exists(sdPath(name)));
}

void dropOldestRam()
{
    free(ramStore.front().data);
    ramBytes -= ramStore.front().len;
    Serial.printf("RAM store full -- dropped %s\n", ramStore.front().name.c_str());
    ramStore.erase(ramStore.begin());
}

} // namespace

// "2026-10-19_14-03-22" from the clock, or "nodate_0000123456" (uptime ms,
// zero-padded so they sort) if neither the RTC nor NTP has set it.
String sequenceName(bool &dated)
{
    time_t now = time(nullptr);
    dated = now > CLOCK_SANE_EPOCH;
    char buf[32];
    if (dated)
    {
        struct tm tm;
        localtime_r(&now, &tm);
        strftime(buf, sizeof(buf), "%Y-%m-%d_%H-%M-%S", &tm);
    }
    else
    {
        snprintf(buf, sizeof(buf), "nodate_%010lu", (unsigned long)millis());
    }
    return buf;
}

namespace
{

// Adds -2, -3, ... until the name is free on both the card and in RAM.
String uniqueName(const String &base)
{
    String name = base + ".jpg";
    for (int n = 2; nameTaken(name); n++)
        name = base + "-" + String(n) + ".jpg";
    return name;
}

bool writeSd(const String &name, const uint8_t *data, size_t len)
{
    File f = SD.open(sdPath(name), FILE_WRITE);
    if (!f)
        return false;
    size_t wrote = f.write(data, len);
    f.close();
    if (wrote != len)
    {
        SD.remove(sdPath(name));
        return false;
    }
    return true;
}

size_t flushRamToSd()
{
    size_t moved = 0;
    while (!ramStore.empty())
    {
        RamPhoto &p = ramStore.front();
        // The name was unique when taken, but the card may already hold one
        // like it (e.g. a nodate_ name from an earlier boot).
        String name = SD.exists(sdPath(p.name)) ? uniqueName(p.name.substring(0, p.name.length() - 4)) : p.name;
        if (!writeSd(name, p.data, p.len))
        {
            Serial.printf("Couldn't move %s to the card -- keeping the rest in RAM\n", p.name.c_str());
            break;
        }
        free(p.data);
        ramBytes -= p.len;
        ramStore.erase(ramStore.begin());
        moved++;
    }
    return moved;
}

} // namespace

bool mountSd(size_t *moved, bool thorough)
{
    if (moved)
        *moved = 0;
    if (mounted)
    {
        SD.end();
        mounted = false;
    }
    // Two possible slots share GPIO 7/8/9 with the display: the Sense board's
    // (CS 21) and the round display's own (CS 3 / D2 -- the one Seeed's wiki
    // points at when the round display is fitted). Both ride on the display's
    // SPI instance (screenSpi()). A thorough pass tries each slot at 20 MHz,
    // then slower; a quick one (used at every wake) tries each once, slow.
    struct Slot
    {
        int cs;
        int otherCs;
        const char *where;
    };
    // The slot that worked last time goes first (remembered in NVS): each
    // empty slot costs ~600 ms to give up on.
    Slot slots[] = {{SD_CS, ROUND_SD_CS, "Sense board"}, {ROUND_SD_CS, SD_CS, "round display"}};
    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, true);
    int preferred = prefs.getInt("sdCs", ROUND_SD_CS);
    prefs.end();
    if (slots[0].cs != preferred)
        std::swap(slots[0], slots[1]);
    const uint32_t fast[] = {SD_FREQUENCY_HZ, SD_SLOW_FREQUENCY_HZ};
    const uint32_t quick[] = {SD_SLOW_FREQUENCY_HZ};
    const uint32_t *freqs = thorough ? fast : quick;
    size_t nFreqs = thorough ? 2 : 1;

    for (const Slot &slot : slots)
    {
        for (size_t i = 0; i < nFreqs; i++)
        {
            pinMode(slot.otherCs, OUTPUT);
            digitalWrite(slot.otherCs, HIGH); // only one card selected at a time
            uint32_t t0 = millis();
            bool ok = SD.begin(slot.cs, screenSpi(), freqs[i]) && SD.cardType() != CARD_NONE;
            Serial.printf("SD: %s slot (CS %d) at %lu MHz: %s (%lu ms)\n", slot.where, slot.cs,
                          (unsigned long)(freqs[i] / 1000000), ok ? "OK" : "no card", (unsigned long)(millis() - t0));
            if (ok)
            {
                mounted = true;
                if (slot.cs != preferred)
                {
                    prefs.begin(NVS_NAMESPACE, false);
                    prefs.putInt("sdCs", slot.cs);
                    prefs.end();
                }
                break;
            }
            SD.end();
        }
        if (mounted)
            break;
    }
    if (!mounted)
    {
        Serial.println("No SD card -- photos will be kept in RAM");
        return false;
    }
    if (!SD.exists(PHOTO_DIR) && !SD.mkdir(PHOTO_DIR))
        Serial.printf("Could not create %s\n", PHOTO_DIR);
    size_t n = flushRamToSd();
    if (moved)
        *moved = n;
    static const char *types[] = {"none", "MMC", "SD", "SDHC", "unknown"};
    uint8_t type = SD.cardType();
    Serial.printf("SD card mounted: %s, %lu MB, %lu MB free%s\n", types[type < 5 ? type : 4],
                  (unsigned long)(SD.cardSize() / (1024 * 1024)), (unsigned long)(sdFreeBytes() / (1024 * 1024)),
                  n ? (", moved " + String(n) + " RAM photos onto it").c_str() : "");
    return true;
}

bool sdIsMounted() { return mounted; }

uint64_t sdFreeBytes()
{
    if (!mounted)
        return 0;
    uint64_t total = SD.totalBytes(), used = SD.usedBytes();
    return total > used ? total - used : 0;
}

SaveResult savePhoto(const uint8_t *data, size_t len, const String &base)
{
    SaveResult r = {false, "", false};
    r.name = uniqueName(base);
    if (mounted)
    {
        if (writeSd(r.name, data, len))
        {
            r.ok = r.onSd = true;
            return r;
        }
        // Most likely the card was pulled. Fall back to RAM until a re-check.
        Serial.println("SD write failed -- treating the card as gone");
        SD.end();
        mounted = false;
    }
    if (len > RAM_PHOTOS_MAX_BYTES)
        return r;
    while (!ramStore.empty() && (ramStore.size() >= RAM_PHOTOS_MAX || ramBytes + len > RAM_PHOTOS_MAX_BYTES))
        dropOldestRam();
    uint8_t *copy = (uint8_t *)ps_malloc(len);
    if (!copy)
        return r;
    memcpy(copy, data, len);
    ramStore.push_back({r.name, copy, len});
    ramBytes += len;
    r.ok = true;
    return r;
}

size_t ramPhotoCount() { return ramStore.size(); }
size_t ramPhotoBytes() { return ramBytes; }

std::vector<String> pendingSdPhotos()
{
    std::vector<String> names;
    if (!mounted)
        return names;
    File dir = SD.open(PHOTO_DIR);
    if (!dir || !dir.isDirectory())
        return names;
    for (File f = dir.openNextFile(); f; f = dir.openNextFile())
    {
        String name = f.name();
        int slash = name.lastIndexOf('/');
        if (slash >= 0)
            name = name.substring(slash + 1);
        if (!f.isDirectory() && !name.startsWith(".") && name.endsWith(".jpg"))
            names.push_back(name);
        f.close();
    }
    dir.close();
    std::sort(names.begin(), names.end()); // timestamped names: oldest first
    return names;
}

bool markSdUploaded(const String &name)
{
    if (!mounted)
        return false;
    if (!SD.exists(UPLOADED_DIR) && !SD.mkdir(UPLOADED_DIR))
        return false;
    String to = String(UPLOADED_DIR) + "/" + name;
    if (SD.exists(to))
        SD.remove(to);
    return SD.rename(sdPath(name), to);
}

std::vector<RamPhotoRef> ramPhotos()
{
    std::vector<RamPhotoRef> out;
    for (const RamPhoto &p : ramStore)
        out.push_back({p.name, p.data, p.len});
    return out;
}

void dropRamPhoto(const String &name)
{
    for (size_t i = 0; i < ramStore.size(); i++)
    {
        if (ramStore[i].name == name)
        {
            free(ramStore[i].data);
            ramBytes -= ramStore[i].len;
            ramStore.erase(ramStore.begin() + i);
            return;
        }
    }
}
