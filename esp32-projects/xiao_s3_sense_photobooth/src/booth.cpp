#include "booth_config.h"

#include "booth.h"
#include "camera.h"
#include "screen.h"
#include "storage.h"

#include <HWCDC.h>

namespace
{

enum class State
{
    Asleep,
    Live,
    Confirm,
};
State state = State::Asleep;
uint32_t stateSinceMs = 0;
uint32_t lastInteractionMs = 0;

void enter(State next)
{
    state = next;
    stateSinceMs = millis();
    touchLockout();
}

void goLive()
{
    lastInteractionMs = millis();
    enter(State::Live);
}

// A frame from the camera, drawn with optional overlays. Returns false if no
// frame came (e.g. the first ones after a size switch).
bool liveFrame(const char *big, const char *small)
{
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb)
        return false;
    bool ok = drawJpeg(fb->buf, fb->len, fb->width, fb->height, big, small);
    esp_camera_fb_return(fb);
    return ok;
}

void goToSleep()
{
    cameraOff();
    panelOff();
    enter(State::Asleep);
    Serial.println("Asleep");
}

void wake()
{
    panelOn();
    drawMessage("One moment...");
    // A card inserted while asleep gets picked up here (and any photos held in
    // RAM move onto it).
    if (!sdIsMounted())
        mountSd(nullptr, false);
    if (!cameraInit())
    {
        drawMessage("Camera error", "is the Sense board seated?");
        delay(5000);
        goToSleep();
        return;
    }
    Serial.printf("Awake: %s, SD %s\n", sensorName(), sdIsMounted() ? "mounted" : "missing");
    goLive();
}

// Wait out `ms` while keeping the live view running, with overlays.
void liveFor(uint32_t ms, const char *big, const char *small)
{
    uint32_t until = millis() + ms;
    while ((int32_t)(until - millis()) > 0)
    {
        if (!liveFrame(big, small))
            delay(10);
        takeTap(); // touches are ignored during a sequence; just drain them
    }
}

void waitUntil(uint32_t untilMs)
{
    while ((int32_t)(untilMs - millis()) > 0)
    {
        takeTap();
        delay(10);
    }
}

// One full-size shot. The camera is already in capture mode (switched on the
// frozen "1"), so the white flash only spans one fresh frame: flash, grab,
// back to black after FLASH_MS, then decode + show the photo for REVIEW_MS,
// and save it while it's on screen.
void shoot(const String &base, char letter)
{
    flashWhite();
    uint32_t flashStart = millis();

    // Copied out so the camera can go straight back to live mode (and settle)
    // while the photo is reviewed and saved.
    camera_fb_t *fb = grabFrame(FLASH_DISCARD_FRAMES);
    uint8_t *jpg = nullptr;
    size_t len = 0;
    int w = 0, h = 0;
    if (fb)
    {
        jpg = (uint8_t *)ps_malloc(fb->len);
        if (jpg)
        {
            memcpy(jpg, fb->buf, fb->len);
            len = fb->len;
            w = fb->width;
            h = fb->height;
        }
        esp_camera_fb_return(fb);
    }
    waitUntil(flashStart + FLASH_MS);
    blankScreen();
    uint32_t flashMs = millis() - flashStart;
    cameraLiveMode();

    if (!jpg)
    {
        drawMessage("Capture failed");
        Serial.printf("Shot %c: capture failed\n", letter);
        waitUntil(millis() + 1500);
        return;
    }
    char label[24];
    snprintf(label, sizeof(label), sdIsMounted() ? "%c" : "%c - no SD card", letter);
    uint32_t decodeStart = millis();
    drawJpeg(jpg, len, w, h, nullptr, label);
    uint32_t reviewStart = millis();

    uint32_t saveStart = millis();
    SaveResult r = savePhoto(jpg, len, base + "_" + letter);
    uint32_t saveMs = millis() - saveStart;
    free(jpg);
    Serial.printf("Shot %c: %dx%d, %u bytes -> %s (%s); flash %lu ms, review decode %lu ms, save %lu ms\n", letter, w, h,
                  (unsigned)len, r.ok ? r.name.c_str() : "NOT SAVED", r.onSd ? "SD" : "RAM", (unsigned long)flashMs,
                  (unsigned long)(reviewStart - decodeStart), (unsigned long)saveMs);
    waitUntil(reviewStart + REVIEW_MS);
}

void runSequence()
{
    bool dated;
    String base = sequenceName(dated); // shared by all shots, taken at "Yes"
    Serial.printf("Sequence %s%s\n", base.c_str(), dated ? "" : " (clock not set)");
    for (uint8_t shot = 0; shot < SHOTS_PER_SEQUENCE; shot++)
    {
        char letter = 'A' + shot;
        char small[2] = {letter, 0};
        for (int n = COUNTDOWN_FROM; n >= 1; n--)
        {
            char big[4];
            snprintf(big, sizeof(big), "%d", n);
            liveFor(COUNTDOWN_STEP_MS, big, small);
        }
        // The "1" stays on screen (frozen) while the camera switches to full
        // size, so the flash itself is short.
        uint32_t t0 = millis();
        cameraCaptureMode();
        Serial.printf("Shot %c: switch to full size %lu ms\n", letter, (unsigned long)(millis() - t0));
        shoot(base, letter);
    }
}

// Asleep, but with a computer on USB: stay awake (screen and camera off) so
// the serial port and uploads keep working -- see STAY_AWAKE_ON_USB_HOST.
bool stayAwake() { return STAY_AWAKE_ON_USB_HOST && HWCDC::isPlugged(); }

} // namespace

void setupBooth()
{
    enter(State::Asleep);
    Serial.println("Booth ready -- tap the screen to wake");
}

void serviceBooth()
{
    uint32_t now = millis();
    switch (state)
    {
    case State::Asleep:
        if (stayAwake())
        {
            if (takeTap())
                wake();
            else
                delay(20);
        }
        else
        {
            sleepUntilTouch(); // returns on a touch, which counts as the tap
            takeTap();
            wake();
        }
        break;

    case State::Live:
        if (takeTap())
        {
            drawPrompt("Capture?");
            enter(State::Confirm);
        }
        else if ((uint32_t)(now - lastInteractionMs) > LIVE_IDLE_SLEEP_MS)
        {
            goToSleep();
        }
        else if (!liveFrame(nullptr, nullptr))
        {
            delay(10);
        }
        break;

    case State::Confirm:
        if (takeTap())
        {
            // The finger is still down, so a point is there to read; give the
            // controller a moment if the first read comes back empty.
            int x = 0, y = 0;
            bool got = false;
            for (int i = 0; i < 10 && !(got = readTouchPoint(x, y)); i++)
                delay(5);
            if (!got)
                break;
            if (x < 120)
                runSequence();
            goLive();
        }
        else if ((uint32_t)(now - stateSinceMs) > CONFIRM_TIMEOUT_MS)
        {
            goLive();
        }
        else
        {
            delay(10);
        }
        break;
    }
}
