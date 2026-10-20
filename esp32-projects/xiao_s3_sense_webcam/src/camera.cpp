#include "camera.h"

#include <Preferences.h>

namespace
{

constexpr const char *NVS_NAMESPACE = "cam";

// The JPEG frame buffers are sized from the frame size passed to
// esp_camera_init(), so it has to be the largest we'll ever switch to. The
// driver should clamp this to the detected sensor's own maximum; if an older
// driver refuses instead, cameraInit() retries at UXGA (the OV2640's maximum).
// QXGA (2048x1536) covers the OV3660; an OV5640 is capped here too (its 5MP
// mode would need ~1MB+ buffers and overrun these).
constexpr framesize_t INIT_FRAMESIZE = FRAMESIZE_QXGA;
constexpr framesize_t FALLBACK_INIT_FRAMESIZE = FRAMESIZE_UXGA;
constexpr framesize_t DEFAULT_FRAMESIZE = FRAMESIZE_SVGA;
constexpr int DEFAULT_QUALITY = 12; // 0-63, lower = better / bigger

bool ready = false;
framesize_t maxSize = FRAMESIZE_UXGA;
const char *name = "none";
camera_status_t defaults; // captured after the boot tweaks, for Reset

struct Control
{
    const char *key; // also the NVS key -- must stay <= 15 chars
    int minValue;
    int maxValue;
    int (*apply)(sensor_t *s, int v);
    int (*read)(const camera_status_t &st);
};

// Order matters when re-applying saved settings: values before the auto
// toggles that use or override them, so turning AEC/AGC off lands on the saved
// manual exposure/gain rather than whatever the sensor had.
const Control CONTROLS[] = {
    {"framesize", 0, FRAMESIZE_QXGA, [](sensor_t *s, int v) { return s->set_framesize(s, (framesize_t)v); },
     [](const camera_status_t &st) { return (int)st.framesize; }},
    {"quality", 4, 63, [](sensor_t *s, int v) { return s->set_quality(s, v); },
     [](const camera_status_t &st) { return (int)st.quality; }},
    {"brightness", -2, 2, [](sensor_t *s, int v) { return s->set_brightness(s, v); },
     [](const camera_status_t &st) { return (int)st.brightness; }},
    {"contrast", -2, 2, [](sensor_t *s, int v) { return s->set_contrast(s, v); },
     [](const camera_status_t &st) { return (int)st.contrast; }},
    {"saturation", -2, 2, [](sensor_t *s, int v) { return s->set_saturation(s, v); },
     [](const camera_status_t &st) { return (int)st.saturation; }},
    {"wb_mode", 0, 4, [](sensor_t *s, int v) { return s->set_wb_mode(s, v); },
     [](const camera_status_t &st) { return (int)st.wb_mode; }},
    {"awb_gain", 0, 1, [](sensor_t *s, int v) { return s->set_awb_gain(s, v); },
     [](const camera_status_t &st) { return (int)st.awb_gain; }},
    {"awb", 0, 1, [](sensor_t *s, int v) { return s->set_whitebal(s, v); },
     [](const camera_status_t &st) { return (int)st.awb; }},
    {"ae_level", -2, 2, [](sensor_t *s, int v) { return s->set_ae_level(s, v); },
     [](const camera_status_t &st) { return (int)st.ae_level; }},
    {"aec_value", 0, 1200, [](sensor_t *s, int v) { return s->set_aec_value(s, v); },
     [](const camera_status_t &st) { return (int)st.aec_value; }},
    {"aec2", 0, 1, [](sensor_t *s, int v) { return s->set_aec2(s, v); },
     [](const camera_status_t &st) { return (int)st.aec2; }},
    {"aec", 0, 1, [](sensor_t *s, int v) { return s->set_exposure_ctrl(s, v); },
     [](const camera_status_t &st) { return (int)st.aec; }},
    {"gainceiling", 0, 6, [](sensor_t *s, int v) { return s->set_gainceiling(s, (gainceiling_t)v); },
     [](const camera_status_t &st) { return (int)st.gainceiling; }},
    {"agc_gain", 0, 30, [](sensor_t *s, int v) { return s->set_agc_gain(s, v); },
     [](const camera_status_t &st) { return (int)st.agc_gain; }},
    {"agc", 0, 1, [](sensor_t *s, int v) { return s->set_gain_ctrl(s, v); },
     [](const camera_status_t &st) { return (int)st.agc; }},
    {"lenc", 0, 1, [](sensor_t *s, int v) { return s->set_lenc(s, v); },
     [](const camera_status_t &st) { return (int)st.lenc; }},
    {"hmirror", 0, 1, [](sensor_t *s, int v) { return s->set_hmirror(s, v); },
     [](const camera_status_t &st) { return (int)st.hmirror; }},
    {"vflip", 0, 1, [](sensor_t *s, int v) { return s->set_vflip(s, v); },
     [](const camera_status_t &st) { return (int)st.vflip; }},
};

const Control *findControl(const String &key)
{
    for (const Control &c : CONTROLS)
    {
        if (key == c.key)
            return &c;
    }
    return nullptr;
}

const char *nameForPid(uint16_t pid)
{
    switch (pid)
    {
    case OV2640_PID:
        return "OV2640";
    case OV3660_PID:
        return "OV3660";
    case OV5640_PID:
        return "OV5640";
    default:
        return "unknown";
    }
}

// Sets one control on the sensor, without touching NVS.
SetResult applyControl(sensor_t *s, const Control &c, int value)
{
    if (value < c.minValue || value > c.maxValue)
        return SetResult::OutOfRange;
    if (&c == findControl("framesize") && value > (int)maxSize)
        return SetResult::OutOfRange;
    return c.apply(s, value) == 0 ? SetResult::Ok : SetResult::SensorRefused;
}

void applySaved(sensor_t *s)
{
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, true))
        return; // nothing saved yet
    for (const Control &c : CONTROLS)
    {
        if (prefs.isKey(c.key))
            applyControl(s, c, prefs.getInt(c.key));
    }
    prefs.end();
}

} // namespace

