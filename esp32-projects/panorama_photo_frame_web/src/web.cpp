#include "frame_config.h" // MUST be first -- see the include-order note there

#include "web.h"
#include "app.h"
#include "storage.h"

#include <WiFi.h>
#include <WebServer.h>
#include <SD.h>

#include "secrets.h"

namespace
{

WebServer server(80);

// -----------------------------------------------------------------------------
// Auth seam
//
// There is deliberately NO authentication by default -- see the README. This
// helper is the single place that changes: uncomment WEB_AUTH_USER/WEB_AUTH_PASS
// in include/secrets.h and every route below is protected at once, because they
// all open with `if (!requireAuth()) return;`.
// -----------------------------------------------------------------------------
bool requireAuth()
{
#ifdef WEB_AUTH_USER
    if (!server.authenticate(WEB_AUTH_USER, WEB_AUTH_PASS))
    {
        server.requestAuthentication();
        return false;
    }
#endif
    return true;
}

// -----------------------------------------------------------------------------
// HTML helpers
// -----------------------------------------------------------------------------

// Escapes for an HTML text node or a quoted attribute. storage.h's xmlEscape()
// covers & < >; quotes matter here too because photo metadata is user text and
// lands inside single-quoted attributes (e.g. an apostrophe in a title).
String htmlEsc(const String &s)
{
    String out = xmlEscape(s);
    out.replace("\"", "&quot;");
    out.replace("'", "&#39;");
    return out;
}

// Shared page chrome. In PROGMEM rather than a String: flash is plentiful here
// (4MB app partition) while the internal-SRAM heap is shared with lwIP, and
// this is emitted on every page.
const char PAGE_HEAD[] PROGMEM =
    "<!DOCTYPE html><html><head><title>Photo Frame</title>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<style>"
    "body{font-family:system-ui,sans-serif;margin:0;padding:1rem;max-width:60rem}"
    "h1{font-size:1.3rem;margin:0 0 .8rem}h2{font-size:1rem;margin:1.4rem 0 .5rem}"
    "nav{margin-bottom:1rem}nav a{margin-right:1rem}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{border-bottom:1px solid #ddd;padding:.4rem;text-align:left;font-size:.9rem}"
    "tr.cur{background:#f4f4f4;font-weight:600}tr.new{background:#fffbe6}"
    "button{padding:.4rem .8rem;font-size:.9rem}"
    "form{display:inline}"
    ".k{color:#666;padding-right:.6rem}"
    "</style></head><body>"
    "<nav><a href='/'>Status</a><a href='/photos'>Photos</a>"
    "<a href='/history'>History</a><a href='/upload'>Upload</a>"
    "<a href='/clock'>Clock</a></nav>";

const char PAGE_FOOT[] PROGMEM = "</body></html>";

void sendPage(const String &body)
{
    String html;
    html.reserve(strlen_P(PAGE_HEAD) + body.length() + 32);
    html += FPSTR(PAGE_HEAD);
    html += body;
    html += FPSTR(PAGE_FOOT);
    server.send(200, "text/html", html);
}

void redirectTo(const char *path)
{
    server.sendHeader("Location", path);
    server.send(303, "text/plain", "");
}

String formatDuration(uint32_t ms)
{
    uint32_t s = ms / 1000;
    uint32_t h = s / 3600;
    uint32_t m = (s % 3600) / 60;
    char buf[32];
    snprintf(buf, sizeof(buf), "%luh %02lum %02lus", (unsigned long)h,
             (unsigned long)m, (unsigned long)(s % 60));
    return String(buf);
}

// The -5..+5 counter row (no 0 -- it would be a no-op that still costs an SD
// write and a track-file line). Each button is its own tiny POST form so the
// whole row works with no JavaScript.
String counterButtons()
{
    String b;
    b.reserve(1200);
    for (int d = -COUNTER_STEP_MAX; d <= COUNTER_STEP_MAX; d++)
    {
        if (d == 0)
        {
            continue;
        }
        b += "<form method='POST' action='/counter'>"
             "<input type='hidden' name='d' value='";
        b += String(d);
        b += "'><button>";
        b += (d > 0) ? "+" : "";
        b += String(d);
        b += "</button></form> ";
    }
    return b;
}

String row(const char *key, const String &value)
{
    return "<tr><td class='k'>" + String(key) + "</td><td>" + value + "</td></tr>";
}

// -----------------------------------------------------------------------------
// Status
// -----------------------------------------------------------------------------

void handleRoot()
{
    if (!requireAuth())
        return;

    const FrameConfig &cfg = appConfig();
    String cur = currentPhotoName();

    String b;
    b.reserve(3072);
    b += "<h1>Photo Frame</h1><table>";
    b += row("Showing", cur.length() ? htmlEsc(cur) : String("(nothing yet)"));
    b += row("Counter", String((long)cfg.counter));
    b += row("Interval", String((unsigned)cfg.refreshHours) + " h");
    b += row("Next refresh in", formatDuration(msUntilNextRefresh()));
    b += row("Panel", displayBusy() ? String("refreshing") : String("idle"));
    b += row("Clock", htmlEsc(formatLocalTime()));
    b += row("Timezone", htmlEsc(cfg.timezone));
    b += row("WiFi", wifiConnected()
                         ? (WiFi.localIP().toString() + " (" + String(WiFi.RSSI()) + " dBm)")
                         : String("not connected"));
    b += row("Hostname", String(HOSTNAME) + ".local");
    b += row("SD card", sdIsMounted()
                            ? ("mounted, " + String((unsigned long)(sdFreeBytes() / 1048576UL)) + " MB free")
                            : String("not mounted"));
    b += row("Uptime", formatDuration(millis()));
    b += row("Heap free / min", String((unsigned long)ESP.getFreeHeap()) + " / " +
                                    String((unsigned long)ESP.getMinFreeHeap()));
    b += "</table>";

    b += "<h2>Display</h2>"
         "<form method='POST' action='/next'><button>Next photo</button></form> "
         "<form method='POST' action='/refresh'><button>Redraw</button></form>";

    b += "<h2>Counter</h2><p>" + counterButtons() + "</p>";
    b += "<p class='k'>The panel keeps showing the old value until the next "
         "refresh &mdash; press Redraw to see it now. Every change is logged to "
         "<a href='/history'>History</a>.</p>";

    b += "<h2>SD card</h2>";
    if (sdIsMounted())
    {
        b += "<form method='POST' action='/sd/eject'><button>Eject card</button></form>"
             "<p class='k'>The card is mounted continuously. Eject before pulling it.</p>";
    }
    else
    {
        b += "<form method='POST' action='/sd/mount'><button>Mount card</button></form>"
             "<p class='k'>Safe to remove.</p>";
    }

    sendPage(b);
}

void handleStatusJson()
{
    if (!requireAuth())
        return;

    const FrameConfig &cfg = appConfig();
    String j;
    j.reserve(768);
    j += "{";
    j += "\"showing\":\"" + currentPhotoName() + "\",";
    j += "\"counter\":" + String((long)cfg.counter) + ",";
    j += "\"refresh_hours\":" + String((unsigned)cfg.refreshHours) + ",";
    j += "\"next_refresh_ms\":" + String((unsigned long)msUntilNextRefresh()) + ",";
    j += "\"display_busy\":" + String(displayBusy() ? "true" : "false") + ",";
    j += "\"clock_valid\":" + String(clockValid() ? "true" : "false") + ",";
    j += "\"local_time\":\"" + formatLocalTime() + "\",";
    j += "\"timezone\":\"" + cfg.timezone + "\",";
    j += "\"wifi\":" + String(wifiConnected() ? "true" : "false") + ",";
    j += "\"ip\":\"" + (wifiConnected() ? WiFi.localIP().toString() : String("")) + "\",";
    j += "\"rssi\":" + String(wifiConnected() ? WiFi.RSSI() : 0) + ",";
    j += "\"sd_mounted\":" + String(sdIsMounted() ? "true" : "false") + ",";
    j += "\"sd_free_bytes\":" + String((unsigned long long)sdFreeBytes()) + ",";
    j += "\"uptime_ms\":" + String((unsigned long)millis()) + ",";
    j += "\"heap_free\":" + String((unsigned long)ESP.getFreeHeap()) + ",";
    j += "\"heap_min\":" + String((unsigned long)ESP.getMinFreeHeap());
    j += "}";
    server.send(200, "application/json", j);
}

// -----------------------------------------------------------------------------
// Photo list
//
// This is the one page whose size is unbounded by user data (one row per photo
// on the card), so it is STREAMED rather than accumulated: peak heap is one row
// (~200 bytes) instead of the whole page.
// -----------------------------------------------------------------------------

void handlePhotos()
{
    if (!requireAuth())
        return;

    String justUploaded = server.hasArg("uploaded") ? server.arg("uploaded") : String("");
    String cur = currentPhotoName();

    server.setContentLength(CONTENT_LENGTH_UNKNOWN);
    server.send(200, "text/html", "");
    server.sendContent_P(PAGE_HEAD);
    server.sendContent("<h1>Photos</h1>");

    if (!sdIsMounted())
    {
        server.sendContent("<p>No SD card mounted.</p>");
        server.sendContent_P(PAGE_FOOT);
        server.sendContent("");
        return;
    }

    std::vector<String> bins = listPictures();
    if (bins.empty())
    {
        server.sendContent("<p>No .bin images in /pictures. Prepare photos with "
                           "prepare_image.py, then <a href='/upload'>upload</a> them.</p>");
        server.sendContent_P(PAGE_FOOT);
        server.sendContent("");
        return;
    }

    server.sendContent("<table><tr><th>File</th><th>Title</th><th>Location</th>"
                       "<th>Artist</th><th>Date</th><th>Sidecar</th><th></th></tr>");

    for (const String &bin : bins)
    {
        PhotoMeta m = loadPhotoMeta(bin);
        bool hasSidecar = m.title.length() || m.artist.length() || m.date.length() ||
                          m.location.length() || m.film.length();

        String r;
        r.reserve(512);
        r += "<tr class='";
        r += (bin == cur) ? "cur" : (bin == justUploaded ? "new" : "");
        r += "'><td>";
        r += htmlEsc(bin);
        r += (bin == cur) ? " &larr; showing" : "";
        r += "</td><td>" + htmlEsc(m.title);
        r += "</td><td>" + htmlEsc(m.location);
        r += "</td><td>" + htmlEsc(m.artist);
        r += "</td><td>" + htmlEsc(m.date);
        r += "</td><td>";
        r += hasSidecar ? "yes" : "<b>missing</b>";
        r += "</td><td><form method='POST' action='/show'>"
             "<input type='hidden' name='name' value='" +
             htmlEsc(bin) + "'><button>Show</button></form></td></tr>";
        server.sendContent(r);
    }

    server.sendContent("</table>");
    server.sendContent_P(PAGE_FOOT);
    server.sendContent(""); // terminate the chunked response
}

// -----------------------------------------------------------------------------
// Display actions -- every one of these responds IMMEDIATELY and lets loop()
// do the multi-second panel work. See the state machine in main.cpp.
// -----------------------------------------------------------------------------

void handleNext()
{
    if (!requireAuth())
        return;
    queueAction(PENDING_ADVANCE);
    redirectTo("/");
}

void handleRefresh()
{
    if (!requireAuth())
        return;
    queueAction(PENDING_REDRAW);
    redirectTo("/");
}

void handleShow()
{
    if (!requireAuth())
        return;

    String name = server.arg("name");
    if (name.length() == 0)
    {
        server.send(400, "text/plain", "Missing name");
        return;
    }

    // Only accept a name that's actually in the current listing -- this is what
    // keeps an arbitrary POST from steering the frame at a path of its choosing.
    bool found = false;
    for (const String &bin : listPictures())
    {
        if (bin == name)
        {
            found = true;
            break;
        }
    }
    if (!found)
    {
        server.send(404, "text/plain", "No such photo");
        return;
    }

    queueJump(name);
    redirectTo("/photos");
}

// One route for the whole -5..+5 row: the delta arrives as `d` and is range
// checked here. The track file's "%+d" format already records any step size, so
// nothing downstream needed changing.
void handleCounterAdjust()
{
    if (!requireAuth())
        return;

    if (!server.hasArg("d"))
    {
        server.send(400, "text/plain", "Missing d");
        return;
    }
    long delta = server.arg("d").toInt();
    if (delta == 0 || delta < -COUNTER_STEP_MAX || delta > COUNTER_STEP_MAX)
    {
        server.send(400, "text/plain", "d must be a non-zero step within +/-5");
        return;
    }

    int32_t newValue = 0;
    if (!applyCounterDelta((int)delta, &newValue))
    {
        server.send(503, "text/plain", "SD card unavailable -- counter unchanged");
        return;
    }
    redirectTo("/");
}

// -----------------------------------------------------------------------------
// SD card mount control
// -----------------------------------------------------------------------------

void handleSdEject()
{
    if (!requireAuth())
        return;
    unmountSd();
    markPicturesDirty();
    Serial.println("SD ejected via web -- safe to remove");
    redirectTo("/");
}

void handleSdMount()
{
    if (!requireAuth())
        return;
    if (mountSd())
    {
        markPicturesDirty();
        queueAction(PENDING_RESCAN);
    }
    redirectTo("/");
}

// -----------------------------------------------------------------------------
// Clock
// -----------------------------------------------------------------------------

void handleClockGet()
{
    if (!requireAuth())
        return;

    const FrameConfig &cfg = appConfig();
    String b;
    b.reserve(2048);
    b += "<h1>Clock</h1><table>";
    b += row("Local time", htmlEsc(formatLocalTime()));
    b += row("Timezone", htmlEsc(cfg.timezone));
    b += row("NTP", wifiConnected() ? String("servers configured, syncing over WiFi")
                                    : String("unreachable (no WiFi)"));
    b += "</table>";

    b += "<h2>Set the clock</h2>"
         "<p class='k'>Normally unnecessary &mdash; the frame syncs over NTP on its "
         "own whenever it has WiFi, so a power cut heals itself. Use this only when "
         "NTP can&#39;t be reached. Note that if NTP later does reach a server it "
         "will step the clock and override anything set here.</p>";

    // One line of JS, with a plain epoch field as the no-JS fallback.
    b += "<form method='POST' action='/clock'>"
         "<input type='hidden' name='epoch' id='e'>"
         "<button onclick=\"document.getElementById('e').value="
         "Math.floor(Date.now()/1000)\">Set from this browser</button></form>";

    b += "<p><form method='POST' action='/clock'>Unix epoch "
         "<input name='epoch' size='12'> <button>Set</button></form> "
         "<span class='k'>(<code>date +%s</code>)</span></p>";

    b += "<h2>Timezone</h2>"
         "<p class='k'>POSIX TZ string, stored in frame_config.xml on the card.</p>"
         "<form method='POST' action='/clock'>"
         "<input name='tz' size='32' value='" +
         htmlEsc(cfg.timezone) + "'> <button>Save</button></form>";

    sendPage(b);
}

void handleClockPost()
{
    if (!requireAuth())
        return;

    bool any = false;

    if (server.hasArg("tz") && server.arg("tz").length())
    {
        if (!setTimezone(server.arg("tz")))
        {
            server.send(400, "text/plain", "Bad timezone string");
            return;
        }
        any = true;
    }

    if (server.hasArg("epoch") && server.arg("epoch").length())
    {
        // strtoll, not toInt(): a Unix epoch overflows the 32-bit long that
        // String::toInt() returns in 2038, and already does for ms-scale typos.
        time_t epoch = (time_t)strtoll(server.arg("epoch").c_str(), nullptr, 10);
        if (!setClockFromEpoch(epoch))
        {
            server.send(400, "text/plain", "Epoch looks wrong (must be after 2025-01-01)");
            return;
        }
        any = true;
    }

    if (!any)
    {
        server.send(400, "text/plain", "Nothing to set");
        return;
    }
    redirectTo("/clock");
}

// -----------------------------------------------------------------------------
// Upload
//
// The fiddliest code in the project. Notes, all verified against the core's
// WebServer/src/Parsing.cpp rather than assumed:
//
//  * The status enum is UPLOAD_FILE_START/WRITE/END/ABORTED (the HTTP_UPLOAD_*
//    spelling is ESP8266's).
//  * Parsing.cpp:542 adds the final chunk to totalSize and THEN fires
//    UPLOAD_FILE_END -- up.buf still holds that tail at END. So bytes are
//    written ONLY on UPLOAD_FILE_WRITE; writing in both branches would
//    double-write the tail and corrupt every single upload.
//  * Non-file form fields are only assembled into the arg list after the whole
//    body is parsed, so server.arg() is unreliable in here. Read args in the
//    done handler only.
//  * Each file part gets its own START/WRITE/END cycle; the done handler runs
//    once, after all parts.
//
// Files stream to temps and are renamed into /pictures only in the done
// handler, so a client that dies after the .bin but before the .xml leaves
// /pictures completely untouched -- the pair lands together or not at all.
// -----------------------------------------------------------------------------

constexpr size_t MAX_XML_BYTES = 8192;
constexpr size_t MAX_UPLOAD_NAME_LEN = 40;
constexpr uint64_t MIN_FREE_BYTES = 2ULL * 1024 * 1024;

struct UploadSlot
{
    File file;
    bool active = false; // a part is currently streaming into this slot
    bool ok = false;     // completed and validated
    bool isBin = false;
    String tmpPath;
    String finalName;
    size_t written = 0;
};

UploadSlot binSlot;
UploadSlot xmlSlot;
// Which slot the current multipart part is streaming into. Parts arrive
// strictly one at a time, so a single pointer is enough -- and it's a lot
// clearer than inferring the slot from the .active flags at each callback.
UploadSlot *activeSlot = nullptr;
String uploadErrors;
bool uploadAuthFailed = false;
// True from the first part of a request until its done handler runs. An
// aborted transfer never reaches the done handler, so without this the leftover
// error text (and slot state) would leak into the NEXT upload and fail it for
// no reason. Checked at the first UPLOAD_FILE_START of each request.
bool uploadRequestActive = false;

void addError(const String &msg)
{
    if (uploadErrors.length())
    {
        uploadErrors += "<br>";
    }
    uploadErrors += htmlEsc(msg);
    Serial.printf("Upload rejected: %s\n", msg.c_str());
}

// Returns a sanitized basename, or "" to reject. Deliberately strict: this is
// the only thing standing between an HTTP request and the filesystem.
String sanitizeUploadName(const String &raw)
{
    String name = raw;

    // Strip any path the client sent -- some send a full local path. Both
    // separators, because Windows clients use backslashes.
    int slash = name.lastIndexOf('/');
    if (slash >= 0)
        name = name.substring(slash + 1);
    int backslash = name.lastIndexOf('\\');
    if (backslash >= 0)
        name = name.substring(backslash + 1);

    if (name.length() == 0 || name.length() > MAX_UPLOAD_NAME_LEN)
        return "";
    if (name.startsWith(".")) // dotfiles and macOS ._ shadow files
        return "";
    if (name.indexOf("..") >= 0)
        return "";

    int dots = 0;
    for (size_t i = 0; i < name.length(); i++)
    {
        char c = name[i];
        bool allowed = isAlphaNumeric(c) || c == '.' || c == '_' || c == '-';
        if (!allowed)
            return "";
        if (c == '.')
            dots++;
    }
    if (dots != 1)
        return "";

    // Lowercase the extension so FOO.BIN is accepted and normalized.
    int dot = name.lastIndexOf('.');
    String base = name.substring(0, dot);
    String ext = name.substring(dot + 1);
    ext.toLowerCase();
    if (base.length() == 0 || (ext != "bin" && ext != "xml"))
        return "";

    return base + "." + ext;
}

void closeAndDiscard(UploadSlot &slot)
{
    if (slot.file)
    {
        slot.file.close();
    }
    if (slot.tmpPath.length() && SD.exists(slot.tmpPath))
    {
        SD.remove(slot.tmpPath);
    }
    slot.active = false;
    slot.ok = false;
    slot.written = 0;
    if (activeSlot == &slot)
    {
        activeSlot = nullptr;
    }
}

void resetUploadState()
{
    closeAndDiscard(binSlot);
    closeAndDiscard(xmlSlot);
    binSlot = UploadSlot();
    xmlSlot = UploadSlot();
    activeSlot = nullptr;
    uploadErrors = "";
    uploadAuthFailed = false;
    // NOTE: uploadRequestActive is deliberately NOT cleared here -- this is
    // called from inside UPLOAD_FILE_START, which has just set it.
}

void handleUploadData()
{
    HTTPUpload &up = server.upload();

    if (up.status == UPLOAD_FILE_START)
    {
        if (!uploadRequestActive)
        {
            // First part of a new request -- clear anything a previous aborted
            // upload left behind.
            resetUploadState();
            uploadRequestActive = true;
        }

        // The upload callback can't issue a 401 challenge mid-stream, so on an
        // auth failure we flag it, swallow the bytes, and let the done handler
        // send the challenge.
        if (!requireAuth())
        {
            uploadAuthFailed = true;
            return;
        }
        if (uploadAuthFailed)
            return;

        if (!sdIsMounted())
        {
            addError("No SD card mounted");
            return;
        }

        String name = sanitizeUploadName(up.filename);
        if (name.length() == 0)
        {
            addError("Rejected filename: " + up.filename);
            return;
        }

        bool isBin = name.endsWith(".bin");
        UploadSlot &slot = isBin ? binSlot : xmlSlot;

        if (slot.ok || slot.active)
        {
            addError("Two " + String(isBin ? ".bin" : ".xml") + " files in one upload");
            return;
        }

        if (sdFreeBytes() < MIN_FREE_BYTES)
        {
            addError("Less than 2 MB free on the card");
            return;
        }

        slot.isBin = isBin;
        slot.finalName = name;
        slot.tmpPath = isBin ? UPLOAD_TMP_BIN : UPLOAD_TMP_XML;
        slot.written = 0;
        slot.ok = false;

        if (SD.exists(slot.tmpPath))
        {
            SD.remove(slot.tmpPath);
        }
        slot.file = SD.open(slot.tmpPath, FILE_WRITE);
        if (!slot.file)
        {
            addError("Could not open temp file for " + name);
            return;
        }
        slot.active = true;
        activeSlot = &slot;
        Serial.printf("Upload started: %s -> %s\n", name.c_str(), slot.tmpPath.c_str());
        return;
    }

    if (up.status == UPLOAD_FILE_ABORTED)
    {
        Serial.println("Upload aborted by client");
        addError("Transfer aborted");
        closeAndDiscard(binSlot);
        closeAndDiscard(xmlSlot);
        uploadRequestActive = false;
        return;
    }

    // Rejected at START (bad name, no card, no space): there is no slot, so
    // swallow the rest of the part quietly. The done handler reports why.
    if (activeSlot == nullptr)
    {
        return;
    }
    UploadSlot &slot = *activeSlot;

    if (up.status == UPLOAD_FILE_WRITE)
    {
        if (!slot.active)
        {
            return;
        }
        size_t cap = slot.isBin ? IMAGE_BYTES : MAX_XML_BYTES;
        if (slot.written + up.currentSize > cap)
        {
            addError(String(slot.finalName) + " is larger than the " +
                     String((unsigned long)cap) + "-byte limit");
            closeAndDiscard(slot);
            return;
        }
        size_t n = slot.file.write(up.buf, up.currentSize);
        if (n != up.currentSize)
        {
            addError("Short write to the card (full or failing?)");
            closeAndDiscard(slot);
            return;
        }
        slot.written += n;
        return;
    }

    if (up.status == UPLOAD_FILE_END)
    {
        // Do NOT write up.buf here -- the tail was already delivered on the
        // preceding UPLOAD_FILE_WRITE. See the note above.
        if (!slot.active)
        {
            return;
        }
        slot.file.close();
        slot.active = false;

        if (slot.isBin && slot.written != IMAGE_BYTES)
        {
            // This exact-length check is what stops a truncated upload from
            // blanking a slot: loadImageBuffer() hard-fails a short read.
            addError(slot.finalName + ": expected " + String((unsigned long)IMAGE_BYTES) +
                     " bytes, got " + String((unsigned long)slot.written));
            closeAndDiscard(slot);
            return;
        }
        if (slot.written == 0)
        {
            addError(slot.finalName + " was empty");
            closeAndDiscard(slot);
            return;
        }

        slot.ok = true;
        Serial.printf("Upload complete: %s (%u bytes)\n", slot.finalName.c_str(),
                      (unsigned)slot.written);
        activeSlot = nullptr;
        return;
    }
}

// Moves one completed temp into /pictures.
bool commitSlot(UploadSlot &slot)
{
    if (!slot.ok)
    {
        return false;
    }
    String finalPath = String(PICTURES_DIR) + "/" + slot.finalName;

    // f_rename returns FR_EXIST if the destination exists, so a replacement
    // needs an explicit remove first. That remove/rename gap would normally be
    // a correctness hole -- here it is safe because nothing else can run between
    // these two statements: the panel refresh only ever executes from loop(),
    // after handleClient() has returned. Do not "fix" this with a lock.
    if (SD.exists(finalPath))
    {
        SD.remove(finalPath);
    }
    if (!SD.rename(slot.tmpPath, finalPath))
    {
        addError("Could not move " + slot.finalName + " into " + String(PICTURES_DIR));
        return false;
    }
    Serial.printf("Committed %s\n", finalPath.c_str());
    return true;
}

void handleUploadDone()
{
    uploadRequestActive = false;

    if (uploadAuthFailed)
    {
        resetUploadState();
        server.requestAuthentication();
        return;
    }
    if (!requireAuth())
    {
        resetUploadState();
        return;
    }

    // All-or-nothing. If ANYTHING went wrong with this request -- a rejected
    // filename, a truncated .bin, a short write -- nothing is committed. A
    // half-updated .bin/.xml pair on the card is worse than no update at all:
    // the frame would show a new photo under the old caption, or vice versa.
    String committed;
    if (uploadErrors.length())
    {
        addError("Nothing was saved");
    }
    else
    {
        if (commitSlot(binSlot))
            committed = binSlot.finalName;
        if (commitSlot(xmlSlot) && committed.length() == 0)
            committed = xmlSlot.finalName;
    }

    closeAndDiscard(binSlot);
    closeAndDiscard(xmlSlot);

    if (committed.length())
    {
        markPicturesDirty();
        // Deliberately no auto-refresh: you may be uploading several photos in
        // a row, and each refresh is a multi-second panel flash.
        resetUploadState();
        String target = "/photos?uploaded=" + committed;
        server.sendHeader("Location", target);
        server.send(303, "text/plain", "");
        return;
    }

    String b = "<h1>Upload failed</h1><p>" +
               (uploadErrors.length() ? uploadErrors : String("Nothing was uploaded.")) +
               "</p><p><a href='/upload'>Try again</a></p>";
    resetUploadState();
    sendPage(b);
}

void handleUploadForm()
{
    if (!requireAuth())
        return;

    String b;
    b.reserve(1536);
    b += "<h1>Upload a photo</h1>"
         "<p class='k'>Prepare the pair on your computer first with "
         "<code>prepare_image.py</code>, then pick the matching "
         "<code>.bin</code> and <code>.xml</code> below. The <code>.bin</code> "
         "must be exactly 1,314,144 bytes. Both files are saved together or not "
         "at all.</p>";
    b += "<form method='POST' action='/upload' enctype='multipart/form-data' "
         "onsubmit=\"this.q.disabled=true;this.q.textContent='Uploading, this "
         "takes 10-30 s...'\">"
         "<p><input type='file' name='f1' accept='.bin,.xml'></p>"
         "<p><input type='file' name='f2' accept='.bin,.xml'></p>"
         "<p><button name='q'>Upload</button></p></form>";
    b += "<p class='k'>Uploading a name that already exists replaces it.</p>";
    sendPage(b);
}

// -----------------------------------------------------------------------------
// Counter history (/counter_track.txt)
//
// The file grows by one line per counter change forever, so the page renders a
// bounded window from the END of it -- newest first, which is the part you
// actually want -- and links to /history/raw for the whole thing. Streamed like
// /photos so peak heap is one row rather than the whole page.
// -----------------------------------------------------------------------------

constexpr size_t HISTORY_WINDOW_BYTES = 16384; // ~500 entries at ~32 bytes each

void handleHistory()
{
    if (!requireAuth())
        return;

    server.setContentLength(CONTENT_LENGTH_UNKNOWN);
    server.send(200, "text/html", "");
    server.sendContent_P(PAGE_HEAD);
    server.sendContent("<h1>Counter history</h1>");

    if (!sdIsMounted())
    {
        server.sendContent("<p>No SD card mounted.</p>");
        server.sendContent_P(PAGE_FOOT);
        server.sendContent("");
        return;
    }

    String tail;
    bool truncated = false;
    size_t totalSize = 0;
    bool ok = readCounterTrackTail(tail, HISTORY_WINDOW_BYTES, &truncated, &totalSize);

    if (!ok || tail.length() == 0)
    {
        server.sendContent("<p>No counter changes recorded yet. The frame writes "
                           "a line to <code>/counter_track.txt</code> every time "
                           "the counter moves.</p>");
        server.sendContent_P(PAGE_FOOT);
        server.sendContent("");
        return;
    }

    // Collect line offsets rather than splitting into a vector<String>: a few
    // hundred Strings would cost far more heap than the text itself.
    std::vector<int> starts;
    starts.push_back(0);
    for (int i = 0; i < (int)tail.length(); i++)
    {
        if (tail[i] == '\n' && i + 1 < (int)tail.length())
        {
            starts.push_back(i + 1);
        }
    }

    String hdr = "<p class='k'>Newest first &middot; ";
    hdr += String((unsigned long)starts.size());
    hdr += " shown";
    if (truncated)
    {
        hdr += " of " + String((unsigned long)totalSize) + " bytes (older entries "
               "not listed)";
    }
    hdr += " &middot; <a href='/history/raw'>view the whole file</a></p>";
    server.sendContent(hdr);

    server.sendContent("<table><tr><th>When</th><th>Change</th><th>Counter</th></tr>");

    for (int i = (int)starts.size() - 1; i >= 0; i--)
    {
        int begin = starts[i];
        int end = tail.indexOf('\n', begin);
        if (end < 0)
        {
            end = (int)tail.length();
        }
        String line = tail.substring(begin, end);
        line.trim();
        if (line.length() == 0)
        {
            continue;
        }

        // Format written by appendCounterTrack(): "<ts>\t<+/-N>\t<value>".
        int t1 = line.indexOf('\t');
        int t2 = (t1 >= 0) ? line.indexOf('\t', t1 + 1) : -1;

        String r = "<tr>";
        if (t1 >= 0 && t2 >= 0)
        {
            r += "<td>" + htmlEsc(line.substring(0, t1)) + "</td>";
            r += "<td>" + htmlEsc(line.substring(t1 + 1, t2)) + "</td>";
            r += "<td>" + htmlEsc(line.substring(t2 + 1)) + "</td>";
        }
        else
        {
            // Unrecognized line -- show it verbatim rather than dropping it.
            r += "<td colspan='3'>" + htmlEsc(line) + "</td>";
        }
        r += "</tr>";
        server.sendContent(r);
    }

    server.sendContent("</table>");
    server.sendContent_P(PAGE_FOOT);
    server.sendContent("");
}

void handleHistoryRaw()
{
    if (!requireAuth())
        return;

    if (!sdIsMounted())
    {
        server.send(503, "text/plain", "No SD card mounted");
        return;
    }
    File f = SD.open(COUNTER_TRACK_PATH, FILE_READ);
    if (!f)
    {
        server.send(404, "text/plain", "No counter history yet");
        return;
    }
    // streamFile() sets Content-Length from the file and streams it out without
    // ever holding it in RAM, so this is safe however large the log gets.
    server.streamFile(f, "text/plain");
    f.close();
}

void handleNotFound()
{
    server.send(404, "text/plain", "Not found");
}

} // namespace

