#include "frame_config.h" // MUST be first -- see the include-order note there

#include "storage.h"

#include <SPI.h>
#include <SD.h>
#include <algorithm>
#include <time.h>

const char *PICTURES_DIR = "/pictures";
const char *CONFIG_PATH = "/frame_config.xml";
const char *COUNTER_TRACK_PATH = "/counter_track.txt";
// Uploads stream here first and are renamed into /pictures only once complete
// and validated -- see web.cpp. Swept at boot so a power cut mid-upload can't
// leave debris behind.
const char *UPLOAD_TMP_BIN = "/upload_bin.tmp";
const char *UPLOAD_TMP_XML = "/upload_xml.tmp";

namespace
{
SPIClass sdSPI(FSPI);
bool mounted = false;
bool everMounted = false;
} // namespace

bool sdIsMounted() { return mounted; }
bool sdEverMounted() { return everMounted; }

bool mountSd()
{
    if (mounted)
    {
        return true;
    }

    pinMode(SD_CS, OUTPUT);
    digitalWrite(SD_CS, HIGH);
    sdSPI.begin(SD_SPI_SCLK, SD_SPI_MISO, SD_SPI_MOSI, SD_CS);

    if (!SD.begin(SD_CS, sdSPI, SD_FREQUENCY_HZ))
    {
        Serial.println("SD.begin() failed -- check card/wiring");
        sdSPI.end();
        return false;
    }
    if (SD.cardType() == CARD_NONE)
    {
        Serial.println("No SD card detected (cardType == CARD_NONE)");
        SD.end();
        sdSPI.end();
        return false;
    }

    mounted = true;
    everMounted = true;

    // The sibling firmware never created this, so the first upload to a freshly
    // formatted card would fail at SD.open() with a confusing error.
    if (!SD.exists(PICTURES_DIR))
    {
        if (SD.mkdir(PICTURES_DIR))
        {
            Serial.printf("Created %s\n", PICTURES_DIR);
        }
        else
        {
            Serial.printf("Could not create %s\n", PICTURES_DIR);
        }
    }

    // Sweep any temp files left by an upload that died mid-transfer.
    for (const char *tmp : {UPLOAD_TMP_BIN, UPLOAD_TMP_XML})
    {
        if (SD.exists(tmp))
        {
            Serial.printf("Removing stale upload temp %s\n", tmp);
            SD.remove(tmp);
        }
    }

    return true;
}

void unmountSd()
{
    if (!mounted)
    {
        return;
    }
    SD.end();
    sdSPI.end();
    mounted = false;
}

uint64_t sdFreeBytes()
{
    if (!mounted)
    {
        return 0;
    }
    uint64_t total = SD.totalBytes();
    uint64_t used = SD.usedBytes();
    return (total > used) ? (total - used) : 0;
}

// Returns the inner text of <tag>...</tag>, or "" if the tag isn't present.
String readTag(const String &xml, const char *tag)
{
    String open = String("<") + tag + ">";
    String close = String("</") + tag + ">";
    int start = xml.indexOf(open);
    if (start < 0)
    {
        return "";
    }
    start += open.length();
    int end = xml.indexOf(close, start);
    if (end < 0)
    {
        return "";
    }
    String value = xml.substring(start, end);
    value.trim();
    return value;
}

// Undo the &amp;/&lt;/&gt; escaping prepare_image.py applies (plus quot/apos
// for good measure). &amp; must be last so "&amp;lt;" doesn't over-decode.
String xmlUnescape(String s)
{
    s.replace("&lt;", "<");
    s.replace("&gt;", ">");
    s.replace("&quot;", "\"");
    s.replace("&apos;", "'");
    s.replace("&amp;", "&");
    return s;
}

// &amp; must be FIRST here, mirroring the unescape order -- otherwise the
// ampersands introduced by the later replacements get double-escaped.
String xmlEscape(const String &s)
{
    String out = s;
    out.replace("&", "&amp;");
    out.replace("<", "&lt;");
    out.replace(">", "&gt;");
    return out;
}

// Parses a "TFT_GRAY_<n>" value (as written by prepare_image.py) into its gray
// level 0-15 -- which is also the value used directly as a text color in
// GRAY_LEVEL16 mode. Returns `fallback` for a missing/blank/unrecognized value.
uint16_t parseGrayColor(const String &value, uint16_t fallback)
{
    const String prefix = "TFT_GRAY_";
    if (!value.startsWith(prefix))
    {
        return fallback;
    }
    long n = value.substring(prefix.length()).toInt();
    if (n < 0 || n > 15)
    {
        return fallback;
    }
    return (uint16_t)n;
}

