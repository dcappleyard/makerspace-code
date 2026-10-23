#include "storage.h"
#include "screen.h"

#include <Preferences.h>
#include <SD.h>
#include <SPI.h>
#include <time.h>
#include <algorithm>

const char *PHOTO_DIR = "/photos";

namespace
{

constexpr const char *NVS_NAMESPACE = "storage";
bool mounted = false;

struct RamPhoto
{
    String name;
    uint8_t *data; // ps_malloc'd
    size_t len;
};
std::vector<RamPhoto> ramPhotos; // oldest first
size_t ramBytes = 0;

String sdPath(const String &name) { return String(PHOTO_DIR) + "/" + name; }

RamPhoto *findRam(const String &name)
{
    for (RamPhoto &p : ramPhotos)
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
    free(ramPhotos.front().data);
    ramBytes -= ramPhotos.front().len;
    Serial.printf("RAM store full -- dropped %s\n", ramPhotos.front().name.c_str());
    ramPhotos.erase(ramPhotos.begin());
}

// "2026-10-19_14-03-22" from the clock, or "nodate_0000123456" (uptime ms,
// zero-padded so they sort) before NTP has set it.
String baseName(bool &dated)
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
    while (!ramPhotos.empty())
    {
        RamPhoto &p = ramPhotos.front();
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
        ramPhotos.erase(ramPhotos.begin());
        moved++;
    }
    return moved;
}

// Dated names newest first, then nodate_ ones (also newest first, they're
// zero-padded uptimes).
bool newerFirst(const PhotoInfo &a, const PhotoInfo &b)
{
    bool aNodate = a.name.startsWith("nodate_"), bNodate = b.name.startsWith("nodate_");
    if (aNodate != bNodate)
        return bNodate;
    return a.name > b.name;
}

} // namespace

bool mountSd(size_t *moved)
{
    if (moved)
        *moved = 0;
    if (mounted)
    {
        SD.end();
        mounted = false;
    }
    // Two possible slots share GPIO 7/8/9 with the round display: the Sense
    // board's (CS 21) and the display's own (CS 3 / D2 -- the one Seeed's wiki
    // points at when the round display is fitted). Both ride on the display's
    // SPI instance (already begun by setupScreen()) rather than the global SPI
    // -- see screenSpi() in screen.h. Each is tried at 20 MHz, then slower;
    // the slot that worked last goes first (remembered in NVS), since an empty
    // slot costs ~600 ms per attempt to give up on.
    struct Slot
    {
        int cs;
        int otherCs;
        const char *where;
    };
    Slot slots[] = {{SD_CS, ROUND_SD_CS, "Sense board"}, {ROUND_SD_CS, SD_CS, "round display"}};
    const uint32_t freqs[] = {SD_FREQUENCY_HZ, SD_SLOW_FREQUENCY_HZ};
    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, true);
    int preferred = prefs.getInt("sdCs", ROUND_SD_CS);
    prefs.end();
    if (slots[0].cs != preferred)
        std::swap(slots[0], slots[1]);

    for (const Slot &slot : slots)
    {
        for (uint32_t hz : freqs)
        {
            pinMode(slot.otherCs, OUTPUT);
            digitalWrite(slot.otherCs, HIGH); // only one card selected at a time
            uint32_t t0 = millis();
            bool ok = SD.begin(slot.cs, screenSpi(), hz) && SD.cardType() != CARD_NONE;
            Serial.printf("SD: %s slot (CS %d) at %lu MHz: %s (%lu ms)\n", slot.where, slot.cs,
                          (unsigned long)(hz / 1000000), ok ? "OK" : "no card", (unsigned long)(millis() - t0));
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
        Serial.println("No SD card -- snapshots will be kept in RAM");
        return false;
    }
    if (!SD.exists(PHOTO_DIR) && !SD.mkdir(PHOTO_DIR))
        Serial.printf("Could not create %s\n", PHOTO_DIR);
    size_t n = flushRamToSd();
    if (moved)
        *moved = n;
    Serial.printf("SD card mounted (%lu MB free)%s\n", (unsigned long)(sdFreeBytes() / (1024 * 1024)),
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

// Our own names only: no paths, no dotfiles, bounded length, .jpg.
bool validPhotoName(const String &name)
{
    if (name.length() < 5 || name.length() > PHOTO_NAME_MAX_LEN || name[0] == '.' || !name.endsWith(".jpg"))
        return false;
    for (size_t i = 0; i < name.length(); i++)
    {
        char c = name[i];
        if (!(isalnum((unsigned char)c) || c == '-' || c == '_' || c == '.'))
            return false;
    }
    return true;
}

SaveResult savePhoto(const uint8_t *data, size_t len)
{
    SaveResult r = {false, "", false, false};
    r.name = uniqueName(baseName(r.dated));
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
    while (!ramPhotos.empty() && (ramPhotos.size() >= RAM_PHOTOS_MAX || ramBytes + len > RAM_PHOTOS_MAX_BYTES))
        dropOldestRam();
    uint8_t *copy = (uint8_t *)ps_malloc(len);
    if (!copy)
        return r;
    memcpy(copy, data, len);
    ramPhotos.push_back({r.name, copy, len});
    ramBytes += len;
    r.ok = true;
    return r;
}

std::vector<PhotoInfo> listPhotos()
{
    std::vector<PhotoInfo> out;
    for (const RamPhoto &p : ramPhotos)
        out.push_back({p.name, p.len, false});
    if (mounted)
    {
        File dir = SD.open(PHOTO_DIR);
        if (dir && dir.isDirectory())
        {
            for (File f = dir.openNextFile(); f; f = dir.openNextFile())
            {
                String name = f.name();
                int slash = name.lastIndexOf('/');
                if (slash >= 0)
                    name = name.substring(slash + 1);
                if (!f.isDirectory() && validPhotoName(name))
                    out.push_back({name, (size_t)f.size(), true});
                f.close();
            }
        }
        dir.close();
    }
    std::sort(out.begin(), out.end(), newerFirst);
    return out;
}

bool findPhoto(const String &name, PhotoInfo &out)
{
    if (!validPhotoName(name))
        return false;
    if (RamPhoto *p = findRam(name))
    {
        out = {p->name, p->len, false};
        return true;
    }
    if (!mounted)
        return false;
    File f = SD.open(sdPath(name), FILE_READ);
    if (!f)
        return false;
    out = {name, (size_t)f.size(), true};
    f.close();
    return true;
}

bool readPhoto(const String &name, const std::function<bool(const uint8_t *, size_t)> &sink)
{
    if (!validPhotoName(name))
        return false;
    if (RamPhoto *p = findRam(name))
        return sink(p->data, p->len);
    if (!mounted)
        return false;
    File f = SD.open(sdPath(name), FILE_READ);
    if (!f)
        return false;
    static uint8_t buf[4096]; // single caller task -- see storage.h
    bool ok = true;
    while (ok && f.available())
    {
        size_t n = f.read(buf, sizeof(buf));
        if (n == 0)
            break;
        ok = sink(buf, n);
    }
    f.close();
    return ok;
}

bool deletePhoto(const String &name)
{
    if (!validPhotoName(name))
        return false;
    for (size_t i = 0; i < ramPhotos.size(); i++)
    {
        if (ramPhotos[i].name == name)
        {
            free(ramPhotos[i].data);
            ramBytes -= ramPhotos[i].len;
            ramPhotos.erase(ramPhotos.begin() + i);
            return true;
        }
    }
    return mounted && SD.remove(sdPath(name));
}

size_t ramPhotoCount() { return ramPhotos.size(); }
size_t ramPhotoBytes() { return ramBytes; }
