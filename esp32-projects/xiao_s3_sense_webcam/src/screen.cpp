#include "cam_config.h" // MUST be first: FS.h before TFT_eSPI.h (see below)

// Seeed_GFX's ESP32-S3 processor header defines FS_NO_GLOBALS before pulling
// in FS.h, which would hide `fs::File`/`fs::FS` from everything after it.
// cam_config.h includes FS.h first, so its `using` declarations fire and
// TFT_eSPI.h's later include is a no-op (same trick as
// ../xiao_s3_ee03_pull_frame/src/frame_config.h). Only this file includes
// TFT_eSPI.h.
#include <TFT_eSPI.h>

#if !defined(USER_SETUP_ID) || USER_SETUP_ID != 501
#error "Seeed_GFX didn't select the round display -- check lib/driver/driver.h (BOARD_SCREEN_COMBO 501) and -I lib/driver"
#endif

#include "screen.h"
#include "camera.h"

#include <Wire.h>
#include <img_converters.h>

namespace
{

TFT_eSPI tft;

enum class State
{
    Off,
    Preview,
    Confirm,
};
State state = State::Off;

constexpr int SCREEN_SIZE = 240;
constexpr uint8_t GC9A01_SLPIN = 0x10;
constexpr uint8_t GC9A01_SLPOUT = 0x11;
constexpr uint8_t GC9A01_DISPOFF = 0x28;
constexpr uint8_t GC9A01_DISPON = 0x29;

// --- Touch ---------------------------------------------------------------------
// Decoding a preview frame takes long enough to miss a quick tap if INT were
// only polled, so a FALLING-edge interrupt records that one happened and the
// loop picks it up.
volatile bool touchIrq = false;
uint32_t lastTouchReportMs = 0; // any touch activity (also the idle timer)
uint32_t stateSinceMs = 0;

void IRAM_ATTR onTouchInt() { touchIrq = true; }

// True once per tap: on the first report after TOUCH_REARM_MS of quiet.
bool takeTap()
{
    bool active = touchIrq || digitalRead(TOUCH_INT_PIN) == LOW;
    touchIrq = false;
    if (!active)
        return false;
    uint32_t now = millis();
    bool fresh = (uint32_t)(now - lastTouchReportMs) > TOUCH_REARM_MS;
    lastTouchReportMs = now;
    return fresh;
}

// One point from the CHSC6X: 5 bytes, no register address; byte 0 == 1 means
// pressed, x = byte 2, y = byte 4 (panel coordinates, rotation 0).
bool readTouchPoint(int &x, int &y)
{
    uint8_t b[5];
    if (Wire.requestFrom(TOUCH_I2C_ADDR, (uint8_t)sizeof(b)) != sizeof(b))
        return false;
    Wire.readBytes(b, sizeof(b));
    if (b[0] != 0x01)
        return false;
    int rx = b[2], ry = b[4];
    switch (DISPLAY_ROTATION % 4) // same mapping as Seeed_GFX's getTouch()
    {
    case 1:
        x = ry, y = SCREEN_SIZE - rx;
        break;
    case 2:
        x = SCREEN_SIZE - rx, y = SCREEN_SIZE - ry;
        break;
    case 3:
        x = SCREEN_SIZE - ry, y = rx;
        break;
    default:
        x = rx, y = ry;
    }
    return true;
}

// --- Panel power ---------------------------------------------------------------

void panelOff()
{
    digitalWrite(TFT_BL, LOW);
    tft.writecommand(GC9A01_DISPOFF);
    tft.writecommand(GC9A01_SLPIN);
}

void panelOn()
{
    tft.writecommand(GC9A01_SLPOUT);
    delay(120); // GC9A01 needs 120 ms after sleep-out
    tft.writecommand(GC9A01_DISPON);
    tft.fillScreen(TFT_BLACK);
    digitalWrite(TFT_BL, HIGH);
}

// --- Preview -------------------------------------------------------------------
uint8_t *rgb = nullptr; // RGB565 decode buffer, PSRAM
size_t rgbCapacity = 0;

void freePreviewBuffer()
{
    free(rgb);
    rgb = nullptr;
    rgbCapacity = 0;
}

// Largest JPEG decode scale that still covers the 240 px circle, so the
// decode stays cheap: VGA -> 1/2 (320x240), SVGA -> 1/2, UXGA -> 1/4 (400x300).
uint8_t pickScale(int w, int h, esp_jpeg_image_scale_t &scale)
{
    int shortSide = w < h ? w : h;
    if (shortSide / 8 >= SCREEN_SIZE)
        return scale = JPG_SCALE_8X, 8;
    if (shortSide / 4 >= SCREEN_SIZE)
        return scale = JPG_SCALE_4X, 4;
    if (shortSide / 2 >= SCREEN_SIZE)
        return scale = JPG_SCALE_2X, 2;
    return scale = JPG_SCALE_NONE, 1;
}

void drawPreviewFrame()
{
    // Not grabFreshFrame(): the latest queued frame is fine for a viewfinder,
    // and the buffer goes straight back so the stream and snapshots aren't
    // starved of the two frame buffers.
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb)
        return;
    esp_jpeg_image_scale_t scale;
    uint8_t div = pickScale(fb->width, fb->height, scale);
    int w = fb->width / div, h = fb->height / div;
    size_t need = (size_t)w * h * 2;
    if (need > rgbCapacity)
    {
        freePreviewBuffer();
        rgb = (uint8_t *)ps_malloc(need);
        if (!rgb)
        {
            esp_camera_fb_return(fb);
            Serial.printf("Preview: no PSRAM for a %dx%d buffer\n", w, h);
            return;
        }
        rgbCapacity = need;
    }
    bool ok = jpg2rgb565(fb->buf, fb->len, rgb, scale);
    esp_camera_fb_return(fb);
    if (ok) // centre-crop: a negative offset, TFT_eSPI clips to the panel
        tft.pushImage((SCREEN_SIZE - w) / 2, (SCREEN_SIZE - h) / 2, w, h, (uint16_t *)rgb);
}