// Scans /pictures for *.bin files (skipping macOS ._ shadow files), returning
// their basenames sorted by filename == display order.
std::vector<String> listPictures()
{
    std::vector<String> bins;
    if (!mounted)
    {
        return bins;
    }

    File dir = SD.open(PICTURES_DIR);
    if (!dir || !dir.isDirectory())
    {
        Serial.printf("%s missing or not a directory\n", PICTURES_DIR);
        return bins;
    }

    for (File entry = dir.openNextFile(); entry; entry = dir.openNextFile())
    {
        if (!entry.isDirectory())
        {
            String name = entry.name();
            int slash = name.lastIndexOf('/');
            if (slash >= 0)
            {
                name = name.substring(slash + 1);
            }
            if (!name.startsWith("._") && name.endsWith(".bin"))
            {
                bins.push_back(name);
            }
        }
        entry.close();
    }
    dir.close();

    std::sort(bins.begin(), bins.end());
    return bins;
}

// Reads a packed nibble image straight from the SD card into a PSRAM buffer.
// Caller owns the returned buffer and must free() it. Returns nullptr on any
// failure (missing file, alloc failure, short read).
uint8_t *loadImageBuffer(const String &binName)
{
    if (!mounted)
    {
        return nullptr;
    }

    String path = String(PICTURES_DIR) + "/" + binName;

    File f = SD.open(path, FILE_READ);
    if (!f)
    {
        Serial.printf("Failed to open %s\n", path.c_str());
        return nullptr;
    }

    uint8_t *buffer = (uint8_t *)ps_malloc(IMAGE_BYTES);
    if (buffer == nullptr)
    {
        Serial.println("ps_malloc failed for image buffer");
        f.close();
        return nullptr;
    }

    size_t bytesRead = f.read(buffer, IMAGE_BYTES);
    f.close();

    if (bytesRead != IMAGE_BYTES)
    {
        Serial.printf("Short read for %s: %u/%u bytes\n", path.c_str(),
                      (unsigned)bytesRead, (unsigned)IMAGE_BYTES);
        free(buffer);
        return nullptr;
    }

    return buffer;
}

// Reads <binBase>.xml alongside the image. A missing/partial sidecar just
// yields blank fields (the caption renders them as empty).
PhotoMeta loadPhotoMeta(const String &binName)
{
    PhotoMeta meta;
    if (!mounted)
    {
        return meta;
    }

    // Swap the .bin extension for .xml.
    String xmlName = binName.substring(0, binName.length() - 4) + ".xml";
    String path = String(PICTURES_DIR) + "/" + xmlName;

    File f = SD.open(path, FILE_READ);
    if (!f)
    {
        Serial.printf("No sidecar %s -- caption fields blank\n", path.c_str());
        return meta;
    }

    String xml = f.readString();
    f.close();

    meta.artist = xmlUnescape(readTag(xml, "artist"));
    meta.date = xmlUnescape(readTag(xml, "date"));
    meta.location = xmlUnescape(readTag(xml, "location"));
    meta.title = xmlUnescape(readTag(xml, "title"));
    meta.film = xmlUnescape(readTag(xml, "film"));
    meta.colorTopLeft = parseGrayColor(readTag(xml, "text_color_top_left"), TFT_GRAY_8);
    meta.colorTopRight = parseGrayColor(readTag(xml, "text_color_top_right"), TFT_GRAY_8);
    meta.colorBottomLeft = parseGrayColor(readTag(xml, "text_color_bottom_left"), TFT_GRAY_8);
    meta.colorBottomRight = parseGrayColor(readTag(xml, "text_color_bottom_right"), TFT_GRAY_8);
    return meta;
}

// Reads /frame_config.xml. Each field falls back to its default if the file is
// missing or the value doesn't parse.
FrameConfig readConfig()
{
    FrameConfig cfg;
    if (!mounted)
    {
        return cfg;
    }

    File f = SD.open(CONFIG_PATH, FILE_READ);
    if (!f)
    {
        Serial.printf("%s missing -- default %u h, counter 0\n", CONFIG_PATH,
                      (unsigned)DEFAULT_REFRESH_HOURS);
        return cfg;
    }
    String xml = f.readString();
    f.close();

    long hours = readTag(xml, "refresh_hours").toInt();
    if (hours >= (long)MIN_REFRESH_HOURS && hours <= (long)MAX_REFRESH_HOURS)
    {
        cfg.refreshHours = (uint32_t)hours;
    }
    else if (hours != 0)
    {
        // A value outside the clamp is a real (if out-of-range) setting, so say
        // so rather than silently substituting. 0 means missing/blank.
        Serial.printf("refresh_hours %ld out of range %u-%u -- using %u h\n", hours,
                      (unsigned)MIN_REFRESH_HOURS, (unsigned)MAX_REFRESH_HOURS,
                      (unsigned)DEFAULT_REFRESH_HOURS);
    }

    // toInt() yields 0 for a missing/blank <counter>, which is the intended
    // default; a real "0" is indistinguishable but harmless.
    cfg.counter = (int32_t)readTag(xml, "counter").toInt();

    String tz = readTag(xml, "timezone");
    if (tz.length())
    {
        cfg.timezone = tz;
    }

    return cfg;
}

