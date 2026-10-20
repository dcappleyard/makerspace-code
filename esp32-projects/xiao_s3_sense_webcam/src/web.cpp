#include "web.h"
#include "app.h"
#include "camera.h"
#include "index_html.h"
#include "storage.h"

#include <WiFi.h>
#include <esp_http_server.h>
#include <atomic>

#include "secrets.h"

#ifdef WEB_AUTH_USER
#include <mbedtls/base64.h>
#endif

namespace
{

httpd_handle_t apiServer = nullptr;
httpd_handle_t streamServer = nullptr;
std::atomic<int> streamClients{0};

// --- Auth ---------------------------------------------------------------------
// Same opt-in seam as the sibling projects: uncomment WEB_AUTH_USER/PASS in
// secrets.h and every API route needs Basic Auth. The stream can't use it (a
// browser won't prompt for credentials on a cross-port <img>), so it takes a
// random per-boot token instead, which the authenticated page reads from
// /api/status.
#ifdef WEB_AUTH_USER
String expectedAuth;
String streamToken;
#endif

void initAuth()
{
#ifdef WEB_AUTH_USER
    String plain = String(WEB_AUTH_USER) + ":" + WEB_AUTH_PASS;
    unsigned char out[128];
    size_t outLen = 0;
    mbedtls_base64_encode(out, sizeof(out) - 1, &outLen, (const unsigned char *)plain.c_str(), plain.length());
    out[outLen] = 0;
    expectedAuth = String("Basic ") + (const char *)out;
    char tok[17];
    snprintf(tok, sizeof(tok), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
    streamToken = tok;
#endif
}

bool getQuery(httpd_req_t *req, const char *key, String &out)
{
    size_t len = httpd_req_get_url_query_len(req);
    if (len == 0 || len > 256)
        return false;
    char query[257];
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK)
        return false;
    char value[128];
    if (httpd_query_key_value(query, key, value, sizeof(value)) != ESP_OK)
        return false;
    out = value;
    return true;
}

bool authorized(httpd_req_t *req)
{
#ifdef WEB_AUTH_USER
    char hdr[160];
    if (httpd_req_get_hdr_value_str(req, "Authorization", hdr, sizeof(hdr)) == ESP_OK && expectedAuth == hdr)
        return true;
    httpd_resp_set_status(req, "401 Unauthorized");
    httpd_resp_set_hdr(req, "WWW-Authenticate", "Basic realm=\"xiao-cam\"");
    httpd_resp_sendstr(req, "authentication required");
    return false;
#else
    return true;
#endif
}

esp_err_t sendJson(httpd_req_t *req, const String &json, const char *status = "200 OK")
{
    httpd_resp_set_status(req, status);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, json.c_str(), json.length());
}

