#include "frame_config.h" // MUST be first -- see the include-order note there

#include "storage.h"

#include <SPI.h>
#include <SD.h>
#include <algorithm>

const char *CACHE_DIR = "/cache";
const char *DOWNLOAD_TMP = "/cache/.download.tmp";

namespace
{
SPIClass sdSPI(FSPI);
bool mounted = false;
} // namespace

bool sdIsMounted() { return mounted; }

bool mountSd()
{
    if (mounted)
    {
        return true;
    }
    pinMode(SD_CS, OUTPUT);
    digitalWrite(SD_CS, HIGH);
    sdSPI.begin(SD_SPI_SCLK, SD_SPI_MISO, SD_SPI_MOSI, SD_CS);
    if (!SD.begin(SD_CS, sdSPI, SD_FREQUENCY_HZ) || SD.cardType() == CARD_NONE)
    {
        Serial.println("SD mount failed -- check card/wiring");
        SD.end();
        sdSPI.end();
        return false;
    }
    mounted = true;
    if (!SD.exists(CACHE_DIR) && !SD.mkdir(CACHE_DIR))
    {
        Serial.printf("Could not create %s\n", CACHE_DIR);
    }
    // A download that died mid-transfer (power cut) leaves its temp behind.
    if (SD.exists(DOWNLOAD_TMP))
    {
        SD.remove(DOWNLOAD_TMP);
    }
    return true;
}

uint64_t sdFreeBytes()
{
    if (!mounted)
    {
        return 0;
    }
    uint64_t total = SD.totalBytes(), used = SD.usedBytes();
    return total > used ? total - used : 0;
}

// Server names look like "12-3f9a0c1d2e4b5a6f_G.bin". Anything else is refused
// before it gets near the filesystem: no paths, no dotfiles, bounded length.
bool validCacheName(const String &name)
{
    if (name.length() < 5 || name.length() > NAME_MAX_LEN || name[0] == '.' || !name.endsWith(".bin"))
    {
        return false;
    }
    for (size_t i = 0; i < name.length(); i++)
    {
        char c = name[i];
        if (!(isalnum((unsigned char)c) || c == '-' || c == '_' || c == '.'))
        {
            return false;
        }
    }
    return true;
}

String cachePath(const String &name) { return String(CACHE_DIR) + "/" + name; }

bool cacheHas(const String &name)
{
    return mounted && validCacheName(name) && SD.exists(cachePath(name));
}

namespace
{
struct CacheEntry
{
    String name;
    time_t written;
};

std::vector<CacheEntry> scanCache()
{
    std::vector<CacheEntry> out;
    if (!mounted)
    {
        return out;
    }
    File dir = SD.open(CACHE_DIR);
    if (!dir || !dir.isDirectory())
    {
        return out;
    }
    for (File f = dir.openNextFile(); f; f = dir.openNextFile())
    {
        String name = f.name();
        int slash = name.lastIndexOf('/');
        if (slash >= 0)
        {
            name = name.substring(slash + 1);
        }
        if (!f.isDirectory() && validCacheName(name))
        {
            out.push_back({name, f.getLastWrite()});
        }
        f.close();
    }
    dir.close();
    return out;
}
} // namespace

std::vector<String> listCache()
{
    std::vector<String> names;
    for (const CacheEntry &e : scanCache())
    {
        names.push_back(e.name);
    }
    std::sort(names.begin(), names.end());
    return names;
}

size_t cacheCount() { return scanCache().size(); }

void pruneCache(const String &keep)
{
    std::vector<CacheEntry> entries = scanCache();
    if (entries.size() <= CACHE_MAX_FILES)
    {
        return;
    }
    // Oldest first. Files written before NTP synced carry a 1980-ish stamp and
    // so go first, which is fine -- they're the oldest anyway.
    std::sort(entries.begin(), entries.end(),
              [](const CacheEntry &a, const CacheEntry &b) { return a.written < b.written; });
    size_t excess = entries.size() - CACHE_MAX_FILES;
    for (const CacheEntry &e : entries)
    {
        if (excess == 0)
        {
            break;
        }
        if (e.name == keep)
        {
            continue;
        }
        SD.remove(cachePath(e.name));
        excess--;
    }
}

uint8_t *loadImageBuffer(const String &name)
{
    if (!cacheHas(name))
    {
        return nullptr;
    }
    File f = SD.open(cachePath(name), FILE_READ);
    if (!f)
    {
        return nullptr;
    }
    uint8_t *buffer = (uint8_t *)ps_malloc(IMAGE_BYTES);
    if (!buffer)
    {
        Serial.println("ps_malloc failed for image buffer");
        f.close();
        return nullptr;
    }
    size_t got = f.read(buffer, IMAGE_BYTES);
    f.close();
    if (got != IMAGE_BYTES)
    {
        Serial.printf("Short read for %s: %u/%u bytes\n", name.c_str(), (unsigned)got, (unsigned)IMAGE_BYTES);
        free(buffer);
        return nullptr;
    }
    return buffer;
}
