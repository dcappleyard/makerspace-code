#include "booth_config.h"

#include "booth.h"
#include "battery.h"
#include "camera.h"
#include "screen.h"
#include "storage.h"
#include "upload.h"

#include <HWCDC.h>

namespace
{

enum class State
{
    Asleep,
    Live,
    Confirm,      // "Capture?" Yes / No / Setup
    Setup,        // exposure, Done, Reboot -- over the live view
    ConfirmReboot,
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
    bool ok = drawJpeg(fb->buf, fb->len, fb->width, fb->height, big, small, LIVE_FLIP_H, LIVE_FLIP_V);
    esp_camera_fb_return(fb);
    return ok;
}

void goToSleep()
{
    cameraOff();
    // Camera off and the screen still on: the moment to send new photos to the
    // server (WiFi comes up just for this, then goes off again).
    if (pendingUploads())
    {
        uploadPending(); // also pushes the battery log while WiFi is up
        takeTap();       // touches during the upload don't carry over
    }
    panelOff();
    logBattery("sleep");
    enter(State::Asleep);
    Serial.println("Asleep");
}

void wake()
{
    logBattery("wake");
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
// `letter` is 0 for a single-shot sequence: no _A suffix, no label.
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
        Serial.printf("Shot %c: capture failed\n", letter ? letter : '-');
        waitUntil(millis() + 1500);
        return;
    }
    char label[24] = "";
    if (letter)
        snprintf(label, sizeof(label), sdIsMounted() ? "%c" : "%c - no SD card", letter);
    else if (!sdIsMounted())
        strcpy(label, "no SD card");
    uint32_t decodeStart = millis();
    drawJpeg(jpg, len, w, h, nullptr, label[0] ? label : nullptr, REVIEW_FLIP_H, REVIEW_FLIP_V);
    uint32_t reviewStart = millis();

    uint32_t saveStart = millis();
    SaveResult r = savePhoto(jpg, len, letter ? base + "_" + letter : base);
    uint32_t saveMs = millis() - saveStart;
    free(jpg);
    Serial.printf("Shot %c: %dx%d, %u bytes -> %s (%s); flash %lu ms, review decode %lu ms, save %lu ms\n", letter ? letter : '-', w, h,
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
        char letter = SHOTS_PER_SEQUENCE > 1 ? 'A' + shot : 0;
        char small[2] = {letter, 0};
        for (int n = COUNTDOWN_FROM; n >= 1; n--)
        {
            char big[4];
            snprintf(big, sizeof(big), "%d", n);
            liveFor(COUNTDOWN_STEP_MS, big, letter ? small : nullptr);
        }
        // The "1" stays on screen (frozen) while the camera switches to full
        // size, so the flash itself is short.
        uint32_t t0 = millis();
        cameraCaptureMode();
        Serial.printf("Shot %c: switch to full size %lu ms\n", letter ? letter : '-', (unsigned long)(millis() - t0));
        shoot(base, letter);
    }
}

// Asleep, but with a computer on USB: stay awake (screen and camera off) so
// the serial port and uploads keep working -- see STAY_AWAKE_ON_USB_HOST.
// Also for the first BOOT_STAY_AWAKE_MS after any boot, so a Setup -> Reboot
// leaves the port up long enough to plug in and start an upload.
bool stayAwake() { return millis() < BOOT_STAY_AWAKE_MS || (STAY_AWAKE_ON_USB_HOST && HWCDC::isPlugged()); }

// The point of the tap that takeTap() just reported. The finger is still down,
// so a point is there to read; give the controller a moment if the first
// read comes back empty.
bool tapPoint(int &x, int &y)
{
    for (int i = 0; i < 10; i++)
    {
        if (readTouchPoint(x, y))
            return true;
        delay(5);
    }
    return false;
}

void showCapturePrompt()
{
    // Best guess so far; see BATTERY_PERCENT_MV in booth_config.h.
    int pct = batteryPercentEstimate();
    char bat[16];
    snprintf(bat, sizeof(bat), "Bat: %d%%", pct);
    drawPrompt("Capture?", pct >= 0 ? bat : nullptr, true);
}

void goSetup()
{
    lastInteractionMs = millis();
    setSetupOverlay(true, exposureComp());
    drawSetupNow();
    enter(State::Setup);
}

void leaveSetup()
{
    setSetupOverlay(false, 0);
    goLive();
}

void reboot()
{
    drawMessage("Rebooting...");
    logBattery("reboot");
    Serial.println("Rebooting (Setup -> Reboot)");
    Serial.flush();
    delay(500);
    ESP.restart();
}

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
        // Battery readings happen while asleep too: the light sleep below is
        // capped at the next reading's due time.
        serviceBatteryTimer();
        if (stayAwake())
        {
            if (takeTap())
                wake();
            else
                delay(20);
        }
        else if (sleepUntilTouch(msUntilBatterySample() + 1)) // a touch counts as the tap
        {
            takeTap();
            wake();
        }
        break;

    case State::Live:
        if (takeTap())
        {
            showCapturePrompt();
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
            int x = 0, y = 0;
            if (!tapPoint(x, y))
                break;
            switch (promptHitAt(x, y, true))
            {
            case PromptHit::Yes:
                runSequence();
                goLive();
                break;
            case PromptHit::No:
                goLive();
                break;
            case PromptHit::Setup:
                goSetup();
                break;
            default:
                break; // the gap between Yes/No and Setup: ignored
            }
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

    case State::Setup:
        if (takeTap())
        {
            int x = 0, y = 0;
            if (!tapPoint(x, y))
                break;
            lastInteractionMs = now;
            switch (setupHitAt(x, y))
            {
            case SetupHit::Minus:
            case SetupHit::Plus:
            {
                int ev = exposureComp() + (setupHitAt(x, y) == SetupHit::Plus ? 1 : -1);
                setExposureComp(ev);
                setSetupOverlay(true, exposureComp());
                drawSetupNow();
                Serial.printf("Exposure compensation %+d\n", exposureComp());
                break;
            }
            case SetupHit::Done:
                leaveSetup();
                break;
            case SetupHit::Reboot:
                drawPrompt("Reboot?", "Plug in USB first to flash", false);
                enter(State::ConfirmReboot);
                break;
            default:
                break;
            }
        }
        else if ((uint32_t)(now - lastInteractionMs) > SETUP_TIMEOUT_MS)
        {
            leaveSetup();
        }
        else if (!liveFrame(nullptr, nullptr)) // carries the Setup overlay
        {
            delay(10);
        }
        break;

    case State::ConfirmReboot:
        if (takeTap())
        {
            int x = 0, y = 0;
            if (!tapPoint(x, y))
                break;
            PromptHit hit = promptHitAt(x, y, false);
            if (hit == PromptHit::Yes)
                reboot();
            else if (hit == PromptHit::No)
                goSetup();
        }
        else if ((uint32_t)(now - stateSinceMs) > CONFIRM_TIMEOUT_MS)
        {
            goSetup();
        }
        else
        {
            delay(10);
        }
        break;
    }
}