esp_err_t sendError(httpd_req_t *req, const char *status, const char *message)
{
    return sendJson(req, String("{\"error\":\"") + message + "\"}", status);
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

const char *tf(bool b) { return b ? "true" : "false"; }

// --- API handlers -------------------------------------------------------------

esp_err_t handleIndex(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

esp_err_t handleStatus(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    String j = "{";
    j += "\"sensor\":" + jsonStr(sensorName());
    j += ",\"camera_ok\":" + String(tf(cameraReady()));
    j += ",\"max_framesize\":" + String((int)maxFramesize());
    j += ",\"settings\":" + cameraSettingsJson();
    j += ",\"ip\":" + jsonStr(wifiStatusText()) + ",\"rssi\":" + String(WiFi.RSSI());
    j += ",\"clock\":" + jsonStr(formatLocalTime()) + ",\"clock_set\":" + tf(clockValid());
    j += ",\"sd\":" + String(tf(sdIsMounted()));
    j += ",\"sd_free_mb\":" + String((unsigned long)(sdFreeBytes() / (1024 * 1024)));
    j += ",\"ram_photos\":" + String(ramPhotoCount()) + ",\"ram_bytes\":" + String(ramPhotoBytes());
    j += ",\"ram_photos_max\":" + String(RAM_PHOTOS_MAX);
    j += ",\"psram_free\":" + String(ESP.getFreePsram()) + ",\"heap_free\":" + String(ESP.getFreeHeap());
    j += ",\"stream_clients\":" + String(streamClients.load());
    j += ",\"stream_port\":" + String(STREAM_PORT);
#ifdef WEB_AUTH_USER
    j += ",\"stream_token\":" + jsonStr(streamToken);
#endif
    j += ",\"uptime_ms\":" + String(millis());
    j += "}";
    return sendJson(req, j);
}

esp_err_t handleControl(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    String var, val;
    if (!getQuery(req, "var", var) || !getQuery(req, "val", val))
        return sendError(req, "400 Bad Request", "need var and val");
    switch (cameraSetControl(var, val.toInt()))
    {
    case SetResult::Ok:
        return sendJson(req, cameraSettingsJson());
    case SetResult::UnknownControl:
        return sendError(req, "400 Bad Request", "unknown control");
    case SetResult::OutOfRange:
        return sendError(req, "400 Bad Request", "value out of range");
    default:
        return sendError(req, "500 Internal Server Error", "this sensor does not support that setting");
    }
}

esp_err_t handleReset(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    cameraResetDefaults();
    return sendJson(req, cameraSettingsJson());
}

esp_err_t handleSnap(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    camera_fb_t *fb = grabFreshFrame();
    if (!fb)
        return sendError(req, "500 Internal Server Error", "camera capture failed");
    SaveResult r = savePhoto(fb->buf, fb->len);
    size_t len = fb->len;
    esp_camera_fb_return(fb);
    if (!r.ok)
        return sendError(req, "500 Internal Server Error", "could not store the photo");
    Serial.printf("Snapshot %s (%u bytes, %s)\n", r.name.c_str(), (unsigned)len, r.onSd ? "SD" : "RAM");
    String j = "{\"name\":" + jsonStr(r.name) + ",\"size\":" + String(len) + ",\"sd\":" + tf(r.onSd) +
               ",\"dated\":" + tf(r.dated) + "}";
    return sendJson(req, j);
}

esp_err_t handlePhotos(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    String j = "[";
    bool first = true;
    for (const PhotoInfo &p : listPhotos())
    {
        if (!first)
            j += ",";
        first = false;
        j += "{\"name\":" + jsonStr(p.name) + ",\"size\":" + String(p.size) + ",\"sd\":" + tf(p.onSd) + "}";
    }
    return sendJson(req, j + "]");
}

esp_err_t handlePhoto(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    String name;
    PhotoInfo info;
    if (!getQuery(req, "name", name) || !findPhoto(name, info))
    {
        httpd_resp_send_404(req);
        return ESP_OK;
    }
    httpd_resp_set_type(req, "image/jpeg");
    httpd_resp_set_hdr(req, "Cache-Control", "private, max-age=3600");
    bool ok = readPhoto(name, [req](const uint8_t *data, size_t len) {
        return httpd_resp_send_chunk(req, (const char *)data, len) == ESP_OK;
    });
    if (ok)
        httpd_resp_send_chunk(req, nullptr, 0);
    return ok ? ESP_OK : ESP_FAIL;
}

esp_err_t handleDelete(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    String name;
    if (!getQuery(req, "name", name) || !deletePhoto(name))
        return sendError(req, "404 Not Found", "no such photo");
    return sendJson(req, "{\"ok\":true}");
}

esp_err_t handleSdMount(httpd_req_t *req)
{
    if (!authorized(req))
        return ESP_OK;
    size_t moved = 0;
    bool ok = mountSd(&moved);
    return sendJson(req, String("{\"sd\":") + tf(ok) + ",\"moved\":" + String(moved) + "}");
}

// --- Stream -------------------------------------------------------------------

constexpr const char *STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=xiaocamframe";
constexpr const char *STREAM_BOUNDARY = "\r\n--xiaocamframe\r\n";

esp_err_t handleStream(httpd_req_t *req)
{
#ifdef WEB_AUTH_USER
    String token;
    if (!getQuery(req, "t", token) || token != streamToken)
    {
        httpd_resp_set_status(req, "403 Forbidden");
        httpd_resp_sendstr(req, "bad stream token");
        return ESP_OK;
    }
#endif
    httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    streamClients++;
    Serial.println("Stream started");
    esp_err_t res = ESP_OK;
    while (res == ESP_OK)
    {
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb)
        {
            res = ESP_FAIL;
            break;
        }
        char part[80];
        int hlen = snprintf(part, sizeof(part), "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n",
                            (unsigned)fb->len);
        res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, part, hlen);
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
        esp_camera_fb_return(fb);
    }
    // The usual way out: the page turned the stream off and the socket closed.
    streamClients--;
    Serial.println("Stream stopped");
    return res;
}

void route(httpd_handle_t server, const char *uri, httpd_method_t method, esp_err_t (*handler)(httpd_req_t *))
{
    httpd_uri_t u = {};
    u.uri = uri;
    u.method = method;
    u.handler = handler;
    httpd_register_uri_handler(server, &u);
}

} // namespace

void startWebServers()
{
    initAuth();

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = HTTP_PORT;
    config.max_uri_handlers = 12;
    config.stack_size = 8192; // String-built JSON + SD file I/O
    config.lru_purge_enable = true;
    if (httpd_start(&apiServer, &config) == ESP_OK)
    {
        // State changes are POST-only, as in the sibling projects: link
        // previewers and LAN scanners issue GETs.
        route(apiServer, "/", HTTP_GET, handleIndex);
        route(apiServer, "/api/status", HTTP_GET, handleStatus);
        route(apiServer, "/api/control", HTTP_POST, handleControl);
        route(apiServer, "/api/reset", HTTP_POST, handleReset);
        route(apiServer, "/api/snap", HTTP_POST, handleSnap);
        route(apiServer, "/api/photos", HTTP_GET, handlePhotos);
        route(apiServer, "/api/photos/delete", HTTP_POST, handleDelete);
        route(apiServer, "/api/sd/mount", HTTP_POST, handleSdMount);
        route(apiServer, "/photo", HTTP_GET, handlePhoto);
    }
    else
    {
        Serial.println("Failed to start the API server");
    }

    config.server_port = STREAM_PORT;
    config.ctrl_port += 1; // each httpd instance needs its own control socket
    config.stack_size = 4096;
    if (httpd_start(&streamServer, &config) == ESP_OK)
        route(streamServer, "/stream", HTTP_GET, handleStream);
    else
        Serial.println("Failed to start the stream server");
}