// --- Yes / No prompt -------------------------------------------------------------
// Two halves of the circle: Yes (left), No (right).
void drawConfirm()
{
    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setTextDatum(MC_DATUM);
    tft.drawString("Turn screen off?", SCREEN_SIZE / 2, 72, 4);
    tft.fillRoundRect(28, 108, 88, 64, 12, TFT_RED);
    tft.fillRoundRect(124, 108, 88, 64, 12, TFT_DARKGREY);
    tft.setTextColor(TFT_WHITE);
    tft.drawString("Yes", 72, 140, 4);
    tft.drawString("No", 168, 140, 4);
}

void enter(State next)
{
    State prev = state;
    state = next;
    stateSinceMs = millis();
    switch (next)
    {
    case State::Off:
        panelOff();
        freePreviewBuffer();
        Serial.println("Screen off");
        break;
    case State::Preview:
        if (prev == State::Off)
        {
            panelOn();
            Serial.println("Screen on");
        }
        else
        {
            tft.fillScreen(TFT_BLACK);
        }
        break;
    case State::Confirm:
        drawConfirm();
        break;
    }
}

} // namespace

void setupScreen()
{
    // Keep the display's own SD slot off the shared bus.
    pinMode(ROUND_SD_CS, OUTPUT);
    digitalWrite(ROUND_SD_CS, HIGH);

    tft.begin(); // also starts Wire for touch, and switches the backlight on...
    tft.setRotation(DISPLAY_ROTATION);
    tft.setSwapBytes(PREVIEW_SWAP_BYTES);
    tft.fillScreen(TFT_BLACK);
    panelOff(); // ...so it's dark again a moment later

    pinMode(TOUCH_INT_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(TOUCH_INT_PIN), onTouchInt, FALLING);
    touchIrq = false;
    Serial.println("Round display ready (off -- tap to wake)");
}

void serviceScreen()
{
    bool tap = takeTap();
    uint32_t now = millis();

    switch (state)
    {
    case State::Off:
        if (tap)
            enter(State::Preview);
        return;

    case State::Preview:
        if (tap)
        {
            enter(State::Confirm);
            return;
        }
        break;

    case State::Confirm:
        if (tap)
        {
            // The finger is still down, so a point is there to read; give the
            // controller a moment if the first read comes back empty.
            int x = 0, y = 0;
            bool got = false;
            for (int i = 0; i < 10 && !(got = readTouchPoint(x, y)); i++)
                delay(5);
            if (got)
            {
                enter(x < SCREEN_SIZE / 2 ? State::Off : State::Preview);
                return;
            }
        }
        else if ((uint32_t)(now - stateSinceMs) > CONFIRM_TIMEOUT_MS)
        {
            enter(State::Preview);
            return;
        }
        break;
    }

    if ((uint32_t)(now - lastTouchReportMs) > SCREEN_IDLE_OFF_MS)
    {
        enter(State::Off);
        return;
    }
    if (state == State::Preview && cameraReady())
        drawPreviewFrame();
}

bool screenOn() { return state != State::Off; }

SPIClass &screenSpi() { return TFT_eSPI::getSPIinstance(); }