// Rewrites /frame_config.xml with <tag> set to `value`, preserving the rest of
// the file (comments, other tags, formatting) via an in-place substring swap.
// If <tag> is absent it's inserted before </config>; if the file is
// missing/empty a minimal config is written.
//
// Generalized from the sibling project's writeConfigCounter() -- same swap,
// same insert-before-</config> fallback, same minimal-file fallback, just with
// the tag name parameterized so <timezone> can reuse it.
bool writeConfigTag(const char *tag, const String &value)
{
    if (!mounted)
    {
        Serial.printf("SD not mounted -- cannot update <%s>\n", tag);
        return false;
    }

    String xml;
    File rf = SD.open(CONFIG_PATH, FILE_READ);
    if (rf)
    {
        xml = rf.readString();
        rf.close();
    }

    const String openTag = String("<") + tag + ">";
    const String closeTag = String("</") + tag + ">";

    int open = xml.indexOf(openTag);
    int close = (open >= 0) ? xml.indexOf(closeTag, open + openTag.length()) : -1;

    if (open >= 0 && close >= 0)
    {
        xml = xml.substring(0, open + openTag.length()) + value + xml.substring(close);
    }
    else
    {
        String tagLine = "  " + openTag + value + closeTag + "\n";
        int cfgEnd = xml.indexOf("</config>");
        if (cfgEnd >= 0)
        {
            xml = xml.substring(0, cfgEnd) + tagLine + xml.substring(cfgEnd);
        }
        else
        {
            xml = "<config>\n" + tagLine + "</config>\n";
        }
    }

    File wf = SD.open(CONFIG_PATH, FILE_WRITE); // "w" -> truncates and rewrites
    if (!wf)
    {
        Serial.printf("Could not open %s to update <%s>\n", CONFIG_PATH, tag);
        return false;
    }
    size_t written = wf.print(xml);
    wf.close();

    if (written != xml.length())
    {
        Serial.printf("Short write updating <%s>: %u/%u bytes\n", tag,
                      (unsigned)written, (unsigned)xml.length());
        return false;
    }
    return true;
}

bool writeConfigCounter(int32_t value)
{
    return writeConfigTag("counter", String((long)value));
}

// Appends one timestamped line per counter change to /counter_track.txt.
// Uses TIME_NOT_SET when the clock has never been set.
void appendCounterTrack(int delta, int32_t newValue, bool clockValid)
{
    if (!mounted)
    {
        return;
    }

    File f = SD.open(COUNTER_TRACK_PATH, FILE_APPEND);
    if (!f)
    {
        Serial.printf("Could not open %s for append\n", COUNTER_TRACK_PATH);
        return;
    }

    char ts[32];
    if (clockValid)
    {
        time_t now = time(nullptr);
        struct tm timeinfo;
        localtime_r(&now, &timeinfo);
        strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", &timeinfo);
    }
    else
    {
        snprintf(ts, sizeof(ts), "TIME_NOT_SET");
    }

    f.printf("%s\t%+d\t%ld\n", ts, delta, (long)newValue);
    f.close();
}

bool readCounterTrackTail(String &out, size_t maxBytes, bool *truncated, size_t *totalSize)
{
    out = "";
    if (truncated)
    {
        *truncated = false;
    }
    if (totalSize)
    {
        *totalSize = 0;
    }
    if (!mounted)
    {
        return false;
    }

    File f = SD.open(COUNTER_TRACK_PATH, FILE_READ);
    if (!f)
    {
        return false;
    }

    size_t size = f.size();
    if (totalSize)
    {
        *totalSize = size;
    }

    size_t start = 0;
    bool cut = false;
    if (size > maxBytes)
    {
        start = size - maxBytes;
        cut = true;
    }
    if (start > 0 && !f.seek(start))
    {
        f.close();
        return false;
    }

    size_t remaining = size - start;
    out.reserve(remaining + 1);

    // Chunked rather than byte-at-a-time: this can be 16KB, and f.read() per
    // byte would be ~16k calls through the FAT layer.
    char chunk[513];
    while (remaining > 0)
    {
        size_t want = (remaining < sizeof(chunk) - 1) ? remaining : (sizeof(chunk) - 1);
        int n = f.read((uint8_t *)chunk, want);
        if (n <= 0)
        {
            break;
        }
        chunk[n] = '\0';
        out += chunk;
        remaining -= (size_t)n;
    }
    f.close();

    // The seek almost certainly landed mid-line; drop that fragment so the page
    // never renders half a record. remove() is in-place, unlike substring().
    if (cut)
    {
        int nl = out.indexOf('\n');
        if (nl >= 0)
        {
            out.remove(0, nl + 1);
        }
    }

    if (truncated)
    {
        *truncated = cut;
    }
    return true;
}
