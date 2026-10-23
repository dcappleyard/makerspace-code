#include "booth_config.h" // MUST be first: FS.h before TFT_eSPI.h (see below)

// Seeed_GFX's ESP32-S3 processor header defines FS_NO_GLOBALS before pulling
// in FS.h, which would hide `fs::File`/`fs::FS` from everything after it.
// booth_config.h includes FS.h first, so its `using` declarations fire and
// TFT_eSPI.h's later include is a no-op (same trick as
// ../xiao_s3_ee03_pull_frame/src/frame_config.h). Only this file includes
// TFT_eSPI.h.
#include <TFT_eSPI.h>

#if !defined(USER_SETUP_ID) || USER_SETUP_ID != 501
#error "Seeed_GFX didn't select the round display -- check lib/driver/driver.h (BOARD_SCREEN_COMBO 501) and -I lib/driver"
#endif

#include "screen.h"

#include <Wire.h>
#include <driver/gpio.h>
#include <esp_sleep.h>
#include <img_converters.h>

namespace
{

TFT_eSPI tft;
TFT_eSprite frame(&tft); // 240x240x16bpp = 115 KB, in PSRAM

constexpr int SCREEN_SIZE = 240;
constexpr uint8_t GC9A01_SLPIN = 0x10;
constexpr uint8_t GC9A01_SLPOUT = 0x11;
constexpr uint8_t GC9A01_DISPOFF = 0x28;
constexpr uint8_t GC9A01_DISPON = 0x29;

// --- Touch ---------------------------------------------------------------------
// Decoding a frame takes long enough to miss a quick tap if INT were only
// polled, so a FALLING-edge interrupt records that one happened.
volatile bool touchIrq = false;
uint32_t lastTouchReportMs = 0;
uint32_t lockoutFromMs = 0;
bool pendingWakeTap = false;

void IRAM_ATTR onTouchInt() { touchIrq = true; }

void attachTouchIrq()
{
    pinMode(TOUCH_INT_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(TOUCH_INT_PIN), onTouchInt, FALLING);
}

// --- Decode buffer --------------------------------------------------------------
uint8_t *rgb = nullptr; // RGB565, PSRAM; grows to the largest decode needed
size_t rgbCapacity = 0;

// Largest JPEG decode scale that still covers the 240 px circle: live VGA ->
// 1/2 (320x240), UXGA/QXGA captures -> 1/4 (400x300 / 512x384).
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

} // namespace

void setupScreen()
{
    // Keep the display's own SD slot off the shared bus.
    pinMode(ROUND_SD_CS, OUTPUT);
    digitalWrite(ROUND_SD_CS, HIGH);

    tft.begin(); // also starts Wire for touch, and switches the backlight on...
    tft.setRotation(DISPLAY_ROTATION);
    tft.fillScreen(TFT_BLACK);
    panelOff(); // ...so it's dark again a moment later

    frame.setColorDepth(16);
    if (!frame.createSprite(SCREEN_SIZE, SCREEN_SIZE))
        Serial.println("Sprite alloc failed -- no PSRAM?");
    frame.setSwapBytes(PREVIEW_SWAP_BYTES);

    attachTouchIrq();
    touchIrq = false;
}

SPIClass &screenSpi() { return TFT_eSPI::getSPIinstance(); }

void panelOn()
{
    gpio_hold_dis((gpio_num_t)BACKLIGHT_PIN);
    tft.writecommand(GC9A01_SLPOUT);
    delay(120); // GC9A01 needs 120 ms after sleep-out
    tft.writecommand(GC9A01_DISPON);
    tft.fillScreen(TFT_BLACK);
    digitalWrite(BACKLIGHT_PIN, HIGH);
}

void panelOff()
{
    digitalWrite(BACKLIGHT_PIN, LOW);
    tft.writecommand(GC9A01_DISPOFF);
    tft.writecommand(GC9A01_SLPIN);
}

// --- Touch ---------------------------------------------------------------------

