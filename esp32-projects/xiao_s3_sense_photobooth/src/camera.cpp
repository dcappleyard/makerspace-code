#include "booth_config.h"

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

bool ready = false;
framesize_t maxSize = FRAMESIZE_UXGA;
const char *name = "none";

struct Control
{
    const char *key; // also the NVS key -- must stay <= 15 chars
    int minValue;
    int maxValue;
    int (*apply)(sensor_t *s, int v);
    int (*read)(const camera_status_t &st);
};

// Image controls re-applied from NVS at every init. The keys are the ones
// ../xiao_s3_sense_webcam saves from its web page, so tuning done there on the
// same board carries over. Frame size and JPEG quality aren't here: the booth
// sets those per mode (live / capture).
//
// Order matters when re-applying saved settings: values before the auto
// toggles that use or override them, so turning AEC/AGC off lands on the saved
// manual exposure/gain rather than whatever the sensor had.
const Control CONTROLS[] = {
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

void applySaved(sensor_t *s)
{
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, true))
        return; // nothing saved yet
    for (const Control &c : CONTROLS)
    {
        if (!prefs.isKey(c.key))
            continue;
        int v = prefs.getInt(c.key);
        if (v >= c.minValue && v <= c.maxValue)
            c.apply(s, v);
    }
    prefs.end();
}

void discard(int frames)
{
    for (int i = 0; i < frames; i++)
    {
        camera_fb_t *fb = esp_camera_fb_get();
        if (fb)
            esp_camera_fb_return(fb);
    }
}

void setMode(framesize_t size, int quality)
{
    sensor_t *s = esp_camera_sensor_get();
    s->set_framesize(s, size);
    s->set_quality(s, quality);
}

} // namespace

// Re-run at every wake: deinit + init is the simplest way to stop XCLK and the
// DMA while asleep (the Sense board has no PWDN line, so the sensor itself
// stays powered, just unclocked).
bool cameraInit()
{
    if (ready)
        return true;
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
    config.jpeg_quality = CAPTURE_QUALITY;
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
    applySaved(s);
    setMode(LIVE_FRAMESIZE, LIVE_QUALITY);
    ready = true;
    discard(WAKE_DISCARD_FRAMES);
    return true;
}

void cameraOff()
{
    if (!ready)
        return;
    esp_camera_deinit();
    ready = false;
}

bool cameraReady() { return ready; }
const char *sensorName() { return name; }
framesize_t maxFramesize() { return maxSize; }

void cameraCaptureMode()
{
    if (!ready)
        return;
    setMode(maxSize, CAPTURE_QUALITY);
    discard(CAPTURE_DISCARD_FRAMES);
}

camera_fb_t *grabFrame(int discardFirst)
{
    if (!ready)
        return nullptr;
    discard(discardFirst);
    return esp_camera_fb_get();
}

void cameraLiveMode()
{
    if (ready)
        setMode(LIVE_FRAMESIZE, LIVE_QUALITY);
}