bool cameraInit()
{
    camera_config_t config = {};
    config.pin_pwdn = CAM_PIN_PWDN;
    config.pin_reset = CAM_PIN_RESET;
    config.pin_xclk = CAM_PIN_XCLK;
    config.pin_sccb_sda = CAM_PIN_SIOD;
    config.pin_sccb_scl = CAM_PIN_SIOC;
    config.pin_d7 = CAM_PIN_D7;
    config.pin_d6 = CAM_PIN_D6;
    config.pin_d5 = CAM_PIN_D5;
    config.pin_d4 = CAM_PIN_D4;
    config.pin_d3 = CAM_PIN_D3;
    config.pin_d2 = CAM_PIN_D2;
    config.pin_d1 = CAM_PIN_D1;
    config.pin_d0 = CAM_PIN_D0;
    config.pin_vsync = CAM_PIN_VSYNC;
    config.pin_href = CAM_PIN_HREF;
    config.pin_pclk = CAM_PIN_PCLK;
    config.xclk_freq_hz = CAM_XCLK_HZ;
    config.ledc_timer = LEDC_TIMER_0;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = INIT_FRAMESIZE;
    config.jpeg_quality = DEFAULT_QUALITY;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.grab_mode = CAMERA_GRAB_LATEST;

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK)
    {
        Serial.printf("Camera init at QXGA failed (0x%x) -- retrying at UXGA\n", err);
        esp_camera_deinit();
        config.frame_size = FALLBACK_INIT_FRAMESIZE;
        err = esp_camera_init(&config);
    }
    if (err != ESP_OK)
    {
        Serial.printf("Camera init failed: 0x%x -- is the Sense board seated?\n", err);
        return false;
    }
    sensor_t *s = esp_camera_sensor_get();
    name = nameForPid(s->id.PID);
    camera_sensor_info_t *info = esp_camera_sensor_get_info(&s->id);
    maxSize = info ? info->max_size : FRAMESIZE_UXGA;
    if (maxSize > config.frame_size)
        maxSize = config.frame_size;

    // Per-sensor tweaks from the core's CameraWebServer example: the OV3660
    // module comes up upside down and washed out.
    if (s->id.PID == OV3660_PID)
    {
        s->set_vflip(s, 1);
        s->set_brightness(s, 1);
        s->set_saturation(s, -2);
    }
    s->set_framesize(s, DEFAULT_FRAMESIZE);
    s->set_quality(s, DEFAULT_QUALITY);
    defaults = s->status;

    applySaved(s);
    ready = true;
    Serial.printf("Camera: %s (PID 0x%04x), max framesize %d\n", name, s->id.PID, (int)maxSize);
    return true;
}

bool cameraReady() { return ready; }
const char *sensorName() { return name; }
framesize_t maxFramesize() { return maxSize; }

String cameraSettingsJson()
{
    String j = "{";
    if (ready)
    {
        const camera_status_t &st = esp_camera_sensor_get()->status;
        bool first = true;
        for (const Control &c : CONTROLS)
        {
            if (!first)
                j += ",";
            first = false;
            j += "\"";
            j += c.key;
            j += "\":";
            j += String(c.read(st));
        }
    }
    return j + "}";
}

SetResult cameraSetControl(const String &key, int value)
{
    const Control *c = findControl(key);
    if (!c)
        return SetResult::UnknownControl;
    if (!ready)
        return SetResult::SensorRefused;
    SetResult r = applyControl(esp_camera_sensor_get(), *c, value);
    if (r == SetResult::Ok)
    {
        Preferences prefs;
        prefs.begin(NVS_NAMESPACE, false);
        prefs.putInt(c->key, value);
        prefs.end();
    }
    return r;
}

void cameraResetDefaults()
{
    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, false);
    prefs.clear();
    prefs.end();
    if (!ready)
        return;
    sensor_t *s = esp_camera_sensor_get();
    for (const Control &c : CONTROLS)
        applyControl(s, c, c.read(defaults));
}

camera_fb_t *grabFreshFrame()
{
    if (!ready)
        return nullptr;
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb)
        esp_camera_fb_return(fb);
    return esp_camera_fb_get();
}