void setupWebServer()
{
    server.on("/", HTTP_GET, handleRoot);
    server.on("/status.json", HTTP_GET, handleStatusJson);
    server.on("/photos", HTTP_GET, handlePhotos);
    server.on("/history", HTTP_GET, handleHistory);
    server.on("/history/raw", HTTP_GET, handleHistoryRaw);

    // State-changing routes are POST-only and answer with a 303 redirect.
    // Browsers, link-preview generators and LAN scanners all issue unsolicited
    // GETs; none of them should be able to advance the frame or move the
    // counter just by touching a URL.
    server.on("/next", HTTP_POST, handleNext);
    server.on("/refresh", HTTP_POST, handleRefresh);
    server.on("/show", HTTP_POST, handleShow);
    server.on("/counter", HTTP_POST, handleCounterAdjust);
    server.on("/sd/eject", HTTP_POST, handleSdEject);
    server.on("/sd/mount", HTTP_POST, handleSdMount);

    server.on("/clock", HTTP_GET, handleClockGet);
    server.on("/clock", HTTP_POST, handleClockPost);

    server.on("/upload", HTTP_GET, handleUploadForm);
    server.on("/upload", HTTP_POST, handleUploadDone, handleUploadData);

    server.onNotFound(handleNotFound);
    server.begin();
    Serial.printf("Web server started: http://%s.local/\n", HOSTNAME);
}

void handleWebClient()
{
    server.handleClient();
}