bool takeTap()
{
    if (pendingWakeTap)
    {
        pendingWakeTap = false;
        return true;
    }
    bool active = touchIrq || digitalRead(TOUCH_INT_PIN) == LOW;
    touchIrq = false;
    if (!active)
        return false;
    uint32_t now = millis();
    bool fresh = (uint32_t)(now - lastTouchReportMs) > TOUCH_REARM_MS;
    lastTouchReportMs = now;
    if ((uint32_t)(now - lockoutFromMs) < TOUCH_LOCKOUT_MS)
        return false;
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

void touchLockout() { lockoutFromMs = millis(); }

void sleepUntilTouch()
{
    // Don't go down with a finger still on the glass (it'd wake at once).
    uint32_t start = millis();
    while (digitalRead(TOUCH_INT_PIN) == LOW && millis() - start < 2000)
        delay(10);

    detachInterrupt(digitalPinToInterrupt(TOUCH_INT_PIN));
    // GPIO outputs aren't guaranteed through light sleep: hold the backlight
    // off and both SD chip-selects deselected (GPIO21 is also the user LED).
    digitalWrite(BACKLIGHT_PIN, LOW);
    digitalWrite(SD_CS, HIGH);
    digitalWrite(ROUND_SD_CS, HIGH);
    for (int pin : {BACKLIGHT_PIN, SD_CS, ROUND_SD_CS})
        gpio_hold_en((gpio_num_t)pin);
    gpio_wakeup_enable((gpio_num_t)TOUCH_INT_PIN, GPIO_INTR_LOW_LEVEL);
    esp_sleep_enable_gpio_wakeup();
    Serial.flush();

    esp_light_sleep_start();

    gpio_wakeup_disable((gpio_num_t)TOUCH_INT_PIN);
    esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_GPIO);
    for (int pin : {BACKLIGHT_PIN, SD_CS, ROUND_SD_CS})
        gpio_hold_dis((gpio_num_t)pin);
    attachTouchIrq();
    touchIrq = false;
    lastTouchReportMs = millis();
    pendingWakeTap = true;
}

// --- Drawing -------------------------------------------------------------------

bool drawJpeg(const uint8_t *jpg, size_t len, int width, int height, const char *big, const char *small)
{
    esp_jpeg_image_scale_t scale;
    uint8_t div = pickScale(width, height, scale);
    int w = width / div, h = height / div;
    size_t need = (size_t)w * h * 2;
    if (need > rgbCapacity)
    {
        free(rgb);
        rgb = (uint8_t *)ps_malloc(need);
        rgbCapacity = rgb ? need : 0;
        if (!rgb)
        {
            Serial.printf("No PSRAM for a %dx%d decode buffer\n", w, h);
            return false;
        }
    }
    if (!jpg2rgb565(jpg, len, rgb, scale))
        return false;
    // Centre-crop: a negative offset, the sprite clips.
    frame.pushImage((SCREEN_SIZE - w) / 2, (SCREEN_SIZE - h) / 2, w, h, (uint16_t *)rgb);
    if (big)
    {
        frame.setTextDatum(MC_DATUM);
        frame.setTextColor(TFT_WHITE);
        frame.setTextSize(2);
        // Font 7 (7-segment) at 2x: ~96 px tall digits. A dark copy offset
        // behind it keeps it readable on a bright scene.
        frame.setTextColor(TFT_BLACK);
        frame.drawString(big, SCREEN_SIZE / 2 + 3, SCREEN_SIZE / 2 + 3, 7);
        frame.setTextColor(TFT_WHITE);
        frame.drawString(big, SCREEN_SIZE / 2, SCREEN_SIZE / 2, 7);
        frame.setTextSize(1);
    }
    if (small)
    {
        frame.setTextDatum(MC_DATUM);
        int tw = frame.textWidth(small, 4) + 20;
        frame.fillRoundRect((SCREEN_SIZE - tw) / 2, 186, tw, 30, 8, TFT_BLACK);
        frame.setTextColor(TFT_WHITE);
        frame.drawString(small, SCREEN_SIZE / 2, 201, 4);
    }
    frame.pushSprite(0, 0);
    return true;
}

void drawPrompt(const char *question)
{
    // Over the last live frame (still in the sprite): a dark band with the
    // question and two halves, Yes left / No right.
    frame.fillRect(0, 60, SCREEN_SIZE, 122, TFT_BLACK);
    frame.setTextDatum(MC_DATUM);
    frame.setTextColor(TFT_WHITE);
    frame.drawString(question, SCREEN_SIZE / 2, 82, 4);
    frame.fillRoundRect(24, 104, 92, 64, 12, TFT_DARKGREEN);
    frame.fillRoundRect(124, 104, 92, 64, 12, TFT_DARKGREY);
    frame.drawString("Yes", 70, 136, 4);
    frame.drawString("No", 170, 136, 4);
    frame.pushSprite(0, 0);
}

void flashWhite() { tft.fillScreen(TFT_WHITE); }

void blankScreen() { tft.fillScreen(TFT_BLACK); }

void drawMessage(const char *line1, const char *line2)
{
    frame.fillSprite(TFT_BLACK);
    frame.setTextDatum(MC_DATUM);
    frame.setTextColor(TFT_WHITE);
    frame.drawString(line1, SCREEN_SIZE / 2, line2 ? 105 : 120, 4);
    if (line2)
        frame.drawString(line2, SCREEN_SIZE / 2, 140, 2);
    frame.pushSprite(0, 0);
}
